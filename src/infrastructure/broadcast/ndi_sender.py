"""
Native NDI (Network Device Interface) & Transparent Video Stream Broadcaster for VerbaClear.
Outputs broadcast-grade 1080p RGBA lower-third overlays with alpha-channel transparency
for OBS Studio, vMix, NewTek TriCaster, and digital video switchers.
"""

import ctypes
import ctypes.util
import logging
from pathlib import Path
import threading
import time
from typing import Optional

from src.domain.models import StageOverlayCard
from src.infrastructure.broadcast.frame_renderer import StageFrameRenderer

logger = logging.getLogger(__name__)


# NDI C-SDK Data Structures (C ABI)
class NDIlib_send_create_t(ctypes.Structure):
    _fields_ = [
        ("p_ndi_name", ctypes.c_char_p),
        ("p_groups", ctypes.c_char_p),
        ("clock_video", ctypes.c_bool),
        ("clock_audio", ctypes.c_bool),
    ]


class NDIlib_video_frame_v2_t(ctypes.Structure):
    _fields_ = [
        ("xres", ctypes.c_int32),
        ("yres", ctypes.c_int32),
        ("FourCC", ctypes.c_uint32),
        ("frame_rate_N", ctypes.c_int32),
        ("frame_rate_D", ctypes.c_int32),
        ("picture_aspect_ratio", ctypes.c_float),
        ("frame_format_type", ctypes.c_int32),
        ("timecode", ctypes.c_int64),
        ("p_data", ctypes.c_void_p),
        ("line_stride_in_bytes", ctypes.c_int32),
        ("p_metadata", ctypes.c_char_p),
        ("timestamp", ctypes.c_int64),
    ]


class NDIBroadcastAdapter:
    """
    NDI Broadcast and Transparent Video Stream Engine.
    Attempts dynamic loading of libndi.so with graceful degradation into
    Virtual NDI / Transparent HTTP Alpha Stream mode if libndi is absent.
    """

    FOURCC_RGBA = 0x41424752  # 'RGBA' FourCC in little-endian

    def __init__(
        self,
        stream_name: str = "VERBACLEAR-STAGE",
        fps: int = 30,
        renderer: Optional[StageFrameRenderer] = None,
        custom_ndi_path: Optional[str] = None,
    ):
        self.stream_name = stream_name
        self.fps = fps
        self.renderer = renderer or StageFrameRenderer(width=1920, height=1080)
        self.custom_ndi_path = custom_ndi_path

        self.is_ndi_available = False
        self.is_streaming = True  # Streaming enabled by default
        self.frame_count = 0

        self._ndi_lib = None
        self._ndi_sender = None
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self._init_ndi_c_library()

    def _init_ndi_c_library(self) -> None:
        """Dynamically locates and loads libndi.so using ctypes."""
        candidate_paths = []
        if self.custom_ndi_path:
            candidate_paths.append(self.custom_ndi_path)

        # Standard system locations and library variations
        candidate_names = [
            "libndi.so",
            "libndi.so.5",
            "libndi.so.4",
            "Processing.NDI.Lib.x64.so",
        ]
        for name in candidate_names:
            candidate_paths.append(name)
            found = ctypes.util.find_library(name)
            if found:
                candidate_paths.append(found)

        candidate_paths.extend([
            "/usr/lib/libndi.so",
            "/usr/local/lib/libndi.so",
            "/usr/lib/x86_64-linux-gnu/libndi.so",
            "/opt/NewTek/NDI/lib/libndi.so",
        ])

        for lib_path in candidate_paths:
            try:
                loaded = ctypes.CDLL(lib_path)
                if hasattr(loaded, "NDIlib_initialize") and hasattr(loaded, "NDIlib_send_create_v2"):
                    self._ndi_lib = loaded
                    self._bind_ndi_functions()
                    logger.info("Successfully bound to native NDI runtime library: %s", lib_path)
                    break
            except (OSError, Exception):
                continue

        if self._ndi_lib is not None:
            try:
                if self._ndi_lib.NDIlib_initialize():
                    self.is_ndi_available = True
                    logger.info("NDI C-SDK initialized. Broadcast source: '%s'", self.stream_name)
                else:
                    logger.warning("NDIlib_initialize() returned False; falling back to Virtual NDI mode.")
            except Exception as e:
                logger.warning("NDI initialization exception: %s. Using Virtual NDI mode.", str(e))
        else:
            logger.info(
                "Native NDI library (libndi.so) not installed on host. Operating in Virtual NDI / Transparent HTTP Alpha Stream mode."
            )

    def _bind_ndi_functions(self) -> None:
        """Sets ctypes function signatures for NDI library calls."""
        lib = self._ndi_lib
        lib.NDIlib_initialize.restype = ctypes.c_bool
        lib.NDIlib_initialize.argtypes = []

        lib.NDIlib_destroy.restype = None
        lib.NDIlib_destroy.argtypes = []

        lib.NDIlib_send_create_v2.restype = ctypes.c_void_p
        lib.NDIlib_send_create_v2.argtypes = [ctypes.POINTER(NDIlib_send_create_t)]

        lib.NDIlib_send_destroy.restype = None
        lib.NDIlib_send_destroy.argtypes = [ctypes.c_void_p]

        lib.NDIlib_send_send_video_v2.restype = None
        lib.NDIlib_send_send_video_v2.argtypes = [ctypes.c_void_p, ctypes.POINTER(NDIlib_video_frame_v2_t)]

    def start(self) -> None:
        """Starts the NDI broadcast output worker."""
        with self._lock:
            if self._worker_thread and self._worker_thread.is_alive():
                return

            self._stop_event.clear()

            if self.is_ndi_available and self._ndi_lib:
                try:
                    create_settings = NDIlib_send_create_t(
                        p_ndi_name=self.stream_name.encode("utf-8"),
                        p_groups=None,
                        clock_video=True,
                        clock_audio=False,
                    )
                    self._ndi_sender = self._ndi_lib.NDIlib_send_create_v2(ctypes.byref(create_settings))
                    logger.info("Created native NDI sender instance: '%s'", self.stream_name)
                except Exception as e:
                    logger.error("Failed to create NDI sender instance: %s", str(e))
                    self._ndi_sender = None

            self._worker_thread = threading.Thread(
                target=self._broadcast_loop,
                name="NDIBroadcastWorker",
                daemon=True,
            )
            self._worker_thread.start()
            logger.info("NDI Broadcast engine running (Mode: %s)", "NATIVE_NDI" if self.is_ndi_available else "VIRTUAL_ALPHA_STREAM")

    def stop(self) -> None:
        """Shuts down the NDI broadcast engine and releases C resources."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None

        with self._lock:
            if self._ndi_sender and self._ndi_lib:
                try:
                    self._ndi_lib.NDIlib_send_destroy(self._ndi_sender)
                except Exception as e:
                    logger.warning("Error destroying NDI sender: %s", str(e))
                self._ndi_sender = None

            if self.is_ndi_available and self._ndi_lib:
                try:
                    self._ndi_lib.NDIlib_destroy()
                except Exception as e:
                    logger.warning("Error destroying NDI library: %s", str(e))
                self.is_ndi_available = False

        logger.info("NDI Broadcast engine stopped.")

    def _broadcast_loop(self) -> None:
        """Continuous video frame transmission loop at target FPS."""
        frame_interval = 1.0 / max(1, self.fps)

        while not self._stop_event.is_set():
            loop_start = time.perf_counter()

            if self.is_streaming:
                # If native NDI sender is active, push raw RGBA buffer to network
                if self.is_ndi_available and self._ndi_sender and self._ndi_lib:
                    try:
                        raw_rgba = self.renderer.get_raw_rgba_bytes()
                        # Cast raw bytes buffer to C pointer
                        c_buf = (ctypes.c_uint8 * len(raw_rgba)).from_buffer_copy(raw_rgba)

                        video_frame = NDIlib_video_frame_v2_t(
                            xres=self.renderer.width,
                            yres=self.renderer.height,
                            FourCC=self.FOURCC_RGBA,
                            frame_rate_N=self.fps * 1000,
                            frame_rate_D=1000,
                            picture_aspect_ratio=16.0 / 9.0,
                            frame_format_type=1,  # Progressive
                            timecode=0,
                            p_data=ctypes.cast(c_buf, ctypes.c_void_p),
                            line_stride_in_bytes=self.renderer.width * 4,
                            p_metadata=None,
                            timestamp=0,
                        )
                        self._ndi_lib.NDIlib_send_send_video_v2(self._ndi_sender, ctypes.byref(video_frame))
                    except Exception as e:
                        logger.error("Error sending NDI frame: %s", str(e))

                self.frame_count += 1

            # Sleep remaining time to maintain target framerate
            elapsed = time.perf_counter() - loop_start
            sleep_time = max(0.001, frame_interval - elapsed)
            time.sleep(sleep_time)

    def set_card(self, card: Optional[StageOverlayCard]) -> None:
        """Updates the active stage overlay card for broadcast output."""
        self.renderer.set_card(card)

    def dismiss_card(self) -> None:
        """Dismisses the active lower-third card immediately."""
        self.renderer.dismiss_card()

    def set_blackout(self, is_blackout: bool) -> None:
        """Enforces or clears blackout blanking across all broadcast outputs."""
        self.renderer.set_blackout(is_blackout)

    def toggle_streaming(self, force_state: Optional[bool] = None) -> bool:
        """Toggles or sets the broadcast video stream active state."""
        with self._lock:
            if force_state is not None:
                self.is_streaming = bool(force_state)
            else:
                self.is_streaming = not self.is_streaming
            return self.is_streaming

    def get_current_frame_png(self) -> bytes:
        """Returns the current rendered 1920x1080 frame as PNG with full alpha transparency."""
        return self.renderer.get_png_bytes()

    def get_current_frame_rgba(self) -> bytes:
        """Returns the raw 1920x1080 RGBA byte buffer."""
        return self.renderer.get_raw_rgba_bytes()

    def get_status(self) -> dict:
        """Returns real-time broadcast and NDI telemetry status."""
        active_card = self.renderer.active_card
        return {
            "isNdiAvailable": self.is_ndi_available,
            "isStreaming": self.is_streaming,
            "streamName": self.stream_name,
            "fps": self.fps,
            "resolution": f"{self.renderer.width}x{self.renderer.height}",
            "mode": "NATIVE_NDI" if self.is_ndi_available else "VIRTUAL_ALPHA_STREAM",
            "frameCount": self.frame_count,
            "hasActiveCard": self.renderer.is_card_active,
            "activeWord": active_card.word if active_card else None,
            "activeCardId": active_card.card_id if active_card else None,
        }

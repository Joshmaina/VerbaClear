"""
PortAudio Audio Capture Adapter for VerbaClear.
Implements the AudioSourcePort using sounddevice and a high-performance circular ring buffer.
"""

from collections import deque
import logging
import threading
from typing import Any, Dict, List, Optional
import numpy as np
import sounddevice as sd

from src.domain.interfaces import AudioSourcePort
from src.domain.models import AudioChunk

logger = logging.getLogger(__name__)


class PortAudioSource(AudioSourcePort):
    """
    Continuous audio streamer wrapping PortAudio via sounddevice.
    Buffers incoming PCM audio frames into an internal lock-protected ring buffer.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_duration_ms: float = 30.0,
        device_index: Optional[int] = None,
        max_buffer_seconds: float = 10.0,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_duration_ms = chunk_duration_ms
        self.chunk_size = int(self.sample_rate * (self.chunk_duration_ms / 1000.0))  # 480 samples
        self.device_index = device_index
        self.max_buffer_chunks = int((max_buffer_seconds * 1000.0) / self.chunk_duration_ms)

        self._buffer: deque[np.ndarray] = deque(maxlen=self.max_buffer_chunks)
        self._lock = threading.Lock()
        self._stream: Optional[sd.InputStream] = None
        self._is_active = False

    @staticmethod
    def list_devices() -> List[Dict[str, Any]]:
        """Lists all audio input devices available on the host machine."""
        try:
            devices = sd.query_devices()
            input_devices = []
            for idx, dev in enumerate(devices):
                if dev["max_input_channels"] > 0:
                    input_devices.append({
                        "index": idx,
                        "name": dev["name"],
                        "channels": dev["max_input_channels"],
                        "default_samplerate": dev["default_samplerate"],
                    })
            return input_devices
        except Exception as e:
            logger.warning("Could not query host audio devices: %s", str(e))
            return []

    def get_current_device_info(self) -> Dict[str, Any]:
        """Returns metadata for the currently configured audio device."""
        devices = self.list_devices()
        if self.device_index is not None:
            for dev in devices:
                if dev["index"] == self.device_index:
                    return dev
            return {"index": self.device_index, "name": f"Audio Device #{self.device_index}"}
        if devices:
            return {"index": None, "name": f"Default ({devices[0]['name']})"}
        return {"index": None, "name": "Default Audio Input"}

    def set_device(self, device_index: Optional[int]) -> bool:
        """
        Dynamically changes the active audio input device.
        If the stream is running, gracefully closes and restarts it on the new device.
        """
        logger.info("Switching audio input device from %s to %s", self.device_index, device_index)
        was_active = self._is_active
        if was_active:
            self.stop_stream()

        self.device_index = device_index
        with self._lock:
            self._buffer.clear()

        if was_active:
            try:
                self.start_stream()
                logger.info("Successfully switched audio input to device %s", device_index)
                return True
            except Exception as e:
                logger.error("Failed to start audio stream on device %s: %s", device_index, str(e))
                return False
        return True

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        """PortAudio native callback executed on high-priority audio thread."""
        if status:
            logger.warning("Audio input status flag: %s", status)

        try:
            # Convert float32 or int16 to 1D float32 normalized between -1.0 and 1.0
            audio_frame = indata[:, 0].copy()

            if hasattr(self, "_lock") and hasattr(self, "_buffer"):
                with self._lock:
                    self._buffer.append(audio_frame)
        except Exception:
            pass

    def start_stream(self) -> None:
        """Starts real-time PortAudio input capture."""
        if self._is_active:
            logger.warning("PortAudio stream is already running.")
            return

        logger.info(
            "Starting audio capture (rate=%d, channels=%d, chunk=%d samples, device=%s)",
            self.sample_rate,
            self.channels,
            self.chunk_size,
            str(self.device_index),
        )

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            blocksize=self.chunk_size,
            device=self.device_index,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._is_active = True

    def stop_stream(self) -> None:
        """Stops audio capture and safely closes PortAudio stream."""
        if not self._is_active or self._stream is None:
            return

        logger.info("Stopping PortAudio capture stream.")
        self._is_active = False
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        finally:
            self._stream = None

    def __del__(self) -> None:
        try:
            self.stop_stream()
        except Exception:
            pass

    def read_chunk(self, frame_size: Optional[int] = None) -> Optional[np.ndarray]:
        """Reads the oldest chunk from the ring buffer in O(1) time."""
        with self._lock:
            if not self._buffer:
                return None
            return self._buffer.popleft()

    @property
    def is_active(self) -> bool:
        return self._is_active

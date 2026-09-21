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

        # Convert float32 or int16 to 1D float32 normalized between -1.0 and 1.0
        audio_frame = indata[:, 0].copy()

        with self._lock:
            self._buffer.append(audio_frame)

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
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self._is_active = False

    def read_chunk(self, frame_size: Optional[int] = None) -> Optional[np.ndarray]:
        """Reads the oldest chunk from the ring buffer in O(1) time."""
        with self._lock:
            if not self._buffer:
                return None
            return self._buffer.popleft()

    @property
    def is_active(self) -> bool:
        return self._is_active

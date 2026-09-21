"""
Silero VAD v5 ONNX Implementation & Speech Segmentation Adapter for VerbaClear.
Implements VoiceActivityDetectorPort for sub-millisecond voice activity detection and audio windowing.
"""

import logging
import os
from pathlib import Path
from typing import Generator, List, Optional, Tuple
import numpy as np
import urllib.request

from src.domain.interfaces import VoiceActivityDetectorPort

logger = logging.getLogger(__name__)

SILERO_VAD_ONNX_URL = (
    "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
)


class SileroVAD(VoiceActivityDetectorPort):
    """
    Evaluates speech probability on 30ms (480 samples @ 16kHz) audio slices using ONNX runtime.
    Maintains recurrent hidden states across continuous audio chunks.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        sample_rate: int = 16000,
        threshold: float = 0.5,
    ):
        self.sample_rate = sample_rate
        self.threshold = threshold

        if model_path is None:
            cache_dir = Path.home() / ".cache" / "verbaclear" / "models"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.model_path = str(cache_dir / "silero_vad.onnx")
        else:
            self.model_path = model_path

        self._ensure_model_downloaded()
        self._session = None
        self._init_session()
        self.reset_state()

    def _ensure_model_downloaded(self) -> None:
        """Downloads official Silero VAD v5 ONNX model if not already present."""
        if not os.path.exists(self.model_path):
            logger.info("Downloading Silero VAD v5 ONNX model to %s...", self.model_path)
            urllib.request.urlretrieve(SILERO_VAD_ONNX_URL, self.model_path)
            logger.info("Silero VAD download complete.")

    def _init_session(self) -> None:
        """Initializes ONNX runtime session with CPU execution provider."""
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._session = ort.InferenceSession(
            self.model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )

    def reset_state(self) -> None:
        """Resets the recurrent hidden state tensor between discontinuous audio streams."""
        # Silero V5 hidden state shape: (2, 1, 128) float32
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def is_speech(self, audio_frame: np.ndarray, threshold: Optional[float] = None) -> bool:
        """
        Evaluates whether an audio slice contains human vocal activity.
        audio_frame must be 1D float32 of length 480 (30ms @ 16kHz) or 512.
        """
        prob, _ = self.evaluate_probability(audio_frame)
        active_thresh = threshold if threshold is not None else self.threshold
        return prob >= active_thresh

    def evaluate_probability(self, audio_frame: np.ndarray) -> Tuple[float, np.ndarray]:
        """
        Returns (speech_probability, updated_hidden_state).
        """
        if len(audio_frame) != 480 and len(audio_frame) != 512:
            # Pad or truncate to 512 if necessary for VAD input compatibility
            if len(audio_frame) < 512:
                audio_input = np.pad(audio_frame, (0, 512 - len(audio_frame)), mode="constant")
            else:
                audio_input = audio_frame[:512]
        else:
            audio_input = audio_frame

        # Input shape: (1, N) float32
        tensor_in = np.expand_dims(audio_input.astype(np.float32), axis=0)
        sr_tensor = np.array(self.sample_rate, dtype=np.int64)

        ort_inputs = {
            "input": tensor_in,
            "state": self._state,
            "sr": sr_tensor,
        }

        out, self._state = self._session.run(None, ort_inputs)
        speech_prob = float(out[0][0])
        return speech_prob, self._state


class SpeechSegmenter:
    """
    Consumes continuous 30ms frames, evaluates speech presence, and yields complete
    speech segments when speaker pauses or maximum window length is reached.
    """

    def __init__(
        self,
        vad: VoiceActivityDetectorPort,
        sample_rate: int = 16000,
        trailing_silence_ms: float = 250.0,
        min_speech_duration_ms: float = 400.0,
        max_speech_duration_ms: float = 3000.0,
    ):
        self.vad = vad
        self.sample_rate = sample_rate
        self.trailing_silence_ms = trailing_silence_ms
        self.min_speech_duration_ms = min_speech_duration_ms
        self.max_speech_duration_ms = max_speech_duration_ms

        self._active_speech_frames: List[np.ndarray] = []
        self._current_silence_ms = 0.0
        self._is_speaking = False

    def process_frame(self, frame: np.ndarray, frame_duration_ms: float = 30.0) -> Optional[np.ndarray]:
        """
        Processes a single audio frame.
        Returns a complete 1D numpy audio array when speech segment completes, else None.
        """
        is_speech = self.vad.is_speech(frame)

        if is_speech:
            self._is_speaking = True
            self._current_silence_ms = 0.0
            self._active_speech_frames.append(frame)

            total_speech_ms = len(self._active_speech_frames) * frame_duration_ms
            if total_speech_ms >= self.max_speech_duration_ms:
                # Force chunk cut at maximum duration
                chunk = np.concatenate(self._active_speech_frames)
                self._active_speech_frames.clear()
                self._is_speaking = False
                return chunk
        else:
            if self._is_speaking:
                self._current_silence_ms += frame_duration_ms
                self._active_speech_frames.append(frame)

                if self._current_silence_ms >= self.trailing_silence_ms:
                    total_speech_ms = len(self._active_speech_frames) * frame_duration_ms
                    if total_speech_ms >= self.min_speech_duration_ms:
                        chunk = np.concatenate(self._active_speech_frames)
                        self._active_speech_frames.clear()
                        self._is_speaking = False
                        self._current_silence_ms = 0.0
                        return chunk
                    else:
                        # Too short (e.g. mic click or cough), discard
                        self._active_speech_frames.clear()
                        self._is_speaking = False
                        self._current_silence_ms = 0.0

        return None

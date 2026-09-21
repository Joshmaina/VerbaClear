"""
faster-whisper (CTranslate2) ASR Adapter for VerbaClear.
Implements SpeechToTextPort with sub-200ms greedy decoding and word-level timestamps.
"""

import logging
import os
import time
from typing import List, Optional
import numpy as np

from src.domain.interfaces import SpeechToTextPort
from src.domain.models import TranscribedSegment

logger = logging.getLogger(__name__)


class FasterWhisperASR(SpeechToTextPort):
    """
    Local speech-to-text inference engine using faster-whisper (CTranslate2).
    Optimized for hard real-time streaming with greedy decoding.
    """

    def __init__(
        self,
        model_size_or_path: str = "base.en",
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        cpu_threads: int = 4,
    ):
        self.model_size = model_size_or_path
        self.cpu_threads = cpu_threads

        # Device auto-detection
        if device is None:
            self.device = self._auto_detect_device()
        else:
            self.device = device

        # Compute type auto-detection
        if compute_type is None:
            if self.device == "cuda":
                self.compute_type = "float16"
            else:
                self.compute_type = "int8"  # High-efficiency CPU quantization
        else:
            self.compute_type = compute_type

        self._model = None
        self._load_model()

    @staticmethod
    def _auto_detect_device() -> str:
        """Determines best hardware acceleration device available."""
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    def _load_model(self) -> None:
        """Loads faster-whisper CTranslate2 model into memory."""
        from faster_whisper import WhisperModel

        logger.info(
            "Initializing faster-whisper model '%s' (device=%s, compute=%s, threads=%d)...",
            self.model_size,
            self.device,
            self.compute_type,
            self.cpu_threads,
        )
        t0 = time.perf_counter()
        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
        )
        elapsed_s = time.perf_counter() - t0
        logger.info("faster-whisper model loaded in %.2f seconds. Running warm-up...", elapsed_s)
        # Warm-up inference to initialize thread pools and CPU caches
        dummy_warmup = np.zeros(3200, dtype=np.float32)  # 0.2s of audio
        _ = list(self._model.transcribe(dummy_warmup, beam_size=1, language="en")[0])
        logger.info("faster-whisper engine warm-up complete.")

    def transcribe(self, audio_buffer: np.ndarray) -> List[TranscribedSegment]:
        """
        Transcribes a 1D float32 audio array (16kHz) into text segments.
        audio_buffer must be normalized between -1.0 and 1.0.
        """
        if self._model is None:
            raise RuntimeError("Whisper model is not initialized.")

        if len(audio_buffer) == 0:
            return []

        # audio_buffer: float32, 16kHz mono
        segments_generator, info = self._model.transcribe(
            audio_buffer,
            beam_size=1,            # Greedy decoding for lowest latency
            best_of=1,
            temperature=0.0,        # Deterministic
            word_timestamps=True,   # Word boundaries
            language="en",
            vad_filter=False,       # Gated externally by Silero VAD
            condition_on_previous_text=False, # Avoid hallucination loops
        )

        results: List[TranscribedSegment] = []
        for seg in segments_generator:
            word_list = [w.word.strip() for w in (seg.words or []) if w.word.strip()]
            results.append(
                TranscribedSegment(
                    text=seg.text.strip(),
                    start_time_s=seg.start,
                    end_time_s=seg.end,
                    confidence=float(np.exp(seg.avg_logprob)) if seg.avg_logprob is not None else 1.0,
                    words=word_list if word_list else seg.text.strip().split(),
                )
            )

        return results

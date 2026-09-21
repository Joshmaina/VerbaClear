"""
Unit and Integration Tests for Phase 1: Audio Capture & Speech-to-Text Pipeline.
Verifies Exit Gate 1: Silence rejection and sub-800ms ASR inference.
"""

import time
import numpy as np
import pytest

from src.domain.interfaces import AudioSourcePort, VoiceActivityDetectorPort
from src.domain.models import AudioChunk, TranscribedSegment
from src.infrastructure.audio.capture import PortAudioSource
from src.infrastructure.audio.vad import SileroVAD, SpeechSegmenter
from src.infrastructure.asr.whisper_engine import FasterWhisperASR


class MockAudioSource(AudioSourcePort):
    """Mock audio source emitting controlled silence or synthetic sine waves."""

    def __init__(self, sample_rate: int = 16000, chunk_size: int = 480):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self._is_active = False
        self.queue: list[np.ndarray] = []

    def start_stream(self) -> None:
        self._is_active = True

    def stop_stream(self) -> None:
        self._is_active = False

    def read_chunk(self, frame_size: int = 480) -> np.ndarray | None:
        if not self.queue:
            return None
        return self.queue.pop(0)

    def feed_silence(self, duration_ms: float = 300.0) -> None:
        num_frames = int(duration_ms / 30.0)
        for _ in range(num_frames):
            self.queue.append(np.zeros(self.chunk_size, dtype=np.float32))

    def feed_tone(self, freq: float = 440.0, duration_ms: float = 600.0) -> None:
        num_samples = int(self.sample_rate * (duration_ms / 1000.0))
        t = np.linspace(0, duration_ms / 1000.0, num_samples, endpoint=False)
        tone = 0.5 * np.sin(2 * np.pi * freq * t).astype(np.float32)
        for i in range(0, num_samples, self.chunk_size):
            chunk = tone[i : i + self.chunk_size]
            if len(chunk) == self.chunk_size:
                self.queue.append(chunk)


def test_mock_audio_source():
    source = MockAudioSource()
    source.feed_silence(90.0)
    assert len(source.queue) == 3
    chunk = source.read_chunk()
    assert chunk is not None
    assert len(chunk) == 480
    assert np.all(chunk == 0.0)


def test_silero_vad_silence_rejection():
    """Verifies that pure silence returns low speech probability."""
    vad = SileroVAD()
    silence_frame = np.zeros(480, dtype=np.float32)
    prob, _ = vad.evaluate_probability(silence_frame)
    assert prob < 0.2, f"Silence yielded unexpectedly high speech probability: {prob}"
    assert not vad.is_speech(silence_frame)


def test_speech_segmenter_silence_dropout():
    """Verifies that silence does not trigger speech segment emissions."""
    vad = SileroVAD()
    segmenter = SpeechSegmenter(vad=vad, trailing_silence_ms=250.0)

    # Feed 1 second of silence
    for _ in range(33):
        frame = np.zeros(480, dtype=np.float32)
        result = segmenter.process_frame(frame)
        assert result is None, "Segmenter emitted chunk on pure silence!"


def test_faster_whisper_synthetic_latency():
    """Verifies that ASR runs within the latency budget (< 800ms) on CPU."""
    asr = FasterWhisperASR(model_size_or_path="tiny.en", compute_type="int8")

    # Generate 1.5 seconds of synthetic audio (silence / low noise)
    sample_rate = 16000
    duration_s = 1.5
    dummy_audio = (0.01 * np.random.randn(int(sample_rate * duration_s))).astype(np.float32)

    # Steady-state inference timing
    t0 = time.perf_counter()
    segments = asr.transcribe(dummy_audio)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n[STEADY-STATE LATENCY] 1.5s audio transcribed in {elapsed_ms:.1f} ms")
    assert elapsed_ms < 800.0, f"Inference took {elapsed_ms:.1f}ms, exceeding 800ms exit gate!"

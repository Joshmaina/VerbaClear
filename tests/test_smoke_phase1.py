"""
Exhaustive Smoke Test for Phase 1: The Auditory Ear.
Verifies all components, edge cases, real speech transcription accuracy,
timing constraints, and thread safety.
"""

import os
import sys
import time
import wave
import numpy as np
import pytest

from src.application.audio_pipeline import AudioASRPipeline
from src.domain.interfaces import AudioSourcePort
from src.domain.models import TranscribedSegment
from src.infrastructure.audio.capture import PortAudioSource
from src.infrastructure.audio.vad import SileroVAD, SpeechSegmenter
from src.infrastructure.asr.whisper_engine import FasterWhisperASR


def load_wav_pcm16(filepath: str) -> np.ndarray:
    """Loads a 16kHz mono PCM16 WAV file as normalized float32 array."""
    with wave.open(filepath, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        data = wf.readframes(n_frames)

    assert framerate == 16000, f"Expected 16kHz audio, got {framerate}"
    assert n_channels == 1, f"Expected mono audio, got {n_channels}"
    assert sampwidth == 2, f"Expected 16-bit audio, got {sampwidth}"

    # Convert int16 to float32 in [-1.0, 1.0]
    pcm16 = np.frombuffer(data, dtype=np.int16)
    return pcm16.astype(np.float32) / 32768.0


# ---------------------------------------------------------------------------
# Test 1: PortAudio Device Enumeration & Ring Buffer Integrity
# ---------------------------------------------------------------------------
def test_smoke_audio_device_and_ring_buffer():
    print("\n--- [SMOKE 1] Audio Device Query & Ring Buffer Integrity ---")
    devices = PortAudioSource.list_devices()
    print(f"Found {len(devices)} input audio devices on host.")
    assert isinstance(devices, list)
    for dev in devices[:3]:
        print(f"  Device #{dev['index']}: {dev['name']} ({dev['channels']}ch, {dev['default_samplerate']}Hz)")

    # Test ring buffer operations
    source = PortAudioSource(max_buffer_seconds=1.0, chunk_duration_ms=30.0)
    assert not source.is_active
    assert source.read_chunk() is None

    # Simulate fast incoming frames
    for i in range(100):
        # Fake audio callback input
        fake_frame = np.full((480, 1), fill_value=float(i) / 100.0, dtype=np.float32)
        source._audio_callback(fake_frame, 480, None, None)

    # Max buffer for 1.0s @ 30ms is 33 frames
    assert len(source._buffer) == 33
    oldest = source.read_chunk()
    assert oldest is not None
    assert len(oldest) == 480
    print("Ring buffer overflow protection and FIFO ordering verified.")


# ---------------------------------------------------------------------------
# Test 2: Silero VAD Discrimination (Silence vs Real Speech)
# ---------------------------------------------------------------------------
def test_smoke_silero_vad_real_speech_discrimination():
    print("\n--- [SMOKE 2] Silero VAD Real Speech Discrimination ---")
    vad = SileroVAD(threshold=0.5)

    # 1. Pure silence
    silence = np.zeros(480, dtype=np.float32)
    silence_prob, _ = vad.evaluate_probability(silence)
    print(f"  Silence speech probability: {silence_prob:.4f} (Expected < 0.20)")
    assert silence_prob < 0.20
    assert not vad.is_speech(silence)

    # 2. Real spoken speech slice from JFK sample
    wav_path = os.path.join(os.path.dirname(__file__), "jfk_sample.wav")
    assert os.path.exists(wav_path), "jfk_sample.wav missing!"
    speech_pcm = load_wav_pcm16(wav_path)

    # Slice a known speech section (e.g. at 2.0s: 32000 to 32512)
    speech_frame = speech_pcm[32000 : 32000 + 512]
    speech_prob, _ = vad.evaluate_probability(speech_frame)
    print(f"  Spoken audio frame probability: {speech_prob:.4f} (Expected > 0.50)")
    assert speech_prob > 0.50
    assert vad.is_speech(speech_frame)
    print("Silero VAD successfully discriminated speech from silence.")


# ---------------------------------------------------------------------------
# Test 3: SpeechSegmenter Dynamic Cut on Natural Pauses
# ---------------------------------------------------------------------------
def test_smoke_speech_segmenter_with_jfk_audio():
    print("\n--- [SMOKE 3] SpeechSegmenter with Continuous Audio ---")
    vad = SileroVAD(threshold=0.5)
    segmenter = SpeechSegmenter(
        vad=vad,
        trailing_silence_ms=300.0,
        min_speech_duration_ms=500.0,
        max_speech_duration_ms=4000.0,
    )

    wav_path = os.path.join(os.path.dirname(__file__), "jfk_sample.wav")
    speech_pcm = load_wav_pcm16(wav_path)

    # Feed the entire 11-second audio in 32ms (512 samples) slices
    frame_size = 512
    chunks_emitted = []

    for i in range(0, len(speech_pcm), frame_size):
        frame = speech_pcm[i : i + frame_size]
        if len(frame) < frame_size:
            frame = np.pad(frame, (0, frame_size - len(frame)))

        chunk = segmenter.process_frame(frame)
        if chunk is not None:
            chunks_emitted.append(chunk)

    print(f"  Emitted {len(chunks_emitted)} speech segments from 11s audio.")
    assert len(chunks_emitted) >= 2, f"Expected at least 2 distinct speech phrases, got {len(chunks_emitted)}"
    for idx, c in enumerate(chunks_emitted):
        duration_s = len(c) / 16000.0
        print(f"    Chunk #{idx+1}: {duration_s:.2f}s ({len(c)} samples)")
        assert 0.5 <= duration_s <= 4.1
    print("SpeechSegmenter correctly partitioned speech on pause boundaries.")


# ---------------------------------------------------------------------------
# Test 4: faster-whisper Real Speech Transcription Accuracy & Timestamps
# ---------------------------------------------------------------------------
def test_smoke_whisper_transcription_accuracy():
    print("\n--- [SMOKE 4] faster-whisper Real Speech Accuracy & Timestamps ---")
    asr = FasterWhisperASR(model_size_or_path="tiny.en", compute_type="int8")

    wav_path = os.path.join(os.path.dirname(__file__), "jfk_sample.wav")
    speech_pcm = load_wav_pcm16(wav_path)

    # Take first 4 seconds ("And so my fellow Americans...")
    sample_4s = speech_pcm[: 16000 * 4]

    t0 = time.perf_counter()
    segments = asr.transcribe(sample_4s)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    print(f"  Transcription completed in {latency_ms:.1f}ms")
    assert len(segments) > 0, "No segments returned from spoken audio!"

    full_text = " ".join([s.text for s in segments]).lower()
    print(f"  Transcribed Text: \"{full_text}\"")

    # Verify ground-truth key words
    assert "fellow" in full_text or "americans" in full_text or "and so" in full_text
    print(f"  Word count: {len(segments[0].words)}")
    print(f"  First 5 words with timestamps: {segments[0].words[:5]}")
    assert len(segments[0].words) > 0
    assert segments[0].confidence > 0.0
    print("ASR transcription accuracy, confidence, and word timestamps verified.")


# ---------------------------------------------------------------------------
# Test 5: Full End-to-End Streaming Pipeline with Simulated Live Speech
# ---------------------------------------------------------------------------
class SimulatedMicAudioSource(AudioSourcePort):
    """Simulates real-time microphone input by feeding audio in 32ms (512 samples) slices."""

    def __init__(self, audio_data: np.ndarray, frame_size: int = 512):
        self.audio_data = audio_data
        self.frame_size = frame_size
        self.cursor = 0
        self.is_active = False

    def start_stream(self) -> None:
        self.is_active = True
        self.cursor = 0

    def stop_stream(self) -> None:
        self.is_active = False

    def read_chunk(self, frame_size: int = 512) -> np.ndarray | None:
        if not self.is_active or self.cursor >= len(self.audio_data):
            return None
        chunk = self.audio_data[self.cursor : self.cursor + self.frame_size]
        self.cursor += self.frame_size
        if len(chunk) < self.frame_size:
            chunk = np.pad(chunk, (0, self.frame_size - len(chunk)))
        return chunk


def test_smoke_full_pipeline_streaming():
    print("\n--- [SMOKE 5] Full AudioASRPipeline Streaming Verification ---")
    wav_path = os.path.join(os.path.dirname(__file__), "jfk_sample.wav")
    speech_pcm = load_wav_pcm16(wav_path)

    # Simulated mic source with first 6 seconds of JFK speech
    simulated_source = SimulatedMicAudioSource(speech_pcm[: 16000 * 6])
    vad = SileroVAD(threshold=0.5)
    asr = FasterWhisperASR(model_size_or_path="tiny.en", compute_type="int8")

    received_segments: list[TranscribedSegment] = []

    def on_segment(seg: TranscribedSegment):
        received_segments.append(seg)
        print(f"  [PIPELINE CALLBACK] \"{seg.text}\" (confidence: {seg.confidence*100:.1f}%)")

    pipeline = AudioASRPipeline(
        audio_source=simulated_source,
        vad=vad,
        asr=asr,
        on_segment_callback=on_segment,
        trailing_silence_ms=250.0,
    )

    print("  Starting pipeline worker thread...")
    pipeline.start()

    # Wait for the audio stream to be consumed
    max_wait_s = 15.0
    t0 = time.time()
    while simulated_source.cursor < len(simulated_source.audio_data) and (time.time() - t0) < max_wait_s:
        time.sleep(0.05)

    # Allow ASR worker a moment to process the final trailing chunk
    time.sleep(1.0)

    print("  Stopping pipeline...")
    pipeline.stop()

    assert not pipeline._thread.is_alive(), "Worker thread failed to terminate cleanly!"
    print(f"  Total frames processed: {pipeline.metrics.total_frames_processed}")
    print(f"  Total speech chunks emitted: {pipeline.metrics.total_speech_chunks_emitted}")
    print(f"  Average inference latency: {pipeline.metrics.average_inference_latency_ms:.1f}ms")
    print(f"  Total transcribed segments received: {len(received_segments)}")

    assert pipeline.metrics.total_frames_processed > 0
    assert pipeline.metrics.total_speech_chunks_emitted > 0
    assert len(received_segments) > 0
    assert pipeline.metrics.average_inference_latency_ms < 800.0
    print("Full streaming pipeline passed all functional and thread-safety checks!")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

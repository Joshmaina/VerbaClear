"""
Audio Processing Pipeline Orchestrator for VerbaClear.
Connects Audio Capture -> Silero VAD -> faster-whisper into a continuous streaming worker.
"""

from dataclasses import dataclass
import logging
import threading
import time
from typing import Callable, List, Optional
import numpy as np

from src.domain.interfaces import AudioSourcePort, SpeechToTextPort, VoiceActivityDetectorPort
from src.domain.models import TranscribedSegment
from src.infrastructure.audio.capture import PortAudioSource
from src.infrastructure.audio.vad import SileroVAD, SpeechSegmenter
from src.infrastructure.asr.whisper_engine import FasterWhisperASR

logger = logging.getLogger(__name__)


@dataclass
class AudioPipelineMetrics:
    total_frames_processed: int = 0
    total_speech_chunks_emitted: int = 0
    last_inference_latency_ms: float = 0.0
    average_inference_latency_ms: float = 0.0


class AudioASRPipeline:
    """
    Coordinates real-time audio capture, silence gating, and speech transcription.
    Runs worker loop on a dedicated thread to decouple compute from ASGI event loops.
    """

    def __init__(
        self,
        audio_source: Optional[AudioSourcePort] = None,
        vad: Optional[VoiceActivityDetectorPort] = None,
        asr: Optional[SpeechToTextPort] = None,
        on_segment_callback: Optional[Callable[[TranscribedSegment], None]] = None,
        trailing_silence_ms: float = 250.0,
    ):
        self.audio_source = audio_source or PortAudioSource()
        self.vad = vad or SileroVAD()
        self.segmenter = SpeechSegmenter(
            vad=self.vad,
            trailing_silence_ms=trailing_silence_ms,
        )
        self.asr = asr or FasterWhisperASR()
        self.on_segment_callback = on_segment_callback

        self.metrics = AudioPipelineMetrics()
        self._is_running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts audio capture and processing worker thread."""
        if self._is_running:
            logger.warning("Pipeline is already running.")
            return

        self._is_running = True
        self.audio_source.start_stream()

        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="AudioASRWorker")
        self._thread.start()
        logger.info("AudioASRPipeline worker thread started.")

    def stop(self) -> None:
        """Stops pipeline worker thread and shuts down audio stream."""
        if not self._is_running:
            return

        logger.info("Stopping AudioASRPipeline...")
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.audio_source.stop_stream()
        logger.info("AudioASRPipeline stopped.")

    def _worker_loop(self) -> None:
        """Main real-time consumer loop processing 30ms audio slices."""
        total_latency = 0.0
        count = 0

        while self._is_running:
            chunk = self.audio_source.read_chunk()
            if chunk is None:
                # No audio frames currently in ring buffer, yield CPU slice
                time.sleep(0.005)
                continue

            self.metrics.total_frames_processed += 1

            # Pass frame to VAD segmenter
            speech_chunk = self.segmenter.process_frame(chunk)
            if speech_chunk is not None:
                self.metrics.total_speech_chunks_emitted += 1

                # Audio chunk is ready for ASR inference
                t0 = time.perf_counter()
                try:
                    segments = self.asr.transcribe(speech_chunk)
                except Exception as e:
                    logger.error("Error during ASR transcription: %s", str(e), exc_info=True)
                    continue

                inference_ms = (time.perf_counter() - t0) * 1000.0
                self.metrics.last_inference_latency_ms = inference_ms
                count += 1
                total_latency += inference_ms
                self.metrics.average_inference_latency_ms = total_latency / count

                logger.debug(
                    "Transcribed %d segments in %.1f ms (chunk length: %.2f s)",
                    len(segments),
                    inference_ms,
                    len(speech_chunk) / 16000.0,
                )

                if self.on_segment_callback:
                    for seg in segments:
                        if seg.text:
                            self.on_segment_callback(seg)

#!/usr/bin/env python3
"""
Phase 1 Verification CLI: Live Microphone to Speech-to-Text.
Run this script to verify Exit Gate 1 using your local microphone or audio interface.
"""

import argparse
import sys
import time

from src.application.audio_pipeline import AudioASRPipeline
from src.domain.models import TranscribedSegment
from src.infrastructure.audio.capture import PortAudioSource
from src.infrastructure.audio.vad import SileroVAD
from src.infrastructure.asr.whisper_engine import FasterWhisperASR


def on_segment(seg: TranscribedSegment):
    print(f"\n[SPEECH DETECTED] ({seg.start_time_s:.2f}s -> {seg.end_time_s:.2f}s)")
    print(f"  Text:       \"{seg.text}\"")
    print(f"  Confidence: {seg.confidence * 100:.1f}%")
    print(f"  Words ({len(seg.words)}): {', '.join(seg.words)}")


def main():
    parser = argparse.ArgumentParser(description="VerbaClear Phase 1 Audio/ASR Live Runner")
    parser.add_argument("--list-devices", action="store_true", help="List available audio input devices")
    parser.add_argument("--device", type=int, default=None, help="Input device index (optional)")
    parser.add_argument("--model", type=str, default="base.en", help="faster-whisper model (e.g. tiny.en, base.en, small.en)")
    parser.add_argument("--threshold", type=float, default=0.5, help="VAD speech threshold (0.1 - 0.9)")
    args = parser.parse_args()

    if args.list_devices:
        print("\n=== Available Audio Input Devices ===")
        devices = PortAudioSource.list_devices()
        for dev in devices:
            print(f"  [{dev['index']}] {dev['name']} (Channels: {dev['channels']}, Default SR: {dev['default_samplerate']})")
        return

    print("==========================================================")
    print("      VerbaClear: Phase 1 (The Auditory Ear) Runner       ")
    print("==========================================================")
    print(f"Model:     {args.model}")
    print(f"Device:    {args.device if args.device is not None else 'Default System Mic'}")
    print(f"VAD Gate:  Threshold {args.threshold} (250ms trailing pause)")
    print("----------------------------------------------------------")

    audio_source = PortAudioSource(device_index=args.device)
    vad = SileroVAD(threshold=args.threshold)
    asr = FasterWhisperASR(model_size_or_path=args.model)

    pipeline = AudioASRPipeline(
        audio_source=audio_source,
        vad=vad,
        asr=asr,
        on_segment_callback=on_segment,
    )

    print("\n[READY] Listening to audio stream. Speak into your microphone!")
    print("Press Ctrl+C to terminate.\n")

    pipeline.start()

    try:
        while True:
            time.sleep(0.5)
            metrics = pipeline.metrics
            if metrics.total_speech_chunks_emitted > 0:
                sys.stdout.write(
                    f"\rFrames: {metrics.total_frames_processed} | "
                    f"Speech Chunks: {metrics.total_speech_chunks_emitted} | "
                    f"Last Latency: {metrics.last_inference_latency_ms:.1f}ms | "
                    f"Avg Latency: {metrics.average_inference_latency_ms:.1f}ms"
                )
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\n\nTerminating audio pipeline...")
        pipeline.stop()
        print("Pipeline shut down cleanly.")


if __name__ == "__main__":
    main()

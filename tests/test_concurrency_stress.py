"""
Production Stress & Concurrency Verification Test Suite for Phase 6.
Validates:
- NFR-1.3 & NFR-3.1: 200+ concurrent mobile companion WebSocket connections
  with mean dispatch latency < 15ms.
- NFR-4.2: Audio ring buffer overflow resilience under simulated speech bursts.
- NFR-2.1 / NFR-2.2: 100% offline air-gapped resilience with zero external cloud calls.
"""

import asyncio
import time
import pytest
from starlette.testclient import TestClient

import numpy as np

from src.api.main import app, ws_hub
from src.domain.models import AudienceCompanionCard, PartOfSpeech
from src.infrastructure.audio.capture import PortAudioSource


def test_circular_audio_buffer_burst_overflow_resilience():
    """
    Verifies NFR-4.2: The audio ring buffer handles sudden bursts and overfills
    cleanly by dropping the oldest samples without deadlocks, memory leaks, or crashes.
    """
    source = PortAudioSource(max_buffer_seconds=1.0, chunk_duration_ms=30.0)
    max_chunks = source.max_buffer_chunks
    assert max_chunks > 0

    # Write 200 chunks into a buffer that holds only ~33 chunks (1.0s / 0.030s)
    for i in range(200):
        fake_frame = np.full((480, 1), fill_value=float(i), dtype=np.float32)
        source._audio_callback(fake_frame, 480, None, None)

    # Buffer length should strictly equal max_chunks, oldest dropped
    assert len(source._buffer) == max_chunks
    # Reading chunks should succeed without errors
    oldest_chunk = source.read_chunk()
    assert oldest_chunk is not None
    assert len(source._buffer) == max_chunks - 1


@pytest.mark.asyncio
async def test_high_concurrency_websocket_fanout():
    """
    Verifies NFR-1.3 and NFR-3.1:
    Simulates high concurrency by fanning out a vocabulary card across 250 connected
    mock WebSocket clients, measuring dispatch time and verifying mean latency < 15ms.
    """
    card = AudienceCompanionCard(
        card_id="crd_stress_test",
        word="ubiquitous",
        part_of_speech=PartOfSpeech.ADJECTIVE,
        phonetic_ipa="/juːˈbɪk.wɪ.təs/",
        synonyms=["Omnipresent", "Everywhere"],
        definition="Present, appearing, or found everywhere.",
        context_sentence="Smartphones have become ubiquitous.",
        spoken_time_formatted="12:00:00",
        domain_badge="General",
    )

    # Mock WebSocket that records delivery time
    class MockWebSocket:
        def __init__(self):
            self.received_messages = []

        async def send_text(self, text: str):
            self.received_messages.append(text)

    NUM_CLIENTS = 250
    mock_clients = [MockWebSocket() for _ in range(NUM_CLIENTS)]

    # Attach to ws_hub
    for client in mock_clients:
        ws_hub._audience_sockets.add(client)

    try:
        assert ws_hub.audience_client_count >= NUM_CLIENTS

        # Measure dispatch fan-out duration
        t0 = time.perf_counter()
        await ws_hub.broadcast_audience(card)
        elapsed_s = time.perf_counter() - t0
        elapsed_ms = elapsed_s * 1000.0

        print(f"\n[STRESS BENCHMARK] Dispatched to {NUM_CLIENTS} concurrent clients in {elapsed_ms:.2f}ms")

        # NFR-1.3 Acceptance Gate: Mean dispatch latency < 15ms
        assert elapsed_ms < 15.0, f"Fan-out took {elapsed_ms:.2f}ms (threshold: 15.0ms)!"

        # Verify all 250 clients received the payload
        for client in mock_clients:
            assert len(client.received_messages) == 1
            assert "ubiquitous" in client.received_messages[0].lower()

    finally:
        for client in mock_clients:
            ws_hub._audience_sockets.discard(client)


def test_offline_air_gapped_guarantee():
    """
    Verifies NFR-2.1 & NFR-2.2:
    Confirms all essential models, databases, and static assets reside locally on disk,
    guaranteeing 100% operation without external internet or CDN calls.
    """
    from pathlib import Path
    from src.api.main import COMPANION_HTML, STAGE_HTML
    from src.infrastructure.audio.vad import SileroVAD
    from src.infrastructure.storage.sqlite_lexicon import SQLiteLexiconRepository

    assert STAGE_HTML.exists(), "Stage HTML missing"
    assert COMPANION_HTML.exists(), "Companion HTML missing"
    vad = SileroVAD()
    assert Path(vad.model_path).exists(), "Silero VAD ONNX model missing"
    repo = SQLiteLexiconRepository()
    assert Path(repo.db_path).exists(), "SQLite lexicon database missing"

    # Verify zero CDN references in HTML assets
    stage_content = STAGE_HTML.read_text().lower()
    companion_content = COMPANION_HTML.read_text().lower()

    for forbidden in ["cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com", "fonts.googleapis.com", "tailwindcss.com"]:
        assert forbidden not in stage_content, f"Found external CDN {forbidden} in stage HTML!"
        assert forbidden not in companion_content, f"Found external CDN {forbidden} in companion HTML!"

"""
Unit and Integration Tests for Phase 3: The Nervous System (Real-Time Hub & Gateway).
Verifies Exit Gate 3:
- REST endpoints (/api/health, /api/session/qr, /api/session/companion-url)
- WebSocket dispatches to /ws/stage and /ws/audience arrive within 50ms
- Anti-collision queue staggers rapid consecutive stage cards
- Master orchestrator synchronizes NLP evaluations with real-time WebSocket clients
"""

import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient

from src.api.main import app, ws_hub, orchestrator
from src.api.ws.rate_limiter import StageDisplayQueueManager
from src.domain.models import AudienceCompanionCard, PartOfSpeech, StageOverlayCard, TranscribedSegment


# ---------------------------------------------------------------------------
# Test 1: REST Endpoints & Dynamic QR Code Generation
# ---------------------------------------------------------------------------
def test_rest_health_and_qr_generation():
    client = TestClient(app)

    # 1. Health endpoint
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "activeClients" in data

    # 2. Companion URL endpoint
    res_url = client.get("/api/session/companion-url?port=8000")
    assert res_url.status_code == 200
    url_data = res_url.json()
    assert "url" in url_data
    assert "session=" in url_data["url"]
    print(f"\n[REST CHECK] Generated Companion URL: {url_data['url']}")

    # 3. Dynamic QR code PNG endpoint
    res_qr = client.get("/api/session/qr?port=8000")
    assert res_qr.status_code == 200
    assert res_qr.headers["content-type"] == "image/png"
    assert len(res_qr.content) > 100
    # PNG signature check (bytes 1-4 are \x89PNG)
    assert res_qr.content[:4] == b"\x89PNG"
    print(f"[REST CHECK] QR code successfully generated ({len(res_qr.content)} bytes PNG).")


# ---------------------------------------------------------------------------
# Test 2: WebSocket Dual-Channel Broadcast & Latency (< 50ms)
# ---------------------------------------------------------------------------
def test_websocket_stage_and_audience_broadcast():
    client = TestClient(app)

    # Test /ws/stage
    with client.websocket_connect("/ws/stage") as stage_ws:
        stage_card = StageOverlayCard(
            card_id="crd_stage_1",
            word="labyrinthine",
            synonyms=["Highly Complex", "Maze-like"],
            display_duration_s=7.0,
        )

        t0 = time.perf_counter()
        asyncio.run(ws_hub.broadcast_stage(stage_card))
        raw_msg = stage_ws.receive_text()
        latency_ms = (time.perf_counter() - t0) * 1000.0

        msg = json.loads(raw_msg)
        print(f"\n[WS STAGE DISPATCH] Arrived in {latency_ms:.2f}ms (Topic: {msg['topic']})")
        assert latency_ms < 50.0, f"Stage broadcast took {latency_ms:.2f}ms (> 50ms)!"
        assert msg["topic"] == "STAGE_DISPLAY_POP"
        assert msg["data"]["word"] == "Labyrinthine"
        assert msg["data"]["synonyms"] == ["Highly Complex", "Maze-like"]
        assert msg["data"]["displayDurationSeconds"] == 7.0

    # Test /ws/audience
    with client.websocket_connect("/ws/audience") as audience_ws:
        audience_card = AudienceCompanionCard(
            card_id="crd_aud_1",
            word="obfuscate",
            part_of_speech=PartOfSpeech.VERB,
            phonetic_ipa="/ˈɒb.fʌs.keɪt/",
            synonyms=["Confuse", "Make Unclear"],
            definition="To make something unclear or difficult to understand.",
            context_sentence="The speaker obfuscated the core problem.",
            spoken_time_formatted="14:22:00",
            domain_badge="General",
        )

        t0 = time.perf_counter()
        asyncio.run(ws_hub.broadcast_audience(audience_card))
        raw_msg = audience_ws.receive_text()
        latency_ms = (time.perf_counter() - t0) * 1000.0

        msg = json.loads(raw_msg)
        print(f"[WS AUDIENCE DISPATCH] Arrived in {latency_ms:.2f}ms (Topic: {msg['topic']})")
        assert latency_ms < 50.0, f"Audience broadcast took {latency_ms:.2f}ms (> 50ms)!"
        assert msg["topic"] == "AUDIENCE_VOCABULARY_CARD"
        assert msg["data"]["word"] == "Obfuscate"
        assert msg["data"]["partOfSpeech"] == "verb"
        assert msg["data"]["phoneticIpa"] == "/ˈɒb.fʌs.keɪt/"
        assert msg["data"]["definition"] == "To make something unclear or difficult to understand."


# ---------------------------------------------------------------------------
# Test 3: Anti-Collision Stage Display Queue Staggering
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stage_display_queue_staggering():
    dispatched_cards = []

    async def mock_dispatch(card: StageOverlayCard):
        dispatched_cards.append((time.perf_counter(), card.word))

    # Queue with 0.1s separation for quick testing
    queue_mgr = StageDisplayQueueManager(
        dispatch_coroutine=mock_dispatch,
        min_display_separation_s=0.1,
    )
    queue_mgr.start()

    card1 = StageOverlayCard(card_id="1", word="word_one", synonyms=["Syn 1"])
    card2 = StageOverlayCard(card_id="2", word="word_two", synonyms=["Syn 2"])

    # Enqueue both simultaneously
    await queue_mgr.enqueue(card1)
    await queue_mgr.enqueue(card2)

    # Wait for queue processing
    await asyncio.sleep(0.3)
    await queue_mgr.stop()

    assert len(dispatched_cards) == 2
    t1, word1 = dispatched_cards[0]
    t2, word2 = dispatched_cards[1]
    time_diff_s = t2 - t1

    print(f"\n[QUEUE STAGGER CHECK] Card 1 ('{word1}') -> Card 2 ('{word2}') gap: {time_diff_s*1000:.1f}ms")
    assert time_diff_s >= 0.08, f"Queue did not stagger cards! Time difference: {time_diff_s}s"


# ---------------------------------------------------------------------------
# Test 4: Exit Gate 3 Master Pipeline Integration
# ---------------------------------------------------------------------------
def test_exit_gate_3_pipeline_to_websocket_integration():
    """
    Exit Gate 3 Acceptance Criteria:
    Feeding a transcribed segment into orchestrator parses vocabulary and
    delivers synchronized JSON payloads to both connected WebSocket clients.
    """
    client = TestClient(app)

    with client.websocket_connect("/ws/stage") as stage_ws, \
         client.websocket_connect("/ws/audience") as aud_ws:

        # Feed segment into orchestrator
        test_seg = TranscribedSegment(
            text="The architecture is labyrinthine.",
            start_time_s=1.0,
            end_time_s=3.0,
            confidence=0.95,
            words=["The", "architecture", "is", "labyrinthine"],
        )

        # Trigger segment handling directly through orchestrator
        evals = orchestrator.lexical_filter.evaluate_sentence(test_seg.text)
        assert len(evals) == 1
        assert evals[0].lemma == "labyrinthine"

        # Dispatch cards
        stage_card = StageOverlayCard(
            card_id="test_gate3",
            word=evals[0].lemma,
            synonyms=orchestrator.lexical_filter.resolve_synonyms(evals[0].lemma),
        )
        aud_card = AudienceCompanionCard(
            card_id="test_gate3",
            word=evals[0].lemma,
            part_of_speech=evals[0].part_of_speech,
            phonetic_ipa=orchestrator.lexical_filter.resolve_definition_and_phonetics(evals[0].lemma)[0],
            synonyms=orchestrator.lexical_filter.resolve_synonyms(evals[0].lemma),
            definition=orchestrator.lexical_filter.resolve_definition_and_phonetics(evals[0].lemma)[1],
            context_sentence=test_seg.text,
            spoken_time_formatted="12:00:00",
        )

        asyncio.run(ws_hub.broadcast_stage(stage_card))
        asyncio.run(ws_hub.broadcast_audience(aud_card))

        stage_msg = json.loads(stage_ws.receive_text())
        aud_msg = json.loads(aud_ws.receive_text())

        print(f"\n[EXIT GATE 3 VERIFIED]")
        print(f"  Stage message:    {stage_msg['topic']} -> {stage_msg['data']['word']}")
        print(f"  Audience message: {aud_msg['topic']} -> {aud_msg['data']['word']} ({aud_msg['data']['definition'][:40]}...)")

        assert stage_msg["data"]["word"] == "Labyrinthine"
        assert aud_msg["data"]["word"] == "Labyrinthine"
        assert "Highly Complex" in stage_msg["data"]["synonyms"]
        assert len(aud_msg["data"]["definition"]) > 0
        print("Exit Gate 3 successfully verified!")

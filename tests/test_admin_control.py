"""
Tests for AV Operator Control Room Dashboard & API.
Validates:
- GET /admin HTML delivery
- Real-time telemetry payload structure
- Stage emergency blackout & dismissal controls
- Manual vocabulary injection
- Microphone mute toggling
"""

import json
import pytest
from fastapi.testclient import TestClient

from src.api.main import app, orchestrator, ws_hub
from src.domain.models import StageOverlayCard


@pytest.fixture
def client():
    return TestClient(app)


def test_admin_dashboard_serves_html(client):
    """Verifies that GET /admin serves the AV operator control room dashboard."""
    response = client.get("/admin")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

    html_content = response.text
    assert "VerbaClear AV Operator Console" in html_content
    assert 'id="vu-meter-fill"' in html_content
    assert 'id="btn-stage-blackout"' in html_content
    assert 'id="btn-stage-dismiss"' in html_content
    assert 'id="btn-toggle-mute"' in html_content
    assert 'id="injection-form"' in html_content
    assert "/ws/telemetry" in html_content


def test_control_state_endpoint(client):
    """Verifies GET /api/control/state returns complete telemetry."""
    response = client.get("/api/control/state")
    assert response.status_code == 200
    data = response.json()

    assert "sessionId" in data
    assert "isActive" in data
    assert "isMuted" in data
    assert "vuRms" in data
    assert "vuDbfs" in data
    assert "vadProb" in data
    assert "connectedStageClients" in data
    assert "connectedAudienceClients" in data
    assert "connectedTelemetryClients" in data
    assert "stageQueueDepth" in data


def test_stage_blackout_and_dismiss_controls(client):
    """
    Verifies that emergency blackout purges the queue and dispatches STAGE_BLACKOUT,
    and dismissal dispatches STAGE_DISMISS.
    """
    with client.websocket_connect("/ws/stage") as ws:
        # Enqueue dummy card
        dummy_card = StageOverlayCard(
            card_id="crd_blackout_test",
            word="esoteric",
            synonyms=["Obscure"],
            display_duration_s=7.0,
        )
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(orchestrator.stage_queue.enqueue(dummy_card))
        finally:
            loop.close()

        # Trigger Blackout
        blackout_resp = client.post("/api/control/stage/blackout")
        assert blackout_resp.status_code == 200
        blackout_data = blackout_resp.json()
        assert blackout_data["action"] == "STAGE_BLACKOUT"
        assert orchestrator.stage_queue.queue_size == 0

        # Receive frame from stage WebSocket
        msg = ws.receive_text()
        frame = json.loads(msg)
        assert frame["topic"] in ["STAGE_BLACKOUT", "STAGE_DISPLAY_POP"]

        # Trigger Dismiss
        dismiss_resp = client.post("/api/control/stage/dismiss")
        assert dismiss_resp.status_code == 200
        assert dismiss_resp.json()["action"] == "STAGE_DISMISS"


def test_manual_card_injection(client):
    """Verifies that an operator can manually inject a vocabulary card to stage & audience."""
    with client.websocket_connect("/ws/audience") as ws:
        payload = {
            "word": "Omnichannel",
            "synonyms": ["Integrated", "Multi-platform"],
            "definition": "A unified retail and communication experience across all channels.",
            "phoneticIpa": "/ˌɒm.nɪˈtʃæn.əl/",
            "durationSeconds": 6.0,
            "domainBadge": "Retail Tech",
        }

        resp = client.post("/api/control/stage/inject", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "CARD_INJECTED"
        assert data["word"] == "Omnichannel"

        # Verify audience client receives the injected card
        msg = ws.receive_text()
        feed_frame = json.loads(msg)
        assert feed_frame["topic"] == "AUDIENCE_VOCABULARY_CARD"
        assert feed_frame["data"]["word"] == "Omnichannel"
        assert "Multi-platform" in feed_frame["data"]["synonyms"]
        assert feed_frame["data"]["domainBadge"] == "Retail Tech"

        # Drain stage queue so subsequent tests run on a fresh queue
        orchestrator.stage_queue.clear_queue()


def test_audio_mute_toggle(client):
    """Verifies that the operator can mute and unmute live audio input."""
    initial_muted = orchestrator.audio_pipeline.is_muted

    resp = client.post("/api/control/audio/toggle")
    assert resp.status_code == 200
    assert resp.json()["isMuted"] == (not initial_muted)
    assert orchestrator.audio_pipeline.is_muted == (not initial_muted)

    # Toggle back to original state
    resp2 = client.post("/api/control/audio/toggle")
    assert resp2.status_code == 200
    assert resp2.json()["isMuted"] == initial_muted


def test_persistent_stage_blackout_state_and_resumption(client):
    """
    Verifies that stage blackout maintains persistent state:
    1. Blackout suppresses new cards from reaching stage_queue while still broadcasting to audience.
    2. Telemetry reflects isStageBlackout state.
    3. New stage WebSocket connections immediately receive STAGE_BLACKOUT when active.
    4. Disengaging blackout resumes normal card queuing.
    """
    try:
        # Ensure starting in non-blackout state
        if orchestrator.is_stage_blackout:
            client.post("/api/control/stage/blackout", json={"state": False})

        assert orchestrator.is_stage_blackout is False

        # 1. Engage blackout
        resp = client.post("/api/control/stage/blackout", json={"state": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["isBlackout"] is True
        assert orchestrator.is_stage_blackout is True

        # 2. Check telemetry endpoint
        state_resp = client.get("/api/control/state")
        assert state_resp.status_code == 200
        assert state_resp.json()["isStageBlackout"] is True

        # 3. New stage connection receives STAGE_BLACKOUT immediately
        with client.websocket_connect("/ws/stage") as stage_ws:
            msg = stage_ws.receive_text()
            frame = json.loads(msg)
            assert frame["topic"] == "STAGE_BLACKOUT"
            assert frame["isBlackout"] is True

        # 4. Injected card during blackout emits audience card but suppresses stage card
        with client.websocket_connect("/ws/audience") as aud_ws:
            inj_resp = client.post("/api/control/stage/inject", json={
                "word": "Cryptic",
                "synonyms": ["Mysterious"],
                "definition": "Difficult to understand; obscure.",
                "durationSeconds": 5.0,
            })
            assert inj_resp.status_code == 200

            # Audience receives the card
            aud_msg = aud_ws.receive_text()
            aud_frame = json.loads(aud_msg)
            assert aud_frame["topic"] == "AUDIENCE_VOCABULARY_CARD"
            assert aud_frame["data"]["word"] == "Cryptic"

            # Stage queue remains empty because blackout suppressed it
            assert orchestrator.stage_queue.queue_size == 0

        # 5. Disengage blackout
        resume_resp = client.post("/api/control/stage/blackout", json={"state": False})
        assert resume_resp.status_code == 200
        assert resume_resp.json()["isBlackout"] is False
        assert orchestrator.is_stage_blackout is False

        state_resp2 = client.get("/api/control/state")
        assert state_resp2.json()["isStageBlackout"] is False
    finally:
        orchestrator.is_stage_blackout = False


def test_stage_queue_delay_interruption():
    """Verifies that interrupt_delay wakes an active wait in StageDisplayQueueManager immediately."""
    import asyncio
    from src.api.ws.rate_limiter import StageDisplayQueueManager
    dispatched_cards = []

    async def mock_dispatch(card):
        dispatched_cards.append(card)

    queue_mgr = StageDisplayQueueManager(
        dispatch_coroutine=mock_dispatch,
        min_display_separation_s=10.0,  # Long delay
    )

    loop = asyncio.new_event_loop()
    try:
        queue_mgr.start(loop=loop)

        card1 = StageOverlayCard(card_id="c1", word="First", synonyms=["1"], display_duration_s=5.0)
        card2 = StageOverlayCard(card_id="c2", word="Second", synonyms=["2"], display_duration_s=5.0)

        async def run_test():
            await queue_mgr.enqueue(card1)
            await queue_mgr.enqueue(card2)
            # Give short moment for card1 to dispatch
            await asyncio.sleep(0.05)
            assert len(dispatched_cards) == 1
            assert dispatched_cards[0].word == "First"

            # Worker is now blocked in the 10.0s delay. Interrupt it!
            queue_mgr.interrupt_delay()
            await asyncio.sleep(0.05)

            # Card2 should be dispatched immediately without waiting 10s
            assert len(dispatched_cards) == 2
            assert dispatched_cards[1].word == "Second"

            await queue_mgr.stop()

        loop.run_until_complete(run_test())
    finally:
        loop.close()


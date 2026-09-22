"""
Tests for Phase 4: Primary Stage Presentation Screen (The Ambient Eye).
Validates HTML overlay delivery, WebSocket contract, and display queuing.
"""

import asyncio
import json
import pytest
from fastapi.testclient import TestClient

from src.api.main import app, ws_hub
from src.domain.models import StageOverlayCard


@pytest.fixture
def client():
    return TestClient(app)


def test_stage_endpoint_returns_html(client):
    """Verifies that GET /stage serves the standalone lower-third HTML."""
    response = client.get("/stage")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

    html_content = response.text
    # Check for core structural elements
    assert "VerbaClear Stage Display Overlay" in html_content
    assert 'id="stage-container"' in html_content
    assert 'id="overlay-card"' in html_content
    assert 'id="original-word"' in html_content
    assert 'id="synonyms-container"' in html_content
    assert 'id="progress-fill"' in html_content
    assert 'id="timer-display"' in html_content
    assert 'id="connection-indicator"' in html_content
    assert "/ws/stage" in html_content


def test_stage_websocket_receives_pop_event(client):
    """
    Verifies that a connected stage client receives the STAGE_DISPLAY_POP event
    with correct word, synonyms list, and duration.
    """
    with client.websocket_connect("/ws/stage") as ws:
        assert ws_hub.stage_client_count >= 1

        card = StageOverlayCard(
            card_id="test_001",
            word="labyrinthine",
            synonyms=["Highly Complex", "Maze-like"],
            display_duration_s=7.0,
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(ws_hub.broadcast_stage(card))
        finally:
            loop.close()

        # Receive from client
        msg = ws.receive_text()
        data = json.loads(msg)

        assert data["topic"] == "STAGE_DISPLAY_POP"
        assert data["data"]["word"] == "Labyrinthine"
        assert len(data["data"]["synonyms"]) == 2
        assert data["data"]["synonyms"][0] == "Highly Complex"
        assert data["data"]["displayDurationSeconds"] == 7.0


def test_stage_css_options():
    """Verifies that CSS styles contain Chroma key and anchor positioning classes."""
    from src.api.main import STAGE_HTML
    content = STAGE_HTML.read_text()

    assert ".theme-chroma" in content
    assert "#00ff00" in content  # Chroma green key
    assert ".pos-bottom-right" in content
    assert ".pos-bottom-left" in content
    assert ".pos-bottom-center" in content
    assert "backdrop-filter: blur" in content  # Glassmorphism
    assert "decayAnimation" in content  # Linear decay bar

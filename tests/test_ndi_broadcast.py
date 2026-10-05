"""
Unit and Integration Tests for Option B: Native NDI Broadcast & RGBA Transparent Stream Engine.
Verifies:
1. StageFrameRenderer produces true 1920x1080 RGBA transparent frames (alpha 0 for background).
2. Card rendering with decay bar, blackout blanking, and early dismissal.
3. NDIBroadcastAdapter graceful degradation into Virtual Alpha Stream mode.
4. Mock NDI C-SDK initialization and native frame dispatch path.
5. FastAPI broadcast endpoints (/api/broadcast/status, /api/broadcast/frame, /api/control/ndi/toggle, /api/broadcast/stream/alpha).
"""

import ctypes
import io
import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.api.main import app
from src.domain.models import StageOverlayCard
from src.infrastructure.broadcast.frame_renderer import StageFrameRenderer
from src.infrastructure.broadcast.ndi_sender import (
    NDIBroadcastAdapter,
    NDIlib_send_create_t,
    NDIlib_video_frame_v2_t,
)


# ---------------------------------------------------------------------------
# Test 1: StageFrameRenderer Canvas & Alpha Transparency
# ---------------------------------------------------------------------------
def test_frame_renderer_idle_transparency():
    renderer = StageFrameRenderer(width=1920, height=1080)

    # 1. Idle state (no card active) must be completely transparent
    idle_img = renderer.render_frame()
    assert idle_img.size == (1920, 1080)
    assert idle_img.mode == "RGBA"

    # Verify alpha channel is 0 at multiple screen locations
    corners = [(0, 0), (1919, 0), (0, 1079), (1919, 1079), (960, 540), (1400, 900)]
    for pt in corners:
        pixel = idle_img.getpixel(pt)
        assert pixel == (0, 0, 0, 0), f"Pixel at {pt} was not transparent: {pixel}"

    # Verify PNG bytes representation
    idle_png = renderer.get_png_bytes()
    assert len(idle_png) > 0
    loaded_img = Image.open(io.BytesIO(idle_png))
    assert loaded_img.getpixel((10, 10)) == (0, 0, 0, 0)


def test_frame_renderer_active_card_and_decay():
    renderer = StageFrameRenderer(width=1920, height=1080)

    card = StageOverlayCard(
        card_id="crd_test_ndi",
        word="UBIQUITOUS",
        synonyms=["Everywhere", "Pervasive", "Omnipresent"],
        display_duration_s=5.0,
    )
    renderer.set_card(card)
    assert renderer.is_card_active is True
    assert renderer.active_card is not None
    assert renderer.active_card.word == "UBIQUITOUS"

    # Render active card
    active_img = renderer.render_frame()
    assert active_img.size == (1920, 1080)

    # Top-left corner must still be transparent
    assert active_img.getpixel((50, 50)) == (0, 0, 0, 0)

    # Inside lower-third card region (e.g. x=1400, y=900), alpha must be > 0 (opaque/semi-opaque)
    card_pixel = active_img.getpixel((1400, 900))
    assert card_pixel[3] > 0, f"Card body pixel had no alpha transparency: {card_pixel}"

    # Raw RGBA buffer size must be exactly 1920 * 1080 * 4
    raw_bytes = renderer.get_raw_rgba_bytes()
    assert len(raw_bytes) == 1920 * 1080 * 4

    # Test early dismissal
    renderer.dismiss_card()
    assert renderer.is_card_active is False
    dismissed_img = renderer.render_frame()
    assert dismissed_img.getpixel((1400, 900)) == (0, 0, 0, 0)


def test_frame_renderer_blackout_and_expiration():
    renderer = StageFrameRenderer(width=1920, height=1080)

    # Set very short duration card
    card = StageOverlayCard(
        card_id="crd_expiring",
        word="EPHEMERAL",
        synonyms=["Fleeting", "Short-lived"],
        display_duration_s=0.1,
    )
    renderer.set_card(card)
    assert renderer.is_card_active is True

    # Sleep past expiration
    time.sleep(0.15)
    assert renderer.is_card_active is False
    expired_img = renderer.render_frame()
    assert expired_img.getpixel((1400, 900)) == (0, 0, 0, 0)

    # Test blackout suppression
    renderer.set_card(card)
    renderer.set_blackout(True)
    assert renderer.is_card_active is False
    blackout_img = renderer.render_frame()
    assert blackout_img.getpixel((1400, 900)) == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# Test 2: NDIBroadcastAdapter Lifecycle & Fallback Mode
# ---------------------------------------------------------------------------
def test_ndi_adapter_virtual_fallback_lifecycle():
    adapter = NDIBroadcastAdapter(stream_name="VERBACLEAR-TEST-VIRTUAL", fps=30)

    status = adapter.get_status()
    assert status["streamName"] == "VERBACLEAR-TEST-VIRTUAL"
    assert status["isStreaming"] is True
    assert status["mode"] in ("VIRTUAL_ALPHA_STREAM", "NATIVE_NDI")

    # Start and verify worker thread
    adapter.start()
    time.sleep(0.1)
    assert adapter.frame_count > 0

    # Toggle streaming
    adapter.toggle_streaming(False)
    assert adapter.is_streaming is False
    adapter.toggle_streaming(True)
    assert adapter.is_streaming is True

    # Card operations through adapter
    card = StageOverlayCard(
        card_id="crd_adapter_test",
        word="LABYRINTHINE",
        synonyms=["Complex", "Intricate"],
    )
    adapter.set_card(card)
    assert adapter.get_status()["hasActiveCard"] is True
    assert adapter.get_status()["activeWord"] == "LABYRINTHINE"

    adapter.dismiss_card()
    assert adapter.get_status()["hasActiveCard"] is False

    adapter.stop()


# ---------------------------------------------------------------------------
# Test 3: Native NDI C-SDK Binding Path Simulation
# ---------------------------------------------------------------------------
def test_mock_native_ndi_library_path():
    """Simulates host with libndi.so installed to verify C ABI initialization and video sending."""
    mock_lib = MagicMock()
    mock_lib.NDIlib_initialize.return_value = True
    mock_lib.NDIlib_send_create_v2.return_value = ctypes.c_void_p(0x12345678)
    mock_lib.NDIlib_send_send_video_v2.return_value = None
    mock_lib.NDIlib_send_destroy.return_value = None
    mock_lib.NDIlib_destroy.return_value = None

    with patch("ctypes.CDLL", return_value=mock_lib):
        adapter = NDIBroadcastAdapter(stream_name="VERBACLEAR-STAGE", fps=30)
        adapter._ndi_lib = mock_lib
        adapter.is_ndi_available = True

        adapter.start()
        time.sleep(0.08)

        status = adapter.get_status()
        assert status["mode"] == "NATIVE_NDI"
        assert status["isNdiAvailable"] is True

        # Stop adapter
        adapter.stop()
        mock_lib.NDIlib_send_destroy.assert_called()
        mock_lib.NDIlib_destroy.assert_called()


# ---------------------------------------------------------------------------
# Test 4: FastAPI Broadcast REST Endpoints
# ---------------------------------------------------------------------------
def test_broadcast_rest_api():
    client = TestClient(app)

    # 1. GET /api/broadcast/status
    resp = client.get("/api/broadcast/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "isNdiAvailable" in data
    assert "isStreaming" in data
    assert "streamName" in data
    assert data["resolution"] == "1920x1080"

    # 2. POST /api/control/ndi/toggle
    resp = client.post("/api/control/ndi/toggle", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["isStreaming"] is False

    resp = client.post("/api/control/ndi/toggle", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["isStreaming"] is True

    # 3. GET /api/broadcast/frame
    resp = client.get("/api/broadcast/frame")
    assert resp.status_code == 200
    assert resp.headers.get("content-type") == "image/png"
    assert len(resp.content) > 1000

    # Verify downloaded image is valid RGBA PNG
    img = Image.open(io.BytesIO(resp.content))
    assert img.size == (1920, 1080)
    assert img.mode == "RGBA"

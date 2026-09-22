"""
Session & QR Code REST Endpoints for VerbaClear.
Provides local network discovery, dynamic attendee QR onboarding, and telemetry.
"""

import io
import logging
import socket
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
import qrcode

router = APIRouter(prefix="/api/session", tags=["Session"])
logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Detects local LAN IP address for venue Wi-Fi access."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually transmit packets, just routes to local interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


@router.get("/status")
async def get_session_status():
    """Returns active session status and connected client counts."""
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    return orchestrator.get_telemetry()


@router.get("/qr")
async def get_session_qr(
    port: int = Query(8000, description="Server port"),
    host_override: Optional[str] = Query(None, description="Custom host or domain override"),
):
    """
    Generates a high-contrast QR code pointing to the audience companion portal.
    Attendees scanning this code are directed immediately to the local venue mobile web app.
    """
    from src.api.main import orchestrator
    session_id = orchestrator.session_id if orchestrator else "default"

    host = host_override if host_override else get_local_ip()
    companion_url = f"http://{host}:{port}/companion?session={session_id}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(companion_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"X-Companion-URL": companion_url},
    )


@router.get("/companion-url")
async def get_companion_url(
    port: int = Query(8000),
    host_override: Optional[str] = None,
):
    """Returns the raw companion URL string for embed/display."""
    from src.api.main import orchestrator
    session_id = orchestrator.session_id if orchestrator else "default"
    host = host_override if host_override else get_local_ip()
    return {
        "url": f"http://{host}:{port}/companion?session={session_id}",
        "localIp": host,
        "port": port,
        "sessionId": session_id,
    }


@router.get("/cards")
async def get_session_cards():
    """
    Returns all vocabulary cards emitted during the active session.
    Allows late-joining mobile companion attendees to populate their feed with past words.
    """
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    cards = orchestrator.get_session_cards()
    from src.infrastructure.export.anki_exporter import _sanitize_card
    return [
        _sanitize_card(c) for c in cards
    ]


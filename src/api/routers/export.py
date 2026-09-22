"""
Export REST Endpoints for VerbaClear.
Provides server-side generation of Anki (.apkg), TSV, and CSV flashcard decks.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from src.infrastructure.export.anki_exporter import (
    generate_anki_apkg,
    generate_anki_tsv,
    generate_csv,
    generate_json,
)

router = APIRouter(prefix="/api/export", tags=["Export"])
logger = logging.getLogger(__name__)


class ExportRequest(BaseModel):
    cards: Optional[List[Dict[str, Any]]] = None
    deckName: Optional[str] = "VerbaClear Event Vocabulary"


def _resolve_cards(request_cards: Optional[List[Dict[str, Any]]]) -> List[Any]:
    """Resolves cards from the request payload or falls back to current session history."""
    if request_cards is not None and len(request_cards) > 0:
        return request_cards

    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    session_cards = orchestrator.get_session_cards()
    if not session_cards:
        # Return empty or sample if nothing recorded yet
        return []
    return session_cards


@router.post("/anki")
async def export_anki(request: Optional[ExportRequest] = None):
    """
    Generates a binary Anki deck package (.apkg) containing collection.anki2 SQLite database.
    Imports directly with one tap/click into Anki Desktop, AnkiDroid, and AnkiMobile.
    """
    cards_input = request.cards if request else None
    deck_name = request.deckName if (request and request.deckName) else "VerbaClear Event Vocabulary"

    cards = _resolve_cards(cards_input)
    if not cards:
        raise HTTPException(status_code=400, detail="No vocabulary cards available to export.")

    apkg_bytes = generate_anki_apkg(cards, deck_name=deck_name)

    from src.api.main import orchestrator
    session_id = orchestrator.session_id if orchestrator else "session"
    filename = f"verbaclear_{session_id}.apkg"

    return Response(
        content=apkg_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Card-Count": str(len(cards)),
        },
    )


@router.post("/tsv")
async def export_tsv(request: Optional[ExportRequest] = None):
    """
    Generates an Anki-compliant tab-separated text file (.txt) with Anki import directives.
    """
    cards_input = request.cards if request else None
    deck_name = request.deckName if (request and request.deckName) else "VerbaClear Event Vocabulary"

    cards = _resolve_cards(cards_input)
    if not cards:
        raise HTTPException(status_code=400, detail="No vocabulary cards available to export.")

    tsv_content = generate_anki_tsv(cards, deck_name=deck_name)

    from src.api.main import orchestrator
    session_id = orchestrator.session_id if orchestrator else "session"
    filename = f"verbaclear_{session_id}_anki.txt"

    return Response(
        content=tsv_content,
        media_type="text/tab-separated-values; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Card-Count": str(len(cards)),
        },
    )


@router.post("/csv")
async def export_csv(request: Optional[ExportRequest] = None):
    """
    Generates a standard RFC 4180 CSV file for spreadsheets and other spaced repetition tools.
    """
    cards_input = request.cards if request else None
    cards = _resolve_cards(cards_input)
    if not cards:
        raise HTTPException(status_code=400, detail="No vocabulary cards available to export.")

    csv_content = generate_csv(cards)

    from src.api.main import orchestrator
    session_id = orchestrator.session_id if orchestrator else "session"
    filename = f"verbaclear_{session_id}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Card-Count": str(len(cards)),
        },
    )


@router.post("/json")
async def export_json(request: Optional[ExportRequest] = None):
    """Generates structured JSON representation of vocabulary cards."""
    cards_input = request.cards if request else None
    cards = _resolve_cards(cards_input)
    json_content = generate_json(cards)

    return Response(
        content=json_content,
        media_type="application/json; charset=utf-8",
    )

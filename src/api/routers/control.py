"""
AV Operator Control Room REST Endpoints for VerbaClear.
Provides sound booth technicians with real-time controls:
- Stage blackout & dismissal overrides
- Live microphone mute/unmute
- Manual vocabulary injection to stage and mobile companions
- Operational telemetry and queue status
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/control", tags=["Operator Control"])
logger = logging.getLogger(__name__)


class StageBlackoutRequest(BaseModel):
    state: Optional[bool] = Field(None, description="True to force blackout, False to force resume, None to toggle")


class InjectCardRequest(BaseModel):
    word: str = Field(..., min_length=1, description="Word or phrase to display")
    synonyms: List[str] = Field(..., min_length=1, description="1 to 3 punchy synonyms")
    definition: str = Field(..., min_length=1, description="Accessible definition sentence")
    phoneticIpa: Optional[str] = Field(None, description="Optional IPA phonetic transcription")
    durationSeconds: float = Field(7.0, ge=2.0, le=30.0, description="Stage card hold duration in seconds")
    domainBadge: Optional[str] = Field("Manual", description="Badge category")


@router.get("/state")
async def get_control_state():
    """Returns real-time telemetry snapshot for the AV operator dashboard."""
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    return orchestrator.get_telemetry()


@router.post("/stage/blackout")
async def trigger_stage_blackout(request: Optional[StageBlackoutRequest] = Body(None)):
    """
    Emergency Stage Blackout:
    Toggles or sets stage blackout state.
    When active, purges all queued vocabulary cards, suppresses stage card emission,
    and forces the stage lower-third screen to blank immediately.
    """
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    force_state = request.state if request else None
    dropped = await orchestrator.blackout_stage(force_state=force_state)
    is_blackout = orchestrator.is_stage_blackout
    return {
        "status": "success",
        "action": "STAGE_BLACKOUT",
        "isBlackout": is_blackout,
        "droppedQueuedCards": dropped,
        "message": f"Stage lower-third blanked immediately; {dropped} queued items purged." if is_blackout else "Stage lower-third display resumed.",
    }


@router.post("/stage/dismiss")
async def dismiss_stage_card():
    """Dismisses the currently active lower-third card on stage ahead of its natural decay timer."""
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    await orchestrator.dismiss_stage_card()
    return {
        "status": "success",
        "action": "STAGE_DISMISS",
        "message": "Active stage card dismissed.",
    }


@router.post("/stage/inject")
async def inject_manual_card(request: InjectCardRequest):
    """
    Manual Card Injection:
    Broadcasts an arbitrary vocabulary card directly to stage and audience channels.
    Allows sound technicians to push speaker-specific jargon, sponsor mentions, or key terms on demand.
    """
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    card_id = await orchestrator.inject_card(
        word=request.word,
        synonyms=request.synonyms,
        definition=request.definition,
        phonetic_ipa=request.phoneticIpa or "",
        domain_badge=request.domainBadge or "Manual",
        duration_s=request.durationSeconds,
    )

    return {
        "status": "success",
        "action": "CARD_INJECTED",
        "cardId": card_id,
        "word": request.word,
        "durationSeconds": request.durationSeconds,
    }


@router.post("/audio/toggle")
async def toggle_audio_mute():
    """Toggles live microphone audio mute state."""
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    is_muted = orchestrator.toggle_audio()
    return {
        "status": "success",
        "isMuted": is_muted,
        "mode": "MUTED (VU meters active, ASR paused)" if is_muted else "LIVE (ASR active)",
    }

"""
Domain Context Pack Management REST Endpoints for VerbaClear.
Provides AV operators with real-time controls to:
- List available specialized vocabulary packs (FinTech, Medical, Legal, AI)
- Hot-swap the active domain pack mid-session without server restarts
- Deactivate packs back to general vocabulary baseline
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/packs", tags=["Domain Context Packs"])
logger = logging.getLogger(__name__)


class ActivatePackRequest(BaseModel):
    packId: Optional[str] = Field(None, description="ID of the context pack to activate (e.g. 'pack_fintech'), or null to revert to General.")


@router.get("")
async def list_available_packs() -> Dict[str, Any]:
    """Returns metadata for all discovered domain context packs and the current active selection."""
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    packs = orchestrator.pack_manager.list_packs()
    return {
        "status": "success",
        "activePackId": orchestrator.active_pack_id,
        "activePackBadge": orchestrator.pack_manager.active_pack_badge,
        "packs": packs,
    }


@router.post("/activate")
async def activate_context_pack(request: ActivatePackRequest) -> Dict[str, Any]:
    """
    Activates or deactivates a domain context pack on the fly.
    Subsequent spoken sentences immediately use the selected domain's terminology overrides.
    """
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    target_id = request.packId
    success = orchestrator.set_active_pack(target_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Context pack '{target_id}' not found")

    return {
        "status": "success",
        "action": "PACK_ACTIVATED" if orchestrator.active_pack_id else "PACK_DEACTIVATED",
        "activePackId": orchestrator.active_pack_id,
        "activePackBadge": orchestrator.pack_manager.active_pack_badge,
        "message": f"Active domain pack set to {orchestrator.pack_manager.active_pack_badge}.",
    }

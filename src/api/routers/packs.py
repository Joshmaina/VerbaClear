"""
Domain Context Pack Management REST Endpoints for VerbaClear.
Provides AV operators with real-time controls to:
- List available specialized vocabulary packs (FinTech, Medical, Legal, AI, Custom)
- Hot-swap the active domain pack mid-session without server restarts
- Create custom packs via JSON payloads
- Upload custom glossaries (.json or .csv) from the AV operator control room
- Delete custom packs safely
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/packs", tags=["Domain Context Packs"])
logger = logging.getLogger(__name__)


class ActivatePackRequest(BaseModel):
    packId: Optional[str] = Field(None, description="ID of the context pack to activate (e.g. 'pack_fintech'), or null to revert to General.")


class PackEntryModel(BaseModel):
    term: str = Field(..., min_length=1, description="Specialized vocabulary term")
    simplified_synonym: str = Field(..., min_length=1, description="Primary punchy simplified synonym")
    domain_definition: str = Field(..., min_length=1, description="Domain-specific definition sentence")
    phonetic_ipa: Optional[str] = Field(None, description="Optional IPA pronunciation")
    part_of_speech: Optional[str] = Field("noun", description="Part of speech (noun, verb, adjective)")
    abbreviation: Optional[str] = Field(None, description="Optional acronym or abbreviation")


class UploadPackPayload(BaseModel):
    filename: Optional[str] = Field("uploaded_pack.json", description="Original filename (e.g. 'pack_quantum.json' or 'quantum.csv')")
    content: str = Field(..., min_length=1, description="Raw file text content (JSON or CSV/TSV)")
    name: Optional[str] = Field(None, description="Optional override name")
    badge: Optional[str] = Field(None, description="Optional override badge")
    description: Optional[str] = Field("", description="Optional override description")


class CreatePackRequest(BaseModel):
    id: str = Field(..., min_length=1, description="Unique slug, e.g. 'pack_quantum' or 'quantum'")
    name: str = Field(..., min_length=1, description="Display name, e.g. 'Quantum Computing & Cryptography'")
    badge: str = Field(..., min_length=1, max_length=16, description="Short category badge, e.g. 'Quantum'")
    description: Optional[str] = Field("", description="Summary description")
    version: Optional[str] = Field("1.0.0", description="Semver string")
    entries: List[PackEntryModel] = Field(..., min_length=1, description="Array of vocabulary entries")


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


@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_custom_pack(request: CreatePackRequest) -> Dict[str, Any]:
    """Creates a new custom domain context pack and saves it to local disk and SQLite."""
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    try:
        pack_data = request.model_dump()
        created = orchestrator.pack_manager.create_custom_pack(pack_data)
        return {
            "status": "success",
            "action": "PACK_CREATED",
            "pack": created,
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("Failed to create context pack: %s", str(e))
        raise HTTPException(status_code=500, detail="Internal server error creating context pack")


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_custom_pack(payload: UploadPackPayload) -> Dict[str, Any]:
    """
    Uploads a custom context pack (.json or .csv/.tsv).
    Persists to the local disk and seeds SQLite for immediate live use.
    """
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    filename = payload.filename or "uploaded_pack.json"
    ext = Path(filename).suffix.lower()
    text_content = payload.content
    base_slug = Path(filename).stem.lower()
    name = payload.name
    badge = payload.badge
    description = payload.description or ""

    try:
        if ext == ".json":
            data = json.loads(text_content)
            if not isinstance(data, dict):
                raise ValueError("JSON must be an object with context pack fields.")
            if name:
                data["name"] = name
            if badge:
                data["badge"] = badge
            if description:
                data["description"] = description
            if not data.get("id"):
                data["id"] = f"pack_{base_slug}"

            created = orchestrator.pack_manager.create_custom_pack(data)
        elif ext in (".csv", ".tsv", ".txt"):
            pack_id = f"pack_{base_slug}"
            pack_name = name or base_slug.replace("_", " ").replace("-", " ").title()
            pack_badge = badge or pack_name[:12].title()
            created = orchestrator.pack_manager.import_from_csv(
                csv_content=text_content,
                pack_id=pack_id,
                name=pack_name,
                badge=pack_badge,
                description=description or f"Custom glossary uploaded from {filename}.",
            )
        else:
            raise ValueError(f"Unsupported file format '{ext}'. Please upload a .json or .csv/.tsv file.")

        return {
            "status": "success",
            "action": "PACK_UPLOADED",
            "pack": created,
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("Failed to process uploaded pack file: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process pack: {str(e)}")


@router.delete("/{pack_id}")
async def delete_custom_pack(pack_id: str) -> Dict[str, Any]:
    """Deletes a custom context pack. Built-in packs cannot be deleted."""
    from src.api.main import orchestrator
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    if pack_id in orchestrator.pack_manager.BUILTIN_PACK_IDS:
        raise HTTPException(status_code=400, detail="Built-in system packs cannot be deleted")

    pack = orchestrator.pack_manager.get_pack(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail=f"Context pack '{pack_id}' not found")

    deleted = orchestrator.pack_manager.delete_pack(pack_id)
    if not deleted:
        raise HTTPException(status_code=500, detail=f"Could not delete pack '{pack_id}'")

    return {
        "status": "success",
        "action": "PACK_DELETED",
        "packId": pack_id,
        "message": f"Context pack '{pack_id}' successfully removed.",
    }

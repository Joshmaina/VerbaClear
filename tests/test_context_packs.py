"""
Automated Test Suite for VerbaClear Specialized Domain Context Packs (FR-3.6).
Verifies:
1. Pack discovery, schema migration, and SQLite WAL seeding for FinTech, Medical, Legal, AI packs.
2. Hot-swapping active packs mid-session with immediate vocabulary overrides.
3. REST API endpoints (GET /api/packs, POST /api/packs/activate).
4. End-to-end card emission with domain badges and specialized definitions.
"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from src.api.main import app, orchestrator
from src.domain.models import TranscribedSegment
from src.infrastructure.nlp.context_packs import ContextPackManager
from src.infrastructure.storage.sqlite_lexicon import SQLiteLexiconRepository


@pytest.fixture
def test_client():
    return TestClient(app)


def test_context_pack_manager_discovery_and_seeding(tmp_path):
    """Verifies that all 4 JSON packs are discovered on disk and seeded into SQLite."""
    test_db = str(tmp_path / "test_packs.db")
    repo = SQLiteLexiconRepository(db_path=test_db)
    manager = ContextPackManager(repo=repo)

    packs = manager.list_packs()
    pack_ids = {p["id"] for p in packs}

    assert "pack_fintech" in pack_ids
    assert "pack_medical" in pack_ids
    assert "pack_legal" in pack_ids
    assert "pack_ai" in pack_ids
    assert len(packs) >= 4

    # Verify FinTech entries in SQLite
    fintech_entry = repo.get_entry("fungibility", active_pack_id="pack_fintech")
    assert fintech_entry is not None
    assert fintech_entry["synonyms"] == ["Interchangeability"]
    assert "mutual substitution" in fintech_entry["definition"]
    assert fintech_entry["phonetic_ipa"] == "/ˌfʌn.dʒəˈbɪl.ə.ti/"
    assert fintech_entry["part_of_speech"] == "noun"

    # Verify Medical entry in SQLite
    med_entry = repo.get_entry("pathogenicity", active_pack_id="pack_medical")
    assert med_entry is not None
    assert med_entry["synonyms"] == ["Disease Potential"]
    assert "disease" in med_entry["definition"]

    # Verify Legal entry in SQLite
    legal_entry = repo.get_entry("indemnification", active_pack_id="pack_legal")
    assert legal_entry is not None
    assert legal_entry["synonyms"] == ["Liability Shield"]

    # Verify AI entry in SQLite
    ai_entry = repo.get_entry("idempotency", active_pack_id="pack_ai")
    assert ai_entry is not None
    assert ai_entry["synonyms"] == ["Repeat-Safe"]


def test_context_pack_activation_and_switching(tmp_path):
    """Verifies activating, hot-swapping, and deactivating domain packs."""
    test_db = str(tmp_path / "test_switch.db")
    repo = SQLiteLexiconRepository(db_path=test_db)
    manager = ContextPackManager(repo=repo)

    # Initial state: no active pack
    assert manager.active_pack_id is None
    assert manager.active_pack_badge == "General"

    # Activate FinTech
    assert manager.activate_pack("pack_fintech") is True
    assert manager.active_pack_id == "pack_fintech"
    assert manager.active_pack_badge == "FinTech"

    # Hot-swap to AI & Distributed Systems
    assert manager.activate_pack("pack_ai") is True
    assert manager.active_pack_id == "pack_ai"
    assert manager.active_pack_badge == "AI & Systems"

    # Deactivate back to General Baseline
    assert manager.activate_pack(None) is True
    assert manager.active_pack_id is None
    assert manager.active_pack_badge == "General"

    # Invalid pack ID returns False
    assert manager.activate_pack("pack_non_existent_xyz") is False


def test_rest_api_packs_endpoints(test_client):
    """Verifies GET /api/packs and POST /api/packs/activate REST behavior."""
    # 1. GET /api/packs
    resp = test_client.get("/api/packs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "packs" in data
    assert len(data["packs"]) >= 4

    # 2. POST /api/packs/activate -> activate Legal pack
    resp = test_client.post("/api/packs/activate", json={"packId": "pack_legal"})
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["action"] == "PACK_ACTIVATED"
    assert res_data["activePackId"] == "pack_legal"
    assert res_data["activePackBadge"] == "Legal"

    # Verify telemetry also reflects active pack
    tel_resp = test_client.get("/api/control/state")
    assert tel_resp.status_code == 200
    tel_data = tel_resp.json()
    assert tel_data["activePackId"] == "pack_legal"
    assert tel_data["activePackBadge"] == "Legal"

    # 3. POST /api/packs/activate with null -> deactivate to General
    resp = test_client.post("/api/packs/activate", json={"packId": None})
    assert resp.status_code == 200
    assert resp.json()["action"] == "PACK_DEACTIVATED"
    assert resp.json()["activePackId"] is None
    assert resp.json()["activePackBadge"] == "General"

    # 4. POST /api/packs/activate with invalid ID -> 404
    resp = test_client.post("/api/packs/activate", json={"packId": "pack_unknown_404"})
    assert resp.status_code == 404


def test_orchestrator_e2e_card_emission_with_context_pack(tmp_path):
    """
    Verifies that spoken sentences processed by orchestrator emit vocabulary cards
    decorated with domain badges and domain-specific definitions when a pack is active.
    """
    from src.application.orchestrator import VerbaClearOrchestrator
    from src.infrastructure.nlp.filter import LexicalFilterEngine

    test_db = str(tmp_path / "test_orch_packs.db")
    repo = SQLiteLexiconRepository(db_path=test_db)
    filter_engine = LexicalFilterEngine(lexicon_repo=repo)
    orch = VerbaClearOrchestrator(lexical_filter=filter_engine)

    # Activate FinTech pack on orchestrator
    orch.set_active_pack("pack_fintech")
    assert orch.active_pack_id == "pack_fintech"
    assert orch.pack_manager.active_pack_badge == "FinTech"

    # Simulate ASR emitting a financial sentence with "fungibility"
    seg = TranscribedSegment(
        text="The fund manager evaluated the fungibility of digital assets.",
        start_time_s=0.0,
        end_time_s=2.5,
        confidence=0.98,
        words=["The", "fund", "manager", "evaluated", "the", "fungibility", "of", "digital", "assets."],
    )
    orch._is_active = True
    orch._handle_transcribed_segment(seg)

    cards = orch.get_session_cards()
    assert len(cards) > 0

    # Find fungibility card
    fungibility_card = next((c for c in cards if c.word == "fungibility"), None)
    assert fungibility_card is not None
    assert fungibility_card.domain_badge == "FinTech"
    assert "Interchangeability" in fungibility_card.synonyms
    assert "mutual substitution" in fungibility_card.definition

    # Switch to Medical pack
    orch.set_active_pack("pack_medical")
    seg_med = TranscribedSegment(
        text="The clinician examined the pathogenicity of the isolated culture.",
        start_time_s=3.0,
        end_time_s=5.5,
        confidence=0.97,
        words=["The", "clinician", "examined", "the", "pathogenicity", "of", "the", "isolated", "culture."],
    )
    orch._handle_transcribed_segment(seg_med)

    cards = orch.get_session_cards()
    patho_card = next((c for c in cards if c.word == "pathogenicity"), None)
    assert patho_card is not None
    assert patho_card.domain_badge == "Biomedical"
    assert "Disease Potential" in patho_card.synonyms

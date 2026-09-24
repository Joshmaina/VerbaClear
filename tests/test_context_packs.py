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


def test_create_custom_pack_programmatic(tmp_path):
    """Verifies creating and deleting a custom pack programmatically."""
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    test_db = str(tmp_path / "test_custom.db")
    repo = SQLiteLexiconRepository(db_path=test_db)
    manager = ContextPackManager(repo=repo, packs_dir=packs_dir)

    pack_data = {
        "id": "pack_space",
        "name": "Astrophysics & Space Flight",
        "badge": "Space",
        "description": "Orbital mechanics and astrophysics terminology.",
        "entries": [
            {
                "term": "apogee",
                "simplified_synonym": "Highest Orbit Point",
                "domain_definition": "The point in the orbit of an object where it is furthest from the Earth.",
                "phonetic_ipa": "/ˈæp.ə.dʒiː/",
                "part_of_speech": "noun",
            },
            {
                "term": "perigee",
                "simplified_synonym": "Lowest Orbit Point",
                "domain_definition": "The point in the orbit of an object where it is nearest to the Earth.",
                "phonetic_ipa": "/ˈper.ɪ.dʒiː/",
                "part_of_speech": "noun",
            },
        ],
    }

    created = manager.create_custom_pack(pack_data)
    assert created["id"] == "pack_space"
    assert created["entryCount"] == 2
    assert created["isCustom"] is True

    # Verify JSON file was created
    assert (packs_dir / "space.json").exists()

    # Verify SQLite entry
    entry = repo.get_entry("apogee", active_pack_id="pack_space")
    assert entry is not None
    assert entry["synonyms"] == ["Highest Orbit Point"]

    # Verify deletion
    assert manager.delete_pack("pack_space") is True
    assert not (packs_dir / "space.json").exists()
    assert repo.get_entry("apogee", active_pack_id="pack_space") is None


def test_import_from_csv_custom_pack(tmp_path):
    """Verifies importing context packs from raw CSV / TSV strings."""
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    test_db = str(tmp_path / "test_csv.db")
    repo = SQLiteLexiconRepository(db_path=test_db)
    manager = ContextPackManager(repo=repo, packs_dir=packs_dir)

    csv_text = """Term,Simplified Synonym,Domain Definition,Phonetic IPA,Part of Speech
qubit,Quantum Bit,Basic unit of quantum information,/ˈkjuː.bɪt/,noun
superposition,Dual State,Ability of a quantum system to be in multiple states simultaneously,/ˌsuː.pə.pəˈzɪʃ.ən/,noun
"""
    created = manager.import_from_csv(
        csv_content=csv_text,
        pack_id="pack_quantum",
        name="Quantum Computing",
        badge="Quantum",
        description="Quantum information science.",
    )

    assert created["id"] == "pack_quantum"
    assert created["entryCount"] == 2
    assert (packs_dir / "quantum.json").exists()

    entry = repo.get_entry("qubit", active_pack_id="pack_quantum")
    assert entry is not None
    assert entry["synonyms"] == ["Quantum Bit"]
    assert entry["phonetic_ipa"] == "/ˈkjuː.bɪt/"


def test_rest_api_pack_create_upload_and_delete(test_client):
    """Verifies POST /api/packs/create, POST /api/packs/upload, and DELETE /api/packs/{pack_id}."""
    # 1. Create via JSON payload (POST /api/packs/create)
    create_payload = {
        "id": "pack_robotics",
        "name": "Robotics & Automation",
        "badge": "Robotics",
        "description": "Kinematics and actuator control.",
        "entries": [
            {
                "term": "actuator",
                "simplified_synonym": "Motive Motor",
                "domain_definition": "A component of a machine responsible for moving and controlling a mechanism.",
                "phonetic_ipa": "/ˈæk.tʃu.eɪ.tər/",
                "part_of_speech": "noun",
            }
        ],
    }
    resp = test_client.post("/api/packs/create", json=create_payload)
    assert resp.status_code == 201
    pack_data = resp.json()["pack"]
    assert pack_data["id"] == "pack_robotics"
    assert pack_data["entryCount"] == 1

    # Verify it can be activated
    act_resp = test_client.post("/api/packs/activate", json={"packId": "pack_robotics"})
    assert act_resp.status_code == 200
    assert act_resp.json()["activePackBadge"] == "Robotics"

    # Delete custom pack (DELETE /api/packs/pack_robotics)
    del_resp = test_client.delete("/api/packs/pack_robotics")
    assert del_resp.status_code == 200
    assert del_resp.json()["action"] == "PACK_DELETED"

    # 2. Upload via CSV content (POST /api/packs/upload)
    csv_text = "term,simplified_synonym,domain_definition\nphotonics,Light Tech,Branch of optics and optical engineering\n"
    upload_resp = test_client.post(
        "/api/packs/upload",
        json={
            "filename": "photonics.csv",
            "content": csv_text,
            "name": "Photonics Optics",
            "badge": "Photonics",
        },
    )
    assert upload_resp.status_code == 201
    uploaded_pack = upload_resp.json()["pack"]
    assert uploaded_pack["id"] == "pack_photonics"
    assert uploaded_pack["badge"] == "Photonics"

    # Clean up uploaded pack
    del_resp2 = test_client.delete("/api/packs/pack_photonics")
    assert del_resp2.status_code == 200

    # 3. Built-in packs cannot be deleted
    resp_protected = test_client.delete("/api/packs/pack_fintech")
    assert resp_protected.status_code == 400
    assert "Built-in" in resp_protected.json()["detail"]


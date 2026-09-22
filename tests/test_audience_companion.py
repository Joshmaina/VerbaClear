"""
Tests for Phase 5: Audience QR Companion Mobile Portal (The Attendee Notebook).
Validates HTML PWA delivery, live WebSocket feed, session history sync,
and flashcard export engines (.apkg, TSV, CSV).
"""

import io
import json
import sqlite3
import tempfile
import zipfile
import pytest
from fastapi.testclient import TestClient

from src.api.main import app, orchestrator, ws_hub
from src.domain.models import AudienceCompanionCard, PartOfSpeech


@pytest.fixture
def client():
    return TestClient(app)


def test_companion_portal_serves_html(client):
    """Verifies that GET /companion serves the offline-ready mobile PWA interface."""
    response = client.get("/companion")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

    html_content = response.text
    # Verify core PWA & UI structures
    assert "VerbaClear Attendee Companion" in html_content
    assert 'id="feed-list"' in html_content
    assert 'id="search-box"' in html_content
    assert 'id="tab-all"' in html_content
    assert 'id="tab-bookmarks"' in html_content
    assert 'id="export-modal"' in html_content
    assert 'id="btn-download-anki-apkg"' in html_content
    assert 'id="btn-download-anki-tsv"' in html_content
    assert 'id="btn-download-csv"' in html_content
    assert "/ws/audience" in html_content
    assert "VerbaClearCompanionDB" in html_content  # IndexedDB


def test_companion_websocket_and_session_history(client):
    """
    Verifies that audience companion clients receive real-time vocabulary cards
    and can synchronize session history via REST.
    """
    card = AudienceCompanionCard(
        card_id="crd_test_777",
        word="obfuscate",
        part_of_speech=PartOfSpeech.VERB,
        phonetic_ipa="/ˈɒb.fə.skeɪt/",
        synonyms=["Confuse", "Make Unclear"],
        definition="To deliberately make something difficult to understand or obscure.",
        context_sentence="Please do not obfuscate the technical roadmap.",
        spoken_time_formatted="10:15:30",
        domain_badge="General",
    )

    # 1. Test live WebSocket transmission
    with client.websocket_connect("/ws/audience") as ws:
        assert ws_hub.audience_client_count >= 1

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(ws_hub.broadcast_audience(card))
        finally:
            loop.close()

        msg = ws.receive_text()
        data = json.loads(msg)

        assert data["topic"] == "AUDIENCE_VOCABULARY_CARD"
        assert data["data"]["cardId"] == "crd_test_777"
        assert data["data"]["word"] == "Obfuscate"
        assert data["data"]["partOfSpeech"] == "verb"
        assert data["data"]["phoneticIpa"] == "/ˈɒb.fə.skeɪt/"
        assert "Confuse" in data["data"]["synonyms"]
        assert "difficult to understand" in data["data"]["definition"]

    # 2. Add to orchestrator session history and verify GET /api/session/cards
    orchestrator.add_card_to_history(card)
    resp = client.get("/api/session/cards")
    assert resp.status_code == 200
    cards_list = resp.json()
    assert len(cards_list) >= 1
    found = any(c["cardId"] == "crd_test_777" for c in cards_list)
    assert found is True


def test_export_anki_apkg_integrity(client):
    """
    Verifies that POST /api/export/anki generates a binary .apkg ZIP package
    with a valid, queryable SQLite collection.anki2 database inside.
    """
    sample_cards = [
        {
            "cardId": "crd_1",
            "word": "Labyrinthine",
            "partOfSpeech": "adjective",
            "phoneticIpa": "/ˌlæb.əˈrɪn.θaɪn/",
            "synonyms": ["Highly Complex", "Maze-like"],
            "definition": "Irregular, intricate, or maze-like in structure.",
            "contextSentence": "The corporate structure was labyrinthine.",
            "spokenTimeFormatted": "09:30:00",
            "domainBadge": "General",
        },
        {
            "cardId": "crd_2",
            "word": "Obfuscate",
            "partOfSpeech": "verb",
            "phoneticIpa": "/ˈɒb.fə.skeɪt/",
            "synonyms": ["Confuse", "Obscure"],
            "definition": "To make obscure, unclear, or unintelligible.",
            "contextSentence": "The speaker obfuscated the data.",
            "spokenTimeFormatted": "09:31:00",
            "domainBadge": "General",
        },
    ]

    response = client.post("/api/export/anki", json={"cards": sample_cards})
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/octet-stream"
    assert "attachment; filename=" in response.headers.get("content-disposition", "")
    assert response.headers.get("x-card-count") == "2"

    apkg_bytes = response.content
    assert len(apkg_bytes) > 1000

    # Unzip in memory and inspect SQLite collection.anki2
    with zipfile.ZipFile(io.BytesIO(apkg_bytes), "r") as zf:
        file_list = zf.namelist()
        assert "collection.anki2" in file_list
        assert "media" in file_list

        db_content = zf.read("collection.anki2")
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(db_content)
            temp_db_path = f.name

        try:
            conn = sqlite3.connect(temp_db_path)
            cur = conn.cursor()

            # Verify tables exist
            tables = [row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            assert "col" in tables
            assert "notes" in tables
            assert "cards" in tables

            # Verify records count matches
            notes_count = cur.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            cards_count = cur.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            assert notes_count == 2
            assert cards_count == 2

            # Verify card content
            sample_note = cur.execute("SELECT flds FROM notes WHERE sfld='Labyrinthine'").fetchone()
            assert sample_note is not None
            assert "Labyrinthine" in sample_note[0]
            assert "Highly Complex" in sample_note[0]
            assert "maze-like" in sample_note[0].lower()

            conn.close()
        finally:
            import os
            if os.path.exists(temp_db_path):
                os.unlink(temp_db_path)


def test_export_tsv_and_csv_formats(client):
    """Verifies that TSV and CSV exports adhere to RFC 4180 and Anki text directives."""
    sample_cards = [
        {
            "cardId": "crd_1",
            "word": "Labyrinthine",
            "partOfSpeech": "adjective",
            "phoneticIpa": "/ˌlæb.əˈrɪn.θaɪn/",
            "synonyms": ["Highly Complex", "Maze-like"],
            "definition": "Irregular, intricate, or maze-like in structure.",
            "contextSentence": "The corporate structure was labyrinthine.",
            "spokenTimeFormatted": "09:30:00",
            "domainBadge": "General",
        }
    ]

    # Test Anki TSV
    tsv_resp = client.post("/api/export/tsv", json={"cards": sample_cards})
    assert tsv_resp.status_code == 200
    tsv_text = tsv_resp.text
    assert "#separator:Tab" in tsv_text
    assert "#html:true" in tsv_text
    assert "#deck:VerbaClear" in tsv_text
    assert "Labyrinthine" in tsv_text

    # Test CSV
    csv_resp = client.post("/api/export/csv", json={"cards": sample_cards})
    assert csv_resp.status_code == 200
    csv_text = csv_resp.text
    assert "Word,Part of Speech,Phonetic IPA,Definition,Synonyms,Context Sentence" in csv_text
    assert "Labyrinthine" in csv_text
    assert "Highly Complex; Maze-like" in csv_text

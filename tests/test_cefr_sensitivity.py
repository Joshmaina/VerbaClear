"""
Unit and Integration Tests for Option C: CEFR / Grade-Level Vocabulary Sensitivity Slider.
Verifies:
1. FrequencyIndex CEFR tiers (B1, B2, C1, C2) and rank thresholds.
2. Vocabulary rarity filtering across demographic tiers:
   - B1 (Intermediate): Flags intermediate terms like 'topology' and 'methodology'.
   - B2 (Upper Intermediate): Accepts 'topology' as common, flags 'paradigm' and 'synergy'.
   - C1 (Advanced/Professional): Accepts 'paradigm' as common, flags 'ubiquitous' and 'ephemeral'.
   - C2 (Mastery): Accepts 'ubiquitous' as common, flags only truly esoteric words like 'labyrinthine' and 'obfuscate'.
3. LexicalFilterEngine dynamic sensitivity switching.
4. REST Endpoints: GET /api/control/sensitivity, POST /api/control/sensitivity, and telemetry integration.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, orchestrator
from src.infrastructure.nlp.filter import LexicalFilterEngine
from src.infrastructure.nlp.frequency import FrequencyIndex


# ---------------------------------------------------------------------------
# Test 1: FrequencyIndex CEFR Tiers & Dynamic Switching
# ---------------------------------------------------------------------------
def test_cefr_frequency_index_tiers():
    freq = FrequencyIndex()

    # Default level is B2 (Threshold Rank: 3500)
    assert freq.current_level == "B2"
    assert freq.rarity_threshold_rank == 3500

    # Base common words must be common across ALL levels
    for word in ["the", "system", "tax", "architecture", "presentation", "audience"]:
        assert freq.is_common(word) is True

    # Esoteric words must be rare across ALL levels
    for word in ["labyrinthine", "obfuscate", "esoteric"]:
        assert freq.is_common(word) is False


def test_cefr_sensitivity_progression():
    freq = FrequencyIndex()

    # 1. Level B1 (Intermediate, Cutoff 2000)
    freq.set_sensitivity("B1")
    assert freq.current_level == "B1"
    assert freq.rarity_threshold_rank == 2000

    # B1 flags intermediate words as rare
    assert freq.is_common("topology") is False
    assert freq.is_common("methodology") is False
    assert freq.is_common("paradigm") is False
    assert freq.is_common("ubiquitous") is False
    assert freq.is_common("labyrinthine") is False

    # 2. Level B2 (Upper Intermediate - Default, Cutoff 3500)
    freq.set_sensitivity("B2")
    assert freq.current_level == "B2"
    assert freq.rarity_threshold_rank == 3500

    # B2 recognizes intermediate terms, but flags advanced industry terms
    assert freq.is_common("topology") is True
    assert freq.is_common("methodology") is True
    assert freq.is_common("paradigm") is False
    assert freq.is_common("synergy") is False
    assert freq.is_common("ubiquitous") is False
    assert freq.is_common("labyrinthine") is False

    # 3. Level C1 (Advanced / Professional, Cutoff 5500)
    freq.set_sensitivity("C1")
    assert freq.current_level == "C1"
    assert freq.rarity_threshold_rank == 5500

    # C1 recognizes standard industry jargon, flags literary/esoteric words
    assert freq.is_common("topology") is True
    assert freq.is_common("paradigm") is True
    assert freq.is_common("synergy") is True
    assert freq.is_common("ubiquitous") is False
    assert freq.is_common("ephemeral") is False
    assert freq.is_common("labyrinthine") is False

    # 4. Level C2 (Mastery / Academic, Cutoff 8000)
    freq.set_sensitivity("C2")
    assert freq.current_level == "C2"
    assert freq.rarity_threshold_rank == 8000

    # C2 recognizes advanced literary words, only flags esoteric unranked words
    assert freq.is_common("topology") is True
    assert freq.is_common("paradigm") is True
    assert freq.is_common("ubiquitous") is True
    assert freq.is_common("ephemeral") is True
    assert freq.is_common("labyrinthine") is False
    assert freq.is_common("obfuscate") is False


def test_cefr_custom_rank_and_validation():
    freq = FrequencyIndex()

    # Custom rank
    res = freq.set_sensitivity("B2", custom_rank=1500)
    assert res["thresholdRank"] == 1500

    # Invalid level
    with pytest.raises(ValueError, match="Unknown CEFR"):
        freq.set_sensitivity("X9")


# ---------------------------------------------------------------------------
# Test 2: LexicalFilterEngine Sentence Evaluation with CEFR Tuning
# ---------------------------------------------------------------------------
def test_lexical_filter_sentence_evaluation_with_cefr():
    engine = LexicalFilterEngine()

    test_sentence = "The topology and paradigm were ubiquitous."

    # 1. Under B1: All 3 uncommon terms flagged
    engine.set_sensitivity("B1")
    evals_b1 = engine.evaluate_sentence(test_sentence)
    lemmas_b1 = {e.lemma for e in evals_b1}
    assert "topology" in lemmas_b1
    assert "paradigm" in lemmas_b1
    assert "ubiquitous" in lemmas_b1

    # 2. Under B2: 'topology' recognized as common; 'paradigm' and 'ubiquitous' flagged
    engine.set_sensitivity("B2")
    evals_b2 = engine.evaluate_sentence(test_sentence)
    lemmas_b2 = {e.lemma for e in evals_b2}
    assert "topology" not in lemmas_b2
    assert "paradigm" in lemmas_b2
    assert "ubiquitous" in lemmas_b2

    # 3. Under C1: 'topology' and 'paradigm' recognized as common; 'ubiquitous' flagged
    engine.set_sensitivity("C1")
    evals_c1 = engine.evaluate_sentence(test_sentence)
    lemmas_c1 = {e.lemma for e in evals_c1}
    assert "topology" not in lemmas_c1
    assert "paradigm" not in lemmas_c1
    assert "ubiquitous" in lemmas_c1

    # 4. Under C2: All 3 recognized as common for academic scholars
    engine.set_sensitivity("C2")
    evals_c2 = engine.evaluate_sentence(test_sentence)
    lemmas_c2 = {e.lemma for e in evals_c2}
    assert "topology" not in lemmas_c2
    assert "paradigm" not in lemmas_c2
    assert "ubiquitous" not in lemmas_c2

    # 5. But truly esoteric words are ALWAYS flagged even in C2
    esoteric_evals = engine.evaluate_sentence("The architecture is labyrinthine and obfuscated.")
    esoteric_lemmas = {e.lemma for e in esoteric_evals}
    assert "labyrinthine" in esoteric_lemmas
    assert "obfuscate" in esoteric_lemmas


# ---------------------------------------------------------------------------
# Test 3: REST API Endpoints & Telemetry
# ---------------------------------------------------------------------------
def test_cefr_rest_endpoints_and_telemetry():
    client = TestClient(app)

    # 1. GET /api/control/sensitivity
    resp = client.get("/api/control/sensitivity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "sensitivity" in data
    assert "availableLevels" in data["sensitivity"]
    assert "B1" in data["sensitivity"]["availableLevels"]

    # 2. POST /api/control/sensitivity (Switch to C1)
    resp = client.post("/api/control/sensitivity", json={"level": "C1"})
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["sensitivity"]["level"] == "C1"
    assert res_data["sensitivity"]["thresholdRank"] == 5500

    # 3. POST invalid level
    resp = client.post("/api/control/sensitivity", json={"level": "INVALID_LEVEL"})
    assert resp.status_code == 400

    # 4. Reset to B2
    resp = client.post("/api/control/sensitivity", json={"level": "B2"})
    assert resp.status_code == 200
    assert resp.json()["sensitivity"]["level"] == "B2"

    # 5. GET /api/control/state includes sensitivity and ndi
    state_resp = client.get("/api/control/state")
    assert state_resp.status_code == 200
    state = state_resp.json()
    assert "sensitivity" in state
    assert state["sensitivity"]["level"] == "B2"
    assert "ndi" in state
    assert "isStreaming" in state["ndi"]

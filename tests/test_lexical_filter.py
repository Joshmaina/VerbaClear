"""
Unit and Integration Tests for Phase 2: The Semantic Brain (Lexical Intelligence).
Verifies Exit Gate 2:
- Sentence filtering: "The tax architecture is labyrinthine and obfuscated"
  isolates ONLY 'labyrinthine' and 'obfuscate' with punchy synonyms.
- Proper nouns and named entities (e.g. "Google", "Joshua") are discarded.
- In-memory frequency Bloom filter runs in sub-millisecond time.
- SQLite lexicon retrieval latency is under 5ms.
"""

import time
import pytest

from src.domain.models import PartOfSpeech
from src.infrastructure.nlp.filter import LexicalFilterEngine
from src.infrastructure.nlp.frequency import BloomFilter, FrequencyIndex
from src.infrastructure.nlp.lemmatizer import SpacyLemmatizer
from src.infrastructure.storage.sqlite_lexicon import SQLiteLexiconRepository


# ---------------------------------------------------------------------------
# Test 1: In-Memory Bloom Filter and NGSL Frequency Index
# ---------------------------------------------------------------------------
def test_bloom_filter_and_frequency_index():
    freq = FrequencyIndex()

    # Common words (in NGSL / Top 3,000)
    assert freq.is_common("the")
    assert freq.is_common("system")
    assert freq.is_common("presentation")
    assert freq.is_common("audience")
    assert freq.is_common("structure")
    assert freq.is_common("tax")
    assert freq.is_common("architecture")

    # Uncommon / Rare words (NOT in NGSL)
    assert not freq.is_common("labyrinthine")
    assert not freq.is_common("obfuscate")
    assert not freq.is_common("esoteric")
    assert not freq.is_common("plethora")
    assert not freq.is_common("superfluous")

    # Latency test: 1,000 lookups
    t0 = time.perf_counter()
    for _ in range(1000):
        _ = freq.is_common("labyrinthine")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    avg_lookup_us = (elapsed_ms / 1000.0) * 1000.0
    print(f"\n[FREQUENCY CHECK] 1,000 lookups in {elapsed_ms:.2f}ms (Average: {avg_lookup_us:.2f} µs per word)")
    assert avg_lookup_us < 50.0, "Frequency lookup took too long!"


# ---------------------------------------------------------------------------
# Test 2: spaCy Lemmatization & Named Entity Recognition (NER) Suppression
# ---------------------------------------------------------------------------
def test_lemmatizer_and_ner_suppression():
    lemmatizer = SpacyLemmatizer()

    # Test inflections
    doc = lemmatizer.analyze_text("The speaker was obfuscating the esoteric parameters.")
    lemmas = {c.lemma for c in doc}
    assert "obfuscate" in lemmas
    assert "esoteric" in lemmas

    # Test Named Entity Suppression (proper nouns, companies, locations)
    ner_text = "Joshua Maina visited Microsoft and Google in Nairobi."
    ner_doc = lemmatizer.analyze_text(ner_text)
    proper_nouns = [c.lemma for c in ner_doc if c.is_proper_noun]

    print(f"\n[NER SUPPRESSION] Detected proper nouns: {proper_nouns}")
    assert any("joshua" in p or "maina" in p for p in proper_nouns)
    assert any("google" in p or "microsoft" in p for p in proper_nouns)
    assert any("nairobi" in p for p in proper_nouns)


# ---------------------------------------------------------------------------
# Test 3: SQLite Lexicon Sub-Millisecond Retrieval
# ---------------------------------------------------------------------------
def test_sqlite_lexicon_retrieval():
    repo = SQLiteLexiconRepository()

    # Test seeded word retrieval
    t0 = time.perf_counter()
    entry = repo.get_entry("labyrinthine")
    latency_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n[SQLITE LATENCY] Retrieved 'labyrinthine' in {latency_ms:.2f}ms")
    assert entry is not None
    assert entry["headword"] == "labyrinthine"
    assert entry["part_of_speech"] == "adjective"
    assert entry["phonetic_ipa"] == "/ˌlæb.əˈrɪn.θaɪn/"
    assert "Highly Complex" in entry["synonyms"]
    assert latency_ms < 5.0, f"SQLite query took {latency_ms:.2f}ms (> 5ms)!"

    # Test punchy synonyms brevity (max 3 words per synonym)
    synonyms = repo.resolve_synonyms("obfuscate")
    assert "Confuse" in synonyms
    for syn in synonyms:
        assert len(syn.split()) <= 3, f"Synonym '{syn}' exceeded 3 words!"


# ---------------------------------------------------------------------------
# Test 4: Exit Gate 2 End-to-End Verification
# ---------------------------------------------------------------------------
def test_exit_gate_2_sentence_filtration():
    """
    Exit Gate 2 Acceptance Criteria:
    Speaking 'The tax architecture is labyrinthine and obfuscated' isolates ONLY
    'labyrinthine' and 'obfuscate' with punchy synonyms, ignoring all common words.
    """
    engine = LexicalFilterEngine()

    test_sentence = "The tax architecture is labyrinthine and obfuscated."

    # Prime engine caches for steady-state measurement
    _ = engine.evaluate_sentence("Warm-up sentence.")

    t0 = time.perf_counter()
    evaluations = engine.evaluate_sentence(test_sentence)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    extracted_lemmas = [e.lemma for e in evaluations]
    print(f"\n[EXIT GATE 2] Sentence: \"{test_sentence}\"")
    print(f"  Extracted rare lemmas: {extracted_lemmas}")
    print(f"  Evaluation Latency: {elapsed_ms:.2f}ms")

    # Verify that ONLY 'labyrinthine' and 'obfuscate' are extracted
    assert set(extracted_lemmas) == {"labyrinthine", "obfuscate"}, (
        f"Expected {{'labyrinthine', 'obfuscate'}}, got {set(extracted_lemmas)}"
    )

    # Verify that common words were filtered out
    assert "the" not in extracted_lemmas
    assert "tax" not in extracted_lemmas
    assert "architecture" not in extracted_lemmas
    assert "is" not in extracted_lemmas
    assert "and" not in extracted_lemmas

    # Verify synonym resolution for extracted words
    for ev in evaluations:
        synonyms = engine.resolve_synonyms(ev.lemma)
        phonetics, definition = engine.resolve_definition_and_phonetics(ev.lemma)
        print(f"    - {ev.lemma.upper()} ({ev.part_of_speech.value}):")
        print(f"        Synonyms:   {synonyms}")
        print(f"        Phonetics:  {phonetics}")
        print(f"        Definition: {definition}")

        assert len(synonyms) > 0
        assert definition is not None

    # Performance Gate
    assert elapsed_ms < 20.0, f"Sentence evaluation took {elapsed_ms:.2f}ms (> 20ms)!"
    print("Exit Gate 2 successfully verified!")

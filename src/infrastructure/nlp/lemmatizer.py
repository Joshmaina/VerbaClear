"""
spaCy NLP Lemmatizer, Part-of-Speech Tagger, and Named Entity Recognition (NER) Adapter.
Extracts candidate vocabulary lemmas while suppressing proper nouns, brands, locations, and stopwords.
"""

from dataclasses import dataclass
import logging
from typing import List, Set
import spacy
from spacy.tokens import Doc

from src.domain.models import PartOfSpeech

logger = logging.getLogger(__name__)

# Named Entity types that must be suppressed from vocabulary simplification
IGNORED_NER_LABELS = {
    "PERSON",      # People's names (e.g. Joshua, Einstein)
    "ORG",         # Companies, agencies, institutions (e.g. Google, OpenAI)
    "GPE",         # Countries, cities, states (e.g. Kenya, London, California)
    "LOC",         # Non-GPE locations (e.g. Mount Everest, Mississippi River)
    "FAC",         # Buildings, airports, highways (e.g. JFK Airport)
    "PRODUCT",     # Commercial objects, vehicles, foods (e.g. iPhone)
    "DATE",        # Absolute or relative dates (e.g. Monday, 2026)
    "TIME",        # Times smaller than a day (e.g. 14:00)
    "PERCENT",     # Percentage figures
    "MONEY",       # Monetary values
    "QUANTITY",    # Measurements
    "ORDINAL",     # "first", "second"
    "CARDINAL",    # Numerals
}

SPACY_POS_MAP = {
    "NOUN": PartOfSpeech.NOUN,
    "PROPN": PartOfSpeech.NOUN,
    "VERB": PartOfSpeech.VERB,
    "ADJ": PartOfSpeech.ADJECTIVE,
    "ADV": PartOfSpeech.ADVERB,
}


@dataclass(frozen=True)
class CandidateToken:
    """Represents a normalized linguistic candidate extracted from a sentence."""
    surface_text: str
    lemma: str
    part_of_speech: PartOfSpeech
    is_proper_noun: bool
    is_stopword: bool
    start_char: int
    end_char: int


class SpacyLemmatizer:
    """
    High-speed linguistic analyzer using spaCy en_core_web_sm.
    Identifies base lemmas, grammatical categories, and Named Entities.
    """

    def __init__(self, model_name: str = "en_core_web_sm"):
        logger.info("Loading spaCy model '%s'...", model_name)
        # Disable heavy parser components if not strictly required, keep tagger, lemmatizer, and ner
        self.nlp = spacy.load(model_name, disable=["parser"])
        logger.info("spaCy model loaded successfully.")

    def analyze_text(self, text: str) -> List[CandidateToken]:
        """
        Parses text into candidate tokens, tagging parts of speech, lemmas, and named entities.
        """
        clean_text = text.strip()
        if not clean_text:
            return []

        doc: Doc = self.nlp(clean_text)

        # Collect named entity character ranges to suppress proper nouns
        ner_char_ranges: Set[int] = set()
        for ent in doc.ents:
            if ent.label_ in IGNORED_NER_LABELS:
                for idx in range(ent.start_char, ent.end_char):
                    ner_char_ranges.add(idx)

        candidates: List[CandidateToken] = []

        for token in doc:
            # Skip punctuation, spaces, numbers, and symbols
            if token.is_punct or token.is_space or token.like_num or len(token.text.strip()) < 2:
                continue

            # Check if token falls inside an ignored Named Entity span
            is_ner = any(idx in ner_char_ranges for idx in range(token.idx, token.idx + len(token.text)))
            is_proper = token.pos_ == "PROPN" or is_ner

            # Normalize lemma
            clean_lemma = token.lemma_.strip().lower()
            if not clean_lemma or clean_lemma.startswith("-"):
                continue

            pos_category = SPACY_POS_MAP.get(token.pos_, PartOfSpeech.UNKNOWN)

            candidates.append(
                CandidateToken(
                    surface_text=token.text,
                    lemma=clean_lemma,
                    part_of_speech=pos_category,
                    is_proper_noun=is_proper,
                    is_stopword=token.is_stop,
                    start_char=token.idx,
                    end_char=token.idx + len(token.text),
                )
            )

        return candidates

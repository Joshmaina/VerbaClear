"""
Lexical Filter Engine for VerbaClear.
Implements LexicalFilterPort by combining spaCy lemmatization, in-memory NGSL Bloom filtering,
and embedded SQLite lexicon resolution into a unified semantic pipeline.
"""

import logging
from typing import List, Optional, Tuple

from src.domain.interfaces import LexicalFilterPort
from src.domain.models import PartOfSpeech, VocabularyEvaluation
from src.infrastructure.nlp.frequency import FrequencyIndex
from src.infrastructure.nlp.lemmatizer import CandidateToken, SpacyLemmatizer
from src.infrastructure.storage.sqlite_lexicon import SQLiteLexiconRepository

logger = logging.getLogger(__name__)


class LexicalFilterEngine(LexicalFilterPort):
    """
    Evaluates speech text against linguistic corpora to detect, extract, and enrich
    uncommon vocabulary and specialized terminology.
    """

    def __init__(
        self,
        lemmatizer: Optional[SpacyLemmatizer] = None,
        frequency_index: Optional[FrequencyIndex] = None,
        lexicon_repo: Optional[SQLiteLexiconRepository] = None,
    ):
        self.lemmatizer = lemmatizer or SpacyLemmatizer()
        self.frequency_index = frequency_index or FrequencyIndex()
        self.lexicon_repo = lexicon_repo or SQLiteLexiconRepository()

    def evaluate_sentence(self, text: str) -> List[VocabularyEvaluation]:
        """
        Parses sentence text, filters out common words, proper nouns, and stopwords,
        and returns evaluations for rare or domain-specific vocabulary.
        """
        candidates: List[CandidateToken] = self.lemmatizer.analyze_text(text)
        evaluations: List[VocabularyEvaluation] = []
        seen_lemmas: set[str] = set()

        for token in candidates:
            # Rule 1: Discard proper nouns and named entities (people, companies, countries)
            if token.is_proper_noun:
                continue

            # Rule 2: Discard grammatical stopwords ("the", "is", "and", "under")
            if token.is_stopword:
                continue

            # Avoid duplicate evaluations for the same lemma within a single sentence
            if token.lemma in seen_lemmas:
                continue

            # Rule 3: Check frequency baseline (NGSL / NAWL)
            is_common = self.frequency_index.is_common(token.lemma)
            rank = self.frequency_index.get_rank(token.lemma)

            # A word is flagged as rare if it is NOT in common vocabulary (Bloom filter/NGSL)
            # OR if it exists in our curated advanced lexicon
            is_in_lexicon = self.lexicon_repo.get_entry(token.lemma) is not None

            is_rare = (not is_common) or is_in_lexicon

            if is_rare:
                seen_lemmas.add(token.lemma)
                evaluations.append(
                    VocabularyEvaluation(
                        lemma=token.lemma,
                        original_surface_form=token.surface_text,
                        part_of_speech=token.part_of_speech,
                        frequency_rank=rank,
                        is_rare=True,
                        context_sentence=text.strip(),
                    )
                )

        return evaluations

    def resolve_synonyms(self, lemma: str, active_pack_id: Optional[str] = None) -> List[str]:
        """Retrieves 1-3 punchy, simplified synonyms for an uncommon lemma."""
        return self.lexicon_repo.resolve_synonyms(lemma, active_pack_id=active_pack_id)

    def resolve_definition_and_phonetics(
        self, lemma: str, active_pack_id: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """Returns (phonetic_ipa, 1_sentence_definition) for a lemma."""
        return self.lexicon_repo.resolve_definition_and_phonetics(lemma, active_pack_id=active_pack_id)

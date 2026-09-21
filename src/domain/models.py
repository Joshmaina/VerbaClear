"""
Core Domain Models for VerbaClear.
Adheres to Clean Architecture principles: pure domain entities independent of external frameworks.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import time


class PartOfSpeech(str, Enum):
    NOUN = "noun"
    VERB = "verb"
    ADJECTIVE = "adjective"
    ADVERB = "adverb"
    IDIOM = "idiom"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AudioChunk:
    """Represents a discrete slice of 16kHz linear PCM audio."""
    samples: bytes
    sample_rate: int = 16000
    duration_ms: float = 30.0
    timestamp_epoch_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(frozen=True)
class TranscribedSegment:
    """Represents text segment produced by the ASR engine with word-level boundaries."""
    text: str
    start_time_s: float
    end_time_s: float
    confidence: float
    words: List[str]


@dataclass(frozen=True)
class VocabularyEvaluation:
    """Linguistic assessment of a word token against standard frequency corpora."""
    lemma: str
    original_surface_form: str
    part_of_speech: PartOfSpeech
    frequency_rank: int
    is_rare: bool
    context_sentence: str


@dataclass(frozen=True)
class StageOverlayCard:
    """Lightweight presentation payload designed for split-second ambient glance."""
    card_id: str
    word: str
    synonyms: List[str]
    display_duration_s: float = 7.0
    accent_color: str = "#0284c7"
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(frozen=True)
class AudienceCompanionCard:
    """Comprehensive educational card designed for attendee mobile companion."""
    card_id: str
    word: str
    part_of_speech: PartOfSpeech
    phonetic_ipa: Optional[str]
    synonyms: List[str]
    definition: str
    context_sentence: str
    spoken_time_formatted: str
    domain_badge: str = "General"
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

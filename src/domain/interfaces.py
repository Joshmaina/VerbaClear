"""
Abstract Domain Interfaces (Ports) for VerbaClear.
Enforces Dependency Inversion Principle (DIP): Core business logic depends on abstractions, not concretions.
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Optional
import numpy as np

from src.domain.models import (
    AudienceCompanionCard,
    AudioChunk,
    StageOverlayCard,
    TranscribedSegment,
    VocabularyEvaluation,
)


class AudioSourcePort(ABC):
    """Port for streaming hardware or virtual audio capture."""

    @abstractmethod
    def start_stream(self) -> None:
        """Initializes the PortAudio stream."""
        pass

    @abstractmethod
    def stop_stream(self) -> None:
        """Terminates the audio stream and releases hardware locks."""
        pass

    @abstractmethod
    def read_chunk(self, frame_size: int = 480) -> Optional[np.ndarray]:
        """Reads a fixed chunk of 16kHz mono audio samples."""
        pass


class VoiceActivityDetectorPort(ABC):
    """Port for Voice Activity Detection (silence and noise rejection)."""

    @abstractmethod
    def is_speech(self, audio_frame: np.ndarray, threshold: float = 0.5) -> bool:
        """Evaluates whether an audio slice contains human vocal activity."""
        pass

    @abstractmethod
    def reset_state(self) -> None:
        """Resets recurrent state tensors between discontinuous audio streams."""
        pass


class SpeechToTextPort(ABC):
    """Port for Automatic Speech Recognition (ASR)."""

    @abstractmethod
    def transcribe(self, audio_buffer: np.ndarray) -> List[TranscribedSegment]:
        """Transcribes raw PCM speech audio into text segments with word timestamps."""
        pass


class LexicalFilterPort(ABC):
    """Port for linguistic rarity evaluation, lemmatization, and synonym matching."""

    @abstractmethod
    def evaluate_sentence(self, text: str, active_pack_id: Optional[str] = None) -> List[VocabularyEvaluation]:
        """Extracts and evaluates tokens from a transcribed sentence against frequency baselines."""
        pass

    @abstractmethod
    def resolve_synonyms(self, lemma: str, active_pack_id: Optional[str] = None) -> List[str]:
        """Retrieves 1-3 punchy, simplified synonyms for an uncommon lemma."""
        pass

    @abstractmethod
    def resolve_definition_and_phonetics(
        self, lemma: str, active_pack_id: Optional[str] = None
    ) -> tuple[Optional[str], Optional[str]]:
        """Returns (phonetic_ipa, 1_sentence_definition) for a lemma."""
        pass


class BroadcasterPort(ABC):
    """Port for real-time WebSocket event dispatch to stage and audience clients."""

    @abstractmethod
    async def broadcast_stage(self, card: StageOverlayCard) -> None:
        """Dispatches an overlay update to the stage screen."""
        pass

    @abstractmethod
    async def broadcast_audience(self, card: AudienceCompanionCard) -> None:
        """Dispatches an educational card to all connected mobile companions."""
        pass

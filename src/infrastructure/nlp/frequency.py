"""
Linguistic Frequency Baselines & In-Memory Bloom Filter for VerbaClear.
Implements sub-microsecond token rarity evaluation using NGSL (New General Service List 1.2)
and NAWL (New Academic Word List) frequency distributions.
"""

import hashlib
import logging
import math
from typing import List, Optional, Set

logger = logging.getLogger(__name__)


class BloomFilter:
    """
    Cache-friendly in-memory Bloom filter for O(k) probabilistic set membership.
    Configured by default to fit entirely within L1 data cache (< 16 KB).
    """

    def __init__(self, capacity: int = 5000, error_rate: float = 0.001):
        self.capacity = capacity
        self.error_rate = error_rate

        # Compute optimal bit array size m and hash function count k
        # m = - (n * ln(p)) / (ln(2)^2)
        # k = (m / n) * ln(2)
        self.num_bits = int(-1 * (capacity * math.log(error_rate)) / (math.log(2) ** 2))
        self.num_hashes = max(1, int((self.num_bits / capacity) * math.log(2)))

        # Bit array represented as an array of integers (bytearray)
        self.byte_array = bytearray(math.ceil(self.num_bits / 8))
        self.size_bytes = len(self.byte_array)
        logger.debug(
            "Initialized BloomFilter (capacity=%d, bits=%d, bytes=%d, hashes=%d, error_rate=%.4f)",
            self.capacity,
            self.num_bits,
            self.size_bytes,
            self.num_hashes,
            self.error_rate,
        )

    def _hashes(self, item: str) -> List[int]:
        """Generates k independent bit positions using double-hashing (Kirsch-Mitzenmacher technique)."""
        # MD5 produces 128 bits (16 bytes)
        h = hashlib.md5(item.encode("utf-8")).digest()
        h1 = int.from_bytes(h[:8], "little")
        h2 = int.from_bytes(h[8:], "little")

        positions = []
        for i in range(self.num_hashes):
            pos = (h1 + i * h2) % self.num_bits
            positions.append(pos)
        return positions

    def add(self, item: str) -> None:
        """Adds an item to the Bloom filter."""
        for pos in self._hashes(item.lower()):
            byte_idx = pos // 8
            bit_idx = pos % 8
            self.byte_array[byte_idx] |= (1 << bit_idx)

    def contains(self, item: str) -> bool:
        """Checks if an item might be in the set. Returns False if definitely not in set."""
        for pos in self._hashes(item.lower()):
            byte_idx = pos // 8
            bit_idx = pos % 8
            if not (self.byte_array[byte_idx] & (1 << bit_idx)):
                return False
        return True


CEFR_PRESETS = {
    "B1": {
        "level": "B1",
        "rank": 2000,
        "name": "B1 - Intermediate",
        "description": "Highest capture rate. Explains intermediate and advanced vocabulary. Ideal for ESL learners and general public audiences.",
    },
    "B2": {
        "level": "B2",
        "rank": 3500,
        "name": "B2 - Upper Intermediate",
        "description": "Standard baseline. Balances clarity without clutter. Explains advanced and uncommon terms for standard industry talks.",
    },
    "C1": {
        "level": "C1",
        "rank": 5500,
        "name": "C1 - Advanced / Professional",
        "description": "Selective capture. Assumes strong professional vocabulary. Explains sophisticated, literary, and specialized terminology.",
    },
    "C2": {
        "level": "C2",
        "rank": 8000,
        "name": "C2 - Mastery / Academic",
        "description": "Minimal capture. Only triggers on truly esoteric, obscure, or highly technical domain jargon.",
    },
}


class FrequencyIndex:
    """
    Multi-tier vocabulary frequency index combining an L1-cache Bloom filter
    with an exact HashSet of English headwords mapped to CEFR sensitivity tiers.
    """

    def __init__(self, rarity_threshold_rank: int = 3500, default_level: str = "B2"):
        self.current_level = default_level
        self.rarity_threshold_rank = rarity_threshold_rank
        self._common_words_set: Set[str] = set()
        self._rank_map: dict[str, int] = {}
        self._bloom = BloomFilter(capacity=8000, error_rate=0.001)

        self._load_ngsl_baselines()

    def _load_ngsl_baselines(self) -> None:
        """Loads core NGSL 1.2 headwords and tiered CEFR vocabulary corpus."""
        from src.infrastructure.nlp.ngsl_words import (
            CORE_NGSL_WORDS,
            TIER_B1_WORDS,
            TIER_B2_WORDS,
            TIER_C1_WORDS,
        )

        logger.info("Ingesting core NGSL and CEFR tiered frequency headwords...")

        # Tier 0 / Core Spoken English: Ranks 1 to ~900 (Common for all CEFR levels)
        for rank, word in enumerate(CORE_NGSL_WORDS, start=1):
            normalized = word.strip().lower()
            self._common_words_set.add(normalized)
            self._rank_map[normalized] = rank
            self._bloom.add(normalized)

        # Tier B1 (Intermediate): Ranks 2001 to 2500 (Rare in B1, common in B2, C1, C2)
        for idx, word in enumerate(TIER_B1_WORDS):
            normalized = word.strip().lower()
            rank = 2001 + idx
            self._common_words_set.add(normalized)
            self._rank_map[normalized] = rank
            self._bloom.add(normalized)

        # Tier B2 (Upper Intermediate): Ranks 3501 to 4500 (Rare in B1, B2; common in C1, C2)
        for idx, word in enumerate(TIER_B2_WORDS):
            normalized = word.strip().lower()
            rank = 3501 + idx
            self._common_words_set.add(normalized)
            self._rank_map[normalized] = rank
            self._bloom.add(normalized)

        # Tier C1 (Advanced): Ranks 5501 to 7500 (Rare in B1, B2, C1; common in C2)
        for idx, word in enumerate(TIER_C1_WORDS):
            normalized = word.strip().lower()
            rank = 5501 + idx
            self._common_words_set.add(normalized)
            self._rank_map[normalized] = rank
            self._bloom.add(normalized)

        logger.info(
            "FrequencyIndex ready: %d words indexed across CEFR tiers (L1 filter size: %.2f KB).",
            len(self._rank_map),
            self._bloom.size_bytes / 1024.0,
        )

    def set_sensitivity(self, level: str, custom_rank: Optional[int] = None) -> dict:
        """Dynamically tunes CEFR sensitivity level (B1, B2, C1, C2) or custom rank threshold."""
        level_upper = level.upper() if level else "B2"
        if custom_rank is not None and custom_rank > 0:
            self.current_level = level_upper
            self.rarity_threshold_rank = int(custom_rank)
        elif level_upper in CEFR_PRESETS:
            self.current_level = level_upper
            self.rarity_threshold_rank = CEFR_PRESETS[level_upper]["rank"]
        else:
            raise ValueError(f"Unknown CEFR sensitivity level: '{level}'. Valid levels: {list(CEFR_PRESETS.keys())}")

        logger.info("Updated vocabulary sensitivity to %s (Threshold rank: %d)", self.current_level, self.rarity_threshold_rank)
        return self.get_sensitivity()

    def get_sensitivity(self) -> dict:
        """Returns snapshot of active CEFR sensitivity settings."""
        preset = CEFR_PRESETS.get(self.current_level, CEFR_PRESETS["B2"])
        return {
            "level": self.current_level,
            "thresholdRank": self.rarity_threshold_rank,
            "name": preset["name"],
            "description": preset["description"],
            "availableLevels": list(CEFR_PRESETS.keys()),
        }

    def is_common(self, word: str) -> bool:
        """
        Evaluates whether a word is part of the common vocabulary for the active CEFR threshold.
        Fast path: Checks Bloom filter first in sub-microsecond time.
        Slow path: Validates exact rank against self.rarity_threshold_rank.
        """
        token = word.strip().lower()
        if not token:
            return True

        # Fast path: Bloom filter check
        if not self._bloom.contains(token):
            # Definitely not in known common corpus -> Rare
            return False

        # Rank check against active CEFR rarity threshold
        rank = self._rank_map.get(token, 99999)
        return rank <= self.rarity_threshold_rank

    def get_rank(self, word: str) -> int:
        """Returns the frequency rank of the word (1 to 8000+), or 99999 if unranked."""
        token = word.strip().lower()
        return self._rank_map.get(token, 99999)

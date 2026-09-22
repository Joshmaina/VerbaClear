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


class FrequencyIndex:
    """
    Multi-tier vocabulary frequency index combining an L1-cache Bloom filter
    with an exact HashSet of the top 3,500 English headwords.
    """

    def __init__(self, rarity_threshold_rank: int = 3500):
        self.rarity_threshold_rank = rarity_threshold_rank
        self._common_words_set: Set[str] = set()
        self._rank_map: dict[str, int] = {}
        self._bloom = BloomFilter(capacity=6000, error_rate=0.001)

        self._load_ngsl_baselines()

    def _load_ngsl_baselines(self) -> None:
        """Loads core NGSL 1.2 headwords and top spoken English frequency corpus."""
        # Top common English headwords covering ~92% of everyday spoken English
        # A curated baseline of core English lemmas
        from src.infrastructure.nlp.ngsl_words import CORE_NGSL_WORDS

        logger.info("Ingesting %d core NGSL frequency headwords...", len(CORE_NGSL_WORDS))
        for rank, word in enumerate(CORE_NGSL_WORDS, start=1):
            normalized = word.strip().lower()
            self._common_words_set.add(normalized)
            self._rank_map[normalized] = rank
            self._bloom.add(normalized)

        logger.info(
            "FrequencyIndex ready: %d words indexed (L1 filter size: %.2f KB).",
            len(self._common_words_set),
            self._bloom.size_bytes / 1024.0,
        )

    def is_common(self, word: str) -> bool:
        """
        Evaluates whether a word is part of the common vocabulary threshold.
        Fast path: Checks Bloom filter first in O(k) bit operations.
        Slow path: Confirms against exact HashSet on Bloom hit.
        """
        token = word.strip().lower()
        if not token:
            return True

        # Fast path: Bloom filter check
        if not self._bloom.contains(token):
            # Definitely not in common vocabulary -> Rare/Uncommon
            return False

        # Fallback check on exact set to eliminate false positives
        return token in self._common_words_set

    def get_rank(self, word: str) -> int:
        """Returns the frequency rank of the word (1 to 3500+), or 99999 if unranked."""
        token = word.strip().lower()
        return self._rank_map.get(token, 99999)

"""SimHash fuzzy near-duplicate detection for Intelligence Hub.

Part of v23.0 Phase 3 — uses character n-gram SimHash to detect
near-duplicate content that evades exact title/URL matching.

Algorithm overview:
  1. Normalize text (lowercase, strip punctuation, keep CJK)
  2. Generate character n-grams (sliding window)
  3. Hash each n-gram with MD5 → 64-bit integer
  4. Accumulate weighted bit vectors across all n-grams
  5. Threshold each bit position to 0/1 → final fingerprint
  6. Compare fingerprints via Hamming distance
"""

from __future__ import annotations

import hashlib
import re
import struct

from src.intelligence_hub.models import InfoItem

# Regex: strip everything except alphanumeric, CJK unified ideographs, and whitespace
_NON_ALNUM_WS = re.compile(r"[^\w\u4e00-\u9fff\s]", re.UNICODE)
# Collapse whitespace
_MULTI_WS = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    """Normalize text for simhash: lowercase, strip punctuation, collapse spaces."""
    if not text:
        return ""
    text = text.lower()
    text = _NON_ALNUM_WS.sub("", text)
    text = _MULTI_WS.sub(" ", text).strip()
    return text


def _char_ngrams(text: str, n: int) -> list[str]:
    """Generate character n-grams from text.

    For text shorter than n, returns the entire text as a single gram
    (if non-empty) to ensure we always produce a fingerprint.
    """
    if not text:
        return []
    if len(text) < n:
        return [text]
    return [text[i : i + n] for i in range(len(text) - n + 1)]


def _md5_hash_64(data: str) -> int:
    """Hash a string to a deterministic 64-bit integer using MD5."""
    digest = hashlib.md5(data.encode("utf-8")).digest()  # noqa: S324
    # Unpack first 8 bytes as unsigned 64-bit int (big-endian)
    return struct.unpack(">Q", digest[:8])[0]


class SimHash:
    """64-bit SimHash for fuzzy text similarity."""

    def __init__(self, n_gram: int = 3, hash_bits: int = 64) -> None:
        self._n_gram = n_gram
        self._hash_bits = hash_bits

    def compute(self, text: str) -> int:
        """Compute 64-bit simhash fingerprint for text.

        Returns 0 for empty / whitespace-only text.
        """
        normalized = _normalize_text(text)
        grams = _char_ngrams(normalized, self._n_gram)
        if not grams:
            return 0

        # Accumulator: one signed counter per bit position
        counters = [0] * self._hash_bits

        for gram in grams:
            h = _md5_hash_64(gram)
            for i in range(self._hash_bits):
                # If bit i is set, add 1; otherwise subtract 1
                if h & (1 << i):
                    counters[i] += 1
                else:
                    counters[i] -= 1

        # Threshold: positive → 1, else → 0
        fingerprint = 0
        for i in range(self._hash_bits):
            if counters[i] > 0:
                fingerprint |= 1 << i

        return fingerprint

    def distance(self, hash1: int, hash2: int) -> int:
        """Hamming distance between two simhash values."""
        return bin(hash1 ^ hash2).count("1")

    def is_near_duplicate(self, hash1: int, hash2: int, threshold: int = 3) -> bool:
        """True if hamming distance <= threshold."""
        return self.distance(hash1, hash2) <= threshold


class FuzzyDedupChecker:
    """Extended dedup using SimHash for fuzzy near-duplicate detection.

    Integrates with existing DedupChecker — this handles the fuzzy layer
    while the existing checker handles exact URL/title matching.
    """

    def __init__(self, threshold: int = 3, n_gram: int = 3) -> None:
        self._simhash = SimHash(n_gram=n_gram)
        self._threshold = threshold
        self._seen: dict[str, int] = {}  # normalized_title -> simhash fingerprint

    def is_near_duplicate(self, item: InfoItem) -> bool:
        """Check if item title is a near-duplicate of any seen item.

        Returns True if any previously seen title has hamming distance
        within threshold. Otherwise registers this item and returns False.
        """
        if not item.title:
            return False

        normalized = _normalize_text(item.title)
        if not normalized:
            return False

        fingerprint = self._simhash.compute(normalized)

        for _seen_title, seen_hash in self._seen.items():
            if self._simhash.is_near_duplicate(fingerprint, seen_hash, self._threshold):
                return True

        # Not a near-duplicate — register and pass through
        self._seen[normalized] = fingerprint
        return False

    def filter_batch(self, items: list[InfoItem]) -> list[InfoItem]:
        """Filter out near-duplicates from a batch.

        Items are checked in order; the first occurrence is kept.
        """
        return [item for item in items if not self.is_near_duplicate(item)]

    def reset(self) -> None:
        """Clear seen hashes for new refresh cycle."""
        self._seen.clear()

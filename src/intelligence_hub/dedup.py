"""Enhanced deduplication — URL and title normalization within a refresh cycle.

Part of v23.0 Multi-Source Intelligence Aggregation.

Within a single refresh cycle:
  1. Normalized URL hash (strip utm_*, ref, source params)
  2. Normalized title hash (lowercase, strip punctuation/whitespace)

Cross-cycle dedup is still handled by INSERT OR IGNORE on item_id PK.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.simhash import FuzzyDedupChecker

# URL params to strip for dedup normalization
_STRIP_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "ref",
        "source",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
    }
)

# Regex: non-alphanumeric (keeping CJK)
_NON_ALNUM = re.compile(r"[^\w\u4e00-\u9fff]", re.UNICODE)


def _normalize_url(url: str) -> str:
    """Strip tracking params and normalize URL for dedup comparison."""
    if not url:
        return ""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=False)
    filtered = {k: v for k, v in params.items() if k not in _STRIP_PARAMS}
    clean_query = urlencode(filtered, doseq=True)
    normalized = urlunparse(
        (
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.params,
            clean_query,
            "",  # strip fragment
        )
    )
    return normalized


def _normalize_title(title: str) -> str:
    """Lowercase + strip punctuation/whitespace for title dedup."""
    if not title:
        return ""
    return _NON_ALNUM.sub("", title.lower())


def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()  # noqa: S324


class DedupChecker:
    """Within-cycle deduplication via normalized URL and title hashes.

    Optionally integrates FuzzyDedupChecker for SimHash-based near-duplicate
    detection (v23.0 Phase 3). When fuzzy_checker is provided, items that pass
    exact dedup are additionally checked for fuzzy near-duplicates.
    """

    def __init__(self, fuzzy_checker: FuzzyDedupChecker | None = None) -> None:
        self._seen_urls: set[str] = set()
        self._seen_titles: set[str] = set()
        self._fuzzy = fuzzy_checker

    def is_duplicate(self, item: InfoItem) -> bool:
        # Check normalized URL
        if item.url:
            url_hash = _hash(_normalize_url(item.url))
            if url_hash in self._seen_urls:
                return True
            self._seen_urls.add(url_hash)

        # Check normalized title
        if item.title:
            title_hash = _hash(_normalize_title(item.title))
            if title_hash in self._seen_titles:
                return True
            self._seen_titles.add(title_hash)

        # Fuzzy near-duplicate check (if enabled)
        if self._fuzzy is not None and self._fuzzy.is_near_duplicate(item):
            return True

        return False

    def filter_batch(self, items: list[InfoItem]) -> list[InfoItem]:
        return [item for item in items if not self.is_duplicate(item)]

    def reset(self) -> None:
        """Clear seen hashes — call at start of each refresh cycle."""
        self._seen_urls.clear()
        self._seen_titles.clear()
        if self._fuzzy is not None:
            self._fuzzy.reset()

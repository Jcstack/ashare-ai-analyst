"""Event clustering — groups related items by title similarity within a time window.

Part of v23.0 Phase 2. Enables cross-verification scoring: more unique sources
covering the same event -> higher confidence.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.intelligence_hub.models import InfoItem

logger = logging.getLogger(__name__)

# Window for clustering related events
_DEFAULT_WINDOW_HOURS = 48

# Minimum Jaccard overlap ratio to consider items as same event.
# Set low to handle paraphrased headlines across sources (e.g. 0.18 for
# "Fed cuts rates by 25bps" vs "Federal Reserve cuts interest rates 25 basis points").
_MIN_SIMILARITY = 0.15

# Regex: alphanumeric words + individual CJK characters
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

# CJK Unicode range for splitting individual characters
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class EventCluster:
    """A group of items covering the same event."""

    cluster_id: str
    items: list[InfoItem] = field(default_factory=list)

    @property
    def unique_sources(self) -> int:
        """Count of unique source_ids in this cluster."""
        return len({item.source_id for item in self.items})

    @property
    def cross_verification_score(self) -> float:
        """0.0-1.0 based on number of unique sources.

        1 source = 0.0, 2 = 0.3, 3 = 0.6, 4+ = 1.0
        """
        n = self.unique_sources
        if n <= 1:
            return 0.0
        if n == 2:
            return 0.3
        if n == 3:
            return 0.6
        return 1.0

    @property
    def representative_title(self) -> str:
        """Title from the highest-scored item."""
        if not self.items:
            return ""
        scored = [i for i in self.items if i.content_score is not None]
        if scored:
            return max(scored, key=lambda i: i.content_score).title  # type: ignore[arg-type, return-value]
        return self.items[0].title


class EventClusterer:
    """Groups InfoItems into event clusters using title word overlap."""

    def __init__(
        self,
        window_hours: float = _DEFAULT_WINDOW_HOURS,
        min_similarity: float = _MIN_SIMILARITY,
    ) -> None:
        self._window_hours = window_hours
        self._min_similarity = min_similarity

    def cluster(self, items: list[InfoItem]) -> list[EventCluster]:
        """Group items into clusters.

        Items not matching any cluster get their own singleton cluster.
        Clustering is O(n*k) where k = number of existing clusters.
        """
        if not items:
            return []

        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=self._window_hours)

        # Filter to items within the time window (items without timestamps are kept)
        eligible = []
        for item in items:
            ts = self._parse_time(item.published_at)
            if ts is None or ts >= cutoff:
                eligible.append(item)

        if not eligible:
            return []

        # Build clusters incrementally
        clusters: list[EventCluster] = []
        cluster_tokens: list[set[str]] = []  # parallel list of token sets

        for item in eligible:
            tokens = self._tokenize(item.title)
            best_idx = -1
            best_sim = 0.0

            for idx, ct in enumerate(cluster_tokens):
                sim = self._jaccard_similarity(tokens, ct)
                if sim >= self._min_similarity and sim > best_sim:
                    best_sim = sim
                    best_idx = idx

            if best_idx >= 0:
                # Check time proximity with existing cluster items
                clusters[best_idx].items.append(item)
                # Update cluster tokens with union for broader matching
                cluster_tokens[best_idx] = cluster_tokens[best_idx] | tokens
            else:
                # Create new singleton cluster
                cid = hashlib.md5(item.title.encode()).hexdigest()[:12]  # noqa: S324
                new_cluster = EventCluster(cluster_id=cid, items=[item])
                clusters.append(new_cluster)
                cluster_tokens.append(tokens)

        return clusters

    def get_cross_verification_map(self, items: list[InfoItem]) -> dict[str, float]:
        """Returns item_id -> cross_verification_score for all items."""
        clusters = self.cluster(items)
        result: dict[str, float] = {}
        for cluster in clusters:
            score = cluster.cross_verification_score
            for item in cluster.items:
                result[item.item_id] = score
        return result

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Extract significant words from text.

        - Lowercase
        - Split on whitespace and punctuation via regex
        - Filter out very short tokens (len < 2) for non-CJK
        - Keep CJK characters as individual tokens
        """
        if not text:
            return set()

        text_lower = text.lower()
        raw_tokens = _TOKEN_RE.findall(text_lower)

        result: set[str] = set()
        for token in raw_tokens:
            # Check if token contains CJK characters
            cjk_chars = _CJK_RE.findall(token)
            if cjk_chars:
                # Add each CJK character as an individual token
                result.update(cjk_chars)
                # Also extract non-CJK parts of the token
                non_cjk = _CJK_RE.sub(" ", token).split()
                for part in non_cjk:
                    if len(part) >= 2:
                        result.add(part)
            elif len(token) >= 2:
                result.add(token)

        return result

    @staticmethod
    def _jaccard_similarity(a: set[str], b: set[str]) -> float:
        """Compute Jaccard similarity between two token sets."""
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    @staticmethod
    def _parse_time(time_str: str) -> datetime | None:
        """Parse a timestamp string to datetime with UTC timezone."""
        if not time_str:
            return None
        try:
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return None

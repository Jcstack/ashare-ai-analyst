"""Unified data model for Intelligence Hub information items.

Part of v21.0 Intelligence Hub.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


# Valid categories and priorities
CATEGORIES = frozenset(
    {
        "policy",
        "macro",
        "industry",
        "company",
        "market",
        "global",
        "social",
        "community",
    }
)
PRIORITIES = frozenset({"breaking", "high", "normal", "low"})


@dataclass
class InfoItem:
    """A single information item from any source."""

    source_id: str
    source_name: str
    title: str
    summary: str = ""
    url: str = ""
    category: str = "market"
    priority: str = "normal"
    tags: list[str] = field(default_factory=list)
    related_symbols: list[str] = field(default_factory=list)
    published_at: str = ""
    fetched_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    )
    is_bookmarked: bool = False
    is_read: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    content_score: float | None = None
    score_explain: dict[str, Any] = field(default_factory=dict)
    item_id: str = ""

    def __post_init__(self) -> None:
        if not self.item_id:
            self.item_id = self._generate_id()
        if self.category not in CATEGORIES:
            self.category = "market"
        if self.priority not in PRIORITIES:
            self.priority = "normal"
        self.published_at = self._normalize_published_at()

    def _normalize_published_at(self) -> str:
        """Normalize published_at to ISO-like format for consistent SQLite sorting."""
        if not self.published_at:
            return self.fetched_at  # fallback: use fetch time
        # Already ISO-like? (e.g. "2026-02-15 18:33:57" or "2026-02-15T14:00:00Z")
        if len(self.published_at) >= 10 and self.published_at[4] == "-":
            return self.published_at[:19].replace(
                "T", " "
            )  # normalize T separator + trim tz
        # Try parsing RFC 2822 / other formats
        try:
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(self.published_at)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            # Keep the original unparseable value so the scorer can detect it
            # and treat it as stale (999h age) rather than fresh
            return self.published_at

    def _generate_id(self) -> str:
        """Generate a deterministic ID from source_id + title + url."""
        raw = f"{self.source_id}:{self.title}:{self.url}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API responses."""
        return {
            "item_id": self.item_id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "category": self.category,
            "priority": self.priority,
            "tags": self.tags,
            "related_symbols": self.related_symbols,
            "published_at": self.published_at,
            "fetched_at": self.fetched_at,
            "is_bookmarked": self.is_bookmarked,
            "is_read": self.is_read,
            "extra": self.extra,
            "content_score": self.content_score,
            "score_explain": self.score_explain,
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> InfoItem:
        """Reconstruct from a SQLite row dict."""
        return cls(
            item_id=row["item_id"],
            source_id=row["source_id"],
            source_name=row["source_name"],
            title=row["title"],
            summary=row.get("summary") or "",
            url=row.get("url") or "",
            category=row.get("category", "market"),
            priority=row.get("priority", "normal"),
            tags=json.loads(row.get("tags") or "[]"),
            related_symbols=json.loads(row.get("related_symbols") or "[]"),
            published_at=row.get("published_at") or "",
            fetched_at=row.get("fetched_at") or "",
            is_bookmarked=bool(row.get("is_bookmarked", 0)),
            is_read=bool(row.get("is_read", 0)),
            extra=json.loads(row.get("extra") or "{}"),
            content_score=row.get("content_score"),
            score_explain=json.loads(row.get("score_explain") or "{}"),
        )

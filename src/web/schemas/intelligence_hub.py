"""Pydantic response models for Intelligence Hub API.

Part of v21.0 Intelligence Hub.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class InfoItemResponse(BaseModel):
    """A single information item in API responses."""

    item_id: str
    source_id: str
    source_name: str
    title: str
    summary: str = ""
    url: str = ""
    category: str = "market"
    priority: str = "normal"
    tags: list[str] = Field(default_factory=list)
    related_symbols: list[str] = Field(default_factory=list)
    published_at: str = ""
    fetched_at: str = ""
    is_bookmarked: bool = False
    is_read: bool = False
    extra: dict = Field(default_factory=dict)
    content_score: float | None = None
    score_explain: dict = Field(default_factory=dict)


class CategoryCount(BaseModel):
    """Category with item counts."""

    category: str
    total: int = 0
    unread: int = 0


class FeedResponse(BaseModel):
    """Paginated feed response."""

    items: list[InfoItemResponse]
    total: int = 0


class OverviewResponse(BaseModel):
    """Overview summary response."""

    total_items: int = 0
    sources_count: int = 0
    categories: dict[str, dict[str, int]] = Field(default_factory=dict)


class BookmarkResponse(BaseModel):
    """Bookmark toggle response."""

    item_id: str
    is_bookmarked: bool


class ReadResponse(BaseModel):
    """Mark-read response."""

    item_id: str
    is_read: bool


class RefreshResponse(BaseModel):
    """Manual refresh response."""

    new_items: int = 0
    status: str = "ok"


class SourceHealthResponse(BaseModel):
    """Per-source health status."""

    source_id: str
    layer: str = ""
    base_weight: float = 0.0
    effective_weight: float = 0.0
    compliance_level: str = "LOW"
    domain_tags: list[str] = Field(default_factory=list)
    status: str = "OK"
    consecutive_failures: int = 0
    avg_latency_ms: float = 0.0

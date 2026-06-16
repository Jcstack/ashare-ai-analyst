"""Intel Report Pydantic schemas for API serialization.

Part of v25.0 Intel-Portfolio Analysis (FR-IA003/004).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReportFactor(BaseModel):
    """A single analysis factor contributing to the signal."""

    category: str = ""
    impact: str = ""
    weight: float = 0.0
    description: str = ""


class ReportPositionContext(BaseModel):
    """Position-aware context within a report."""

    cost_price: float | None = None
    shares: int | None = None
    pnl_percent: float | None = None
    advice: str = ""
    key_levels: dict[str, float | None] | None = None


class IntelReportResponse(BaseModel):
    """Single intel report returned by the API."""

    id: str
    symbol: str
    stock_name: str = ""
    intel_item_ids: list[str] = Field(default_factory=list)
    refresh_cycle: str = ""
    action: str = "hold"
    signal: str = "neutral"
    confidence: float = 0.5
    summary: str = ""
    factors: list[ReportFactor] = Field(default_factory=list)
    position_context: ReportPositionContext | None = None
    risk_warnings: list[str] = Field(default_factory=list)
    outlook: str = ""
    reasoning: list[str] = Field(default_factory=list)
    intel_summary: str = ""
    model_used: str = ""
    generated_at: str = ""
    created_at: str = ""
    thread_id: str | None = None
    is_read: bool = False


class ReportListResponse(BaseModel):
    """Paginated list of reports."""

    reports: list[IntelReportResponse] = Field(default_factory=list)
    total: int = 0


class ReportUnreadCountResponse(BaseModel):
    """Unread report count."""

    count: int = 0


class ChatFromReportResponse(BaseModel):
    """Response after creating a chat thread from a report."""

    thread_id: str
    initial_message: str = ""

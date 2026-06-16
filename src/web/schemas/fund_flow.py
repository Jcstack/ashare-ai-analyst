"""Fund flow and support/resistance Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FundFlowItem(BaseModel):
    """Single-day fund flow data for a stock."""

    date: str = ""
    close: float | None = None
    pct_change: float | None = None
    main_net: float | None = None
    main_net_pct: float | None = None
    super_large_net: float | None = None
    large_net: float | None = None
    medium_net: float | None = None
    small_net: float | None = None


class FundFlowDetail(BaseModel):
    """Per-stock inflow/outflow detail from real-time data."""

    symbol: str = ""
    name: str = ""
    price: float | None = None
    pct_change: float | None = None
    inflow: float | None = None
    outflow: float | None = None
    net: float | None = None
    amount: float | None = None


class SRKeyLevel(BaseModel):
    """A single key support/resistance level from AI analysis."""

    price: float = 0.0
    type: str = ""
    strength: str = ""
    comment: str = ""


class SRAnalysisResult(BaseModel):
    """AI-enhanced support/resistance analysis result."""

    status: str = "success"
    symbol: str = ""
    summary: str = ""
    key_levels: list[SRKeyLevel] = Field(default_factory=list)
    advice: str = ""
    risk_warnings: list[str] = Field(default_factory=list)
    generated_at: str | None = None
    message: str | None = None

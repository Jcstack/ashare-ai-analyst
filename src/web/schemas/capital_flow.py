"""Capital flow Pydantic schemas.

Per PRD v26.0 FR-CF003: Capital flow API request/response models.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MacroChannelItem(BaseModel):
    """Single macro capital channel data point."""

    channel: str = Field(description="Channel name: northbound/southbound/margin/etf")
    value: float = Field(description="Amount in 亿元")
    direction: str = Field(description="up/down/flat")


class MacroFlowOverview(BaseModel):
    """Macro capital flow overview response."""

    date: str = ""
    environment_score: float = Field(0.0, description="Composite score [-100, +100]")
    signal: str = Field("neutral", description="bullish/bearish/neutral")
    northbound_net: float = Field(0.0, description="北向净买入 (亿元)")
    southbound_net: float = Field(0.0, description="南向净买入 (亿元)")
    margin_balance: float = Field(0.0, description="融资余额 (亿元)")
    margin_balance_change: float = Field(0.0, description="融资余额变化 (亿元)")
    etf_net_flow: float = Field(0.0, description="ETF 净申购 (亿元)")
    channels: list[MacroChannelItem] = Field(default_factory=list)
    interpretation: str = Field("", description="Rule-based Chinese interpretation")
    updated_at: str = ""


class MacroFlowHistoryItem(BaseModel):
    """Single day in macro flow history."""

    date: str
    environment_score: float = 0.0
    signal: str = "neutral"
    northbound_net: float = 0.0
    southbound_net: float = 0.0
    margin_balance_change: float = 0.0
    etf_net_flow: float = 0.0


class MacroFlowHistoryResponse(BaseModel):
    """Macro flow history response."""

    days: int = 30
    items: list[MacroFlowHistoryItem] = Field(default_factory=list)


# ------------------------------------------------------------------
# Sector-level capital flow schemas (Phase 2)
# ------------------------------------------------------------------


class SectorFlowItem(BaseModel):
    """Single sector capital flow data point."""

    sector_name: str
    sector_type: str = "industry"  # industry | concept
    change_pct: float | None = None
    net_inflow: float = 0.0  # 亿元
    main_net_inflow: float = 0.0
    turnover: float = 0.0


class SectorFlowResponse(BaseModel):
    """Sector capital flow ranking response."""

    type: str = "industry"
    period: str = "today"
    items: list[SectorFlowItem] = Field(default_factory=list)
    interpretation: str = Field("", description="Rule-based Chinese interpretation")


class HeatmapItem(BaseModel):
    """Single heatmap data point for sector flow visualisation."""

    name: str
    net_inflow: float = 0.0
    change_pct: float = 0.0
    turnover: float = 0.0
    color_value: float = 0.0  # normalised [-1, 1]


class HeatmapResponse(BaseModel):
    """Sector flow heatmap response."""

    items: list[HeatmapItem] = Field(default_factory=list)
    updated_at: str = ""

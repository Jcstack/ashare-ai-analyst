"""Pydantic models for the AI Trading Advisor API.

Per PRD v3.2 FR-TA001~004, FR-HS003~004.
"""

from pydantic import BaseModel, Field


class QuantSignals(BaseModel):
    """Quantitative signal summary from Layer 1."""

    technical_score: float = Field(0.0, description="Technical indicator score 0~1")
    momentum_score: float = Field(0.0, description="Momentum score 0~1")
    strategy_consensus: str = Field(
        "", description="Strategy consensus: 看多/看空/分歧"
    )
    bayesian_probability: float = Field(0.0, description="Bayesian probability 0~1")


class TargetPrice(BaseModel):
    """Target price range."""

    low: float = Field(0.0, description="Lower target price")
    high: float = Field(0.0, description="Upper target price")


class StockAdviceResult(BaseModel):
    """AI-generated operation advice for a single stock."""

    status: str = "success"
    symbol: str
    name: str = ""
    action: str = Field(description="buy | add | hold | reduce | sell | watch")
    action_label: str = Field(description="操作标签 (中文)")
    confidence: float = Field(description="Confidence 0~1")
    risk_level: str = Field(description="low | medium | high")
    quant_signals: dict = Field(default_factory=dict)
    ai_reasoning: list[str] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    target_price: TargetPrice | None = None
    stop_loss: float | None = None
    disclaimer: str = ""
    generated_at: str = ""
    model_used: str = ""


class WatchlistStrategyItem(BaseModel):
    """Single stock advice within a watchlist strategy report."""

    symbol: str
    name: str = ""
    action: str
    action_label: str
    confidence: float
    risk_level: str
    ai_reasoning: list[str] = Field(default_factory=list)


class WatchlistStrategyResult(BaseModel):
    """Strategy report for the user's watchlist."""

    status: str = "success"
    items: list[WatchlistStrategyItem] = Field(default_factory=list)
    total: int = 0
    generated_at: str = ""
    disclaimer: str = ""


class PositionAdvice(BaseModel):
    """Add/reduce advice for a single held position."""

    symbol: str
    name: str = ""
    action: str
    action_label: str
    confidence: float
    risk_level: str
    cost_price: float = 0.0
    current_price: float = 0.0
    pnl_pct: float = 0.0
    shares: int = 0
    holding_days: int = 0
    ai_reasoning: list[str] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    stop_loss: float | None = None


class PortfolioAdviceResult(BaseModel):
    """AI advice for the entire portfolio."""

    status: str = "success"
    positions: list[PositionAdvice] = Field(default_factory=list)
    total: int = 0
    generated_at: str = ""
    disclaimer: str = ""


class PortfolioAdviceRequest(BaseModel):
    """Request body for portfolio advice endpoint."""

    positions: list[dict] = Field(
        description="List of position dicts with symbol, cost_price, shares, etc."
    )


class HolidayImpactFactor(BaseModel):
    """A single factor contributing to holiday impact."""

    name: str
    impact: str = Field(description="positive | negative | neutral")
    weight: float = Field(0.0, description="Factor weight 0~1")
    description: str = ""


class HolidayImpactResult(BaseModel):
    """Holiday period impact assessment for a stock."""

    status: str = "success"
    symbol: str = ""
    impact_score: float = Field(0.5, description="Impact severity 0~1")
    impact_direction: str = Field(
        "neutral", description="positive | negative | neutral"
    )
    factors: list[HolidayImpactFactor] = Field(default_factory=list)
    ai_assessment: str = ""
    suggested_action: str = Field("watch", description="hold | reduce | watch")
    confidence: float = 0.0
    generated_at: str = ""
    disclaimer: str = ""


class PositionImpact(BaseModel):
    """Impact on a single position in the reopen briefing."""

    symbol: str
    impact: str = Field(description="positive | negative | neutral")
    brief: str = ""


class ReopenBriefingResult(BaseModel):
    """Pre-open comprehensive briefing report."""

    status: str = "success"
    market_outlook: str = Field("neutral", description="bullish | bearish | neutral")
    confidence: float = 0.0
    summary: str = ""
    key_events: list[str] = Field(default_factory=list)
    position_impacts: list[PositionImpact] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    generated_at: str = ""
    disclaimer: str = ""

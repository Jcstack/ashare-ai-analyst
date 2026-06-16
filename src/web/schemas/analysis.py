"""Analysis Pydantic models (Bayesian, move analysis, chart events, AI results)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IndicatorProbabilities(BaseModel):
    """Probability distribution for a binned indicator."""

    up: float = 0.0
    flat: float = 0.0
    down: float = 0.0


class BayesianIndicatorItem(BaseModel):
    """Bayesian analysis result for a single indicator."""

    indicator: str = ""
    current_value: float = 0.0
    bin_label: str = ""
    probabilities: IndicatorProbabilities = Field(
        default_factory=IndicatorProbabilities
    )
    sample_count: int = 0
    interpretation: str = ""
    analogy: str = ""
    data_sufficient: bool = False


class BayesianComposite(BaseModel):
    """Composite signal aggregated across all indicators."""

    signal: str = "中性"
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    summary: str = ""


class BayesianAnalysisResult(BaseModel):
    """Full Bayesian indicator analysis response."""

    symbol: str = ""
    name: str = ""
    analysis_date: str = ""
    lookback_days: int = 250
    forward_days: int = 5
    indicators: list[BayesianIndicatorItem] = Field(default_factory=list)
    composite: BayesianComposite = Field(default_factory=BayesianComposite)


class MoveAnalysisRequest(BaseModel):
    """Optional position context for move analysis."""

    cost_price: float | None = None
    shares: int | None = None
    holding_days: int | None = None


class MoveAnalysisFactor(BaseModel):
    """A single attribution factor for the price move."""

    category: str = ""
    impact: str = "neutral"
    weight: float = 0.0
    description: str = ""


class MoveAnalysisPositionContext(BaseModel):
    """Position-aware advice returned when portfolio data is provided."""

    cost_price: float | None = None
    current_price: float | None = None
    pnl_percent: float | None = None
    holding_days: int | None = None
    advice: str = ""
    key_levels: dict[str, float] | None = None


class MoveAnalysisResult(BaseModel):
    """Full move attribution analysis result."""

    status: str = "success"
    symbol: str = ""
    name: str = ""
    analysis_date: str = ""
    price_change: float | None = None
    move_summary: str = ""
    factors: list[MoveAnalysisFactor] = Field(default_factory=list)
    position_context: MoveAnalysisPositionContext | None = None
    outlook: str = ""
    reasoning: list[str] = Field(default_factory=list)
    generated_at: str | None = None
    model_used: str | None = None
    message: str | None = None


class ChartEvent(BaseModel):
    """A single event to annotate on a K-line chart."""

    date: str = ""
    type: str = ""
    title: str = ""
    impact: str = "neutral"
    details: str = ""
    url: str | None = None


class ChartEventsResult(BaseModel):
    """Aggregated chart events for annotation."""

    symbol: str = ""
    events: list[ChartEvent] = Field(default_factory=list)


class AIAnalysisResult(BaseModel):
    """Full AI analysis result."""

    status: str = "success"
    symbol: str = ""
    trend: str | None = None
    signal: str | None = None
    confidence: float | None = None
    risk_level: str | None = None
    reasoning: list[str] = Field(default_factory=list)
    target_price_range: dict | None = None
    key_factors: list[str] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    news_sentiment: str | None = None
    generated_at: str | None = None
    model_used: str | None = None
    message: str | None = None


class Alert(BaseModel):
    """Stock alert notification."""

    id: str = ""
    symbol: str = ""
    name: str = ""
    alert_type: str = ""
    severity: str = "info"
    title: str = ""
    description: str = ""
    value: float | None = None
    threshold: float | None = None
    timestamp: str = ""


class IndicatorExplanation(BaseModel):
    """Technical indicator explanation for beginners."""

    name: str
    short_desc: str
    full_desc: str
    params: dict[str, str] | None = None
    signals: dict[str, str]
    beginner_tip: str

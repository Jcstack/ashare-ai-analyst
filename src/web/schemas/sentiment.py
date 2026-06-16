"""Pydantic models for sentiment analysis and cross-market correlation.

Per PRD v3.2 FR-TN003 (resonance), FR-TN004 (sentiment report),
FR-GM004 (cross-market).
"""

from pydantic import BaseModel


# --- FR-TN003: Resonance ---


class ResonanceTimelineEntry(BaseModel):
    platform: str
    rank: int
    timestamp: str


class ResonanceEventItem(BaseModel):
    event_id: str
    title: str
    resonance_level: str
    platforms: list[str]
    rank_timeline: list[ResonanceTimelineEntry] = []
    related_stocks: list[str] = []
    sentiment: str = "neutral"
    first_appeared: str = ""
    last_updated: str = ""
    heat_score: float = 0.0


class ResonanceResult(BaseModel):
    status: str
    events: list[ResonanceEventItem]
    total: int
    generated_at: str


# --- FR-TN004: Sentiment Report ---


class SentimentCoreTrend(BaseModel):
    topic: str
    resonance_level: str = "L1"
    sentiment: str = "neutral"
    related_stocks: list[str] = []
    summary: str = ""


class SentimentPolicySignal(BaseModel):
    title: str
    impact: str = "neutral"
    affected_sectors: list[str] = []
    confidence: float = 0.5
    summary: str = ""


class SentimentGlobalLinkage(BaseModel):
    us_market_summary: str = ""
    commodity_impact: str = ""
    forex_impact: str = ""


class SentimentRiskAlert(BaseModel):
    type: str = ""
    title: str = ""
    severity: str = "medium"
    mitigation: str = ""


class SentimentSectorOutlook(BaseModel):
    bullish: list[str] = []
    bearish: list[str] = []
    neutral: list[str] = []


class SentimentReportResult(BaseModel):
    status: str
    core_trends: list[SentimentCoreTrend] = []
    policy_signals: list[SentimentPolicySignal] = []
    global_linkage: SentimentGlobalLinkage = SentimentGlobalLinkage()
    risk_alerts: list[SentimentRiskAlert] = []
    sector_outlook: SentimentSectorOutlook = SentimentSectorOutlook()
    overall_outlook: str = ""
    generated_at: str = ""
    disclaimer: str = ""
    model_used: str | None = None
    message: str | None = None


# --- FR-GM004: Cross-Market ---


class CrossMarketPeer(BaseModel):
    symbol: str
    price: float | None = None
    pct_change: float | None = None


class CrossMarketGroup(BaseModel):
    trend: str = "neutral"
    peers: list[CrossMarketPeer] = []
    impact_score: float = 0.0
    avg_pct_change: float | None = None
    summary: str | None = None


class CrossMarketResult(BaseModel):
    symbol: str
    tags: list[str] = []
    us_market: CrossMarketGroup = CrossMarketGroup()
    hk_market: CrossMarketGroup = CrossMarketGroup()
    commodity_exposure: CrossMarketGroup = CrossMarketGroup()
    global_indices: CrossMarketGroup = CrossMarketGroup()
    combined_impact_score: float = 0.0
    impact_direction: str = "neutral"
    generated_at: str = ""

"""Pydantic models for the Holiday Research Workbench API.

Supports auto-collected context, user notes, structured evidence,
research questions, scenario analysis, comprehensive AI analysis,
and follow-up Q&A for holiday period stock research.

v3.4 additions: AssociationProfileResponse, ResearchQuestion,
EvidenceItem, Scenario, ScenarioResult.
"""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# v3.2 original models (kept for backward compatibility)
# ---------------------------------------------------------------------------


class UserNote(BaseModel):
    """A user-created research note."""

    id: str = ""
    content: str = ""
    note_type: str = Field(
        "observation",
        description="observation | box_office | industry_report | policy | custom",
    )
    created_at: str = ""


class AddNoteRequest(BaseModel):
    """Request body for adding a user research note."""

    content: str = Field(description="Note content text")
    note_type: str = Field(
        "observation",
        description="observation | box_office | industry_report | policy | custom",
    )


# ---------------------------------------------------------------------------
# v3.4 — Association Profile
# ---------------------------------------------------------------------------


class ConceptLinkResponse(BaseModel):
    """A concept board linked to the stock."""

    code: str = ""
    name: str = ""
    pct_change: float = 0.0
    rank_pct: float | None = None


class PeerLinkResponse(BaseModel):
    """A cross-market peer."""

    symbol: str = ""
    market: str = ""
    tags: list[str] = Field(default_factory=list)


class IndustryProfileResponse(BaseModel):
    """Industry-specific research dimensions."""

    tag: str = ""
    display: str = ""
    key_metrics: list[str] = Field(default_factory=list)
    seasonal_events: dict = Field(default_factory=dict)
    value_chain: list[str] = Field(default_factory=list)
    research_hints: dict[str, str] = Field(default_factory=dict)
    concept_keywords: list[str] = Field(default_factory=list)


class AssociationProfileResponse(BaseModel):
    """Unified multi-dimensional stock association profile."""

    symbol: str = ""
    industry: str = ""
    concepts: list[ConceptLinkResponse] = Field(default_factory=list)
    resonance_level: str = Field("none", description="none | weak | moderate | strong")
    cross_market_peers: list[PeerLinkResponse] = Field(default_factory=list)
    cross_market_tags: list[str] = Field(default_factory=list)
    keyword_themes: list[str] = Field(default_factory=list)
    industry_profile: IndustryProfileResponse | None = None


# ---------------------------------------------------------------------------
# v3.4 — Research Questions
# ---------------------------------------------------------------------------


class ResearchQuestion(BaseModel):
    """An LLM-generated research question for holiday research."""

    id: str = ""
    category: str = Field(
        "",
        description="industry_event | competitor | policy | macro | cross_market | supply_chain",
    )
    text: str = ""
    priority: str = Field("medium", description="high | medium | low")
    data_hint: str = Field("", description="Where to find the answer")
    status: str = Field("pending", description="pending | answered")


class ResearchChecklist(BaseModel):
    """LLM-generated research checklist for a stock."""

    status: str = "success"
    symbol: str = ""
    questions: list[ResearchQuestion] = Field(default_factory=list)
    generated_at: str = ""


# ---------------------------------------------------------------------------
# v3.4 — Structured Evidence
# ---------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    """A structured evidence item linked to a research question."""

    id: str = ""
    content: str = ""
    evidence_type: str = Field(
        "observation",
        description="data_point | observation | source_link | analysis",
    )
    linked_question_id: str = Field("", description="Optional research question ID")
    impact: str = Field("neutral", description="bullish | bearish | neutral")
    confidence: str = Field("medium", description="low | medium | high")
    source: str = Field("", description="User-provided source description")
    created_at: str = ""


class AddEvidenceRequest(BaseModel):
    """Request body for adding a structured evidence item."""

    content: str = Field(description="Evidence content text")
    evidence_type: str = Field(
        "observation", description="data_point | observation | source_link | analysis"
    )
    linked_question_id: str = Field("", description="Optional research question ID")
    impact: str = Field("neutral", description="bullish | bearish | neutral")
    confidence: str = Field("medium", description="low | medium | high")
    source: str = Field("", description="Source description")


# ---------------------------------------------------------------------------
# v3.4 — Scenario Analysis
# ---------------------------------------------------------------------------


class Scenario(BaseModel):
    """A user-defined or auto-generated analysis scenario."""

    name: str = ""
    description: str = ""
    key_assumptions: list[str] = Field(default_factory=list)


class ScenarioPriceImpact(BaseModel):
    """Price impact assessment for a scenario."""

    direction: str = Field("flat", description="up | down | flat")
    magnitude: str = Field("small", description="small | medium | large")


class ScenarioResult(BaseModel):
    """LLM evaluation result for a single scenario."""

    name: str = ""
    probability: str = Field("medium", description="low | medium | high")
    price_impact: ScenarioPriceImpact = Field(default_factory=ScenarioPriceImpact)
    key_drivers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    reasoning: str = ""


class ScenarioAnalysisRequest(BaseModel):
    """Request body for scenario analysis."""

    scenarios: list[Scenario] = Field(
        default_factory=list,
        description="User-defined scenarios. Empty = use auto-generated defaults.",
    )


class ScenarioAnalysisResult(BaseModel):
    """Full scenario analysis output."""

    status: str = "success"
    symbol: str = ""
    scenarios: list[ScenarioResult] = Field(default_factory=list)
    generated_at: str = ""
    disclaimer: str = ""


# ---------------------------------------------------------------------------
# v3.2 original models — context and analysis (enhanced in v3.4)
# ---------------------------------------------------------------------------


class HolidayResearchContext(BaseModel):
    """Auto-collected research context for a stock during holiday."""

    status: str = "success"
    symbol: str = ""
    holiday_key: str = Field(
        "", description="Next trading day ISO date, e.g. 2026-02-24"
    )
    news: list[dict] = Field(
        default_factory=list, description="Stock-specific news items"
    )
    concepts: list[dict] = Field(
        default_factory=list, description="Related concept sector data"
    )
    global_market: dict = Field(
        default_factory=dict, description="Global market snapshot"
    )
    cross_market: dict = Field(
        default_factory=dict, description="Cross-market peer comparison"
    )
    sentiment_matches: list[dict] = Field(
        default_factory=list, description="Matched trend news items"
    )
    user_notes: list[UserNote] = Field(
        default_factory=list, description="User-created notes"
    )
    calendar_info: dict = Field(
        default_factory=dict, description="Trading calendar info"
    )
    # v3.4: association profile included in context
    association_profile: AssociationProfileResponse | None = Field(
        None, description="Multi-dimensional stock association profile"
    )


class BusinessFactor(BaseModel):
    """A business factor contributing to the analysis."""

    name: str = ""
    impact: str = Field("neutral", description="positive | negative | neutral")
    weight: float = Field(0.0, description="Factor weight 0~1")
    analysis: str = ""


class SectorAnalysis(BaseModel):
    """Sector/concept analysis summary."""

    summary: str = ""
    key_concepts: list[str] = Field(default_factory=list)
    sector_trend: str = Field("neutral", description="bullish | bearish | neutral")


class PeerComparison(BaseModel):
    """Cross-market peer comparison summary."""

    summary: str = ""
    us_peers: list[dict] = Field(default_factory=list)
    hk_peers: list[dict] = Field(default_factory=list)


class RiskItem(BaseModel):
    """A single risk matrix entry."""

    risk: str = ""
    probability: str = Field("medium", description="low | medium | high")
    impact: str = Field("medium", description="low | medium | high")
    mitigation: str = ""


class ReopeningStrategy(BaseModel):
    """Recommended strategy for market reopening."""

    action: str = Field("watch", description="buy | add | hold | reduce | sell | watch")
    confidence: float = Field(0.0, description="Confidence 0~1")
    reasoning: str = ""
    target_range: list[float] = Field(
        default_factory=list, description="[low, high] target prices"
    )
    stop_loss: float | None = None


class ComprehensiveAnalysisResult(BaseModel):
    """Full holiday research analysis output from AI."""

    status: str = "success"
    symbol: str = ""
    business_factors: list[BusinessFactor] = Field(default_factory=list)
    sector_analysis: SectorAnalysis = Field(default_factory=SectorAnalysis)
    peer_comparison: PeerComparison = Field(default_factory=PeerComparison)
    risk_matrix: list[RiskItem] = Field(default_factory=list)
    reopening_strategy: ReopeningStrategy = Field(default_factory=ReopeningStrategy)
    key_watch_items: list[str] = Field(default_factory=list)
    overall_assessment: str = ""
    generated_at: str = ""
    disclaimer: str = ""
    # v3.4 enhancements
    evidence_completeness: float = Field(
        0.0, description="Answered questions / total questions (0~1)"
    )
    association_context: str = Field(
        "", description="Summary of how association data influenced analysis"
    )


class ConversationMessage(BaseModel):
    """A single message in a multi-turn conversation."""

    role: str = Field(description="user | assistant")
    content: str = ""
    timestamp: str = ""


class FollowupRequest(BaseModel):
    """Request body for a follow-up question."""

    question: str = Field(description="The follow-up question to ask")


class FollowupResponse(BaseModel):
    """Response to a follow-up question."""

    status: str = "success"
    question: str = ""
    answer: str = ""
    generated_at: str = ""
    disclaimer: str = ""
    messages: list[ConversationMessage] = Field(
        default_factory=list,
        description="Full conversation history (for multi-turn dialog)",
    )


# ---------------------------------------------------------------------------
# Profile Override (custom association profile)
# ---------------------------------------------------------------------------


class ProfileOverrideConceptItem(BaseModel):
    """A user-added concept for profile override."""

    code: str = Field("", description="Concept board code, e.g. BK0123")
    name: str = Field("", description="Concept name")


class ProfileOverridePeerItem(BaseModel):
    """A user-added cross-market peer for profile override."""

    symbol: str = Field("", description="Peer ticker symbol")
    market: str = Field("us", description="us | hk | commodity")
    tags: list[str] = Field(default_factory=list)


class ProfileOverrideRequest(BaseModel):
    """Request body for updating profile overrides."""

    added_concepts: list[ProfileOverrideConceptItem] | None = None
    removed_concept_codes: list[str] | None = None
    added_peers: list[ProfileOverridePeerItem] | None = None
    removed_peer_symbols: list[str] | None = None
    added_keywords: list[str] | None = None
    removed_keywords: list[str] | None = None
    industry_override: str | None = None


class ProfileOverrideResponse(BaseModel):
    """Current profile override state for a symbol."""

    symbol: str = ""
    has_override: bool = False
    added_concepts: list[ProfileOverrideConceptItem] = Field(default_factory=list)
    removed_concept_codes: list[str] = Field(default_factory=list)
    added_peers: list[ProfileOverridePeerItem] = Field(default_factory=list)
    removed_peer_symbols: list[str] = Field(default_factory=list)
    added_keywords: list[str] = Field(default_factory=list)
    removed_keywords: list[str] = Field(default_factory=list)
    industry_override: str | None = None
    updated_at: str = ""

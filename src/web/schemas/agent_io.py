"""Agent I/O Pydantic schemas — mandatory output contract.

Every agent output inherits ``AgentOutputBase`` which enforces the
spec's five non-negotiable fields:
  1. confidence_score  (float 0-1)
  2. key_assumptions   (list[str])
  3. failure_modes     (list[str])
  4. data_lineage      (list[DataLineageRef])
  5. data_gaps         (list[str])

Part of v18.0 Agent Spec Compliance — Phase 2.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Shared types ──────────────────────────────────────────────


class DataLineageRef(BaseModel):
    """Reference to a data snapshot used in the analysis."""

    snapshot_id: str = ""
    source: str = ""
    source_type: str = ""
    timestamp: str = ""


# ── Base models ───────────────────────────────────────────────


class AgentInputBase(BaseModel):
    """Base model for all agent inputs.

    Carries request-level metadata for traceability.
    """

    schema_version: str = "1.0.0"
    request_id: str = ""
    timestamp: str = ""


class AgentOutputBase(BaseModel):
    """Base model for all agent outputs.

    Every agent MUST populate these fields (Rule 7).
    The five mandatory elements ensure institutional-grade
    transparency in every analysis output.
    """

    schema_version: str = "1.0.0"
    request_id: str = ""
    timestamp: str = ""
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    key_assumptions: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    data_lineage: list[DataLineageRef] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


# ── 1. Data QA Agent ──────────────────────────────────────────


class DataQAInput(AgentInputBase):
    """Input for the Data QA agent."""

    symbol: str = ""
    portfolio: list[dict] | None = None  # for portfolio_review pipeline


class DataQAOutput(AgentOutputBase):
    """Output from the Data QA agent."""

    data_quality_score: int = Field(default=0, ge=0, le=100)
    freshness_checks: dict = Field(default_factory=dict)
    is_sufficient: bool = True


# ── 2. Analyst Agent ──────────────────────────────────────────


class AnalystInput(AgentInputBase):
    """Input for the Analyst agent."""

    symbol: str = ""
    quote: dict = Field(default_factory=dict)
    indicators: dict = Field(default_factory=dict)
    data_quality_score: int = 100


class AnalystOutput(AgentOutputBase):
    """Output from the Analyst agent."""

    signal: str = "watch"
    dimensions: list[dict] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)


# ── 3. Backtest & Validation Agent ────────────────────────────


class BacktestInput(AgentInputBase):
    """Input for the Backtest agent."""

    symbol: str = ""
    signal: str = ""
    daily_returns: list[float] = Field(default_factory=list)


class BacktestOutput(AgentOutputBase):
    """Output from the Backtest agent."""

    walk_forward_report: dict = Field(default_factory=dict)
    overfit_warning: bool = False
    regime_sensitivity: dict = Field(default_factory=dict)


# ── 4. Risk Agent ─────────────────────────────────────────────


class RiskInput(AgentInputBase):
    """Input for the Risk agent."""

    symbol: str = ""
    portfolio: dict = Field(default_factory=dict)
    signals: dict = Field(default_factory=dict)
    regime: str = ""
    sentiment_score: float | None = None
    current_regime: str = ""
    overfit_warning: bool | None = None
    data_quality_score: int = 100


class RiskOutput(AgentOutputBase):
    """Output from the Risk agent."""

    risk_level: str = "medium"
    risk_assessment: dict = Field(default_factory=dict)
    var_result: dict = Field(default_factory=dict)
    position_suggestion: dict = Field(default_factory=dict)
    risk_approved: bool = False
    warnings: list[str] = Field(default_factory=list)


# ── 5. Sentiment Agent ────────────────────────────────────────


class SentimentInput(AgentInputBase):
    """Input for the Sentiment agent."""

    symbol: str = ""
    news_items: list[dict] = Field(default_factory=list)


class SentimentOutput(AgentOutputBase):
    """Output from the Sentiment agent."""

    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    sentiment_signal: str = "neutral"
    key_events: list[dict] = Field(default_factory=list)


# ── 6. Macro/Regime Agent ─────────────────────────────────────


class RegimeInput(AgentInputBase):
    """Input for the Regime agent."""

    symbol: str = ""
    daily_returns: list[float] = Field(default_factory=list)
    indices_data: dict = Field(default_factory=dict)


class RegimeOutput(AgentOutputBase):
    """Output from the Regime agent."""

    current_regime: str = "unknown"
    regime_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    transition_matrix: dict = Field(default_factory=dict)


# ── 7. Correlation Agent ──────────────────────────────────────


class CorrelationInput(AgentInputBase):
    """Input for the Correlation agent."""

    symbols: list[str] = Field(default_factory=list)
    returns_matrix: dict = Field(default_factory=dict)
    portfolio: list[dict] = Field(default_factory=list)


class CorrelationOutput(AgentOutputBase):
    """Output from the Correlation agent."""

    correlation_matrix: dict = Field(default_factory=dict)
    highly_correlated: list[dict] = Field(default_factory=list)
    diversification_score: float = Field(default=0.0, ge=0.0, le=1.0)


# ── 8. Portfolio Construction Agent ───────────────────────────


class PortfolioInput(AgentInputBase):
    """Input for the Portfolio agent."""

    holdings: list[dict] = Field(default_factory=list)
    risk_budget: dict = Field(default_factory=dict)
    signals: dict = Field(default_factory=dict)
    risk_level: str = ""
    position_suggestion: dict = Field(default_factory=dict)
    capital_balance: float = 0.0
    correlation_matrix: dict = Field(default_factory=dict)
    diversification_score: float = 0.0


class PortfolioOutput(AgentOutputBase):
    """Output from the Portfolio agent."""

    adjustments: list[dict] = Field(default_factory=list)
    suggested_shares: int = 0
    suggested_weight: float = 0.0
    concentration_warnings: list[str] = Field(default_factory=list)


# ── 9. Execution Planning Agent ───────────────────────────────


class ExecPlanInput(AgentInputBase):
    """Input for the Execution Planning agent."""

    symbol: str = ""
    action: str = ""
    suggested_shares: int = 0
    price: float = 0.0
    risk_approved: bool = False
    risk_level: str = ""
    position_suggestion: dict = Field(default_factory=dict)


class ExecPlanOutput(AgentOutputBase):
    """Output from the Execution Planning agent."""

    gate_request_id: str = ""
    execution_plan: dict = Field(default_factory=dict)
    simulation_record: dict = Field(default_factory=dict)


# ── 10. Prediction Monitoring Agent ───────────────────────────


class MonitorInput(AgentInputBase):
    """Input for the Prediction Monitoring agent."""

    window_days: int = 30


class MonitorOutput(AgentOutputBase):
    """Output from the Prediction Monitoring agent."""

    accuracy_summary: dict = Field(default_factory=dict)
    drift_report: dict = Field(default_factory=dict)
    flagged_symbols: list[str] = Field(default_factory=list)


# ── 11. Report Agent ──────────────────────────────────────────


class ReportInput(AgentInputBase):
    """Input for the Report agent."""

    step_results: dict = Field(default_factory=dict)


class ReportOutput(AgentOutputBase):
    """Output from the Report agent."""

    report_markdown: str = ""
    executive_summary: str = ""
    scenarios: list[dict] = Field(default_factory=list)


# ── 12. Orchestrator (meta) ───────────────────────────────────


class OrchestratorInput(AgentInputBase):
    """Input for the Orchestrator meta-agent."""

    user_message: str = ""
    thread_context: dict = Field(default_factory=dict)


class OrchestratorOutput(AgentOutputBase):
    """Output from the Orchestrator meta-agent."""

    pipeline_name: str = ""
    steps_executed: int = 0
    total_tokens: int = 0
    report_markdown: str = ""
    executive_summary: str = ""
    scenarios: list[dict] = Field(default_factory=list)


# ── Schema version map (for auto-registration) ───────────────

AGENT_SCHEMAS: dict[str, tuple[type[AgentInputBase], type[AgentOutputBase], str]] = {
    "data_qa": (DataQAInput, DataQAOutput, "1.0.0"),
    "analyst": (AnalystInput, AnalystOutput, "1.0.0"),
    "backtest": (BacktestInput, BacktestOutput, "1.0.0"),
    "risk": (RiskInput, RiskOutput, "1.0.0"),
    "sentiment": (SentimentInput, SentimentOutput, "1.0.0"),
    "regime": (RegimeInput, RegimeOutput, "1.0.0"),
    "correlation": (CorrelationInput, CorrelationOutput, "1.0.0"),
    "portfolio": (PortfolioInput, PortfolioOutput, "1.0.0"),
    "exec_plan": (ExecPlanInput, ExecPlanOutput, "1.0.0"),
    "monitor": (MonitorInput, MonitorOutput, "1.0.0"),
    "report": (ReportInput, ReportOutput, "1.0.0"),
    "orchestrator": (OrchestratorInput, OrchestratorOutput, "1.0.0"),
}


def register_all_schemas(registry: object) -> None:
    """Convenience: register every agent schema in one call.

    Args:
        registry: A SchemaRegistry instance.
    """
    for agent_name, (inp, out, ver) in AGENT_SCHEMAS.items():
        registry.register(agent_name, ver, inp, out)

"""Strategy lab Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NLStrategyRequest(BaseModel):
    """Request for natural-language strategy creation."""

    description: str
    symbol: str | None = None


class NLStrategyResult(BaseModel):
    """Result of NL strategy creation."""

    status: str = "success"
    strategy_key: str = ""
    params: dict = Field(default_factory=dict)
    explanation: str = ""
    confidence: float = 0.0
    message: str | None = None


class AIOptimizationRequest(BaseModel):
    """Request for AI parameter optimization."""

    symbol: str
    strategy_key: str
    current_params: dict[str, float] = Field(default_factory=dict)
    current_metrics: dict[str, float] = Field(default_factory=dict)


class AIOptimizationResult(BaseModel):
    """Result of AI parameter optimization."""

    status: str = "success"
    suggested_params: dict = Field(default_factory=dict)
    reasoning: list[str] = Field(default_factory=list)
    param_explanations: dict = Field(default_factory=dict)
    message: str | None = None


class AIAttributionRequest(BaseModel):
    """Request for AI attribution analysis."""

    symbol: str
    strategy_name: str
    round_trips: list[dict] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)


class AIAttributionResult(BaseModel):
    """Result of AI attribution analysis."""

    status: str = "success"
    summary: str = ""
    key_findings: list[str] = Field(default_factory=list)
    win_factors: list[str] = Field(default_factory=list)
    loss_factors: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    risk_assessment: str = ""
    message: str | None = None


class LatestSignalItem(BaseModel):
    """Latest signal from a strategy for a symbol."""

    symbol: str = ""
    strategy_key: str = ""
    strategy_name: str = ""
    signal: str = "hold"
    signal_value: int = 0
    strength: float = 0.0
    reason: str = ""


class CheckSignalsRequest(BaseModel):
    """Request to check signals for paper trade positions."""

    positions: list[dict] = Field(default_factory=list)

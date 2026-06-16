"""Pydantic models for the unified AI agent analysis endpoint.

v8.0: Merges P01 comprehensive analysis + P03 trading advice into one
seven-dimension response schema.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DimensionAnalysis(BaseModel):
    """Single dimension result from the seven-dimension framework."""

    key: str = ""
    label: str = ""
    signal: str = "neutral"
    score: float = 0.5
    reasoning: str = ""


class ConfidenceResult(BaseModel):
    """Structured confidence with semantic label and basis."""

    score: float = 0.0
    label: str = ""
    basis: list[str] = Field(default_factory=list)


class DataReference(BaseModel):
    """Data point referenced by the AI analysis."""

    field: str = ""
    value: str = ""
    source: str = ""


class RiskWarning(BaseModel):
    """Structured risk warning with type and data reference."""

    type: str = ""
    description: str = ""
    data_reference: str = ""


class TargetPrice(BaseModel):
    """Target price range."""

    low: float = 0.0
    high: float = 0.0


class UnifiedAnalysisResult(BaseModel):
    """Response model for the unified seven-dimension AI analysis endpoint."""

    status: str = "ok"
    symbol: str = ""
    action: str = "watch"
    action_label: str = "建议观望"
    confidence: ConfidenceResult = Field(default_factory=ConfidenceResult)
    risk_level: str = "medium"
    summary: str = ""
    dimensions: list[DimensionAnalysis] = Field(default_factory=list)
    risk_warnings: list[RiskWarning] = Field(default_factory=list)
    target_price: TargetPrice | None = None
    stop_loss: float | None = None
    contrarian_check: str = ""
    data_references: list[DataReference] = Field(default_factory=list)
    disclaimer: str = ""
    model_used: str = ""
    generated_at: str = ""
    message: str | None = None
    # Backward compatibility fields
    trend: str = ""
    signal: str = ""
    confidence_number: float = 0.0
    reasoning: list[str] = Field(default_factory=list)
    quant_signals: dict = Field(default_factory=dict)
    ai_reasoning: list[str] = Field(default_factory=list)

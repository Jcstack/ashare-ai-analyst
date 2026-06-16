"""Prediction Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PredictionRequest(BaseModel):
    """Request body for prediction (currently no extra fields needed)."""

    pass


class PredictionResult(BaseModel):
    """Claude prediction analysis result."""

    status: str
    symbol: str | None = None
    trend: str | None = None
    signal: str | None = None
    confidence: float | None = None
    risk_level: str | None = None
    reasoning: str | None = None
    target_price_range: list[float] | None = None
    key_factors: list[str] | None = None
    risk_warnings: list[str] | None = None
    message: str | None = None


class QuickInsight(BaseModel):
    """Quick AI one-liner insight."""

    symbol: str
    signal: str = "neutral"
    confidence: float = 0.0
    summary: str = ""
    risk_badge: str = "medium"
    generated_at: str | None = None


class EnhancedPredictionRequest(BaseModel):
    """Request body for enhanced single-stock prediction."""

    sources: list[str] = Field(
        default=["indicators", "fund_flow"],
        description="Data sources: indicators, dragon_tiger, fund_flow, bayesian, risk, news",
    )
    include_bayesian: bool = False
    include_risk: bool = False


class ComparisonPredictionRequest(BaseModel):
    """Request body for multi-stock comparison prediction."""

    symbols: list[str] = Field(min_length=2, max_length=10)
    sources: list[str] = Field(default=["indicators", "fund_flow"])


class EnhancedPredictionResult(BaseModel):
    """Enhanced prediction result with richer data."""

    status: str = "success"
    symbol: str | None = None
    trend: str | None = None
    signal: str | None = None
    confidence: float | None = None
    risk_level: str | None = None
    reasoning: str | None = None
    target_price_range: list[float] | None = None
    key_factors: list[str] | None = None
    risk_warnings: list[str] | None = None
    data_sources: list[str] = Field(default_factory=list)
    message: str | None = None
    generated_at: str | None = None


class ComparisonPredictionResult(BaseModel):
    """Multi-stock comparison prediction result."""

    status: str = "success"
    analyses: list[EnhancedPredictionResult] = Field(default_factory=list)
    comparison_summary: str | None = None
    recommendation_order: list[str] = Field(default_factory=list)
    message: str | None = None
    generated_at: str | None = None

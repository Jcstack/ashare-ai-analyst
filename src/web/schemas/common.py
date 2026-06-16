"""Common/shared response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    """Generic API response wrapper."""

    status: str
    message: str | None = None
    data: dict | None = None


class MarketAIOverview(BaseModel):
    """Market-level AI overview/briefing."""

    status: str = "success"
    market_trend: str = "neutral"
    risk_assessment: str = "medium"
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    sector_outlook: dict | None = None
    generated_at: str | None = None

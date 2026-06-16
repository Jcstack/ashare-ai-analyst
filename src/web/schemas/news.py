"""News and sentiment Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StockNewsItem(BaseModel):
    """Stock news article."""

    title: str
    content: str = ""
    datetime: str = ""
    source: str = ""
    url: str = ""
    sentiment: str | None = None
    impact_level: str | None = None


class AnomalyItem(BaseModel):
    """Stock anomaly/unusual activity record."""

    datetime: str = ""
    symbol: str = ""
    name: str = ""
    change_type: str = ""
    description: str = ""
    sector: str | None = None


class SentimentSummary(BaseModel):
    """Aggregated news sentiment summary."""

    symbol: str
    overall: str = "neutral"
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    total_count: int = 0
    score: float = 0.0
    summary: str | None = None


class ResearchResult(BaseModel):
    """Aggregated research data for a stock."""

    symbol: str = ""
    news: list[StockNewsItem] = Field(default_factory=list)
    sentiment: SentimentSummary | None = None
    fund_holdings: list[dict] = Field(default_factory=list)
    analyst_ratings: list[dict] = Field(default_factory=list)

"""Pydantic models for concept board API responses.

Per PRD v3.3 FR-CS004.
"""

from __future__ import annotations

from pydantic import BaseModel


class ConceptLeader(BaseModel):
    """Leader stock within a concept board."""

    symbol: str = ""
    name: str = ""
    pct_change: float = 0.0


class ConceptHeatResponse(BaseModel):
    """A concept board with heat score for the hot-ranking endpoint."""

    code: str
    name: str
    pct_change: float = 0.0
    amount: float = 0.0
    up_count: int = 0
    down_count: int = 0
    heat_score: float = 0.0
    leader: ConceptLeader = ConceptLeader()


class ConceptHeatListResponse(BaseModel):
    """Response for GET /concept/hot."""

    items: list[ConceptHeatResponse] = []
    updated_at: str = ""


class ConceptConstituentItem(BaseModel):
    """A constituent stock within a concept board."""

    symbol: str
    name: str
    price: float | None = None
    pct_change: float | None = None
    amount: float | None = None
    amplitude: float | None = None


class ConceptHistoryRecord(BaseModel):
    """One day of concept board OHLCV history."""

    date: str
    open: float = 0.0
    close: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    pct_change: float = 0.0


class StockConceptItemResponse(BaseModel):
    """A concept associated with a stock."""

    code: str
    name: str
    pct_change: float = 0.0
    amount: float = 0.0
    up_count: int = 0
    down_count: int = 0
    stock_rank_pct: float | None = None
    zt_count: int = 0  # real limit-up count (cross-matched with limit pool)
    dt_count: int = 0  # real limit-down count (cross-matched with limit pool)


class ResonanceResponse(BaseModel):
    """Concept resonance detection result."""

    level: str = "none"
    concepts: list[str] = []
    top_driver: str | None = None
    rank_in_driver: str = ""


class StockConceptsResponse(BaseModel):
    """Response for GET /stock/{symbol}/concepts."""

    symbol: str
    industry: str = ""
    concepts: list[StockConceptItemResponse] = []
    resonance: ResonanceResponse = ResonanceResponse()

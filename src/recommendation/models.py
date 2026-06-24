"""Data models for the smart stock recommendation system.

StockCandidate represents a screened stock before LLM review.
Recommendation represents a finalized, reviewable pick.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StockCandidate:
    """A stock that passed multi-factor screening."""

    symbol: str
    name: str
    price: float
    change_pct: float
    volume: float
    turnover_rate: float
    pe_ratio: float | None
    pb_ratio: float | None
    market_cap: float | None
    sector: str
    score: float  # composite screening score
    factors: dict = field(default_factory=dict)  # {"value": 0.8, "momentum": 0.6, ...}


@dataclass
class Recommendation:
    """A finalized stock recommendation after LLM review."""

    id: str  # uuid
    symbol: str
    name: str
    action: str  # "buy"
    style: str  # investment style that triggered this
    session: str  # trading session (e.g. "early", "mid")
    score: float
    confidence: str  # "high" | "medium" | "low"
    reason: str  # LLM-generated Chinese explanation
    risk_notes: str
    entry_price: float | None  # suggested entry price
    target_price: float | None
    stop_loss: float | None
    factors: dict
    created_at: str  # ISO timestamp
    status: str = "active"  # "active" | "expired" | "dismissed"
    ai_analyzed: bool = False  # True when LLM review succeeded
    run_id: str | None = None  # pipeline run identifier
    sub_scores: dict | None = None  # per-dimension scores from LLM review

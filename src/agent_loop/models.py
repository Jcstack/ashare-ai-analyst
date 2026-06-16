from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class UrgencyTier(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    DEEP = "deep"


class SignalDirection(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    REDUCE = "reduce"
    ADD = "add"


@dataclass
class InvestmentThesis:
    symbol: str
    name: str
    direction: str  # "bullish" / "bearish" / "neutral"
    conviction: float
    thesis_text: str
    key_assumptions: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    entry_price_target: float | None = None
    stop_loss_pct: float | None = None
    sector: str = ""
    status: str = "active"  # "active" / "invalidated" / "expired"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    invalidated_at: datetime | None = None
    invalidation_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "name": self.name,
            "direction": self.direction,
            "conviction": self.conviction,
            "thesis_text": self.thesis_text,
            "key_assumptions": self.key_assumptions,
            "invalidation_conditions": self.invalidation_conditions,
            "entry_price_target": self.entry_price_target,
            "stop_loss_pct": self.stop_loss_pct,
            "sector": self.sector,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "invalidated_at": self.invalidated_at.isoformat()
            if self.invalidated_at
            else None,
            "invalidation_reason": self.invalidation_reason,
        }


@dataclass
class AggregatedSignal:
    symbol: str
    name: str
    direction: SignalDirection
    source: str
    confidence: float
    urgency: UrgencyTier
    reason: str
    priority_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "name": self.name,
            "direction": self.direction.value,
            "source": self.source,
            "confidence": self.confidence,
            "urgency": self.urgency.value,
            "priority_score": self.priority_score,
            "reason": self.reason,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class TradeProposal:
    symbol: str
    name: str
    action: str  # "buy" / "sell" / "add" / "reduce" / "hold"
    shares: int
    confidence: float
    debate_summary: str
    bull_score: float
    bear_score: float
    price_target: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_reward_ratio: float | None = None
    thesis: InvestmentThesis | None = None
    risk_notes: list[str] = field(default_factory=list)
    portfolio_impact: dict[str, Any] = field(default_factory=dict)
    overnight_risk_pct: float | None = None
    reasoning_chain: list[str] = field(default_factory=list)
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "symbol": self.symbol,
            "name": self.name,
            "action": self.action,
            "shares": self.shares,
            "price_target": self.price_target,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "confidence": self.confidence,
            "risk_reward_ratio": self.risk_reward_ratio,
            "thesis": self.thesis.to_dict() if self.thesis else None,
            "debate_summary": self.debate_summary,
            "bull_score": self.bull_score,
            "bear_score": self.bear_score,
            "risk_notes": self.risk_notes,
            "portfolio_impact": self.portfolio_impact,
            "overnight_risk_pct": self.overnight_risk_pct,
            "reasoning_chain": self.reasoning_chain,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CycleState:
    positions: list[dict[str, Any]]
    available_cash: float
    regime: str
    pending_signals: list[AggregatedSignal] = field(default_factory=list)
    active_theses: list[InvestmentThesis] = field(default_factory=list)
    daily_pnl_pct: float = 0.0
    consecutive_losses: int = 0
    cycle_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class CycleResult:
    cycle_id: str
    duration_seconds: float
    signals_processed: int
    proposals_generated: list[TradeProposal] = field(default_factory=list)
    theses_updated: int = 0
    theses_invalidated: int = 0
    outcomes_checked: int = 0
    errors: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "timestamp": self.timestamp.isoformat(),
            "duration_seconds": self.duration_seconds,
            "signals_processed": self.signals_processed,
            "proposals_generated": [p.to_dict() for p in self.proposals_generated],
            "theses_updated": self.theses_updated,
            "theses_invalidated": self.theses_invalidated,
            "outcomes_checked": self.outcomes_checked,
            "errors": self.errors,
        }


@dataclass
class DecisionOutcome:
    proposal_id: str
    symbol: str
    action: str
    decided_at: datetime
    decided_price: float
    t1_price: float | None = None
    t3_price: float | None = None
    t5_price: float | None = None
    t1_return_pct: float | None = None
    t3_return_pct: float | None = None
    t5_return_pct: float | None = None
    direction_correct: bool | None = None
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "symbol": self.symbol,
            "action": self.action,
            "decided_at": self.decided_at.isoformat(),
            "decided_price": self.decided_price,
            "t1_price": self.t1_price,
            "t3_price": self.t3_price,
            "t5_price": self.t5_price,
            "t1_return_pct": self.t1_return_pct,
            "t3_return_pct": self.t3_return_pct,
            "t5_return_pct": self.t5_return_pct,
            "direction_correct": self.direction_correct,
        }

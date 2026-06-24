from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


@dataclass
class ContingencyRule:
    """Execution contingency rule attached to a TradeProposal.

    Tells the execution trader what to do if specific conditions occur
    after the trade is placed.
    """

    condition: str  # e.g. "价格跌破 XX 元" or "涨幅超过 5%"
    action: str  # e.g. "减仓50%" or "全部卖出" or "追加买入"
    priority: str  # "critical" | "important" | "optional"
    expiry_session: str  # "morning" | "afternoon" | "next_day"


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
    source_count: int = 1  # number of independent source domains contributing
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
            "source_count": self.source_count,
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
    contingencies: list[ContingencyRule] = field(default_factory=list)
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
            "contingencies": [
                {
                    "condition": c.condition,
                    "action": c.action,
                    "priority": c.priority,
                    "expiry_session": c.expiry_session,
                }
                for c in self.contingencies
            ],
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
class PortfolioContext:
    """Full portfolio context for signal evaluation.

    Combines position data, risk budget, regime information, and
    belief-state-derived limits into a single context object.
    """

    positions: list[dict[str, Any]] = field(default_factory=list)
    total_value: float = 0.0
    cash: float = 0.0
    cash_pct: float = 0.0
    sector_weights: dict[str, float] = field(default_factory=dict)
    theme_weights: dict[str, float] = field(default_factory=dict)
    active_theses: list[dict[str, Any]] = field(default_factory=list)
    weakest_thesis: dict[str, Any] | None = None
    risk_budget_remaining: float = 0.03
    sentiment_phase: str = "unknown"
    max_position_pct: float = 0.20
    max_equity_pct: float = 0.50
    buys_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_value": self.total_value,
            "cash": self.cash,
            "cash_pct": self.cash_pct,
            "position_count": len(self.positions),
            "sector_weights": self.sector_weights,
            "theme_weights": self.theme_weights,
            "active_theses_count": len(self.active_theses),
            "weakest_thesis": self.weakest_thesis,
            "risk_budget_remaining": self.risk_budget_remaining,
            "sentiment_phase": self.sentiment_phase,
            "max_position_pct": self.max_position_pct,
            "max_equity_pct": self.max_equity_pct,
            "buys_allowed": self.buys_allowed,
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

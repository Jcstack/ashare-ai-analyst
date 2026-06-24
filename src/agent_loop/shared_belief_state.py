"""Shared Belief State — central state shared by all agent teams.

Provides regime tracking, risk budget management, cash strategy,
daily planning, and position limits. Backed by Redis for cross-process
access when available.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RegimeState:
    """Current market regime."""

    hmm_state: str = "unknown"  # bull/bear/consolidation
    hmm_probability: float = 0.5
    switch_probability: float = 0.0
    sentiment_phase: str = "unknown"  # freezing/ignition/acceleration/climax/ebb
    sentiment_phase_cn: str = "未知"
    reflexivity_state: str = "unknown"  # strengthening/exhausting/breaking
    updated_at: datetime | None = None


@dataclass
class RiskBudget:
    """Daily risk budget tracking."""

    daily_limit_pct: float = 0.03  # 3% max daily loss
    realized_losses_today: float = 0.0
    remaining_pct: float = 0.03
    consecutive_losses: int = 0
    is_halted: bool = False  # True if budget exhausted or circuit breaker


@dataclass
class CashStrategy:
    """Regime-dependent cash allocation targets."""

    target_cash_pct: float = 0.50
    current_cash_pct: float = 0.0
    regime_targets: dict[str, float] = field(
        default_factory=lambda: {
            "freezing": 0.85,
            "ignition": 0.55,
            "acceleration": 0.25,
            "climax": 0.45,
            "ebb": 0.85,
        }
    )


@dataclass
class DailyPlan:
    """Today's trading plan from morning review."""

    date: str = ""
    watch_list: list[str] = field(default_factory=list)
    buy_candidates: list[dict[str, Any]] = field(default_factory=list)
    sell_plan: list[dict[str, Any]] = field(default_factory=list)
    key_events: list[str] = field(default_factory=list)
    notes: str = ""


# Sentiment phase -> position limits mapping
_PHASE_POSITION_LIMITS: dict[str, dict[str, Any]] = {
    "freezing": {
        "max_position_pct": 0.10,
        "max_equity_pct": 0.20,
        "buys_allowed": True,
    },
    "ignition": {
        "max_position_pct": 0.20,
        "max_equity_pct": 0.50,
        "buys_allowed": True,
    },
    "acceleration": {
        "max_position_pct": 0.25,
        "max_equity_pct": 0.80,
        "buys_allowed": True,
    },
    "climax": {"max_position_pct": 0.15, "max_equity_pct": 0.60, "buys_allowed": True},
    "ebb": {"max_position_pct": 0.05, "max_equity_pct": 0.10, "buys_allowed": False},
}

_DEFAULT_POSITION_LIMITS: dict[str, Any] = {
    "max_position_pct": 0.20,
    "max_equity_pct": 0.50,
    "buys_allowed": True,
}

_REDIS_HASH_KEY = "belief_state"


class SharedBeliefState:
    """Central state shared by all agent teams.

    Backed by Redis for cross-process access. Falls back to in-memory
    when Redis is unavailable.
    """

    def __init__(self, redis_client: Any = None) -> None:
        self._redis = redis_client
        self.regime = RegimeState()
        self.risk_budget = RiskBudget()
        self.cash_strategy = CashStrategy()
        self.daily_plan = DailyPlan()
        self._signal_accuracy: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Regime
    # ------------------------------------------------------------------

    def update_regime(self, **kwargs: Any) -> None:
        """Update regime state and persist to Redis."""
        for k, v in kwargs.items():
            if hasattr(self.regime, k):
                setattr(self.regime, k, v)
        self.regime.updated_at = datetime.now()
        self._persist("regime")
        logger.info(
            "Belief: regime updated — hmm=%s phase=%s reflexivity=%s",
            self.regime.hmm_state,
            self.regime.sentiment_phase,
            self.regime.reflexivity_state,
        )

    # ------------------------------------------------------------------
    # Risk budget
    # ------------------------------------------------------------------

    def update_risk_budget(self, realized_loss: float = 0.0) -> None:
        """Update risk budget after a loss."""
        self.risk_budget.realized_losses_today += abs(realized_loss)
        self.risk_budget.remaining_pct = max(
            0.0,
            self.risk_budget.daily_limit_pct - self.risk_budget.realized_losses_today,
        )
        if self.risk_budget.remaining_pct <= 0:
            self.risk_budget.is_halted = True
            logger.warning("Belief: risk budget EXHAUSTED — trading halted")
        self._persist("risk_budget")

    def record_consecutive_loss(self) -> None:
        """Increment consecutive loss counter."""
        self.risk_budget.consecutive_losses += 1
        self._persist("risk_budget")

    def reset_consecutive_losses(self) -> None:
        """Reset consecutive loss counter after a win."""
        self.risk_budget.consecutive_losses = 0
        self._persist("risk_budget")

    # ------------------------------------------------------------------
    # Cash strategy
    # ------------------------------------------------------------------

    def update_cash_strategy(self, current_cash_pct: float | None = None) -> None:
        """Recalculate target cash based on current sentiment phase."""
        phase = self.regime.sentiment_phase
        self.cash_strategy.target_cash_pct = self.cash_strategy.regime_targets.get(
            phase, 0.50
        )
        if current_cash_pct is not None:
            self.cash_strategy.current_cash_pct = current_cash_pct
        self._persist("cash_strategy")

    # ------------------------------------------------------------------
    # Position limits
    # ------------------------------------------------------------------

    def get_position_limits(self) -> dict[str, Any]:
        """Get regime-dependent position limits."""
        return _PHASE_POSITION_LIMITS.get(
            self.regime.sentiment_phase, _DEFAULT_POSITION_LIMITS
        )

    # ------------------------------------------------------------------
    # Daily plan
    # ------------------------------------------------------------------

    def set_daily_plan(self, plan: DailyPlan) -> None:
        """Set today's daily plan."""
        self.daily_plan = plan
        self._persist("daily_plan")

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    def reset_daily(self) -> None:
        """Reset daily counters (call at market open)."""
        self.risk_budget.realized_losses_today = 0.0
        self.risk_budget.remaining_pct = self.risk_budget.daily_limit_pct
        self.risk_budget.is_halted = False
        self.daily_plan = DailyPlan(date=datetime.now().strftime("%Y-%m-%d"))
        self._persist("risk_budget")
        logger.info("Belief: daily reset complete")

    # ------------------------------------------------------------------
    # Signal accuracy tracking
    # ------------------------------------------------------------------

    def update_signal_accuracy(self, source: str, accuracy: float) -> None:
        """Track signal source accuracy for weighting."""
        self._signal_accuracy[source] = accuracy
        self._persist("signal_accuracy")

    def get_signal_accuracy(self, source: str) -> float:
        """Get tracked accuracy for a signal source."""
        return self._signal_accuracy.get(source, 0.5)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize full belief state for logging / messaging."""
        return {
            "regime": {
                "hmm_state": self.regime.hmm_state,
                "hmm_probability": self.regime.hmm_probability,
                "sentiment_phase": self.regime.sentiment_phase,
                "sentiment_phase_cn": self.regime.sentiment_phase_cn,
                "reflexivity_state": self.regime.reflexivity_state,
                "updated_at": str(self.regime.updated_at)
                if self.regime.updated_at
                else None,
            },
            "risk_budget": {
                "daily_limit_pct": self.risk_budget.daily_limit_pct,
                "realized_losses_today": self.risk_budget.realized_losses_today,
                "remaining_pct": self.risk_budget.remaining_pct,
                "consecutive_losses": self.risk_budget.consecutive_losses,
                "is_halted": self.risk_budget.is_halted,
            },
            "cash_strategy": {
                "target_cash_pct": self.cash_strategy.target_cash_pct,
                "current_cash_pct": self.cash_strategy.current_cash_pct,
            },
            "daily_plan": {
                "date": self.daily_plan.date,
                "watch_list": self.daily_plan.watch_list,
                "buy_candidates_count": len(self.daily_plan.buy_candidates),
                "sell_plan_count": len(self.daily_plan.sell_plan),
            },
            "signal_accuracy": self._signal_accuracy,
        }

    # ------------------------------------------------------------------
    # Redis persistence
    # ------------------------------------------------------------------

    def _persist(self, key: str) -> None:
        """Persist state to Redis hash."""
        if not self._redis:
            return
        try:
            data = getattr(self, key, None)
            if data is None:
                return
            if key == "signal_accuracy":
                serialized = data
            elif hasattr(data, "__dict__"):
                serialized = data.__dict__
            else:
                serialized = data
            self._redis.hset(_REDIS_HASH_KEY, key, json.dumps(serialized, default=str))
        except Exception as exc:
            logger.debug("Failed to persist belief_state.%s to Redis: %s", key, exc)

    def load_from_redis(self) -> None:
        """Load state from Redis on startup."""
        if not self._redis:
            return
        for key in ["regime", "risk_budget", "cash_strategy"]:
            try:
                raw = self._redis.hget(_REDIS_HASH_KEY, key)
                if raw:
                    data = json.loads(raw)
                    obj = getattr(self, key)
                    for k, v in data.items():
                        if hasattr(obj, k) and k != "updated_at":
                            setattr(obj, k, v)
            except Exception as exc:
                logger.debug("Failed to load belief_state.%s from Redis: %s", key, exc)

        # Load signal accuracy
        try:
            raw = self._redis.hget(_REDIS_HASH_KEY, "signal_accuracy")
            if raw:
                self._signal_accuracy = json.loads(raw)
        except Exception:
            pass

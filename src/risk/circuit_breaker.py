"""Portfolio circuit breaker mechanism.

Part of v17.0 Institutional Risk Engine.

Monitors portfolio P&L and triggers halts when thresholds are breached:
- Daily loss >= 15%: Trading halt for 1 day
- Weekly loss >= 25%: Trading pause for 3 days
- Consecutive halts escalation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class BreakerState(str, Enum):
    """Current state of the circuit breaker."""

    NORMAL = "normal"
    DAILY_HALT = "daily_halt"
    WEEKLY_PAUSE = "weekly_pause"
    ESCALATED = "escalated"


@dataclass
class BreakerStatus:
    """Current circuit breaker status."""

    state: BreakerState
    triggered_at: date | None = None
    resume_at: date | None = None
    trigger_reason: str = ""
    daily_pnl_pct: float = 0.0
    weekly_pnl_pct: float = 0.0
    consecutive_halts: int = 0
    can_trade: bool = True
    warnings: list[str] = field(default_factory=list)


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    daily_loss_threshold: float = -0.15
    weekly_loss_threshold: float = -0.25
    daily_cooldown_days: int = 1
    weekly_cooldown_days: int = 3
    max_consecutive_halts: int = 3


class CircuitBreaker:
    """Monitors portfolio losses and triggers trading halts."""

    def __init__(self, config: CircuitBreakerConfig | None = None):
        self.config = config or CircuitBreakerConfig()
        self._state = BreakerState.NORMAL
        self._triggered_at: date | None = None
        self._resume_at: date | None = None
        self._consecutive_halts = 0

    @property
    def state(self) -> BreakerState:
        return self._state

    def check(
        self,
        daily_pnl_pct: float,
        weekly_pnl_pct: float,
        current_date: date | None = None,
    ) -> BreakerStatus:
        """Check portfolio P&L against circuit breaker thresholds.

        Args:
            daily_pnl_pct: Today's portfolio return (e.g., -0.08 = -8%).
            weekly_pnl_pct: This week's cumulative return.
            current_date: Current date (defaults to today).
        """
        today = current_date or date.today()
        warnings: list[str] = []

        # If currently in a halt/pause state, check if cooldown expired
        if self._state != BreakerState.NORMAL:
            if self._resume_at and today >= self._resume_at:
                logger.info("Circuit breaker cooldown expired, resuming normal trading")
                self._state = BreakerState.NORMAL
                self._triggered_at = None
                self._resume_at = None
            else:
                # Still in cooldown
                return BreakerStatus(
                    state=self._state,
                    triggered_at=self._triggered_at,
                    resume_at=self._resume_at,
                    trigger_reason=self._get_trigger_reason(),
                    daily_pnl_pct=daily_pnl_pct,
                    weekly_pnl_pct=weekly_pnl_pct,
                    consecutive_halts=self._consecutive_halts,
                    can_trade=False,
                    warnings=[f"交易暂停中，预计 {self._resume_at} 恢复"],
                )

        # Check weekly threshold first (more severe)
        if weekly_pnl_pct <= self.config.weekly_loss_threshold:
            self._state = BreakerState.WEEKLY_PAUSE
            self._triggered_at = today
            self._resume_at = today + timedelta(days=self.config.weekly_cooldown_days)
            self._consecutive_halts += 1
            warnings.append(
                f"周亏损 {weekly_pnl_pct:.1%} 触发周熔断"
                f"（阈值 {self.config.weekly_loss_threshold:.1%}）"
            )

        # Check daily threshold
        elif daily_pnl_pct <= self.config.daily_loss_threshold:
            self._state = BreakerState.DAILY_HALT
            self._triggered_at = today
            self._resume_at = today + timedelta(days=self.config.daily_cooldown_days)
            self._consecutive_halts += 1
            warnings.append(
                f"日亏损 {daily_pnl_pct:.1%} 触发日熔断"
                f"（阈值 {self.config.daily_loss_threshold:.1%}）"
            )

        else:
            # Normal — reset consecutive counter
            self._consecutive_halts = 0

        # Check consecutive halts escalation
        if self._consecutive_halts >= self.config.max_consecutive_halts:
            self._state = BreakerState.ESCALATED
            self._resume_at = today + timedelta(
                days=self.config.weekly_cooldown_days * 2
            )
            warnings.append(f"连续 {self._consecutive_halts} 次熔断，触发升级暂停")

        can_trade = self._state == BreakerState.NORMAL

        # Near-threshold warnings
        if can_trade:
            if daily_pnl_pct <= self.config.daily_loss_threshold * 0.7:
                warnings.append(
                    f"日亏损 {daily_pnl_pct:.1%} 接近熔断阈值"
                    f"（{self.config.daily_loss_threshold:.1%}）"
                )
            if weekly_pnl_pct <= self.config.weekly_loss_threshold * 0.7:
                warnings.append(
                    f"周亏损 {weekly_pnl_pct:.1%} 接近熔断阈值"
                    f"（{self.config.weekly_loss_threshold:.1%}）"
                )

        # Persist state change to Redis
        if self._state != BreakerState.NORMAL or self._consecutive_halts == 0:
            self.save_to_redis()

        return BreakerStatus(
            state=self._state,
            triggered_at=self._triggered_at,
            resume_at=self._resume_at,
            trigger_reason=self._get_trigger_reason(),
            daily_pnl_pct=daily_pnl_pct,
            weekly_pnl_pct=weekly_pnl_pct,
            consecutive_halts=self._consecutive_halts,
            can_trade=can_trade,
            warnings=warnings,
        )

    def is_halted(self) -> bool:
        """Quick check: is trading currently halted?

        Loads persisted state from Redis if available, then checks
        if cooldown has expired.
        """
        self.load_from_redis()
        today = date.today()
        if self._state != BreakerState.NORMAL:
            if self._resume_at and today >= self._resume_at:
                self._state = BreakerState.NORMAL
                self._triggered_at = None
                self._resume_at = None
                self.save_to_redis()
                return False
            return True
        return False

    def save_to_redis(self) -> None:
        """Persist circuit breaker state to Redis (24h TTL)."""
        try:
            import json

            from src.web.dependencies import get_redis

            r = get_redis()
            if r is None:
                return
            data = {
                "state": self._state.value,
                "triggered_at": self._triggered_at.isoformat()
                if self._triggered_at
                else None,
                "resume_at": self._resume_at.isoformat() if self._resume_at else None,
                "consecutive_halts": self._consecutive_halts,
            }
            r.setex(
                "risk:circuit_breaker",
                86400,  # 24h TTL
                json.dumps(data),
            )
        except Exception:
            logger.debug("Failed to save circuit breaker to Redis", exc_info=True)

    def load_from_redis(self) -> None:
        """Load circuit breaker state from Redis if available."""
        try:
            import json

            from src.web.dependencies import get_redis

            r = get_redis()
            if r is None:
                return
            raw = r.get("risk:circuit_breaker")
            if not raw:
                return
            data = json.loads(raw)
            self._state = BreakerState(data.get("state", "normal"))
            triggered = data.get("triggered_at")
            self._triggered_at = date.fromisoformat(triggered) if triggered else None
            resume = data.get("resume_at")
            self._resume_at = date.fromisoformat(resume) if resume else None
            self._consecutive_halts = data.get("consecutive_halts", 0)
        except Exception:
            logger.debug("Failed to load circuit breaker from Redis", exc_info=True)

    def reset(self) -> None:
        """Manually reset the circuit breaker to normal state."""
        self._state = BreakerState.NORMAL
        self._triggered_at = None
        self._resume_at = None
        self._consecutive_halts = 0
        self.save_to_redis()

    def _get_trigger_reason(self) -> str:
        if self._state == BreakerState.DAILY_HALT:
            return "日亏损触发熔断"
        if self._state == BreakerState.WEEKLY_PAUSE:
            return "周亏损触发暂停"
        if self._state == BreakerState.ESCALATED:
            return "连续熔断升级"
        return ""

"""Tests for circuit breaker mechanism.

Part of v17.0 Risk Engine.
"""

from __future__ import annotations

from datetime import date

from src.risk.circuit_breaker import (
    BreakerState,
    CircuitBreaker,
    CircuitBreakerConfig,
)


class TestNormalOperation:
    def test_normal_when_no_loss(self):
        cb = CircuitBreaker()
        status = cb.check(0.02, 0.05)
        assert status.state == BreakerState.NORMAL
        assert status.can_trade is True
        assert len(status.warnings) == 0

    def test_normal_moderate_loss(self):
        cb = CircuitBreaker()
        status = cb.check(-0.05, -0.08)
        assert status.state == BreakerState.NORMAL
        assert status.can_trade is True


class TestDailyHalt:
    def test_triggers_on_threshold(self):
        cb = CircuitBreaker()
        status = cb.check(-0.15, -0.10, current_date=date(2026, 2, 15))
        assert status.state == BreakerState.DAILY_HALT
        assert status.can_trade is False
        assert status.triggered_at == date(2026, 2, 15)
        assert status.resume_at == date(2026, 2, 16)

    def test_triggers_beyond_threshold(self):
        cb = CircuitBreaker()
        status = cb.check(-0.20, -0.10)
        assert status.state == BreakerState.DAILY_HALT
        assert status.can_trade is False

    def test_warning_includes_threshold(self):
        cb = CircuitBreaker()
        status = cb.check(-0.16, -0.10)
        assert any("日亏损" in w for w in status.warnings)

    def test_cooldown_expires(self):
        cb = CircuitBreaker()
        # Day 1: trigger halt
        cb.check(-0.16, -0.10, current_date=date(2026, 2, 15))
        assert cb.state == BreakerState.DAILY_HALT

        # Day 2: cooldown expired, should resume
        status = cb.check(0.01, -0.05, current_date=date(2026, 2, 16))
        assert status.state == BreakerState.NORMAL
        assert status.can_trade is True


class TestWeeklyPause:
    def test_triggers_on_weekly_threshold(self):
        cb = CircuitBreaker()
        status = cb.check(-0.05, -0.25, current_date=date(2026, 2, 15))
        assert status.state == BreakerState.WEEKLY_PAUSE
        assert status.can_trade is False
        assert status.resume_at == date(2026, 2, 18)  # 3 days cooldown

    def test_weekly_overrides_daily(self):
        """If both thresholds breached, weekly takes priority."""
        cb = CircuitBreaker()
        status = cb.check(-0.20, -0.30)
        assert status.state == BreakerState.WEEKLY_PAUSE  # Not DAILY_HALT

    def test_cooldown_not_expired(self):
        cb = CircuitBreaker()
        cb.check(-0.05, -0.25, current_date=date(2026, 2, 15))
        # Day 2: still in cooldown (3-day pause)
        status = cb.check(0.01, -0.10, current_date=date(2026, 2, 16))
        assert status.can_trade is False
        assert "交易暂停中" in status.warnings[0]


class TestConsecutiveHalts:
    def test_consecutive_tracking(self):
        cb = CircuitBreaker()
        # Trigger daily halt
        cb.check(-0.16, -0.10, current_date=date(2026, 2, 10))
        assert cb._consecutive_halts == 1

        # Cooldown expires, trigger again
        cb.check(-0.16, -0.10, current_date=date(2026, 2, 11))
        assert cb._consecutive_halts == 2

    def test_escalation_on_max_consecutive(self):
        config = CircuitBreakerConfig(max_consecutive_halts=2)
        cb = CircuitBreaker(config)

        cb.check(-0.16, -0.10, current_date=date(2026, 2, 10))
        cb.check(-0.16, -0.10, current_date=date(2026, 2, 11))

        # Should be escalated
        assert cb.state == BreakerState.ESCALATED

    def test_normal_resets_counter(self):
        cb = CircuitBreaker()
        cb.check(-0.16, -0.10, current_date=date(2026, 2, 10))
        assert cb._consecutive_halts == 1

        # Normal day after cooldown
        cb.check(0.02, 0.03, current_date=date(2026, 2, 11))
        assert cb._consecutive_halts == 0


class TestNearThresholdWarnings:
    def test_daily_near_threshold(self):
        cb = CircuitBreaker()
        # -15% * 0.7 = -10.5%, so -11% should trigger warning
        status = cb.check(-0.11, 0.0)
        assert status.can_trade is True
        assert any("接近熔断" in w for w in status.warnings)

    def test_weekly_near_threshold(self):
        cb = CircuitBreaker()
        # -25% * 0.7 = -17.5%, so -18% should trigger warning
        status = cb.check(0.0, -0.18)
        assert status.can_trade is True
        assert any("接近熔断" in w for w in status.warnings)


class TestReset:
    def test_manual_reset(self):
        cb = CircuitBreaker()
        cb.check(-0.20, -0.10)
        assert cb.state == BreakerState.DAILY_HALT

        cb.reset()
        assert cb.state == BreakerState.NORMAL
        assert cb._consecutive_halts == 0


class TestCustomConfig:
    def test_custom_thresholds(self):
        config = CircuitBreakerConfig(
            daily_loss_threshold=-0.10,
            weekly_loss_threshold=-0.20,
        )
        cb = CircuitBreaker(config)

        # -12% daily → triggers with custom -10% threshold
        status = cb.check(-0.12, -0.05)
        assert status.state == BreakerState.DAILY_HALT

    def test_custom_cooldown(self):
        config = CircuitBreakerConfig(daily_cooldown_days=2)
        cb = CircuitBreaker(config)
        cb.check(-0.16, -0.10, current_date=date(2026, 2, 15))
        assert cb._resume_at == date(2026, 2, 17)  # 2-day cooldown

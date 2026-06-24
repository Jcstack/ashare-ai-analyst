"""Tests for SharedBeliefState — central state management for agent teams."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.agent_loop.shared_belief_state import (
    DailyPlan,
    SharedBeliefState,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def belief() -> SharedBeliefState:
    """SharedBeliefState without Redis."""
    return SharedBeliefState()


@pytest.fixture
def belief_with_redis() -> SharedBeliefState:
    """SharedBeliefState with mocked Redis."""
    mock_redis = MagicMock()
    mock_redis.hget.return_value = None
    return SharedBeliefState(redis_client=mock_redis)


# ------------------------------------------------------------------
# RegimeState tests
# ------------------------------------------------------------------


class TestRegimeUpdate:
    def test_update_regime_sets_fields(self, belief: SharedBeliefState):
        belief.update_regime(
            hmm_state="bull",
            hmm_probability=0.8,
            sentiment_phase="acceleration",
            sentiment_phase_cn="加速",
        )

        assert belief.regime.hmm_state == "bull"
        assert belief.regime.hmm_probability == 0.8
        assert belief.regime.sentiment_phase == "acceleration"
        assert belief.regime.sentiment_phase_cn == "加速"
        assert belief.regime.updated_at is not None

    def test_update_regime_ignores_unknown_fields(self, belief: SharedBeliefState):
        belief.update_regime(hmm_state="bear", nonexistent_field="ignored")
        assert belief.regime.hmm_state == "bear"
        assert not hasattr(belief.regime, "nonexistent_field")

    def test_update_regime_persists_to_redis(
        self, belief_with_redis: SharedBeliefState
    ):
        belief_with_redis.update_regime(hmm_state="consolidation")
        belief_with_redis._redis.hset.assert_called()
        call_args = belief_with_redis._redis.hset.call_args
        assert call_args[0][0] == "belief_state"
        assert call_args[0][1] == "regime"

    def test_default_regime_is_unknown(self, belief: SharedBeliefState):
        assert belief.regime.hmm_state == "unknown"
        assert belief.regime.sentiment_phase == "unknown"
        assert belief.regime.reflexivity_state == "unknown"


# ------------------------------------------------------------------
# RiskBudget tests
# ------------------------------------------------------------------


class TestRiskBudget:
    def test_update_risk_budget_tracks_losses(self, belief: SharedBeliefState):
        belief.update_risk_budget(realized_loss=0.01)
        assert belief.risk_budget.realized_losses_today == pytest.approx(0.01)
        assert belief.risk_budget.remaining_pct == pytest.approx(0.02)
        assert not belief.risk_budget.is_halted

    def test_risk_budget_halts_when_exhausted(self, belief: SharedBeliefState):
        belief.update_risk_budget(realized_loss=0.03)
        assert belief.risk_budget.remaining_pct == pytest.approx(0.0)
        assert belief.risk_budget.is_halted

    def test_cumulative_losses(self, belief: SharedBeliefState):
        belief.update_risk_budget(realized_loss=0.01)
        belief.update_risk_budget(realized_loss=0.01)
        assert belief.risk_budget.realized_losses_today == pytest.approx(0.02)
        assert belief.risk_budget.remaining_pct == pytest.approx(0.01)
        assert not belief.risk_budget.is_halted

    def test_overshoot_clamps_to_zero(self, belief: SharedBeliefState):
        belief.update_risk_budget(realized_loss=0.05)
        assert belief.risk_budget.remaining_pct == 0.0
        assert belief.risk_budget.is_halted

    def test_consecutive_loss_tracking(self, belief: SharedBeliefState):
        belief.record_consecutive_loss()
        belief.record_consecutive_loss()
        assert belief.risk_budget.consecutive_losses == 2

        belief.reset_consecutive_losses()
        assert belief.risk_budget.consecutive_losses == 0

    def test_negative_loss_treated_as_absolute(self, belief: SharedBeliefState):
        belief.update_risk_budget(realized_loss=-0.01)
        assert belief.risk_budget.realized_losses_today == pytest.approx(0.01)


# ------------------------------------------------------------------
# Position limits per sentiment phase
# ------------------------------------------------------------------


class TestPositionLimits:
    @pytest.mark.parametrize(
        "phase,expected_max_pos,expected_max_equity,buys_allowed",
        [
            ("freezing", 0.10, 0.20, True),
            ("ignition", 0.20, 0.50, True),
            ("acceleration", 0.25, 0.80, True),
            ("climax", 0.15, 0.60, True),
            ("ebb", 0.05, 0.10, False),
        ],
    )
    def test_limits_by_phase(
        self, belief, phase, expected_max_pos, expected_max_equity, buys_allowed
    ):
        belief.update_regime(sentiment_phase=phase)
        limits = belief.get_position_limits()

        assert limits["max_position_pct"] == pytest.approx(expected_max_pos)
        assert limits["max_equity_pct"] == pytest.approx(expected_max_equity)
        assert limits["buys_allowed"] is buys_allowed

    def test_unknown_phase_returns_defaults(self, belief: SharedBeliefState):
        belief.update_regime(sentiment_phase="unknown")
        limits = belief.get_position_limits()
        assert limits["max_position_pct"] == pytest.approx(0.20)
        assert limits["buys_allowed"] is True


# ------------------------------------------------------------------
# CashStrategy tests
# ------------------------------------------------------------------


class TestCashStrategy:
    def test_target_updates_with_phase(self, belief: SharedBeliefState):
        belief.update_regime(sentiment_phase="freezing")
        belief.update_cash_strategy()
        assert belief.cash_strategy.target_cash_pct == pytest.approx(0.85)

    def test_acceleration_low_cash_target(self, belief: SharedBeliefState):
        belief.update_regime(sentiment_phase="acceleration")
        belief.update_cash_strategy()
        assert belief.cash_strategy.target_cash_pct == pytest.approx(0.25)

    def test_unknown_phase_defaults_to_50pct(self, belief: SharedBeliefState):
        belief.update_regime(sentiment_phase="nonexistent")
        belief.update_cash_strategy()
        assert belief.cash_strategy.target_cash_pct == pytest.approx(0.50)

    def test_current_cash_pct_updated(self, belief: SharedBeliefState):
        belief.update_cash_strategy(current_cash_pct=0.35)
        assert belief.cash_strategy.current_cash_pct == pytest.approx(0.35)


# ------------------------------------------------------------------
# Daily reset tests
# ------------------------------------------------------------------


class TestDailyReset:
    def test_reset_clears_losses(self, belief: SharedBeliefState):
        belief.update_risk_budget(realized_loss=0.02)
        assert belief.risk_budget.is_halted is False

        belief.update_risk_budget(realized_loss=0.02)
        assert belief.risk_budget.is_halted is True

        belief.reset_daily()
        assert belief.risk_budget.realized_losses_today == 0.0
        assert belief.risk_budget.remaining_pct == pytest.approx(0.03)
        assert belief.risk_budget.is_halted is False

    def test_reset_creates_new_daily_plan(self, belief: SharedBeliefState):
        belief.daily_plan.watch_list = ["000001", "000002"]
        belief.reset_daily()
        assert belief.daily_plan.watch_list == []
        assert belief.daily_plan.date != ""


# ------------------------------------------------------------------
# Signal accuracy tracking
# ------------------------------------------------------------------


class TestSignalAccuracy:
    def test_update_and_get(self, belief: SharedBeliefState):
        belief.update_signal_accuracy("technical", 0.72)
        assert belief.get_signal_accuracy("technical") == pytest.approx(0.72)

    def test_unknown_source_defaults_to_half(self, belief: SharedBeliefState):
        assert belief.get_signal_accuracy("nonexistent") == pytest.approx(0.5)


# ------------------------------------------------------------------
# Serialization
# ------------------------------------------------------------------


class TestSerialization:
    def test_to_dict_includes_all_sections(self, belief: SharedBeliefState):
        belief.update_regime(hmm_state="bull", sentiment_phase="ignition")
        d = belief.to_dict()
        assert "regime" in d
        assert "risk_budget" in d
        assert "cash_strategy" in d
        assert "daily_plan" in d
        assert "signal_accuracy" in d
        assert d["regime"]["hmm_state"] == "bull"


# ------------------------------------------------------------------
# Redis persistence
# ------------------------------------------------------------------


class TestRedisPersistence:
    def test_persist_without_redis_is_noop(self, belief: SharedBeliefState):
        # Should not raise
        belief.update_regime(hmm_state="bear")

    def test_load_from_redis_restores_state(self):
        mock_redis = MagicMock()
        mock_redis.hget.side_effect = lambda _hash, key: {
            "regime": json.dumps(
                {
                    "hmm_state": "bear",
                    "hmm_probability": 0.9,
                    "sentiment_phase": "ebb",
                    "sentiment_phase_cn": "退潮",
                    "reflexivity_state": "breaking",
                }
            ),
            "risk_budget": json.dumps(
                {
                    "daily_limit_pct": 0.03,
                    "realized_losses_today": 0.01,
                    "remaining_pct": 0.02,
                    "consecutive_losses": 1,
                    "is_halted": False,
                }
            ),
            "cash_strategy": json.dumps(
                {
                    "target_cash_pct": 0.85,
                    "current_cash_pct": 0.60,
                }
            ),
            "signal_accuracy": json.dumps({"technical": 0.65}),
        }.get(key)

        belief = SharedBeliefState(redis_client=mock_redis)
        belief.load_from_redis()

        assert belief.regime.hmm_state == "bear"
        assert belief.regime.sentiment_phase == "ebb"
        assert belief.risk_budget.realized_losses_today == pytest.approx(0.01)
        assert belief.cash_strategy.target_cash_pct == pytest.approx(0.85)
        assert belief.get_signal_accuracy("technical") == pytest.approx(0.65)

    def test_load_from_redis_handles_missing_keys(self):
        mock_redis = MagicMock()
        mock_redis.hget.return_value = None

        belief = SharedBeliefState(redis_client=mock_redis)
        belief.load_from_redis()  # Should not raise

        # Defaults preserved
        assert belief.regime.hmm_state == "unknown"


# ------------------------------------------------------------------
# Daily plan
# ------------------------------------------------------------------


class TestDailyPlan:
    def test_set_daily_plan(self, belief: SharedBeliefState):
        plan = DailyPlan(
            date="2026-03-13",
            watch_list=["000001", "600519"],
            buy_candidates=[{"symbol": "000001", "conviction": 0.8}],
            sell_plan=[],
            key_events=["CPI数据公布"],
            notes="ignition phase",
        )
        belief.set_daily_plan(plan)

        assert belief.daily_plan.date == "2026-03-13"
        assert len(belief.daily_plan.watch_list) == 2
        assert len(belief.daily_plan.buy_candidates) == 1
        assert belief.daily_plan.key_events == ["CPI数据公布"]

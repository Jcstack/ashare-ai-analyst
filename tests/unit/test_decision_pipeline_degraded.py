"""Tests for #56 — graceful degradation of the LLM-debate dependency.

By default a buy is refused when the debate engine is unavailable; with
``allow_degraded_buys`` the deterministic stack may issue a damped buy off the
Bayesian prescreen instead of silently dropping the signal.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.agent_loop.decision_pipeline import DecisionPipeline


def _buy_signal():
    return SimpleNamespace(direction=SimpleNamespace(value="buy"))


class TestDegradedBuy:
    def test_refused_by_default(self):
        dp = DecisionPipeline()
        assert dp._degraded_buy_record(_buy_signal(), 0.9) is None

    def test_enabled_issues_damped_buy_above_threshold(self):
        dp = DecisionPipeline(
            config={"allow_degraded_buys": True, "degraded_buy_min_prob": 0.6}
        )
        rec = dp._degraded_buy_record(_buy_signal(), 0.9)
        assert rec is not None
        assert rec["degraded"] is True
        assert rec["bull_score"] > rec["bear_score"]
        assert rec["bull_score"] < 0.9  # damped — no debate corroboration

    def test_enabled_but_below_threshold_refused(self):
        dp = DecisionPipeline(
            config={"allow_degraded_buys": True, "degraded_buy_min_prob": 0.6}
        )
        assert dp._degraded_buy_record(_buy_signal(), 0.5) is None

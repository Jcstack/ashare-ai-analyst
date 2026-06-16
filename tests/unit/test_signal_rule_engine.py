"""Unit tests for SignalRuleEngine (v20.0 Phase 4).

Tests cover:
- Normal signal with decent confidence → allowed
- Low-confidence signal → blocked by L1 noise_filter
- Non-system signal with empty assets → blocked
- SYSTEM_ALERT with empty assets → exempt (allowed)
- Custom L4 user rule blocks matching signals
- L1 blocks before L4 is evaluated (rule hierarchy priority)
- get_rules returns dict with L1_system key containing default rules
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.web.schemas.market_signal import MarketPhase, MarketSignal, SignalType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    *,
    signal_type: SignalType = SignalType.S1_TREND,
    assets: list[str] | None = None,
    confidence: float = 60.0,
) -> MarketSignal:
    """Build a minimal MarketSignal for testing."""
    return MarketSignal(
        signal_type=signal_type,
        timestamp=datetime.now(timezone.utc),
        assets=assets if assets is not None else ["600519"],
        phase=MarketPhase.MORNING,
        confidence_score=confidence,
        producer="test",
        summary_short="test signal summary",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    """Create a SignalRuleEngine, patching load_config to avoid file dependency."""
    with patch(
        "src.market_intelligence.signal_rule_engine.load_config",
        side_effect=FileNotFoundError,
    ):
        from src.market_intelligence.signal_rule_engine import SignalRuleEngine

        return SignalRuleEngine()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEvaluateAllowed:
    """Normal signal with confidence=60 → allowed."""

    def test_evaluate_allowed(self, engine) -> None:
        signal = _make_signal(confidence=60.0)

        result = engine.evaluate(signal)

        assert result["allowed"] is True
        assert result["blocked_by"] is None
        assert result["rule_level"] is None
        assert result["reason"] == "all rules passed"


class TestNoiseFilterBlocks:
    """Signal with confidence_score < 10 → blocked by L1 noise_filter."""

    def test_noise_filter_blocks(self, engine) -> None:
        signal = _make_signal(confidence=5.0)

        result = engine.evaluate(signal)

        assert result["allowed"] is False
        assert result["blocked_by"] == "noise_filter"
        assert result["rule_level"] == "L1_system"
        assert "noise threshold" in result["reason"].lower()


class TestEmptyAssetsBlocks:
    """Non-system signal with empty assets → blocked."""

    def test_empty_assets_blocks(self, engine) -> None:
        signal = _make_signal(
            signal_type=SignalType.S1_TREND,
            assets=[],
        )

        result = engine.evaluate(signal)

        assert result["allowed"] is False
        assert result["blocked_by"] == "empty_assets_filter"
        assert result["rule_level"] == "L1_system"


class TestSystemAlertExempt:
    """SYSTEM_ALERT with empty assets → allowed (exempt from empty-assets filter)."""

    def test_system_alert_exempt(self, engine) -> None:
        signal = _make_signal(
            signal_type=SignalType.SYSTEM_ALERT,
            assets=[],
            confidence=60.0,
        )

        result = engine.evaluate(signal)

        assert result["allowed"] is True


class TestAddCustomRule:
    """Add L4 user rule, verify it blocks matching signals."""

    def test_add_custom_rule(self, engine) -> None:
        # Custom rule: block any signal targeting "600519"
        engine.add_rule(
            level="L4_user",
            name="block_600519",
            condition=lambda sig, ctx: "600519" in sig.assets,
            reason="User blocked stock 600519",
        )

        signal = _make_signal(assets=["600519"])
        result = engine.evaluate(signal)

        assert result["allowed"] is False
        assert result["blocked_by"] == "block_600519"
        assert result["rule_level"] == "L4_user"

    def test_custom_rule_does_not_block_other_stocks(self, engine) -> None:
        engine.add_rule(
            level="L4_user",
            name="block_600519",
            condition=lambda sig, ctx: "600519" in sig.assets,
            reason="User blocked stock 600519",
        )

        signal = _make_signal(assets=["000858"])
        result = engine.evaluate(signal)

        assert result["allowed"] is True


class TestRuleHierarchyPriority:
    """L1 blocks before L4 is evaluated."""

    def test_rule_hierarchy_priority(self, engine) -> None:
        # Add an L4 rule that would block everything
        l4_called = {"value": False}

        def l4_block_all(sig, ctx):
            l4_called["value"] = True
            return True

        engine.add_rule(
            level="L4_user",
            name="block_all",
            condition=l4_block_all,
            reason="Block everything (L4)",
        )

        # Use a signal that L1 noise_filter will block (confidence < 10)
        signal = _make_signal(confidence=3.0)
        result = engine.evaluate(signal)

        # L1 should have blocked it — L4 should never execute
        assert result["allowed"] is False
        assert result["rule_level"] == "L1_system"
        assert result["blocked_by"] == "noise_filter"
        assert l4_called["value"] is False


class TestGetRules:
    """Verify returns dict with L1_system key containing default rules."""

    def test_get_rules(self, engine) -> None:
        rules = engine.get_rules()

        assert isinstance(rules, dict)
        assert "L1_system" in rules
        assert "L2_risk" in rules
        assert "L3_phase" in rules
        assert "L4_user" in rules

        l1_rules = rules["L1_system"]
        assert len(l1_rules) >= 2

        rule_names = [r["name"] for r in l1_rules]
        assert "noise_filter" in rule_names
        assert "empty_assets_filter" in rule_names

        # Each rule should have name and reason, but no condition callable
        for rule in l1_rules:
            assert "name" in rule
            assert "reason" in rule
            assert "condition" not in rule

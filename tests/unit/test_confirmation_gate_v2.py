"""Tests for SignalConfirmationGate (signal-level confirmation).

Part of v20.0 Market Intelligence Phase 2.

This tests the *signal* confirmation gate at
``src/market_intelligence/confirmation_gate.py``, distinct from the
trade-level confirmation gate tested in ``test_confirmation_gate.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.market_intelligence.confirmation_gate import SignalConfirmationGate
from src.web.schemas.market_signal import (
    MarketPhase,
    MarketSignal,
    SignalType,
    SourceReference,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(provider: str = "akshare") -> SourceReference:
    """Build a minimal SourceReference."""
    return SourceReference(
        source_id="src-1",
        provider=provider,
        data_type="quote",
        timestamp=datetime.now(timezone.utc),
        reliability_score=0.8,
    )


def _make_signal(
    *,
    signal_type: SignalType = SignalType.S1_TREND,
    num_sources: int = 0,
) -> MarketSignal:
    """Build a minimal MarketSignal with N sources."""
    providers = ["akshare", "sina", "xueqiu", "policy_news"]
    sources = [
        _make_source(provider=providers[i % len(providers)]) for i in range(num_sources)
    ]
    return MarketSignal(
        signal_type=signal_type,
        timestamp=datetime.now(timezone.utc),
        assets=["600519"],
        phase=MarketPhase.CLOSED,
        confidence_score=50.0,
        sources=sources,
        producer="test",
        summary_short="test signal",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSignalConfirmationGate:
    """Tests for SignalConfirmationGate check, get_rules, and override_rule."""

    def test_auto_confirm_system_alert(self):
        """SYSTEM_ALERT with 0 sources -> confirmed=True."""
        gate = SignalConfirmationGate()
        signal = _make_signal(signal_type=SignalType.SYSTEM_ALERT, num_sources=0)

        result = gate.check(signal)

        assert result.confirmed is True

    def test_auto_confirm_correlation_shift(self):
        """S6_CORRELATION_SHIFT -> confirmed=True."""
        gate = SignalConfirmationGate()
        signal = _make_signal(
            signal_type=SignalType.S6_CORRELATION_SHIFT,
            num_sources=0,
        )

        result = gate.check(signal)

        assert result.confirmed is True

    def test_trend_needs_two_sources(self):
        """S1_TREND with 1 source -> confirmed=False."""
        gate = SignalConfirmationGate()
        signal = _make_signal(signal_type=SignalType.S1_TREND, num_sources=1)

        result = gate.check(signal)

        assert result.confirmed is False
        assert result.confirmation_sources == []

    def test_trend_confirmed_with_two_sources(self):
        """S1_TREND with 2 sources -> confirmed=True."""
        gate = SignalConfirmationGate()
        signal = _make_signal(signal_type=SignalType.S1_TREND, num_sources=2)

        result = gate.check(signal)

        assert result.confirmed is True
        assert len(result.confirmation_sources) == 2

    def test_anomaly_needs_one_source(self):
        """S4_ANOMALY with 0 sources -> confirmed=False."""
        gate = SignalConfirmationGate()
        signal = _make_signal(signal_type=SignalType.S4_ANOMALY, num_sources=0)

        result = gate.check(signal)

        assert result.confirmed is False

    def test_anomaly_confirmed_with_one_source(self):
        """S4_ANOMALY with 1 source -> confirmed=True."""
        gate = SignalConfirmationGate()
        signal = _make_signal(signal_type=SignalType.S4_ANOMALY, num_sources=1)

        result = gate.check(signal)

        assert result.confirmed is True
        assert len(result.confirmation_sources) == 1

    def test_get_rules(self):
        """Verify returns dict with all signal types."""
        gate = SignalConfirmationGate()

        rules = gate.get_rules()

        assert len(rules) == len(SignalType)
        # Spot-check known rules
        assert rules["S1_TREND"] == 2
        assert rules["S4_ANOMALY"] == 1
        assert rules["SYSTEM_ALERT"] == 0
        assert rules["S6_CORRELATION_SHIFT"] == 0

        # Verify all SignalType members are represented
        for st in SignalType:
            assert st.value in rules

    def test_override_rule(self):
        """Override S1_TREND to require 3 sources, verify enforcement."""
        gate = SignalConfirmationGate()
        gate.override_rule("S1_TREND", 3)

        # 2 sources no longer sufficient
        signal_2 = _make_signal(signal_type=SignalType.S1_TREND, num_sources=2)
        result_2 = gate.check(signal_2)
        assert result_2.confirmed is False

        # 3 sources now pass
        signal_3 = _make_signal(signal_type=SignalType.S1_TREND, num_sources=3)
        result_3 = gate.check(signal_3)
        assert result_3.confirmed is True

        # Verify rules reflect the override
        rules = gate.get_rules()
        assert rules["S1_TREND"] == 3

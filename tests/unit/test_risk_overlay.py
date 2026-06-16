"""Tests for RiskOverlayEngine.

Part of v20.0 Market Intelligence Phase 2.
"""

from __future__ import annotations

import types
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.market_intelligence.risk_overlay import RiskOverlayEngine
from src.web.schemas.market_signal import (
    MarketPhase,
    MarketSignal,
    RiskLevel,
    SignalType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    *,
    signal_type: SignalType = SignalType.S1_TREND,
    confidence_score: float = 50.0,
    risk_level: RiskLevel = RiskLevel.LOW,
) -> MarketSignal:
    """Build a minimal MarketSignal for testing."""
    return MarketSignal(
        signal_type=signal_type,
        timestamp=datetime.now(timezone.utc),
        assets=["600519"],
        phase=MarketPhase.CLOSED,
        confidence_score=confidence_score,
        sources=[],
        producer="test",
        summary_short="test signal",
        risk_level=risk_level,
    )


def _make_engine(
    *,
    regime_label: str = "low",
    breaker_state: str = "NORMAL",
    breaker_can_trade: bool = True,
    var_pct: float = 0.02,
    regime_raises: bool = False,
) -> RiskOverlayEngine:
    """Build a RiskOverlayEngine with mock dependencies.

    Args:
        regime_label: Label returned by RegimeDetector.detect().
        breaker_state: State string for circuit breaker.
        breaker_can_trade: Whether the breaker allows trading.
        var_pct: VaR percentage returned by historical_var().
        regime_raises: If True, regime_detector.detect will raise.
    """
    # RegimeDetector
    regime_detector = MagicMock()
    if regime_raises:
        regime_detector.detect.side_effect = RuntimeError("detector down")
    else:
        regime_report = types.SimpleNamespace(
            current_regime=types.SimpleNamespace(regime_label=regime_label)
        )
        regime_detector.detect.return_value = regime_report

    # CircuitBreaker
    circuit_breaker = MagicMock()
    breaker_status = types.SimpleNamespace(
        state=types.SimpleNamespace(value=breaker_state),
        can_trade=breaker_can_trade,
        trigger_reason=None if breaker_can_trade else breaker_state,
    )
    circuit_breaker.check.return_value = breaker_status

    # VaRCalculator
    var_calculator = MagicMock()
    var_result = types.SimpleNamespace(var_pct=var_pct)
    var_calculator.historical_var.return_value = var_result

    return RiskOverlayEngine(
        regime_detector=regime_detector,
        circuit_breaker=circuit_breaker,
        var_calculator=var_calculator,
    )


def _default_portfolio_context() -> dict:
    """Build a minimal portfolio context dict."""
    return {
        "daily_returns": [0.01, -0.005, 0.003, 0.002, -0.001],
        "daily_pnl_pct": -0.01,
        "weekly_pnl_pct": 0.02,
        "portfolio_value": 1_000_000.0,
        "position_weights": {"600519": 0.3, "000858": 0.2},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRiskOverlayEngine:
    """Tests for the RiskOverlayEngine evaluate and should_block methods."""

    def test_evaluate_low_risk(self):
        """Mock all 3 dependencies to return calm values, verify risk_level == LOW."""
        engine = _make_engine(regime_label="low", breaker_state="NORMAL", var_pct=0.02)
        signal = _make_signal()
        ctx = _default_portfolio_context()

        result = engine.evaluate(signal, ctx)

        assert result.risk_level == RiskLevel.LOW
        assert result.risk_context is not None
        assert result.risk_context.volatility_regime == "low"
        assert result.risk_context.circuit_breaker_state == "NORMAL"

    def test_evaluate_extreme_risk_circuit_breaker(self):
        """Mock breaker state != NORMAL, verify EXTREME."""
        engine = _make_engine(
            breaker_state="DAILY_HALT",
            breaker_can_trade=False,
        )
        signal = _make_signal()
        ctx = _default_portfolio_context()

        result = engine.evaluate(signal, ctx)

        assert result.risk_level == RiskLevel.EXTREME

    def test_evaluate_extreme_risk_high_var(self):
        """Mock var_pct > 0.08, verify EXTREME."""
        engine = _make_engine(var_pct=0.10)
        signal = _make_signal()
        ctx = _default_portfolio_context()

        result = engine.evaluate(signal, ctx)

        assert result.risk_level == RiskLevel.EXTREME

    def test_evaluate_elevated_risk_high_volatility(self):
        """Mock regime=high, verify ELEVATED."""
        engine = _make_engine(regime_label="high", var_pct=0.02)
        signal = _make_signal()
        ctx = _default_portfolio_context()

        result = engine.evaluate(signal, ctx)

        assert result.risk_level == RiskLevel.ELEVATED

    def test_evaluate_moderate_risk(self):
        """Mock var_pct between 0.03 and 0.05, verify MODERATE."""
        engine = _make_engine(regime_label="low", var_pct=0.04)
        signal = _make_signal()
        ctx = _default_portfolio_context()

        result = engine.evaluate(signal, ctx)

        assert result.risk_level == RiskLevel.MODERATE

    def test_should_block_extreme_low_confidence(self):
        """Set risk_level=EXTREME, confidence_score=30, verify should_block returns True."""
        engine = _make_engine()
        signal = _make_signal(
            confidence_score=30.0,
            risk_level=RiskLevel.EXTREME,
        )

        assert engine.should_block(signal) is True

    def test_should_not_block_extreme_high_confidence(self):
        """EXTREME + confidence=60, should_block returns False."""
        engine = _make_engine()
        signal = _make_signal(
            confidence_score=60.0,
            risk_level=RiskLevel.EXTREME,
        )

        assert engine.should_block(signal) is False

    def test_dependency_failure_defaults_moderate(self):
        """Mock regime_detector.detect to raise, verify risk defaults gracefully.

        When the regime detector fails, the engine defaults to "medium"
        volatility regime, which maps to MODERATE risk level (assuming
        low VaR and normal circuit breaker).
        """
        engine = _make_engine(regime_raises=True, var_pct=0.01)
        signal = _make_signal()
        ctx = _default_portfolio_context()

        result = engine.evaluate(signal, ctx)

        # Regime defaults to "medium" on failure -> MODERATE
        assert result.risk_level == RiskLevel.MODERATE
        assert result.risk_context is not None
        assert result.risk_context.volatility_regime == "medium"

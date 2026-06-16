"""Tests for compute_quant_signals tech_score bias fix (I-049).

Verifies that the 5-subscore weighted composite correctly reflects
bearish, bullish, and neutral market conditions.
"""

from __future__ import annotations

from src.prediction.analysis_frameworks import compute_quant_signals


def _make_indicators(
    *,
    rsi: float = 50.0,
    ma5: float = 10.0,
    ma10: float = 10.0,
    ma20: float = 10.0,
    ma60: float = 10.0,
    macd: float = 0.0,
    macd_signal: float = 0.0,
    macd_hist: float = 0.0,
    bb_upper: float = 11.0,
    bb_lower: float = 9.0,
    bb_middle: float = 10.0,
) -> dict:
    return {
        "RSI": rsi,
        "MA_5": ma5,
        "MA_10": ma10,
        "MA_20": ma20,
        "MA_60": ma60,
        "MACD": {"MACD": macd, "signal": macd_signal, "histogram": macd_hist},
        "BB_upper": bb_upper,
        "BB_lower": bb_lower,
        "BB_middle": bb_middle,
    }


class TestComputeQuantSignalsBias:
    """Verify tech_score reflects actual market conditions."""

    def test_full_bearish_arrangement(self) -> None:
        """Full bearish MA arrangement + RSI=42 + negative MACD hist → score < 35."""
        indicators = _make_indicators(
            rsi=42,
            ma5=9.0,
            ma10=9.5,
            ma20=10.0,
            ma60=10.5,
            macd=-0.1,
            macd_signal=0.05,
            macd_hist=-0.15,
            bb_upper=11.0,
            bb_lower=9.0,
            bb_middle=10.0,
        )
        result = compute_quant_signals(
            indicators, None, None, current_price=9.2
        )
        assert result["technical_score"] < 35

    def test_full_bullish_arrangement(self) -> None:
        """Full bullish MA arrangement + RSI=65 + positive MACD hist → score > 65."""
        indicators = _make_indicators(
            rsi=65,
            ma5=11.0,
            ma10=10.5,
            ma20=10.0,
            ma60=9.5,
            macd=0.2,
            macd_signal=0.1,
            macd_hist=0.1,
            bb_upper=11.5,
            bb_lower=9.5,
            bb_middle=10.5,
        )
        result = compute_quant_signals(
            indicators, None, None, current_price=11.2
        )
        assert result["technical_score"] > 65

    def test_neutral_consolidation(self) -> None:
        """MA粘合 + RSI=50 + MACD hist≈0 → score between 40-60."""
        indicators = _make_indicators(
            rsi=50,
            ma5=10.0,
            ma10=10.0,
            ma20=10.0,
            ma60=10.0,
            macd=0.0,
            macd_signal=0.0,
            macd_hist=0.0,
        )
        result = compute_quant_signals(
            indicators, None, None, current_price=10.0
        )
        assert 40 <= result["technical_score"] <= 60

    def test_none_indicators(self) -> None:
        """None indicators → default tech_score = 50."""
        result = compute_quant_signals(None, None, None)
        assert result["technical_score"] == 50.0

    def test_no_current_price(self) -> None:
        """Missing current_price should not crash; function returns normally."""
        indicators = _make_indicators(rsi=55)
        result = compute_quant_signals(indicators, None, None)
        assert "technical_score" in result
        assert 0 <= result["technical_score"] <= 100

    def test_backward_compat_fields(self) -> None:
        """Result should still include momentum_score, bayesian_probability, etc."""
        result = compute_quant_signals(None, None, None)
        assert "momentum_score" in result
        assert "bayesian_probability" in result
        assert "strategy_consensus" in result

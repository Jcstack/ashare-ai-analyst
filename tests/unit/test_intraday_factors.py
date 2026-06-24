"""Tests for IntradayFactorEngine — intraday factor computation."""

from __future__ import annotations

import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timedelta


def _make_minute_bars(
    n_bars: int = 48, base_price: float = 10.0, trend: float = 0.001
) -> pd.DataFrame:
    """Create synthetic 5-minute bars for testing.

    48 bars = full trading day (4 hours / 5 minutes).
    """
    np.random.seed(42)  # reproducibility
    dates = []
    base = datetime(2026, 3, 10, 9, 30)
    for i in range(n_bars):
        if i < 24:  # Morning: 9:30-11:30
            dates.append(base + timedelta(minutes=i * 5))
        else:  # Afternoon: 13:00-15:00
            dates.append(datetime(2026, 3, 10, 13, 0) + timedelta(minutes=(i - 24) * 5))

    prices = [
        base_price * (1 + trend * i + np.random.normal(0, 0.002)) for i in range(n_bars)
    ]

    return pd.DataFrame(
        {
            "datetime": dates,
            "open": [p * 0.999 for p in prices],
            "high": [p * 1.005 for p in prices],
            "low": [p * 0.995 for p in prices],
            "close": prices,
            "volume": [
                int(100000 * max(0.1, 1 + np.random.normal(0, 0.3)))
                for _ in range(n_bars)
            ],
            "amount": [p * 100000 for p in prices],
        }
    )


class TestIntradayFactorEngine:
    @pytest.fixture()
    def engine(self):
        from src.quant.intraday_factors import IntradayFactorEngine

        return IntradayFactorEngine()

    def test_compute_returns_dict(self, engine):
        bars = _make_minute_bars()
        result = engine.compute(bars)
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_all_factors_present(self, engine):
        bars = _make_minute_bars()
        result = engine.compute(bars)
        expected_keys = [
            "vwap_deviation",
            "high_reversal_pct",
            "intraday_momentum_5m",
            "intraday_momentum_30m",
            "volume_price_divergence",
            "late_session_momentum",
            "volume_concentration",
            "open_drive",
            "bar_strength",
            "amplitude",
        ]
        for key in expected_keys:
            assert key in result, f"Missing factor: {key}"

    def test_factors_in_range(self, engine):
        """All factors should be in [0, 1] range."""
        bars = _make_minute_bars()
        result = engine.compute(bars)
        for key, value in result.items():
            assert 0.0 <= value <= 1.0, f"Factor {key}={value} out of [0,1] range"

    def test_empty_dataframe(self, engine):
        result = engine.compute(pd.DataFrame())
        assert isinstance(result, dict)
        # Should return neutral factors (all 0.5)
        for key, value in result.items():
            assert value == 0.5, f"Neutral factor {key} should be 0.5, got {value}"

    def test_none_input(self, engine):
        result = engine.compute(None)
        assert isinstance(result, dict)
        assert all(v == 0.5 for v in result.values())

    def test_few_bars(self, engine):
        """Should handle gracefully when only a few bars available."""
        bars = _make_minute_bars(n_bars=3)
        result = engine.compute(bars)
        assert isinstance(result, dict)
        # All values should still be in [0, 1]
        for key, value in result.items():
            assert 0.0 <= value <= 1.0, (
                f"Factor {key}={value} out of range with few bars"
            )

    def test_high_reversal_detected(self, engine):
        """When price dropped from high, high_reversal_pct should be < 1.0."""
        bars = _make_minute_bars(n_bars=48, trend=0.002)
        # Simulate reversal: last few bars drop significantly
        bars.loc[bars.index[-5:], "close"] = bars["close"].iloc[-6] * 0.95
        bars.loc[bars.index[-5:], "high"] = bars["close"].iloc[-6] * 0.96
        result = engine.compute(bars)
        assert result.get("high_reversal_pct", 1.0) < 0.8

    def test_volume_price_divergence_bearish(self, engine):
        """Price up but volume down should give bearish divergence (< 0.5)."""
        bars = _make_minute_bars(n_bars=48, trend=0.003)
        # Make volume decrease while price increases
        for i in range(len(bars)):
            bars.loc[bars.index[i], "volume"] = max(1000, 200000 - i * 4000)
        result = engine.compute(bars)
        # Bearish divergence: price up, volume down → factor around 0.3
        assert result.get("volume_price_divergence", 0.5) < 0.5

    def test_compute_batch(self, engine):
        data = {
            "600519": _make_minute_bars(),
            "000001": _make_minute_bars(),
        }
        result = engine.compute_batch(data)
        assert isinstance(result, dict)
        assert "600519" in result
        assert "000001" in result
        # Each value should be a factor dict
        for sym, factors in result.items():
            assert isinstance(factors, dict)
            assert "vwap_deviation" in factors

    def test_compute_batch_with_quotes(self, engine):
        data = {
            "600519": _make_minute_bars(),
        }
        quotes = {
            "600519": {
                "price": 10.5,
                "open": 10.0,
                "high": 10.6,
                "low": 9.9,
                "prev_close": 10.0,
                "volume": 1000000,
            },
        }
        result = engine.compute_batch(data, quotes=quotes)
        assert "600519" in result

    def test_compute_batch_handles_exception(self, engine):
        """Batch should return neutral factors for symbols that fail."""
        data = {
            "600519": _make_minute_bars(),
            "BAD": pd.DataFrame({"wrong_col": [1, 2]}),
        }
        result = engine.compute_batch(data)
        assert "BAD" in result
        # Should be neutral factors, not a crash
        assert all(v == 0.5 for v in result["BAD"].values())

    def test_bar_strength_with_all_bullish(self, engine):
        """When all bars close > open, bar_strength should be 1.0."""
        bars = _make_minute_bars(n_bars=48)
        # Force all bars bullish
        bars["open"] = bars["close"] * 0.99
        result = engine.compute(bars)
        assert result["bar_strength"] == 1.0

    def test_amplitude_calm_market(self, engine):
        """Small amplitude (high ≈ low) should give high amplitude factor."""
        bars = _make_minute_bars(n_bars=48, trend=0.0)
        # Make high and low very close to close
        bars["high"] = bars["close"] * 1.001
        bars["low"] = bars["close"] * 0.999
        result = engine.compute(bars)
        # Low amplitude → factor close to 1.0
        assert result["amplitude"] > 0.8

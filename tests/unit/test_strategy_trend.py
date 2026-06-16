"""Unit tests for TrendFollowingStrategy.

Tests cover:
- Output DataFrame has the correct columns
- Golden-cross (buy) detection
- Death-cross (sell) detection
- No signal when market is sideways
- Volume filter blocking weak-volume buy signals
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.base import SIGNAL_BUY, SIGNAL_HOLD, SIGNAL_SELL
from src.strategy.trend_following import TrendFollowingStrategy


# ---- Helpers ---------------------------------------------------------


def _make_ohlcv(
    close_series: list[float],
    volume_series: list[float] | None = None,
    start_date: str = "2024-01-02",
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame from a close series.

    Open/high/low are derived from close with small offsets so that
    indicator calculations receive realistic data.
    """
    n = len(close_series)
    dates = pd.date_range(start_date, periods=n, freq="B")
    close = np.array(close_series, dtype=float)
    if volume_series is None:
        volume_series = [1_000_000.0] * n
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.998,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": volume_series,
        }
    )


def _golden_cross_data(n: int = 50) -> pd.DataFrame:
    """Build data where MA5 starts below MA20 and crosses above.

    The first 30 bars trend slightly downward, then the last 20 bars
    trend sharply upward so that the fast MA crosses the slow MA.
    """
    # Downward phase
    down = np.linspace(12.0, 10.0, 30)
    # Upward phase
    up = np.linspace(10.2, 15.0, n - 30)
    close = np.concatenate([down, up])
    # High volume on the upward leg to pass volume filter
    volume = [800_000.0] * 30 + [2_500_000.0] * (n - 30)
    return _make_ohlcv(close.tolist(), volume)


def _death_cross_data(n: int = 50) -> pd.DataFrame:
    """Build data where MA5 starts above MA20 and crosses below."""
    up = np.linspace(10.0, 14.0, 30)
    down = np.linspace(13.8, 9.0, n - 30)
    close = np.concatenate([up, down])
    volume = [1_000_000.0] * n
    return _make_ohlcv(close.tolist(), volume)


def _sideways_data(n: int = 50) -> pd.DataFrame:
    """Build data that oscillates around a fixed mean (no trend)."""
    base = 10.0
    np.random.seed(42)
    noise = np.random.normal(0, 0.02, n)
    close = base + noise
    return _make_ohlcv(close.tolist())


# ---- Fixtures --------------------------------------------------------


@pytest.fixture
def strategy():
    return TrendFollowingStrategy(config_path="strategy")


# ---- Tests -----------------------------------------------------------


class TestGenerateSignalsOutput:
    """Verify the output shape and columns."""

    def test_returns_dataframe(self, strategy):
        df = _golden_cross_data()
        result = strategy.generate_signals(df)
        assert isinstance(result, pd.DataFrame)

    def test_has_required_columns(self, strategy):
        df = _golden_cross_data()
        result = strategy.generate_signals(df)
        for col in ("date", "signal", "strength", "reason"):
            assert col in result.columns, f"Missing column: {col}"

    def test_same_length_as_input(self, strategy):
        df = _golden_cross_data()
        result = strategy.generate_signals(df)
        assert len(result) == len(df)

    def test_does_not_modify_input(self, strategy):
        df = _golden_cross_data()
        original_cols = set(df.columns)
        _ = strategy.generate_signals(df)
        assert set(df.columns) == original_cols, "Input DataFrame was modified"


class TestBuySignalGoldenCross:
    """Golden cross should produce at least one BUY signal."""

    def test_buy_signal_exists(self, strategy):
        df = _golden_cross_data()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        assert len(buy_signals) > 0, "Expected at least one BUY signal"

    def test_buy_signal_has_positive_strength(self, strategy):
        df = _golden_cross_data()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        assert (buy_signals["strength"] > 0).all()

    def test_buy_signal_reason_in_chinese(self, strategy):
        df = _golden_cross_data()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        for reason in buy_signals["reason"]:
            assert "金叉" in reason


class TestSellSignalDeathCross:
    """Death cross should produce at least one SELL signal."""

    def test_sell_signal_exists(self, strategy):
        df = _death_cross_data()
        result = strategy.generate_signals(df)
        sell_signals = result[result["signal"] == SIGNAL_SELL]
        assert len(sell_signals) > 0, "Expected at least one SELL signal"

    def test_sell_signal_has_positive_strength(self, strategy):
        df = _death_cross_data()
        result = strategy.generate_signals(df)
        sell_signals = result[result["signal"] == SIGNAL_SELL]
        assert (sell_signals["strength"] > 0).all()

    def test_sell_signal_reason_in_chinese(self, strategy):
        df = _death_cross_data()
        result = strategy.generate_signals(df)
        sell_signals = result[result["signal"] == SIGNAL_SELL]
        for reason in sell_signals["reason"]:
            assert "死叉" in reason


class TestNoSignalSideways:
    """Sideways market should produce mostly HOLD signals."""

    def test_mostly_hold(self, strategy):
        df = _sideways_data()
        result = strategy.generate_signals(df)
        hold_count = (result["signal"] == SIGNAL_HOLD).sum()
        total = len(result)
        # Expect at least 80% hold in a sideways market
        assert hold_count / total >= 0.8, (
            f"Expected >= 80% HOLD, got {hold_count}/{total}"
        )


class TestVolumeFilterBlocksWeakVolume:
    """When volume_filter is on, low volume should block buy signals."""

    def test_weak_volume_suppresses_buy(self):
        """Golden cross with low volume should not produce a BUY."""
        # Build golden-cross data but with uniformly low volume
        n = 50
        down = np.linspace(12.0, 10.0, 30)
        up = np.linspace(10.2, 15.0, n - 30)
        close = np.concatenate([down, up])
        # Volume is flat and low -- below the 1.5x threshold
        low_volume = [500_000.0] * n
        df = _make_ohlcv(close.tolist(), low_volume)

        strategy = TrendFollowingStrategy(config_path="strategy")
        result = strategy.generate_signals(df)

        buy_signals = result[result["signal"] == SIGNAL_BUY]
        assert len(buy_signals) == 0, "Expected NO buy signals with weak volume"

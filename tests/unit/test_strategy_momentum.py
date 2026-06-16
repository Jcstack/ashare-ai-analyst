"""Unit tests for MomentumStrategy.

Tests cover:
- Buy signal when ROC > 0 with volume surge
- Sell signal when ROC < 0 with weak RSI
- No buy signal when volume is insufficient despite positive ROC
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.base import SIGNAL_BUY, SIGNAL_SELL
from src.strategy.momentum import MomentumStrategy


# ---- Helpers ---------------------------------------------------------


def _make_ohlcv(
    close_series: list[float],
    volume_series: list[float] | None = None,
    start_date: str = "2024-01-02",
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame from a close series."""
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


def _positive_roc_with_volume_surge(n: int = 50) -> pd.DataFrame:
    """Build data with a steady uptrend and late volume surge.

    The first 30 bars are flat, then the last 20 bars trend up steadily
    with a big volume spike to satisfy the volume_surge_threshold.
    """
    flat = [10.0] * 30
    up = np.linspace(10.5, 14.0, n - 30).tolist()
    close = flat + up
    # Low volume in flat phase, huge surge in uptrend phase
    volume = [500_000.0] * 30 + [3_000_000.0] * (n - 30)
    return _make_ohlcv(close, volume)


def _negative_roc_data(n: int = 50) -> pd.DataFrame:
    """Build data with a clear downtrend (negative ROC, low RSI)."""
    flat = [14.0] * 20
    down = np.linspace(13.5, 8.0, n - 20).tolist()
    close = flat + down
    volume = [1_000_000.0] * n
    return _make_ohlcv(close, volume)


def _positive_roc_low_volume(n: int = 50) -> pd.DataFrame:
    """Build data with uptrend but uniformly low volume.

    ROC will be positive, but volume never surges above the threshold.
    """
    flat = [10.0] * 30
    up = np.linspace(10.5, 14.0, n - 30).tolist()
    close = flat + up
    # Uniform low volume -- never exceeds 2x average
    volume = [500_000.0] * n
    return _make_ohlcv(close, volume)


# ---- Fixtures --------------------------------------------------------


@pytest.fixture
def strategy():
    return MomentumStrategy(config_path="strategy")


# ---- Tests -----------------------------------------------------------


class TestBuySignalPositiveROC:
    """Positive ROC + volume surge should produce BUY signals."""

    def test_buy_signal_exists(self, strategy):
        df = _positive_roc_with_volume_surge()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        assert len(buy_signals) > 0, (
            "Expected at least one BUY signal with positive ROC and volume surge"
        )

    def test_buy_signal_has_positive_strength(self, strategy):
        df = _positive_roc_with_volume_surge()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        if len(buy_signals) > 0:
            assert (buy_signals["strength"] > 0).all()

    def test_buy_reason_mentions_roc(self, strategy):
        df = _positive_roc_with_volume_surge()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        for reason in buy_signals["reason"]:
            assert "ROC" in reason

    def test_buy_reason_mentions_volume(self, strategy):
        df = _positive_roc_with_volume_surge()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        for reason in buy_signals["reason"]:
            assert "成交量" in reason

    def test_output_columns(self, strategy):
        df = _positive_roc_with_volume_surge()
        result = strategy.generate_signals(df)
        for col in ("date", "signal", "strength", "reason"):
            assert col in result.columns

    def test_same_length_as_input(self, strategy):
        df = _positive_roc_with_volume_surge()
        result = strategy.generate_signals(df)
        assert len(result) == len(df)

    def test_does_not_modify_input(self, strategy):
        df = _positive_roc_with_volume_surge()
        original_cols = set(df.columns)
        _ = strategy.generate_signals(df)
        assert set(df.columns) == original_cols


class TestSellSignalNegativeROC:
    """Negative ROC + RSI below threshold should produce SELL signals."""

    def test_sell_signal_exists(self, strategy):
        df = _negative_roc_data()
        result = strategy.generate_signals(df)
        sell_signals = result[result["signal"] == SIGNAL_SELL]
        assert len(sell_signals) > 0, (
            "Expected at least one SELL signal with negative ROC"
        )

    def test_sell_signal_has_positive_strength(self, strategy):
        df = _negative_roc_data()
        result = strategy.generate_signals(df)
        sell_signals = result[result["signal"] == SIGNAL_SELL]
        if len(sell_signals) > 0:
            assert (sell_signals["strength"] > 0).all()

    def test_sell_reason_mentions_roc(self, strategy):
        df = _negative_roc_data()
        result = strategy.generate_signals(df)
        sell_signals = result[result["signal"] == SIGNAL_SELL]
        for reason in sell_signals["reason"]:
            assert "ROC" in reason


class TestNoSignalLowVolume:
    """Positive ROC but no volume surge should suppress BUY signals."""

    def test_no_buy_signal_with_low_volume(self, strategy):
        df = _positive_roc_low_volume()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        assert len(buy_signals) == 0, (
            "Expected NO buy signals when volume is below surge threshold"
        )

    def test_mostly_hold_or_sell(self, strategy):
        """With low volume, signals should be HOLD or SELL (no buys)."""
        df = _positive_roc_low_volume()
        result = strategy.generate_signals(df)
        assert (result["signal"] != SIGNAL_BUY).all()

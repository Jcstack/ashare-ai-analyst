"""Unit tests for MeanReversionStrategy.

Tests cover:
- Buy signal when price is below lower Bollinger Band with RSI oversold
- Sell signal when price is above upper Bollinger Band with RSI overbought
- No signal when price is between bands with neutral RSI
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.base import SIGNAL_BUY, SIGNAL_HOLD, SIGNAL_SELL
from src.strategy.mean_reversion import MeanReversionStrategy


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


def _oversold_data(n: int = 50) -> pd.DataFrame:
    """Build data that drives price far below the lower Bollinger Band.

    20 bars of stable prices (to establish the band), followed by a
    sharp drop so that close < BB_lower and RSI becomes oversold.
    Volume increases on the drop to satisfy volume_confirm.
    """
    stable = [10.0] * 25
    # Sharp decline: 10 -> 7 in 25 bars
    decline = np.linspace(9.5, 7.0, n - 25).tolist()
    close = stable + decline
    # Elevated volume on the decline phase
    volume = [800_000.0] * 25 + [2_000_000.0] * (n - 25)
    return _make_ohlcv(close, volume)


def _overbought_data(n: int = 50) -> pd.DataFrame:
    """Build data that drives price far above the upper Bollinger Band.

    20 bars of stable prices, followed by a sharp rally so that
    close > BB_upper and RSI becomes overbought.
    """
    stable = [10.0] * 25
    rally = np.linspace(10.5, 14.0, n - 25).tolist()
    close = stable + rally
    volume = [1_000_000.0] * n
    return _make_ohlcv(close, volume)


def _neutral_data(n: int = 50) -> pd.DataFrame:
    """Build data that stays near the middle Bollinger Band.

    Oscillates gently around 10.0 with minimal variance.
    """
    np.random.seed(123)
    noise = np.random.normal(0, 0.05, n)
    close = (10.0 + noise).tolist()
    return _make_ohlcv(close)


# ---- Fixtures --------------------------------------------------------


@pytest.fixture
def strategy():
    return MeanReversionStrategy(config_path="strategy")


# ---- Tests -----------------------------------------------------------


class TestBuySignalAtLowerBand:
    """Price below BB_lower + RSI oversold should trigger BUY."""

    def test_buy_signal_exists(self, strategy):
        df = _oversold_data()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        assert len(buy_signals) > 0, "Expected at least one BUY signal in oversold data"

    def test_buy_signal_has_positive_strength(self, strategy):
        df = _oversold_data()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        if len(buy_signals) > 0:
            assert (buy_signals["strength"] > 0).all()

    def test_buy_reason_mentions_bollinger(self, strategy):
        df = _oversold_data()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        for reason in buy_signals["reason"]:
            assert "布林" in reason or "下轨" in reason

    def test_buy_reason_mentions_rsi(self, strategy):
        df = _oversold_data()
        result = strategy.generate_signals(df)
        buy_signals = result[result["signal"] == SIGNAL_BUY]
        for reason in buy_signals["reason"]:
            assert "RSI" in reason


class TestSellSignalAtUpperBand:
    """Price above BB_upper + RSI overbought should trigger SELL."""

    def test_sell_signal_exists(self, strategy):
        df = _overbought_data()
        result = strategy.generate_signals(df)
        sell_signals = result[result["signal"] == SIGNAL_SELL]
        assert len(sell_signals) > 0, (
            "Expected at least one SELL signal in overbought data"
        )

    def test_sell_signal_has_positive_strength(self, strategy):
        df = _overbought_data()
        result = strategy.generate_signals(df)
        sell_signals = result[result["signal"] == SIGNAL_SELL]
        if len(sell_signals) > 0:
            assert (sell_signals["strength"] > 0).all()

    def test_sell_reason_mentions_bollinger(self, strategy):
        df = _overbought_data()
        result = strategy.generate_signals(df)
        sell_signals = result[result["signal"] == SIGNAL_SELL]
        for reason in sell_signals["reason"]:
            assert "布林" in reason or "上轨" in reason


class TestNoSignalInMiddle:
    """Neutral data should produce mostly HOLD signals."""

    def test_mostly_hold(self, strategy):
        df = _neutral_data()
        result = strategy.generate_signals(df)
        hold_count = (result["signal"] == SIGNAL_HOLD).sum()
        total = len(result)
        assert hold_count / total >= 0.8, (
            f"Expected >= 80% HOLD in neutral data, got {hold_count}/{total}"
        )

    def test_output_columns(self, strategy):
        df = _neutral_data()
        result = strategy.generate_signals(df)
        for col in ("date", "signal", "strength", "reason"):
            assert col in result.columns

    def test_does_not_modify_input(self, strategy):
        df = _neutral_data()
        original_cols = set(df.columns)
        _ = strategy.generate_signals(df)
        assert set(df.columns) == original_cols

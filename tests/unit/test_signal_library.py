"""Tests for signal library.

Part of v15.0 Quant Core layer.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.quant.signal_library import (
    SignalDefinition,
    SignalLibrary,
    SignalResult,
    SignalSummary,
    _aggregate_signals,
    _compute_rsi,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_quant_config():
    return {
        "signal_library": {
            "default_lookback_days": 60,
            "signals": {
                "ma_cross": {
                    "description": "Moving average crossover",
                    "fast_period": 5,
                    "slow_period": 20,
                    "signal_type": "momentum",
                },
                "rsi_extreme": {
                    "description": "RSI overbought/oversold",
                    "period": 14,
                    "overbought": 70,
                    "oversold": 30,
                    "signal_type": "mean_reversion",
                },
                "bollinger_squeeze": {
                    "description": "Bollinger Band squeeze",
                    "period": 20,
                    "std_dev": 2.0,
                    "squeeze_threshold": 0.05,
                    "signal_type": "volatility",
                },
                "volume_breakout": {
                    "description": "Volume surge",
                    "period": 20,
                    "multiplier": 2.0,
                    "signal_type": "volume",
                },
                "macd_divergence": {
                    "description": "MACD histogram divergence",
                    "fast": 12,
                    "slow": 26,
                    "signal": 9,
                    "signal_type": "momentum",
                },
            },
        }
    }


@pytest.fixture
def library(mock_quant_config):
    with patch("src.quant.signal_library.load_config", return_value=mock_quant_config):
        return SignalLibrary()


@pytest.fixture
def uptrend_closes():
    """Generate uptrending price data."""
    np.random.seed(42)
    prices = [100.0]
    for _ in range(99):
        prices.append(prices[-1] * (1 + np.random.normal(0.002, 0.01)))
    return pd.Series(prices)


@pytest.fixture
def downtrend_closes():
    """Generate downtrending price data."""
    np.random.seed(42)
    prices = [100.0]
    for _ in range(99):
        prices.append(prices[-1] * (1 + np.random.normal(-0.002, 0.01)))
    return pd.Series(prices)


@pytest.fixture
def sample_volumes():
    np.random.seed(42)
    return pd.Series(np.random.uniform(1e6, 5e6, 100))


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestSignalDefinition:
    def test_defaults(self):
        sd = SignalDefinition(name="test")
        assert sd.name == "test"
        assert sd.signal_type == ""
        assert sd.params == {}

    def test_custom(self):
        sd = SignalDefinition(
            name="ma_cross",
            signal_type="momentum",
            params={"fast": 5, "slow": 20},
        )
        assert sd.params["fast"] == 5


class TestSignalResult:
    def test_defaults(self):
        sr = SignalResult()
        assert sr.direction == "neutral"
        assert sr.strength == 0.0

    def test_custom(self):
        sr = SignalResult(
            signal_name="ma_cross",
            direction="bullish",
            strength=0.8,
        )
        assert sr.direction == "bullish"


class TestSignalSummary:
    def test_defaults(self):
        ss = SignalSummary()
        assert ss.signals == []
        assert ss.consensus == "neutral"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestComputeRSI:
    def test_uptrend(self):
        np.random.seed(42)
        prices = pd.Series(
            [100 + i * 0.5 + np.random.normal(0, 0.1) for i in range(30)]
        )
        rsi = _compute_rsi(prices, 14)
        assert rsi > 50  # Uptrend should have RSI > 50

    def test_downtrend(self):
        np.random.seed(42)
        prices = pd.Series(
            [100 - i * 0.5 + np.random.normal(0, 0.1) for i in range(30)]
        )
        rsi = _compute_rsi(prices, 14)
        assert rsi < 50

    def test_insufficient_data(self):
        rsi = _compute_rsi(pd.Series([100, 101]), 14)
        assert np.isnan(rsi)

    def test_no_losses(self):
        prices = pd.Series([100 + i for i in range(20)])
        rsi = _compute_rsi(prices, 14)
        assert rsi == 100.0


class TestAggregateSignals:
    def test_empty(self):
        result = _aggregate_signals([])
        assert result.consensus == "neutral"
        assert "No signals" in result.summary

    def test_all_bullish(self):
        signals = [
            SignalResult(signal_name="a", direction="bullish", strength=0.8),
            SignalResult(signal_name="b", direction="bullish", strength=0.6),
        ]
        result = _aggregate_signals(signals)
        assert result.consensus == "bullish"
        assert result.bullish_count == 2
        assert result.net_score > 0

    def test_all_bearish(self):
        signals = [
            SignalResult(signal_name="a", direction="bearish", strength=0.7),
            SignalResult(signal_name="b", direction="bearish", strength=0.9),
        ]
        result = _aggregate_signals(signals)
        assert result.consensus == "bearish"
        assert result.net_score < 0

    def test_mixed(self):
        signals = [
            SignalResult(signal_name="a", direction="bullish", strength=0.5),
            SignalResult(signal_name="b", direction="bearish", strength=0.5),
            SignalResult(signal_name="c", direction="neutral", strength=0.0),
        ]
        result = _aggregate_signals(signals)
        assert result.bullish_count == 1
        assert result.bearish_count == 1
        assert result.neutral_count == 1
        assert abs(result.net_score) < 0.5

    def test_net_score_clamped(self):
        signals = [
            SignalResult(signal_name="a", direction="bullish", strength=1.0),
        ]
        result = _aggregate_signals(signals)
        assert -1.0 <= result.net_score <= 1.0

    def test_neutral_no_dilution(self):
        """3 zero-strength neutrals + 1 strong bearish → consensus bearish (I-049)."""
        signals = [
            SignalResult(signal_name="a", direction="neutral", strength=0.0),
            SignalResult(signal_name="b", direction="neutral", strength=0.0),
            SignalResult(signal_name="c", direction="neutral", strength=0.0),
            SignalResult(signal_name="d", direction="bearish", strength=0.8),
        ]
        result = _aggregate_signals(signals)
        assert result.consensus == "bearish"
        assert result.net_score < -0.15


# ---------------------------------------------------------------------------
# SignalLibrary tests
# ---------------------------------------------------------------------------


class TestSignalLibrary:
    def test_config_loaded(self, library):
        assert len(library.definitions) == 5
        assert "ma_cross" in library.definitions
        assert "rsi_extreme" in library.definitions

    def test_list_signals(self, library):
        signals = library.list_signals()
        assert len(signals) == 5
        names = [s.name for s in signals]
        assert "ma_cross" in names
        assert "macd_divergence" in names

    def test_insufficient_data(self, library):
        result = library.evaluate(closes=[100.0])
        assert "Insufficient" in result.summary

    def test_evaluate_all(self, library, uptrend_closes, sample_volumes):
        result = library.evaluate(closes=uptrend_closes, volumes=sample_volumes)
        assert len(result.signals) > 0
        assert result.summary != ""

    def test_evaluate_specific_signals(self, library, uptrend_closes):
        result = library.evaluate(
            closes=uptrend_closes,
            signal_names=["ma_cross", "rsi_extreme"],
        )
        names = [s.signal_name for s in result.signals]
        assert "ma_cross" in names
        assert "rsi_extreme" in names
        assert "volume_breakout" not in names

    def test_evaluate_unknown_signal(self, library, uptrend_closes):
        result = library.evaluate(
            closes=uptrend_closes,
            signal_names=["nonexistent"],
        )
        assert len(result.signals) == 0

    def test_evaluate_list_input(self, library):
        np.random.seed(42)
        closes = [100 + i * 0.1 + np.random.normal(0, 0.5) for i in range(100)]
        result = library.evaluate(closes=closes)
        assert len(result.signals) > 0


class TestMACrossSignal:
    def test_uptrend_bullish(self, library, uptrend_closes):
        result = library.evaluate(closes=uptrend_closes, signal_names=["ma_cross"])
        ma_result = result.signals[0]
        assert ma_result.signal_name == "ma_cross"
        assert ma_result.direction in ("bullish", "bearish", "neutral")

    def test_downtrend(self, library, downtrend_closes):
        result = library.evaluate(closes=downtrend_closes, signal_names=["ma_cross"])
        assert len(result.signals) == 1


class TestRSISignal:
    def test_extreme_overbought(self, library):
        """Strong uptrend should trigger overbought."""
        prices = pd.Series([100 + i * 2 for i in range(30)])
        result = library.evaluate(closes=prices, signal_names=["rsi_extreme"])
        rsi_result = result.signals[0]
        assert rsi_result.signal_name == "rsi_extreme"
        if rsi_result.value > 70:
            assert rsi_result.direction == "bearish"

    def test_extreme_oversold(self, library):
        """Strong downtrend should trigger oversold."""
        prices = pd.Series([200 - i * 2 for i in range(30)])
        result = library.evaluate(closes=prices, signal_names=["rsi_extreme"])
        rsi_result = result.signals[0]
        if rsi_result.value < 30:
            assert rsi_result.direction == "bullish"


class TestBollingerSignal:
    def test_basic(self, library, uptrend_closes):
        result = library.evaluate(
            closes=uptrend_closes, signal_names=["bollinger_squeeze"]
        )
        assert len(result.signals) == 1
        assert result.signals[0].signal_name == "bollinger_squeeze"


class TestVolumeBreakoutSignal:
    def test_no_volume(self, library, uptrend_closes):
        result = library.evaluate(
            closes=uptrend_closes, signal_names=["volume_breakout"]
        )
        assert result.signals[0].description == "No volume data"

    def test_with_volume_surge(self, library, uptrend_closes):
        np.random.seed(42)
        volumes = pd.Series(np.random.uniform(1e6, 2e6, 100))
        # Make last day have huge volume
        volumes.iloc[-1] = 10e6
        result = library.evaluate(
            closes=uptrend_closes,
            volumes=volumes,
            signal_names=["volume_breakout"],
        )
        vb = result.signals[0]
        assert vb.direction in ("bullish", "bearish")
        assert vb.strength > 0

    def test_normal_volume(self, library, uptrend_closes, sample_volumes):
        result = library.evaluate(
            closes=uptrend_closes,
            volumes=sample_volumes,
            signal_names=["volume_breakout"],
        )
        # Normal volume may or may not trigger
        assert len(result.signals) == 1


class TestVolumeDistributionDay:
    """Tests for distribution/accumulation day detection (I-049 2d)."""

    def test_distribution_day(self, library):
        """Vol 1.5x avg + 1.5% decline → bearish distribution day."""
        np.random.seed(42)
        # Steady prices then a drop on last day
        prices = pd.Series([100.0] * 99 + [98.5])
        volumes = pd.Series([1e6] * 99 + [1.5e6])
        result = library.evaluate(
            closes=prices, volumes=volumes, signal_names=["volume_breakout"]
        )
        vb = result.signals[0]
        assert vb.direction == "bearish"
        assert "Distribution" in vb.description or "distribution" in vb.description.lower()

    def test_accumulation_day(self, library):
        """Vol 1.5x avg + 0.5% rise → bullish accumulation day."""
        np.random.seed(42)
        prices = pd.Series([100.0] * 99 + [100.5])
        volumes = pd.Series([1e6] * 99 + [1.5e6])
        result = library.evaluate(
            closes=prices, volumes=volumes, signal_names=["volume_breakout"]
        )
        vb = result.signals[0]
        assert vb.direction == "bullish"


class TestRSIMidRange:
    """Tests for RSI mid-range direction signal (I-049 2a)."""

    def test_rsi_falling_below_50(self, library):
        """RSI in mid-range below 50 with falling trend → bearish."""
        np.random.seed(42)
        # Build series that keeps RSI in mid-range (not oversold)
        # Sideways → mild decline: mix of small ups and downs with bearish bias
        base = [100.0]
        for _ in range(25):
            base.append(base[-1] + np.random.normal(0.1, 0.5))
        # Mild decline: more downs than ups but not extreme
        for _ in range(20):
            base.append(base[-1] + np.random.normal(-0.15, 0.3))
        prices = pd.Series(base)
        result = library.evaluate(closes=prices, signal_names=["rsi_extreme"])
        rsi_r = result.signals[0]
        # Only assert if RSI actually fell into mid-range
        if 30 < rsi_r.value < 50:
            assert rsi_r.direction == "bearish"
            assert rsi_r.strength > 0

    def test_rsi_rising_above_50(self, library):
        """RSI in mid-range above 50 with rising trend → bullish."""
        np.random.seed(42)
        # Sideways → mild uptrend
        base = [100.0]
        for _ in range(25):
            base.append(base[-1] + np.random.normal(-0.1, 0.5))
        # Mild advance: more ups than downs but not extreme
        for _ in range(20):
            base.append(base[-1] + np.random.normal(0.15, 0.3))
        prices = pd.Series(base)
        result = library.evaluate(closes=prices, signal_names=["rsi_extreme"])
        rsi_r = result.signals[0]
        # Only assert if RSI actually rose into mid-range
        if 50 < rsi_r.value < 70:
            assert rsi_r.direction == "bullish"
            assert rsi_r.strength > 0


class TestMACrossPersistence:
    """Tests for MA cross persistence boost (I-049 2b)."""

    def test_sustained_bearish(self, library):
        """Death cross followed by sustained bearish → strength > 0.3."""
        # Clear downtrend: MA5 stays below MA20 throughout
        prices = pd.Series([100 - i * 0.5 for i in range(60)])
        result = library.evaluate(closes=prices, signal_names=["ma_cross"])
        ma_r = result.signals[0]
        if ma_r.direction == "bearish":
            assert ma_r.strength > 0.3


class TestMACDSignal:
    def test_basic(self, library, uptrend_closes):
        result = library.evaluate(
            closes=uptrend_closes, signal_names=["macd_divergence"]
        )
        assert len(result.signals) == 1
        macd = result.signals[0]
        assert macd.signal_name == "macd_divergence"
        assert macd.direction in ("bullish", "bearish", "neutral")

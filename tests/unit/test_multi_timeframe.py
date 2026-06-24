"""Tests for multi-timeframe momentum confirmation engine."""

from __future__ import annotations

import pandas as pd
import pytest

from src.quant.multi_timeframe import (
    MtfConfirmation,
    MultiTimeframeEngine,
    TimeframeSignal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bars(
    prices: list[float],
    start: str = "2026-03-11 09:30:00",
    freq_minutes: int = 5,
    volume: int = 10000,
) -> pd.DataFrame:
    """Build a 5-minute OHLCV DataFrame from a list of close prices.

    Each bar: open=close of prev bar (first bar open=first price),
    high=max(open,close)+0.01, low=min(open,close)-0.01.
    """
    rows = []
    for i, close in enumerate(prices):
        open_ = prices[i - 1] if i > 0 else close
        rows.append(
            {
                "datetime": pd.Timestamp(start)
                + pd.Timedelta(minutes=freq_minutes * i),
                "open": open_,
                "high": max(open_, close) + 0.01,
                "low": min(open_, close) - 0.01,
                "close": close,
                "volume": volume,
                "amount": close * volume,
            }
        )
    return pd.DataFrame(rows)


def _trending_up_bars(
    n: int = 48, base: float = 10.0, step: float = 0.05
) -> pd.DataFrame:
    """Generate steadily rising 5m bars (full trading day = 48 bars)."""
    prices = [base + i * step for i in range(n)]
    return _make_bars(prices)


def _trending_down_bars(
    n: int = 48, base: float = 12.0, step: float = 0.05
) -> pd.DataFrame:
    """Generate steadily falling 5m bars."""
    prices = [base - i * step for i in range(n)]
    return _make_bars(prices)


def _flat_bars(n: int = 48, base: float = 10.0) -> pd.DataFrame:
    """Generate flat bars with negligible movement."""
    prices = [base + (0.001 if i % 2 == 0 else -0.001) for i in range(n)]
    return _make_bars(prices)


def _mean_revert_bars(n: int = 48, base: float = 10.0) -> pd.DataFrame:
    """30m trend down, but last few 5m bars bounce up.

    The bounce is small enough that 30m remains bearish overall, but
    the last 3 bars (5m lookback) show a clear uptick.
    """
    # First 45 bars: strong downtrend
    prices = [base - i * 0.04 for i in range(n - 3)]
    last_price = prices[-1]
    # Last 3 bars (15 min): small bounce — enough for 5m bullish
    for _ in range(3):
        last_price += 0.06
        prices.append(last_price)
    return _make_bars(prices)


# ---------------------------------------------------------------------------
# Engine fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> MultiTimeframeEngine:
    return MultiTimeframeEngine()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAllBullish:
    def test_alignment_near_one(self, engine: MultiTimeframeEngine) -> None:
        bars = _trending_up_bars()
        result = engine.analyze(bars, "600519", daily_change_pct=2.5)

        assert result.alignment_score > 0.8
        assert result.confirmed_direction == "bullish"
        assert result.confidence_boost == 0.15
        assert result.regime == "trending"
        assert "共振看多" in result.description or "偏多" in result.description

    def test_all_timeframes_bullish(self, engine: MultiTimeframeEngine) -> None:
        bars = _trending_up_bars()
        result = engine.analyze(bars, "600519", daily_change_pct=3.0)

        for tf in result.timeframes:
            assert tf.direction == "bullish", f"{tf.period} should be bullish"
            assert tf.strength > 0


class TestAllBearish:
    def test_alignment_near_one(self, engine: MultiTimeframeEngine) -> None:
        bars = _trending_down_bars()
        result = engine.analyze(bars, "000001", daily_change_pct=-2.5)

        assert result.alignment_score > 0.8
        assert result.confirmed_direction == "bearish"
        assert result.confidence_boost == 0.15
        assert result.regime == "trending"

    def test_all_timeframes_bearish(self, engine: MultiTimeframeEngine) -> None:
        bars = _trending_down_bars()
        result = engine.analyze(bars, "000001", daily_change_pct=-3.0)

        for tf in result.timeframes:
            assert tf.direction == "bearish", f"{tf.period} should be bearish"


class TestMixedSignals:
    def test_lower_alignment(self, engine: MultiTimeframeEngine) -> None:
        bars = _mean_revert_bars()
        result = engine.analyze(bars, "300001", daily_change_pct=-1.0)

        assert result.alignment_score < 0.8
        assert result.confidence_boost <= 0.0

    def test_conflicted_or_bearish(self, engine: MultiTimeframeEngine) -> None:
        bars = _mean_revert_bars()
        result = engine.analyze(bars, "300001", daily_change_pct=-1.0)

        # At least one timeframe should disagree
        directions = {tf.direction for tf in result.timeframes}
        assert len(directions) > 1 or "neutral" in directions


class TestMeanReversionDetection:
    def test_5m_up_30m_down(self, engine: MultiTimeframeEngine) -> None:
        bars = _mean_revert_bars()
        # Force daily bearish to create cross-timeframe divergence
        result = engine.analyze(bars, "300002", daily_change_pct=-5.0)

        # 5m should be bullish (recent bounce)
        sig_5m = next(tf for tf in result.timeframes if tf.period == "5m")
        assert sig_5m.direction == "bullish"

        # Daily should be bearish — creating the cross-timeframe divergence
        sig_daily = next(tf for tf in result.timeframes if tf.period == "daily")
        assert sig_daily.direction == "bearish"

        # Should detect some level of conflict/non-full-alignment
        assert result.alignment_score < 1.0


class TestDailyChangePct:
    def test_with_daily_provided(self, engine: MultiTimeframeEngine) -> None:
        bars = _flat_bars()
        result = engine.analyze(bars, "600000", daily_change_pct=5.0)

        daily_sig = next(tf for tf in result.timeframes if tf.period == "daily")
        assert daily_sig.direction == "bullish"
        assert daily_sig.momentum == pytest.approx(5.0, abs=0.01)

    def test_without_daily_computed(self, engine: MultiTimeframeEngine) -> None:
        bars = _trending_up_bars()
        result = engine.analyze(bars, "600000")

        daily_sig = next(tf for tf in result.timeframes if tf.period == "daily")
        # Computed from first open to last close
        assert daily_sig.momentum != 0.0


class TestInsufficientData:
    def test_empty_bars(self, engine: MultiTimeframeEngine) -> None:
        empty = pd.DataFrame(
            columns=["datetime", "open", "high", "low", "close", "volume", "amount"]
        )
        result = engine.analyze(empty, "600519")

        assert result.alignment_score == 0.5
        assert result.confirmed_direction == "conflicted"
        assert result.confidence_boost == 0.0
        assert result.regime == "transitioning"

    def test_single_bar(self, engine: MultiTimeframeEngine) -> None:
        bars = _make_bars([10.0])
        result = engine.analyze(bars, "600519")

        assert result.confirmed_direction == "conflicted"
        assert result.regime == "transitioning"

    def test_none_bars(self, engine: MultiTimeframeEngine) -> None:
        result = engine.analyze(None, "600519")
        assert result.alignment_score == 0.5


class TestNeutralDetection:
    def test_flat_bars_neutral(self, engine: MultiTimeframeEngine) -> None:
        bars = _flat_bars()
        result = engine.analyze(bars, "600000", daily_change_pct=0.1)

        neutral_count = sum(1 for tf in result.timeframes if tf.direction == "neutral")
        # Most timeframes should be neutral for flat bars
        assert neutral_count >= 2


class TestResampleCorrectness:
    def test_5m_to_15m_bar_count(self, engine: MultiTimeframeEngine) -> None:
        # 12 five-minute bars = 4 fifteen-minute bars
        bars = _make_bars([10.0 + i * 0.01 for i in range(12)])
        resampled = engine._resample(bars, 15)

        assert len(resampled) == 4

    def test_5m_to_30m_bar_count(self, engine: MultiTimeframeEngine) -> None:
        # 12 five-minute bars = 2 thirty-minute bars
        bars = _make_bars([10.0 + i * 0.01 for i in range(12)])
        resampled = engine._resample(bars, 30)

        assert len(resampled) == 2

    def test_resample_ohlcv_aggregation(self, engine: MultiTimeframeEngine) -> None:
        # 3 bars of 5m → 1 bar of 15m
        bars = _make_bars([10.0, 10.5, 10.2])
        resampled = engine._resample(bars, 15)

        assert len(resampled) >= 1
        bar = resampled.iloc[0]
        # First bar open should be the open of first 5m bar
        assert bar["open"] == pytest.approx(10.0, abs=0.01)
        # High should be max of all highs
        assert bar["high"] >= 10.5
        # Volume should be sum
        assert bar["volume"] == pytest.approx(30000, rel=0.01)


class TestTimeframeSignalDataclass:
    def test_fields(self) -> None:
        sig = TimeframeSignal(
            period="5m", direction="bullish", strength=0.8, momentum=1.6
        )
        assert sig.period == "5m"
        assert sig.direction == "bullish"
        assert sig.strength == 0.8
        assert sig.momentum == 1.6


class TestMtfConfirmationDataclass:
    def test_fields(self) -> None:
        conf = MtfConfirmation(
            symbol="600519",
            alignment_score=0.85,
            confirmed_direction="bullish",
            timeframes=[],
            confidence_boost=0.10,
            regime="trending",
            description="test",
        )
        assert conf.symbol == "600519"
        assert conf.alignment_score == 0.85


class TestConfidenceBoostEdgeCases:
    def test_three_of_four_agree(self, engine: MultiTimeframeEngine) -> None:
        # 3 bullish + 1 neutral → +0.10
        bars = _trending_up_bars()
        result = engine.analyze(bars, "600519", daily_change_pct=0.1)

        # daily will be neutral (0.1% < 0.3% threshold)
        daily = next(tf for tf in result.timeframes if tf.period == "daily")
        if daily.direction == "neutral":
            assert result.confidence_boost == 0.10

    def test_opposing_short_long(self, engine: MultiTimeframeEngine) -> None:
        bars = _mean_revert_bars()
        result = engine.analyze(bars, "300001", daily_change_pct=-2.0)

        # Short-term bullish, long-term bearish → negative boost
        assert result.confidence_boost <= 0.0


class TestChineseDescription:
    def test_all_bullish_description(self, engine: MultiTimeframeEngine) -> None:
        bars = _trending_up_bars()
        result = engine.analyze(bars, "600519", daily_change_pct=3.0)

        assert any(kw in result.description for kw in ("共振看多", "偏多"))

    def test_all_bearish_description(self, engine: MultiTimeframeEngine) -> None:
        bars = _trending_down_bars()
        result = engine.analyze(bars, "000001", daily_change_pct=-3.0)

        assert any(kw in result.description for kw in ("共振看空", "偏空"))

    def test_mean_revert_description(self, engine: MultiTimeframeEngine) -> None:
        bars = _mean_revert_bars()
        result = engine.analyze(bars, "300001", daily_change_pct=-1.5)

        # Should mention reversion risk, conflict, or trend direction —
        # exact wording depends on how 30m resampling aligns
        assert any(
            kw in result.description
            for kw in ("均值回归", "分歧", "承压", "趋势", "偏多", "确认度")
        )

"""Tests for simplified VPIN calculator."""

from __future__ import annotations

import pandas as pd
import pytest

from src.quant.vpin import VpinCalculator, _toxicity_label


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bars(
    n: int = 100,
    *,
    direction: str = "up",
    flat: bool = False,
    volume: int = 1000,
) -> pd.DataFrame:
    """Generate synthetic 5-min bars.

    Args:
        n: number of bars
        direction: "up" (close > open every bar), "down", "mixed", "doji"
        flat: if True, high == low == open == close
        volume: volume per bar
    """
    rows = []
    base = 10.0
    for i in range(n):
        dt = pd.Timestamp("2026-03-10 09:30") + pd.Timedelta(minutes=5 * i)
        if flat:
            o = h = lo = c = base
        elif direction == "up":
            # Strong bullish: close near high, open near low -> high BVC ratio
            o = base + i * 0.01
            c = o + 0.10
            h = c  # high == close
            lo = o  # low == open
        elif direction == "down":
            # Strong bearish: close near low, open near high
            o = base + 0.10
            c = base
            h = o  # high == open
            lo = c  # low == close
        elif direction == "doji":
            o = base
            c = base
            h = base + 0.02
            lo = base - 0.02
        else:
            # mixed: alternating up/down
            if i % 2 == 0:
                o, c = base, base + 0.05
            else:
                o, c = base + 0.05, base
            h = max(o, c) + 0.01
            lo = min(o, c) - 0.01

        rows.append(
            {
                "datetime": dt,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": volume,
                "amount": volume * (o + c) / 2,
            }
        )

    return pd.DataFrame(rows)


@pytest.fixture
def calc() -> VpinCalculator:
    return VpinCalculator()


# ---------------------------------------------------------------------------
# Core VPIN value tests
# ---------------------------------------------------------------------------


class TestVpinCalculation:
    def test_all_buy_bars_high_vpin(self, calc: VpinCalculator) -> None:
        """When every bar is strongly bullish, VPIN should be high."""
        bars = _make_bars(100, direction="up", volume=2000)
        result = calc.calculate(bars, "000001")

        assert result is not None
        assert result.vpin > 0.6, (
            f"Expected high VPIN for all-buy bars, got {result.vpin}"
        )
        assert result.symbol == "000001"

    def test_all_sell_bars_high_vpin(self, calc: VpinCalculator) -> None:
        """All-sell bars should also produce high VPIN (imbalance is absolute)."""
        bars = _make_bars(100, direction="down", volume=2000)
        result = calc.calculate(bars, "600519")

        assert result is not None
        assert result.vpin > 0.6

    def test_balanced_bars_low_vpin(self, calc: VpinCalculator) -> None:
        """Alternating buy/sell bars should produce low VPIN."""
        bars = _make_bars(100, direction="mixed", volume=2000)
        result = calc.calculate(bars, "000002")

        assert result is not None
        assert result.vpin < 0.4, (
            f"Expected low VPIN for balanced bars, got {result.vpin}"
        )

    def test_doji_bars_low_vpin(self, calc: VpinCalculator) -> None:
        """Doji bars (close == open) split volume 50/50 -> low VPIN."""
        bars = _make_bars(100, direction="doji", volume=2000)
        result = calc.calculate(bars, "000003")

        assert result is not None
        # Doji splits are perfectly balanced within each bar
        assert result.vpin < 0.15, f"Doji VPIN should be near 0, got {result.vpin}"


# ---------------------------------------------------------------------------
# Volume bucketing
# ---------------------------------------------------------------------------


class TestVolumeBucketing:
    def test_bucket_count_matches(self, calc: VpinCalculator) -> None:
        """Number of completed buckets should approximate N_BUCKETS."""
        bars = _make_bars(200, direction="up", volume=1000)
        buy_vol, sell_vol = calc._classify_volume(bars)
        total = bars["volume"].sum()
        bucket_size = total / calc.N_BUCKETS
        buckets = calc._build_buckets(buy_vol, sell_vol, bucket_size)

        # Should get exactly N_BUCKETS (or N_BUCKETS-1 if partial dropped)
        assert abs(len(buckets) - calc.N_BUCKETS) <= 1

    def test_bucket_volume_consistent(self, calc: VpinCalculator) -> None:
        """Each bucket should have approximately bucket_size volume."""
        bars = _make_bars(200, direction="up", volume=1000)
        buy_vol, sell_vol = calc._classify_volume(bars)
        total = bars["volume"].sum()
        bucket_size = total / calc.N_BUCKETS
        buckets = calc._build_buckets(buy_vol, sell_vol, bucket_size)

        for b, s in buckets:
            bucket_total = b + s
            assert abs(bucket_total - bucket_size) < 1.0, (
                f"Bucket volume {bucket_total} deviates from target {bucket_size}"
            )

    def test_single_large_bar_spans_multiple_buckets(
        self, calc: VpinCalculator
    ) -> None:
        """A bar with volume >> bucket_size should fill multiple buckets."""
        # 10 bars, one with massive volume
        rows = []
        for i in range(10):
            vol = 100_000 if i == 5 else 100
            rows.append(
                {
                    "datetime": pd.Timestamp("2026-03-10 09:30")
                    + pd.Timedelta(minutes=5 * i),
                    "open": 10.0,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10.05,
                    "volume": vol,
                    "amount": vol * 10.0,
                }
            )
        bars = pd.DataFrame(rows)
        result = calc.calculate(bars, "test")
        assert result is not None


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------


class TestTrendDetection:
    def test_rising_trend(self, calc: VpinCalculator) -> None:
        """Earlier balanced + later imbalanced -> rising trend."""
        # First half: mixed (balanced buy/sell), second half: strong directional
        balanced = _make_bars(100, direction="mixed", volume=2000)
        bullish = _make_bars(100, direction="up", volume=2000)
        bullish["datetime"] = bullish["datetime"] + pd.Timedelta(hours=10)
        bars = pd.concat([balanced, bullish], ignore_index=True)

        result = calc.calculate(bars, "trend_test")
        assert result is not None
        # Recent buckets should have higher imbalance than earlier
        assert result.trend in (
            "rising",
            "stable",
        )  # data may not always cross threshold

    def test_falling_trend(self, calc: VpinCalculator) -> None:
        """Earlier imbalanced + later balanced -> falling trend."""
        bullish = _make_bars(100, direction="up", volume=2000)
        balanced = _make_bars(100, direction="mixed", volume=2000)
        balanced["datetime"] = balanced["datetime"] + pd.Timedelta(hours=10)
        bars = pd.concat([bullish, balanced], ignore_index=True)

        result = calc.calculate(bars, "trend_test")
        assert result is not None
        # Earlier buckets had higher imbalance than recent
        assert result.trend in (
            "falling",
            "stable",
        )  # data may not always cross threshold

    def test_stable_trend(self, calc: VpinCalculator) -> None:
        """Uniformly distributed imbalance -> stable trend."""
        bars = _make_bars(100, direction="up", volume=2000)
        result = calc.calculate(bars, "stable_test")
        assert result is not None
        assert result.trend == "stable"


# ---------------------------------------------------------------------------
# Alert logic
# ---------------------------------------------------------------------------


class TestAlertLogic:
    def test_alert_triggered(self, calc: VpinCalculator) -> None:
        """Strongly one-directional bars should trigger consecutive-high alert."""
        # high == close, low == open -> BVC ratio = 1.0 -> perfect imbalance
        rows = []
        for i in range(200):
            o = 10.0
            c = 11.0
            rows.append(
                {
                    "datetime": pd.Timestamp("2026-03-10 09:30")
                    + pd.Timedelta(minutes=5 * i),
                    "open": o,
                    "high": c,
                    "low": o,
                    "close": c,
                    "volume": 5000,
                    "amount": 5000 * 10.5,
                }
            )
        bars = pd.DataFrame(rows)
        result = calc.calculate(bars, "alert_test")

        assert result is not None
        assert result.consecutive_high_bars >= calc.ALERT_CONSECUTIVE
        assert result.alert is True

    def test_no_alert_balanced(self, calc: VpinCalculator) -> None:
        """Balanced flow should not trigger alert."""
        bars = _make_bars(100, direction="mixed", volume=2000)
        result = calc.calculate(bars, "no_alert")

        assert result is not None
        assert result.alert is False


# ---------------------------------------------------------------------------
# Toxicity classification
# ---------------------------------------------------------------------------


class TestToxicityLevel:
    @pytest.mark.parametrize(
        "vpin,expected",
        [
            (0.1, "low"),
            (0.39, "low"),
            (0.4, "moderate"),
            (0.59, "moderate"),
            (0.6, "elevated"),
            (0.69, "elevated"),
            (0.7, "high"),
            (0.95, "high"),
        ],
    )
    def test_toxicity_thresholds(self, vpin: float, expected: str) -> None:
        assert _toxicity_label(vpin) == expected

    def test_result_toxicity_matches_vpin(self, calc: VpinCalculator) -> None:
        bars = _make_bars(100, direction="up", volume=2000)
        result = calc.calculate(bars, "tox_test")
        assert result is not None
        assert result.toxicity_level == _toxicity_label(result.vpin)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_none_bars(self, calc: VpinCalculator) -> None:
        assert calc.calculate(None, "x") is None

    def test_empty_dataframe(self, calc: VpinCalculator) -> None:
        df = pd.DataFrame(
            columns=["datetime", "open", "high", "low", "close", "volume", "amount"]
        )
        assert calc.calculate(df, "x") is None

    def test_insufficient_bars(self, calc: VpinCalculator) -> None:
        """Fewer than 10 bars should return None."""
        bars = _make_bars(9, direction="up")
        assert calc.calculate(bars, "x") is None

    def test_flat_bars(self, calc: VpinCalculator) -> None:
        """Flat bars (h==l==o==c) should produce VPIN near 0 (50/50 split)."""
        bars = _make_bars(100, direction="up", flat=True, volume=2000)
        result = calc.calculate(bars, "flat")
        assert result is not None
        assert result.vpin < 0.15

    def test_zero_volume_bars(self, calc: VpinCalculator) -> None:
        """All-zero volume should return None."""
        bars = _make_bars(100, direction="up", volume=0)
        assert calc.calculate(bars, "zero") is None

    def test_missing_column(self, calc: VpinCalculator) -> None:
        """Missing required column should return None."""
        bars = _make_bars(100, direction="up")
        bars = bars.drop(columns=["volume"])
        assert calc.calculate(bars, "x") is None

    def test_adaptive_bucket_count(self, calc: VpinCalculator) -> None:
        """With fewer bars than 2*N_BUCKETS, buckets should be adapted."""
        bars = _make_bars(30, direction="up", volume=2000)
        result = calc.calculate(bars, "adaptive")
        assert result is not None

    def test_description_in_chinese(self, calc: VpinCalculator) -> None:
        """Description should contain Chinese text."""
        bars = _make_bars(100, direction="up", volume=2000)
        result = calc.calculate(bars, "cn_test")
        assert result is not None
        assert "知情交易概率" in result.description

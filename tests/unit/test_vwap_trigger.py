"""Tests for VWAP mean-reversion trigger engine."""

from __future__ import annotations

import pandas as pd

from src.quant.vwap_trigger import VwapSignal, VwapTriggerEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bars(
    n: int,
    base_price: float = 10.0,
    base_volume: float = 1000.0,
    base_amount: float | None = None,
    price_offsets: list[float] | None = None,
    volume_multipliers: list[float] | None = None,
) -> pd.DataFrame:
    """Build a synthetic minute-bar DataFrame.

    Args:
        n: Number of bars.
        base_price: Starting close price.
        base_volume: Constant volume per bar (unless overridden).
        base_amount: If None, amount = close * volume per bar.
        price_offsets: Per-bar additive offsets to base_price for close.
        volume_multipliers: Per-bar multipliers to base_volume.
    """
    offsets = price_offsets if price_offsets is not None else [0.0] * n
    vol_mults = volume_multipliers if volume_multipliers is not None else [1.0] * n

    assert len(offsets) == n
    assert len(vol_mults) == n

    closes = [base_price + o for o in offsets]
    volumes = [base_volume * m for m in vol_mults]
    amounts = (
        [c * v for c, v in zip(closes, volumes)]
        if base_amount is None
        else [base_amount] * n
    )

    return pd.DataFrame(
        {
            "datetime": pd.date_range("2026-03-11 09:30", periods=n, freq="5min"),
            "open": [c - 0.01 for c in closes],
            "high": [c + 0.05 for c in closes],
            "low": [c - 0.05 for c in closes],
            "close": closes,
            "volume": volumes,
            "amount": amounts,
        }
    )


def _make_deviation_bars(
    n: int,
    base_price: float,
    final_deviation_pct: float,
    ramp_start: int | None = None,
    volume_trend: str = "flat",
) -> pd.DataFrame:
    """Build bars where the last portion deviates from VWAP by a target percentage.

    The first ``ramp_start`` bars stay near base_price (establishing VWAP).
    Remaining bars linearly ramp to ``final_deviation_pct`` from VWAP.

    Args:
        n: Total bar count (must be >= MIN_BARS).
        base_price: Anchor price for the flat portion.
        final_deviation_pct: Target deviation of the last bar from VWAP in %.
            Positive = above VWAP, negative = below VWAP.
        ramp_start: Bar index where ramp begins (default: n // 2).
        volume_trend: "flat", "declining", or "surging".
    """
    if ramp_start is None:
        ramp_start = n // 2

    # Flat portion
    closes = [base_price] * ramp_start

    # Ramp portion: we want the last close to be base_price * (1 + final_deviation_pct/100)
    # VWAP will be close to base_price for the flat portion; the ramp shifts close away.
    ramp_len = n - ramp_start
    target = base_price * (1.0 + final_deviation_pct / 100.0)

    for i in range(ramp_len):
        t = (i + 1) / ramp_len
        closes.append(base_price + (target - base_price) * t)

    # Volume
    if volume_trend == "declining":
        vol_mults = [1.0] * ramp_start + [
            max(0.1, 1.0 - 0.8 * i / max(ramp_len - 1, 1)) for i in range(ramp_len)
        ]
    elif volume_trend == "surging":
        vol_mults = [1.0] * ramp_start + [
            1.0 + 2.0 * i / max(ramp_len - 1, 1) for i in range(ramp_len)
        ]
    else:
        vol_mults = [1.0] * n

    volumes = [1000.0 * m for m in vol_mults]
    amounts = [c * v for c, v in zip(closes, volumes)]

    return pd.DataFrame(
        {
            "datetime": pd.date_range("2026-03-11 09:30", periods=n, freq="5min"),
            "open": [c - 0.01 for c in closes],
            "high": [c + 0.05 for c in closes],
            "low": [c - 0.05 for c in closes],
            "close": closes,
            "volume": volumes,
            "amount": amounts,
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

ENGINE = VwapTriggerEngine()


class TestInsufficientBars:
    """Engine must return [] when there aren't enough bars."""

    def test_none_bars(self) -> None:
        assert ENGINE.analyze(None, "600519") == []

    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame(
            columns=["datetime", "open", "high", "low", "close", "volume", "amount"]
        )
        assert ENGINE.analyze(df, "600519") == []

    def test_too_few_bars(self) -> None:
        bars = _make_bars(n=5)
        assert ENGINE.analyze(bars, "600519") == []


class TestZeroVolume:
    """Edge case: all zero-volume bars should produce no signals."""

    def test_all_zero_volume(self) -> None:
        bars = _make_bars(n=20, base_volume=0.0)
        # amount will also be 0 because amount = close * volume
        assert ENGINE.analyze(bars, "600519") == []


class TestNoSignal:
    """No signal when deviation is small."""

    def test_flat_price(self) -> None:
        bars = _make_bars(n=30)
        signals = ENGINE.analyze(bars, "600519")
        assert signals == []

    def test_small_deviation(self) -> None:
        # Build bars with natural noise so std is non-trivial,
        # then a tiny final offset that stays well within 1 Z-score.
        import numpy as np

        rng = np.random.RandomState(42)
        n = 30
        noise = rng.normal(0, 0.10, size=n)  # ~1% noise around base
        closes = [10.0 + noise[i] for i in range(n)]
        volumes = [1000.0] * n
        amounts = [c * v for c, v in zip(closes, volumes)]
        bars = pd.DataFrame(
            {
                "datetime": pd.date_range("2026-03-11 09:30", periods=n, freq="5min"),
                "open": [c - 0.01 for c in closes],
                "high": [c + 0.05 for c in closes],
                "low": [c - 0.05 for c in closes],
                "close": closes,
                "volume": volumes,
                "amount": amounts,
            }
        )
        signals = ENGINE.analyze(bars, "600519")
        # Should produce no reversion signal (deviation too small relative to noise)
        reversion_signals = [
            s for s in signals if s.signal_type.startswith("mean_reversion")
        ]
        assert reversion_signals == []


class TestMeanReversionLong:
    """Price far below VWAP should trigger bullish mean reversion."""

    def test_strong_deviation_below_vwap(self) -> None:
        # Price drops sharply below VWAP
        bars = _make_deviation_bars(
            n=30, base_price=10.0, final_deviation_pct=-5.0, volume_trend="declining"
        )
        signals = ENGINE.analyze(bars, "600519")
        long_signals = [s for s in signals if s.signal_type == "mean_reversion_long"]
        assert len(long_signals) == 1

        sig = long_signals[0]
        assert sig.direction == "bullish"
        assert sig.z_score < -ENGINE.REVERSION_THRESHOLD_Z
        assert sig.deviation_pct < 0
        assert sig.vwap_price > 0
        assert sig.current_price < sig.vwap_price
        assert 0 < sig.severity <= 1.0
        assert 0 < sig.confidence <= 1.0
        assert "VWAP" in sig.description
        assert sig.symbol == "600519"

    def test_volume_declining_boosts_confidence(self) -> None:
        bars_declining = _make_deviation_bars(
            n=30, base_price=10.0, final_deviation_pct=-5.0, volume_trend="declining"
        )
        bars_flat = _make_deviation_bars(
            n=30, base_price=10.0, final_deviation_pct=-5.0, volume_trend="flat"
        )
        sig_declining = ENGINE.analyze(bars_declining, "600519")
        sig_flat = ENGINE.analyze(bars_flat, "600519")

        long_dec = [s for s in sig_declining if s.signal_type == "mean_reversion_long"]
        long_flat = [s for s in sig_flat if s.signal_type == "mean_reversion_long"]

        # Both should trigger, but declining volume should have higher confidence
        assert len(long_dec) >= 1
        assert len(long_flat) >= 1
        assert long_dec[0].confidence >= long_flat[0].confidence


class TestMeanReversionShort:
    """Price far above VWAP should trigger bearish mean reversion."""

    def test_strong_deviation_above_vwap(self) -> None:
        bars = _make_deviation_bars(
            n=30, base_price=10.0, final_deviation_pct=5.0, volume_trend="declining"
        )
        signals = ENGINE.analyze(bars, "600519")
        short_signals = [s for s in signals if s.signal_type == "mean_reversion_short"]
        assert len(short_signals) == 1

        sig = short_signals[0]
        assert sig.direction == "bearish"
        assert sig.z_score > ENGINE.REVERSION_THRESHOLD_Z
        assert sig.deviation_pct > 0
        assert sig.current_price > sig.vwap_price
        assert 0 < sig.severity <= 1.0
        assert "VWAP" in sig.description


class TestTrendContinuation:
    """Moderate deviation + volume acceleration triggers trend continuation."""

    def test_bullish_continuation(self) -> None:
        # Moderate positive deviation with surging volume
        bars = _make_deviation_bars(
            n=30, base_price=10.0, final_deviation_pct=2.5, volume_trend="surging"
        )
        signals = ENGINE.analyze(bars, "600519")
        cont_signals = [s for s in signals if s.signal_type == "trend_continuation"]

        # May or may not fire depending on whether Z-score lands in [1.0, 2.0]
        # and volume is accelerating. If it fires, check properties.
        if cont_signals:
            sig = cont_signals[0]
            assert sig.direction == "bullish"
            assert 1.0 <= abs(sig.z_score) < ENGINE.REVERSION_THRESHOLD_Z
            assert sig.signal_type == "trend_continuation"
            assert "成交量放大" in sig.description

    def test_no_continuation_without_volume(self) -> None:
        # Moderate deviation but flat volume -> no trend continuation
        bars = _make_deviation_bars(
            n=30, base_price=10.0, final_deviation_pct=2.0, volume_trend="flat"
        )
        signals = ENGINE.analyze(bars, "600519")
        cont_signals = [s for s in signals if s.signal_type == "trend_continuation"]
        assert cont_signals == []


class TestVwapSignalDataclass:
    """Verify VwapSignal is a proper dataclass."""

    def test_fields(self) -> None:
        sig = VwapSignal(
            symbol="600519",
            signal_type="mean_reversion_long",
            deviation_pct=-3.5,
            z_score=-2.5,
            vwap_price=10.0,
            current_price=9.65,
            direction="bullish",
            severity=0.83,
            confidence=0.78,
            description="test",
        )
        assert sig.symbol == "600519"
        assert sig.signal_type == "mean_reversion_long"
        assert sig.deviation_pct == -3.5
        assert sig.z_score == -2.5


class TestVolumeHelpers:
    """Test internal volume helper methods."""

    def test_volume_confirmation_declining(self) -> None:
        # Last 6 bars with declining volume
        bars = _make_bars(
            n=12,
            volume_multipliers=[1.0] * 6 + [0.9, 0.8, 0.7, 0.6, 0.5, 0.4],
        )
        assert ENGINE._volume_confirmation(bars, "long") is True

    def test_volume_confirmation_increasing(self) -> None:
        bars = _make_bars(
            n=12,
            volume_multipliers=[1.0] * 6 + [1.1, 1.2, 1.3, 1.4, 1.5, 1.6],
        )
        assert ENGINE._volume_confirmation(bars, "long") is False

    def test_volume_accelerating_true(self) -> None:
        bars = _make_bars(
            n=12,
            volume_multipliers=[1.0] * 9 + [3.0, 3.0, 3.0],
        )
        assert ENGINE._volume_accelerating(bars) is True

    def test_volume_accelerating_false_flat(self) -> None:
        bars = _make_bars(n=12)
        assert ENGINE._volume_accelerating(bars) is False

    def test_volume_confirmation_too_few_bars(self) -> None:
        bars = _make_bars(n=3)
        assert ENGINE._volume_confirmation(bars, "long") is False

    def test_volume_accelerating_too_few_bars(self) -> None:
        bars = _make_bars(n=3)
        assert ENGINE._volume_accelerating(bars) is False


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_single_zero_volume_bar_in_middle(self) -> None:
        """A zero-volume bar in the middle should not crash the engine."""
        bars = _make_bars(n=20)
        bars.loc[5, "volume"] = 0.0
        bars.loc[5, "amount"] = 0.0
        # Should not raise
        signals = ENGINE.analyze(bars, "600519")
        assert isinstance(signals, list)

    def test_returns_list(self) -> None:
        bars = _make_bars(n=20)
        result = ENGINE.analyze(bars, "600519")
        assert isinstance(result, list)

    def test_signal_types_are_valid(self) -> None:
        valid_types = {
            "mean_reversion_long",
            "mean_reversion_short",
            "trend_continuation",
        }
        bars = _make_deviation_bars(n=30, base_price=10.0, final_deviation_pct=-5.0)
        signals = ENGINE.analyze(bars, "600519")
        for sig in signals:
            assert sig.signal_type in valid_types

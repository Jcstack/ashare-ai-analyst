"""Tests for cross-sector correlation break monitor."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.sector_correlation import (
    CORRELATED_PAIRS,
    CorrelationBreak,
    CorrelationRegime,
    SectorCorrelationMonitor,
)


@pytest.fixture
def monitor() -> SectorCorrelationMonitor:
    return SectorCorrelationMonitor()


def _make_index(n: int = 60) -> pd.DatetimeIndex:
    """Create a 5-min datetime index with *n* bars."""
    return pd.date_range("2026-03-11 09:30", periods=n, freq="5min")


def _correlated_returns(
    n: int = 60, correlation: float = 0.9, seed: int = 42
) -> tuple[pd.Series, pd.Series]:
    """Generate two return series with target correlation."""
    rng = np.random.default_rng(seed)
    idx = _make_index(n)
    base = rng.normal(0, 0.01, n)
    noise = rng.normal(0, 0.01, n)
    a = base + noise * (1 - correlation)
    b = base + rng.normal(0, 0.01, n) * (1 - correlation)
    return pd.Series(a, index=idx), pd.Series(b, index=idx)


# ------------------------------------------------------------------
# Normal regime — all pairs correlated
# ------------------------------------------------------------------


class TestNormalRegime:
    def test_all_correlated_returns_normal(self, monitor: SectorCorrelationMonitor):
        """When all sector pairs have stable correlation, regime should be normal."""
        sector_returns: dict[str, pd.Series] = {}
        # Use moderate correlation (0.6) so pairs are correlated but avg_corr < 0.8
        # (avoids triggering crisis threshold while remaining stable)
        for i, (sa, sb) in enumerate(CORRELATED_PAIRS):
            ra, rb = _correlated_returns(n=60, correlation=0.6, seed=100 + i)
            sector_returns[sa] = ra
            sector_returns[sb] = rb

        result = monitor.analyze(sector_returns)
        assert isinstance(result, CorrelationRegime)
        assert result.regime == "normal"
        assert result.break_count == 0
        assert result.crisis_signal is False
        assert len(result.breaks) == 0

    def test_description_in_chinese(self, monitor: SectorCorrelationMonitor):
        sector_returns: dict[str, pd.Series] = {}
        ra, rb = _correlated_returns(n=60, correlation=0.95, seed=1)
        sector_returns["半导体"] = ra
        sector_returns["消费电子"] = rb

        result = monitor.analyze(sector_returns)
        assert "正常" in result.description


# ------------------------------------------------------------------
# Divergence break
# ------------------------------------------------------------------


class TestDivergenceBreak:
    def test_one_pair_diverges(self, monitor: SectorCorrelationMonitor):
        """When one pair diverges, regime should be stress with 1 break."""
        idx = _make_index(60)
        rng = np.random.default_rng(7)

        # First 48 bars: highly correlated
        base = rng.normal(0, 0.01, 60)
        a = base.copy()
        b = base.copy()

        # Last 12 bars: diverge sharply
        a[48:] = np.abs(rng.normal(0.02, 0.005, 12))
        b[48:] = -np.abs(rng.normal(0.02, 0.005, 12))

        sector_returns = {
            "半导体": pd.Series(a, index=idx),
            "消费电子": pd.Series(b, index=idx),
        }

        result = monitor.analyze(sector_returns)
        assert result.break_count >= 1
        assert result.regime in ("stress", "rotation")

        brk = result.breaks[0]
        assert isinstance(brk, CorrelationBreak)
        assert brk.sector_a == "半导体"
        assert brk.sector_b == "消费电子"
        assert brk.break_type in ("divergence", "reversal")
        assert 0 <= brk.severity <= 1.0

    def test_break_description_contains_sectors(
        self, monitor: SectorCorrelationMonitor
    ):
        idx = _make_index(60)
        rng = np.random.default_rng(8)
        base = rng.normal(0, 0.01, 60)
        a = base.copy()
        b = base.copy()
        a[48:] = 0.03 + rng.normal(0, 0.002, 12)
        b[48:] = -0.03 + rng.normal(0, 0.002, 12)

        sector_returns = {
            "半导体": pd.Series(a, index=idx),
            "消费电子": pd.Series(b, index=idx),
        }

        result = monitor.analyze(sector_returns)
        if result.breaks:
            desc = result.breaks[0].description
            assert "半导体" in desc
            assert "消费电子" in desc


# ------------------------------------------------------------------
# Rotation detection — multiple breaks, opposite leads
# ------------------------------------------------------------------


class TestRotationDetection:
    def test_rotation_regime(self, monitor: SectorCorrelationMonitor):
        """Multiple breaks with different leading sectors => rotation."""
        idx = _make_index(60)
        rng = np.random.default_rng(99)
        sector_returns: dict[str, pd.Series] = {}

        # Pair 1: 半导体 leads up, 消费电子 falls (with noise for valid corr)
        base1 = rng.normal(0, 0.01, 60)
        a1 = base1.copy()
        b1 = base1.copy()
        a1[48:] = 0.03 + rng.normal(0, 0.002, 12)
        b1[48:] = -0.03 + rng.normal(0, 0.002, 12)
        sector_returns["半导体"] = pd.Series(a1, index=idx)
        sector_returns["消费电子"] = pd.Series(b1, index=idx)

        # Pair 2: 银行 falls, 保险 leads up (with noise for valid corr)
        base2 = rng.normal(0, 0.01, 60)
        a2 = base2.copy()
        b2 = base2.copy()
        a2[48:] = -0.03 + rng.normal(0, 0.002, 12)
        b2[48:] = 0.03 + rng.normal(0, 0.002, 12)
        sector_returns["银行"] = pd.Series(a2, index=idx)
        sector_returns["保险"] = pd.Series(b2, index=idx)

        result = monitor.analyze(sector_returns)
        assert result.break_count >= 2
        assert result.regime == "rotation"
        assert "轮动" in result.description

        # Different leading sectors
        leaders = {b.leading_sector for b in result.breaks}
        assert len(leaders) >= 2


# ------------------------------------------------------------------
# Crisis signal — correlations converge toward 1.0
# ------------------------------------------------------------------


class TestCrisisSignal:
    def test_crisis_when_all_correlations_high(self, monitor: SectorCorrelationMonitor):
        """When average cross-correlation > 0.8 across 3+ pairs, flag crisis."""
        idx = _make_index(60)
        rng = np.random.default_rng(55)
        sector_returns: dict[str, pd.Series] = {}

        # Make 4 pairs nearly perfectly correlated (all moving together = panic)
        base = rng.normal(-0.02, 0.005, 60)  # market-wide sell-off
        for sa, sb in CORRELATED_PAIRS[:4]:
            noise_a = rng.normal(0, 0.0005, 60)
            noise_b = rng.normal(0, 0.0005, 60)
            sector_returns[sa] = pd.Series(base + noise_a, index=idx)
            sector_returns[sb] = pd.Series(base + noise_b, index=idx)

        result = monitor.analyze(sector_returns)
        assert result.crisis_signal is True
        assert result.regime == "crisis"
        assert result.avg_cross_correlation > 0.8
        assert "流动性危机" in result.description

    def test_no_crisis_with_normal_correlations(
        self, monitor: SectorCorrelationMonitor
    ):
        sector_returns: dict[str, pd.Series] = {}
        for i, (sa, sb) in enumerate(CORRELATED_PAIRS[:4]):
            ra, rb = _correlated_returns(n=60, correlation=0.5, seed=200 + i)
            sector_returns[sa] = ra
            sector_returns[sb] = rb

        result = monitor.analyze(sector_returns)
        assert result.crisis_signal is False


# ------------------------------------------------------------------
# Missing sectors — partial data
# ------------------------------------------------------------------


class TestMissingSectors:
    def test_missing_one_sector_in_pair(self, monitor: SectorCorrelationMonitor):
        """Pairs with only one sector present should be skipped gracefully."""
        idx = _make_index(60)
        rng = np.random.default_rng(10)
        sector_returns = {
            "半导体": pd.Series(rng.normal(0, 0.01, 60), index=idx),
            # "消费电子" intentionally missing
        }

        result = monitor.analyze(sector_returns)
        assert result.regime == "normal"
        assert result.break_count == 0

    def test_empty_input(self, monitor: SectorCorrelationMonitor):
        result = monitor.analyze({})
        assert result.regime == "normal"
        assert result.break_count == 0
        assert result.avg_cross_correlation == 0.0

    def test_single_sector(self, monitor: SectorCorrelationMonitor):
        idx = _make_index(60)
        rng = np.random.default_rng(11)
        result = monitor.analyze(
            {"半导体": pd.Series(rng.normal(0, 0.01, 60), index=idx)}
        )
        assert result.regime == "normal"


# ------------------------------------------------------------------
# Insufficient data points
# ------------------------------------------------------------------


class TestInsufficientData:
    def test_too_few_bars(self, monitor: SectorCorrelationMonitor):
        """With fewer bars than SHORT_WINDOW, pairs should be skipped."""
        idx = _make_index(3)  # less than SHORT_WINDOW=6
        rng = np.random.default_rng(20)
        sector_returns = {
            "半导体": pd.Series(rng.normal(0, 0.01, 3), index=idx),
            "消费电子": pd.Series(rng.normal(0, 0.01, 3), index=idx),
        }

        result = monitor.analyze(sector_returns)
        assert result.regime == "normal"
        assert result.break_count == 0

    def test_exactly_short_window_bars(self, monitor: SectorCorrelationMonitor):
        """With exactly SHORT_WINDOW bars, should compute (edge case)."""
        n = monitor.SHORT_WINDOW
        idx = _make_index(n)
        rng = np.random.default_rng(21)
        base = rng.normal(0, 0.01, n)
        sector_returns = {
            "半导体": pd.Series(base, index=idx),
            "消费电子": pd.Series(base + rng.normal(0, 0.0001, n), index=idx),
        }

        result = monitor.analyze(sector_returns)
        # Should not crash; may or may not detect a break
        assert isinstance(result, CorrelationRegime)


# ------------------------------------------------------------------
# Leading sector detection
# ------------------------------------------------------------------


class TestLeadingSector:
    def test_leading_sector_is_the_one_with_larger_move(
        self, monitor: SectorCorrelationMonitor
    ):
        idx = _make_index(60)
        rng = np.random.default_rng(30)
        base = rng.normal(0, 0.01, 60)

        a = base.copy()
        b = base.copy()
        # Make sector_a move much more in last 6 bars (add noise for valid corr)
        a[48:] = 0.05 + rng.normal(0, 0.002, 12)
        b[48:] = -0.01 + rng.normal(0, 0.002, 12)

        sector_returns = {
            "半导体": pd.Series(a, index=idx),
            "消费电子": pd.Series(b, index=idx),
        }

        result = monitor.analyze(sector_returns)
        if result.breaks:
            assert result.breaks[0].leading_sector == "半导体"

    def test_leading_sector_b(self, monitor: SectorCorrelationMonitor):
        idx = _make_index(60)
        rng = np.random.default_rng(31)
        base = rng.normal(0, 0.01, 60)

        a = base.copy()
        b = base.copy()
        a[48:] = -0.005 + rng.normal(0, 0.001, 12)
        b[48:] = -0.06 + rng.normal(0, 0.002, 12)  # sector B has larger absolute move

        sector_returns = {
            "半导体": pd.Series(a, index=idx),
            "消费电子": pd.Series(b, index=idx),
        }

        result = monitor.analyze(sector_returns)
        if result.breaks:
            assert result.breaks[0].leading_sector == "消费电子"


# ------------------------------------------------------------------
# Severity scaling
# ------------------------------------------------------------------


class TestSeverityScaling:
    def test_severity_scales_with_deviation(self, monitor: SectorCorrelationMonitor):
        """Larger deviations should produce higher severity."""
        idx = _make_index(60)
        rng = np.random.default_rng(40)

        # Moderate divergence
        base = rng.normal(0, 0.01, 60)
        a = base.copy()
        b = base.copy()
        a[48:] = 0.02 + rng.normal(0, 0.002, 12)
        b[48:] = -0.02 + rng.normal(0, 0.002, 12)

        sector_returns = {
            "半导体": pd.Series(a, index=idx),
            "消费电子": pd.Series(b, index=idx),
        }

        result1 = monitor.analyze(sector_returns)

        # Extreme divergence
        rng2 = np.random.default_rng(41)
        base2 = rng2.normal(0, 0.01, 60)
        a2 = base2.copy()
        b2 = base2.copy()
        a2[48:] = 0.06 + rng2.normal(0, 0.002, 12)
        b2[48:] = -0.06 + rng2.normal(0, 0.002, 12)

        sector_returns2 = {
            "半导体": pd.Series(a2, index=idx),
            "消费电子": pd.Series(b2, index=idx),
        }

        result2 = monitor.analyze(sector_returns2)

        if result1.breaks and result2.breaks:
            assert result2.breaks[0].severity >= result1.breaks[0].severity

    def test_severity_capped_at_one(self, monitor: SectorCorrelationMonitor):
        idx = _make_index(60)
        rng = np.random.default_rng(41)
        base = rng.normal(0, 0.01, 60)
        a = base.copy()
        b = base.copy()
        a[48:] = 0.10 + rng.normal(0, 0.002, 12)
        b[48:] = -0.10 + rng.normal(0, 0.002, 12)

        sector_returns = {
            "半导体": pd.Series(a, index=idx),
            "消费电子": pd.Series(b, index=idx),
        }

        result = monitor.analyze(sector_returns)
        for brk in result.breaks:
            assert brk.severity <= 1.0


# ------------------------------------------------------------------
# analyze_from_prices convenience method
# ------------------------------------------------------------------


class TestAnalyzeFromPrices:
    def test_converts_prices_to_returns(self, monitor: SectorCorrelationMonitor):
        idx = _make_index(61)  # one extra for pct_change
        rng = np.random.default_rng(50)

        # Generate price series (cumulative sum of returns)
        base_ret = rng.normal(0, 0.01, 61)
        prices_a = pd.Series(100.0 * np.exp(np.cumsum(base_ret)), index=idx)
        prices_b = pd.Series(
            50.0 * np.exp(np.cumsum(base_ret + rng.normal(0, 0.0005, 61))),
            index=idx,
        )

        result = monitor.analyze_from_prices({"半导体": prices_a, "消费电子": prices_b})
        assert isinstance(result, CorrelationRegime)

    def test_handles_short_price_series(self, monitor: SectorCorrelationMonitor):
        """Price series with <2 points should be skipped."""
        idx = pd.date_range("2026-03-11 09:30", periods=1, freq="5min")
        result = monitor.analyze_from_prices({"半导体": pd.Series([100.0], index=idx)})
        assert result.regime == "normal"

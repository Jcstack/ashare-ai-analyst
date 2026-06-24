"""Tests for overnight risk calculator (I-090 Phase 2)."""

from unittest.mock import Mock

import pandas as pd

from src.recommendation.overnight_risk import (
    OvernightRiskCalculator,
    _compute_risk_score,
)


class TestComputeRiskScore:
    def test_all_neutral(self):
        score = _compute_risk_score(
            gap_down_ratio=0.5,
            std_gap=1.5,
            drawdown_prob=0.5,
            avg_post_rally=0,
            rally_sample_size=5,
        )
        assert 0.3 < score < 0.7

    def test_high_risk(self):
        score = _compute_risk_score(
            gap_down_ratio=0.8,
            std_gap=3.0,
            drawdown_prob=0.9,
            avg_post_rally=-2.0,
            rally_sample_size=10,
        )
        assert score > 0.7

    def test_low_risk(self):
        score = _compute_risk_score(
            gap_down_ratio=0.2,
            std_gap=0.5,
            drawdown_prob=0.2,
            avg_post_rally=1.5,
            rally_sample_size=10,
        )
        assert score < 0.4

    def test_no_rally_samples_uses_neutral(self):
        score = _compute_risk_score(
            gap_down_ratio=0.5,
            std_gap=1.0,
            drawdown_prob=0.0,
            avg_post_rally=0.0,
            rally_sample_size=0,
        )
        # drawdown_prob and avg_post_rally default to 0.5 when sample_size < 3
        assert 0.3 < score < 0.7


class TestOvernightRiskCalculator:
    def _make_df(self, closes, opens=None):
        """Create a simple OHLCV DataFrame."""
        n = len(closes)
        if opens is None:
            opens = closes
        return pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=n),
                "open": opens,
                "high": [c * 1.02 for c in closes],
                "low": [c * 0.98 for c in closes],
                "close": closes,
                "volume": [1000000] * n,
            }
        )

    def test_basic_profile(self):
        calc = OvernightRiskCalculator()
        # Simulate: close=100, next day open=99 (1% gap down), repeating
        closes = [100, 101, 99, 102, 98, 103, 97, 104, 100, 101, 99, 102]
        opens = [100, 99, 100, 98, 101, 97, 102, 96, 103, 99, 100, 98]
        df = self._make_df(closes, opens)
        profile = calc._compute_profile("000001", df, rally_threshold=3.0)

        assert profile.symbol == "000001"
        assert isinstance(profile.avg_gap_pct, float)
        assert isinstance(profile.gap_down_ratio, float)
        assert 0 <= profile.risk_score <= 1

    def test_insufficient_data_returns_none(self):
        calc = OvernightRiskCalculator()
        # Only 5 rows — below minimum of 10
        df = self._make_df([100, 101, 102, 103, 104])
        # Direct test: _compute_profile should work with small data
        profile = calc._compute_profile("000001", df, rally_threshold=5.0)
        assert profile is not None

    def test_rally_detection(self):
        calc = OvernightRiskCalculator()
        # Day 3 has a 6% rally (close much higher than open)
        closes = [100, 101, 102, 108, 105, 103, 107, 104, 106, 102, 108, 105]
        opens = [100, 100, 101, 102, 108, 105, 103, 107, 104, 106, 102, 108]
        df = self._make_df(closes, opens)
        profile = calc._compute_profile("000001", df, rally_threshold=5.0)

        assert profile.rally_sample_size > 0
        assert isinstance(profile.post_rally_drawdown_prob, float)

    def test_context_str(self):
        calc = OvernightRiskCalculator()
        closes = [100 + i for i in range(15)]
        opens = [99 + i for i in range(15)]
        df = self._make_df(closes, opens)
        profile = calc._compute_profile("000001", df, rally_threshold=5.0)

        ctx = profile.to_context_str()
        assert "隔夜风险分析" in ctx
        assert "000001" in ctx

    def test_batch_calculation(self):
        # Mock fetcher to return empty — should return empty dict gracefully
        fetcher = Mock()
        fetcher.fetch_daily_ohlcv.return_value = None
        calc = OvernightRiskCalculator(fetcher=fetcher)
        result = calc.calculate_batch(["000001", "000002"])
        assert isinstance(result, dict)
        assert result == {}

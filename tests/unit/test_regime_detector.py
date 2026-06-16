"""Tests for regime detection engine.

Part of v15.0 Quant Core layer.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.quant.regime_detector import (
    RegimeDetector,
    RegimeReport,
    RegimeState,
    TransitionMatrix,
    _avg_regime_duration,
    _classify_regimes,
    _compute_transition_matrix,
    _percentile_rank,
    _regime_distribution,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_quant_config():
    return {
        "regime_detection": {
            "n_regimes": 3,
            "volatility_window_days": 10,
            "lookback_days": 252,
            "min_observations": 20,
            "regime_labels": {
                0: "low_volatility",
                1: "medium_volatility",
                2: "high_volatility",
            },
        }
    }


@pytest.fixture
def detector(mock_quant_config):
    with patch("src.quant.regime_detector.load_config", return_value=mock_quant_config):
        return RegimeDetector()


@pytest.fixture
def sample_returns():
    np.random.seed(42)
    return pd.Series(np.random.normal(0.001, 0.02, 200))


@pytest.fixture
def sample_dates():
    dates = pd.date_range("2025-01-01", periods=200, freq="B")
    return [d.strftime("%Y-%m-%d") for d in dates]


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestRegimeState:
    def test_defaults(self):
        rs = RegimeState()
        assert rs.regime_id == 0
        assert rs.volatility == 0.0

    def test_custom(self):
        rs = RegimeState(regime_id=2, regime_label="high_volatility", volatility=0.35)
        assert rs.regime_label == "high_volatility"


class TestTransitionMatrix:
    def test_defaults(self):
        tm = TransitionMatrix()
        assert tm.matrix == []

    def test_custom(self):
        tm = TransitionMatrix(
            matrix=[[0.8, 0.1, 0.1], [0.2, 0.6, 0.2], [0.1, 0.2, 0.7]],
            regime_labels={0: "low", 1: "med", 2: "high"},
        )
        assert len(tm.matrix) == 3
        assert abs(sum(tm.matrix[0]) - 1.0) < 1e-10


class TestRegimeReport:
    def test_defaults(self):
        rr = RegimeReport()
        assert rr.regime_history == []
        assert rr.summary == ""


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestClassifyRegimes:
    def test_basic(self):
        vol = pd.Series([0.1, 0.2, 0.3, 0.15, 0.25, 0.35, 0.12, 0.22, 0.32])
        regimes = _classify_regimes(vol)
        assert len(regimes) == len(vol)
        assert set(regimes).issubset({0, 1, 2})

    def test_all_same(self):
        vol = pd.Series([0.2, 0.2, 0.2, 0.2])
        regimes = _classify_regimes(vol)
        # All same value → all in one regime
        assert len(set(regimes)) == 1

    def test_three_groups(self):
        vol = pd.Series([0.1, 0.1, 0.1, 0.5, 0.5, 0.5, 0.9, 0.9, 0.9])
        regimes = _classify_regimes(vol)
        assert set(regimes) == {0, 1, 2}


class TestPercentileRank:
    def test_empty(self):
        assert _percentile_rank(pd.Series([]), 0.5) == 0.0

    def test_all_below(self):
        assert _percentile_rank(pd.Series([0.1, 0.2, 0.3]), 0.5) == 1.0

    def test_all_above(self):
        assert _percentile_rank(pd.Series([0.5, 0.6, 0.7]), 0.1) == 0.0

    def test_middle(self):
        rank = _percentile_rank(pd.Series([0.1, 0.2, 0.3, 0.4, 0.5]), 0.3)
        assert 0.0 < rank < 1.0


class TestComputeTransitionMatrix:
    def test_basic(self):
        regimes = np.array([0, 0, 1, 1, 2, 2, 0])
        matrix = _compute_transition_matrix(regimes, 3)
        assert len(matrix) == 3
        for row in matrix:
            row_sum = sum(row)
            if row_sum > 0:
                assert abs(row_sum - 1.0) < 1e-10

    def test_single_regime(self):
        regimes = np.array([0, 0, 0, 0])
        matrix = _compute_transition_matrix(regimes, 3)
        assert matrix[0][0] == 1.0
        # Other rows are all zeros
        assert sum(matrix[1]) == 0.0
        assert sum(matrix[2]) == 0.0

    def test_empty(self):
        regimes = np.array([])
        matrix = _compute_transition_matrix(regimes, 3)
        assert len(matrix) == 3


class TestRegimeDistribution:
    def test_basic(self):
        regimes = np.array([0, 0, 0, 1, 1, 2])
        labels = {0: "low", 1: "med", 2: "high"}
        dist = _regime_distribution(regimes, 3, labels)
        assert abs(dist["low"] - 0.5) < 1e-10
        assert abs(dist["med"] - 1 / 3) < 1e-10
        assert abs(dist["high"] - 1 / 6) < 1e-10

    def test_empty(self):
        regimes = np.array([])
        dist = _regime_distribution(regimes, 3, {0: "a", 1: "b", 2: "c"})
        assert dist == {}


class TestAvgRegimeDuration:
    def test_basic(self):
        regimes = np.array([0, 0, 0, 1, 1, 0, 0])
        labels = {0: "low", 1: "med", 2: "high"}
        durations = _avg_regime_duration(regimes, 3, labels)
        # low: [3, 2] → avg 2.5
        assert abs(durations["low"] - 2.5) < 1e-10
        # med: [2] → avg 2.0
        assert abs(durations["med"] - 2.0) < 1e-10
        # high: [] → 0
        assert durations["high"] == 0.0

    def test_empty(self):
        durations = _avg_regime_duration(np.array([]), 3, {0: "a", 1: "b", 2: "c"})
        assert durations == {}


# ---------------------------------------------------------------------------
# RegimeDetector tests
# ---------------------------------------------------------------------------


class TestRegimeDetector:
    def test_config_loaded(self, detector):
        assert detector.n_regimes == 3
        assert detector.vol_window == 10
        assert detector.min_obs == 20

    def test_insufficient_data(self, detector):
        report = detector.detect(daily_returns=[0.01] * 5)
        assert "Insufficient data" in report.summary

    def test_basic_detection(self, detector, sample_returns, sample_dates):
        report = detector.detect(daily_returns=sample_returns, dates=sample_dates)
        assert report.current_regime.regime_label != ""
        assert len(report.regime_history) > 0
        assert report.summary != ""

    def test_current_regime_valid(self, detector, sample_returns, sample_dates):
        report = detector.detect(daily_returns=sample_returns, dates=sample_dates)
        cr = report.current_regime
        assert cr.regime_id in (0, 1, 2)
        assert cr.volatility >= 0
        assert 0 <= cr.percentile <= 1

    def test_transition_matrix_valid(self, detector, sample_returns, sample_dates):
        report = detector.detect(daily_returns=sample_returns, dates=sample_dates)
        tm = report.transition_matrix
        assert len(tm.matrix) == 3
        for row in tm.matrix:
            row_sum = sum(row)
            if row_sum > 0:
                assert abs(row_sum - 1.0) < 1e-10

    def test_regime_distribution(self, detector, sample_returns, sample_dates):
        report = detector.detect(daily_returns=sample_returns, dates=sample_dates)
        dist = report.regime_distribution
        total = sum(dist.values())
        assert abs(total - 1.0) < 1e-10

    def test_avg_duration(self, detector, sample_returns, sample_dates):
        report = detector.detect(daily_returns=sample_returns, dates=sample_dates)
        for label, dur in report.avg_duration.items():
            assert dur >= 0

    def test_list_input(self, detector):
        np.random.seed(42)
        returns = list(np.random.normal(0.001, 0.02, 200))
        report = detector.detect(daily_returns=returns)
        assert len(report.regime_history) > 0

    def test_without_dates(self, detector, sample_returns):
        report = detector.detect(daily_returns=sample_returns)
        assert len(report.regime_history) > 0
        # Dates should be numeric string indices
        assert (
            report.regime_history[0].date.isdigit()
            or report.regime_history[0].date == "0"
        )

    def test_high_volatility_data(self, detector):
        """High volatility data should classify some periods as high vol."""
        np.random.seed(42)
        # Mix of calm and volatile periods
        calm = np.random.normal(0.001, 0.005, 50)
        volatile = np.random.normal(0.0, 0.05, 50)
        calm2 = np.random.normal(0.001, 0.005, 50)
        volatile2 = np.random.normal(0.0, 0.05, 50)
        returns = pd.Series(np.concatenate([calm, volatile, calm2, volatile2]))
        report = detector.detect(daily_returns=returns)
        assert report.current_regime.regime_label != ""
        # Should detect regime changes
        labels_seen = set(s.regime_label for s in report.regime_history)
        assert len(labels_seen) >= 2

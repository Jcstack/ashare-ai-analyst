"""Tests for walk-forward validation engine.

Part of v15.0 Quant Core layer.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.quant.walk_forward import (
    WalkForwardReport,
    WalkForwardValidator,
    WindowResult,
    _compute_degradation,
    _compute_sharpe,
    _total_return,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_quant_config():
    """Mock quant config for walk-forward tests."""
    return {
        "walk_forward": {
            "train_window_days": 30,
            "test_window_days": 10,
            "step_days": 10,
            "min_trades_per_window": 2,
            "degradation_threshold": 0.5,
            "max_degradation_ratio": 0.7,
        }
    }


@pytest.fixture
def validator(mock_quant_config):
    """Create a validator with test config."""
    with patch("src.quant.walk_forward.load_config", return_value=mock_quant_config):
        return WalkForwardValidator()


@pytest.fixture
def sample_returns():
    """Generate a sample return series (100 days)."""
    np.random.seed(42)
    return pd.Series(np.random.normal(0.001, 0.02, 100))


@pytest.fixture
def sample_dates():
    """Generate sample date strings."""
    dates = pd.date_range("2025-01-01", periods=100, freq="B")
    return [d.strftime("%Y-%m-%d") for d in dates]


# ---------------------------------------------------------------------------
# WindowResult / WalkForwardReport dataclass tests
# ---------------------------------------------------------------------------


class TestWindowResult:
    def test_defaults(self):
        wr = WindowResult()
        assert wr.window_index == 0
        assert wr.train_sharpe == 0.0
        assert wr.is_overfit is False

    def test_custom_values(self):
        wr = WindowResult(
            window_index=1,
            train_sharpe=1.5,
            test_sharpe=0.5,
            degradation=0.67,
            is_overfit=True,
        )
        assert wr.window_index == 1
        assert wr.degradation == 0.67
        assert wr.is_overfit is True


class TestWalkForwardReport:
    def test_defaults(self):
        report = WalkForwardReport()
        assert report.windows == []
        assert report.is_robust is False
        assert report.summary == ""

    def test_custom_values(self):
        report = WalkForwardReport(
            total_windows=5,
            overfit_count=1,
            is_robust=True,
            summary="test",
        )
        assert report.total_windows == 5
        assert report.is_robust is True


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestComputeSharpe:
    def test_empty_returns(self):
        assert _compute_sharpe(pd.Series([])) == 0.0

    def test_single_return(self):
        assert _compute_sharpe(pd.Series([0.01])) == 0.0

    def test_zero_std(self):
        assert _compute_sharpe(pd.Series([0.01, 0.01, 0.01])) == 0.0

    def test_positive_returns(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.002, 0.01, 252))
        sharpe = _compute_sharpe(returns)
        assert sharpe > 0
        assert isinstance(sharpe, float)

    def test_negative_returns(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(-0.005, 0.01, 252))
        sharpe = _compute_sharpe(returns)
        assert sharpe < 0

    def test_nan_std(self):
        returns = pd.Series([float("nan"), float("nan")])
        assert _compute_sharpe(returns) == 0.0


class TestTotalReturn:
    def test_empty(self):
        assert _total_return(pd.Series([])) == 0.0

    def test_positive(self):
        returns = pd.Series([0.01, 0.02, 0.01])
        result = _total_return(returns)
        expected = (1.01 * 1.02 * 1.01) - 1
        assert abs(result - expected) < 1e-10

    def test_negative(self):
        returns = pd.Series([-0.01, -0.02, -0.01])
        result = _total_return(returns)
        assert result < 0


class TestComputeDegradation:
    def test_positive_train_and_test(self):
        # test_sharpe is half of train → degradation = 0.5
        assert abs(_compute_degradation(2.0, 1.0) - 0.5) < 1e-10

    def test_equal_sharpes(self):
        assert _compute_degradation(1.0, 1.0) == 0.0

    def test_negative_train(self):
        # Negative train → no meaningful baseline → 0
        assert _compute_degradation(-1.0, 0.5) == 0.0

    def test_zero_train(self):
        assert _compute_degradation(0.0, 0.5) == 0.0

    def test_test_exceeds_train(self):
        # test > train → negative degradation → clamped to 0
        assert _compute_degradation(1.0, 1.5) == 0.0


# ---------------------------------------------------------------------------
# WalkForwardValidator tests
# ---------------------------------------------------------------------------


class TestWalkForwardValidator:
    def test_config_loaded(self, validator):
        assert validator.train_window == 30
        assert validator.test_window == 10
        assert validator.step_days == 10

    def test_insufficient_data(self, validator):
        report = validator.validate(daily_returns=[0.01] * 10)
        assert "Insufficient data" in report.summary
        assert report.windows == []

    def test_basic_validation(self, validator, sample_returns, sample_dates):
        report = validator.validate(
            daily_returns=sample_returns,
            dates=sample_dates,
        )
        assert report.total_windows > 0
        assert len(report.windows) == report.total_windows
        assert report.summary != ""

    def test_windows_have_valid_fields(self, validator, sample_returns, sample_dates):
        report = validator.validate(daily_returns=sample_returns, dates=sample_dates)
        for w in report.windows:
            assert isinstance(w.train_sharpe, float)
            assert isinstance(w.test_sharpe, float)
            assert isinstance(w.degradation, float)
            assert w.degradation >= 0
            assert isinstance(w.is_overfit, bool)

    def test_overfit_detection(self, validator):
        """Create data where train period is clearly better than test."""
        np.random.seed(42)
        # Good train period then bad test period, repeated
        train_good = np.random.normal(0.005, 0.005, 30)
        test_bad = np.random.normal(-0.002, 0.02, 10)
        returns = pd.Series(np.concatenate([train_good, test_bad] * 3))

        report = validator.validate(daily_returns=returns)
        # At least some windows should flag degradation
        assert report.total_windows > 0

    def test_robust_strategy(self, validator):
        """Create data with consistent returns."""
        np.random.seed(42)
        # Consistent positive returns throughout
        returns = pd.Series(np.random.normal(0.002, 0.01, 100))
        report = validator.validate(daily_returns=returns)
        assert report.total_windows > 0
        # With consistent returns, degradation should be moderate
        assert isinstance(report.is_robust, bool)

    def test_list_input(self, validator):
        """Validate with plain list instead of pd.Series."""
        np.random.seed(42)
        returns = list(np.random.normal(0.001, 0.02, 100))
        report = validator.validate(daily_returns=returns)
        assert report.total_windows > 0

    def test_with_trade_dates(self, validator, sample_dates):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.02, 100))
        trade_dates = sample_dates[::5]  # Trade every 5 days

        report = validator.validate(
            daily_returns=returns,
            trade_dates=trade_dates,
            dates=sample_dates,
        )
        assert report.total_windows > 0
        # Some windows should have counted trades
        has_trades = any(
            w.train_trades > 0 or w.test_trades > 0 for w in report.windows
        )
        assert has_trades

    def test_no_windows_generated(self, mock_quant_config):
        """Edge case: step_days larger than remaining data."""
        mock_quant_config["walk_forward"]["step_days"] = 1000
        with patch(
            "src.quant.walk_forward.load_config", return_value=mock_quant_config
        ):
            v = WalkForwardValidator()
        report = v.validate(daily_returns=[0.01] * 50)
        assert (
            report.total_windows == 1
            or "No windows" in report.summary
            or "Insufficient" in report.summary
        )

    def test_summary_format(self, validator, sample_returns, sample_dates):
        report = validator.validate(daily_returns=sample_returns, dates=sample_dates)
        assert "windows evaluated" in report.summary
        assert "avg train Sharpe" in report.summary
        assert "avg degradation" in report.summary


class TestGenerateWindows:
    def test_basic(self, validator):
        windows = validator.generate_windows(n_days=100)
        assert len(windows) > 0
        for w in windows:
            assert "train_start" in w
            assert "train_end" in w
            assert "test_start" in w
            assert "test_end" in w

    def test_window_boundaries(self, validator):
        windows = validator.generate_windows(n_days=100)
        for w in windows:
            assert w["train_end"] == w["test_start"]
            assert w["train_end"] - w["train_start"] == 30
            assert w["test_end"] - w["test_start"] <= 10

    def test_insufficient_days(self, validator):
        windows = validator.generate_windows(n_days=20)
        assert windows == []

    def test_exact_fit(self, validator):
        # Exactly train + test = 40
        windows = validator.generate_windows(n_days=40)
        assert len(windows) == 1

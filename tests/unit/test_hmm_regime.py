"""Tests for HMM-based regime detection (PRD v50.0 SS5.6).

Tests the 3-state Gaussian HMM regime detector with synthetic data
that has clearly distinct bull/bear/consolidation regimes.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.quant.regime_detector import RegimeDetector, RegimeReport


@pytest.fixture()
def detector() -> RegimeDetector:
    """Create a RegimeDetector with default config."""
    with patch("src.quant.regime_detector.load_config") as mock_cfg:
        mock_cfg.return_value = {
            "regime_detection": {
                "n_regimes": 3,
                "volatility_window_days": 20,
                "lookback_days": 252,
                "min_observations": 60,
                "hmm_n_iter": 100,
                "regime_labels": {
                    0: "low_volatility",
                    1: "medium_volatility",
                    2: "high_volatility",
                },
            }
        }
        return RegimeDetector()


def _make_synthetic_returns(
    n_bull: int = 84,
    n_bear: int = 84,
    n_consolidation: int = 84,
    seed: int = 42,
) -> tuple[pd.Series, list[str]]:
    """Generate synthetic daily returns with 3 distinct regimes.

    Bull: +0.5% avg, 1.5% std
    Bear: -0.5% avg, 2.0% std
    Consolidation: 0.0% avg, 0.8% std

    Returns:
        Tuple of (returns series, date strings).
    """
    rng = np.random.default_rng(seed)

    bull_returns = rng.normal(0.005, 0.015, n_bull)
    bear_returns = rng.normal(-0.005, 0.020, n_bear)
    consolidation_returns = rng.normal(0.0, 0.008, n_consolidation)

    # Stack: bull → bear → consolidation
    all_returns = np.concatenate([bull_returns, bear_returns, consolidation_returns])
    total = len(all_returns)
    dates = [f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(total)]

    return pd.Series(all_returns, dtype=float), dates


class TestHMMRegimeDetection:
    """Tests for detect_hmm method."""

    def test_hmm_returns_report(self, detector: RegimeDetector) -> None:
        """HMM detection produces a valid RegimeReport."""
        returns, dates = _make_synthetic_returns()
        report = detector.detect_hmm(returns, dates)

        assert isinstance(report, RegimeReport)
        assert report.method == "hmm"
        assert report.current_regime.hmm_state in ("bull", "bear", "consolidation")
        assert 0.0 <= report.current_regime.hmm_probability <= 1.0
        assert 0.0 <= report.current_regime.switch_probability <= 1.0

    def test_hmm_state_labels(self, detector: RegimeDetector) -> None:
        """HMM maps all states to valid semantic labels."""
        returns, dates = _make_synthetic_returns()
        report = detector.detect_hmm(returns, dates)

        valid_labels = {"bull", "bear", "consolidation"}
        for state in report.regime_history:
            assert state.hmm_state in valid_labels
            assert state.regime_label in valid_labels

    def test_hmm_transition_matrix_shape(self, detector: RegimeDetector) -> None:
        """Transition matrix is 3x3 with rows summing to ~1."""
        returns, dates = _make_synthetic_returns()
        report = detector.detect_hmm(returns, dates)

        tm = report.transition_matrix.matrix
        assert len(tm) == 3
        for row in tm:
            assert len(row) == 3
            assert abs(sum(row) - 1.0) < 1e-6

    def test_hmm_distribution_sums_to_one(self, detector: RegimeDetector) -> None:
        """Regime distribution fractions sum to ~1."""
        returns, dates = _make_synthetic_returns()
        report = detector.detect_hmm(returns, dates)

        total = sum(report.regime_distribution.values())
        assert abs(total - 1.0) < 1e-6

    def test_hmm_avg_duration_positive(self, detector: RegimeDetector) -> None:
        """Average durations are positive for regimes that appear."""
        returns, dates = _make_synthetic_returns()
        report = detector.detect_hmm(returns, dates)

        for label, dur in report.avg_duration.items():
            if report.regime_distribution.get(label, 0) > 0:
                assert dur > 0, f"Duration for {label} should be positive"

    def test_hmm_identifies_distinct_regimes(self, detector: RegimeDetector) -> None:
        """HMM finds multiple distinct regimes in structured data."""
        returns, dates = _make_synthetic_returns()
        report = detector.detect_hmm(returns, dates)

        # With clearly distinct regimes, HMM should find at least 2 distinct states
        unique_states = set(s.hmm_state for s in report.regime_history)
        assert len(unique_states) >= 2

    def test_hmm_probabilities_valid(self, detector: RegimeDetector) -> None:
        """All state probabilities are in [0, 1]."""
        returns, dates = _make_synthetic_returns()
        report = detector.detect_hmm(returns, dates)

        for state in report.regime_history:
            assert 0.0 <= state.hmm_probability <= 1.0
            assert 0.0 <= state.switch_probability <= 1.0

    def test_hmm_history_length(self, detector: RegimeDetector) -> None:
        """History length matches valid observations (after rolling window warmup)."""
        returns, dates = _make_synthetic_returns()
        report = detector.detect_hmm(returns, dates)

        # History should be total - (vol_window - 1) observations
        expected_len = len(returns) - (detector.vol_window - 1)
        assert len(report.regime_history) == expected_len

    def test_hmm_summary_contains_state(self, detector: RegimeDetector) -> None:
        """Summary string contains the current HMM state."""
        returns, dates = _make_synthetic_returns()
        report = detector.detect_hmm(returns, dates)

        assert report.current_regime.hmm_state in report.summary


class TestHMMFallback:
    """Tests for graceful fallback when hmmlearn is unavailable."""

    def test_detect_falls_back_to_volatility(self, detector: RegimeDetector) -> None:
        """detect() falls back to volatility method when HMM import fails."""
        returns, dates = _make_synthetic_returns()

        with patch(
            "src.quant.regime_detector.RegimeDetector.detect_hmm",
            side_effect=ImportError("no hmmlearn"),
        ):
            report = detector.detect(returns, dates)

        assert isinstance(report, RegimeReport)
        assert report.method == "volatility_percentile"
        # Should still produce valid output
        assert report.current_regime.regime_label != ""

    def test_detect_falls_back_on_hmm_error(self, detector: RegimeDetector) -> None:
        """detect() falls back when HMM fitting raises an exception."""
        returns, dates = _make_synthetic_returns()

        with patch(
            "src.quant.regime_detector.RegimeDetector.detect_hmm",
            side_effect=RuntimeError("convergence failed"),
        ):
            report = detector.detect(returns, dates)

        assert isinstance(report, RegimeReport)
        assert report.method == "volatility_percentile"

    def test_detect_hmm_import_error(self, detector: RegimeDetector) -> None:
        """detect_hmm raises ImportError when hmmlearn missing."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name: str, *args, **kwargs):
            if name == "hmmlearn.hmm":
                raise ImportError("No module named 'hmmlearn'")
            return original_import(name, *args, **kwargs)

        returns, dates = _make_synthetic_returns()

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="hmmlearn"):
                detector.detect_hmm(returns, dates)


class TestInsufficientData:
    """Tests for insufficient data handling."""

    def test_detect_insufficient_data(self, detector: RegimeDetector) -> None:
        """detect() returns empty report for too few observations."""
        short_returns = pd.Series([0.01, -0.01, 0.005] * 10)
        report = detector.detect(short_returns)

        assert "Insufficient" in report.summary
        assert report.current_regime.hmm_state == ""

    def test_detect_hmm_insufficient_data(self, detector: RegimeDetector) -> None:
        """detect_hmm raises ValueError for too few observations."""
        short_returns = pd.Series([0.01, -0.01, 0.005] * 10)

        with pytest.raises(ValueError, match="Insufficient"):
            detector.detect_hmm(short_returns)


class TestVolatilityFallback:
    """Tests for the original volatility-percentile method."""

    def test_volatility_method_works(self, detector: RegimeDetector) -> None:
        """_detect_volatility still works independently."""
        returns, dates = _make_synthetic_returns()
        report = detector._detect_volatility(returns, dates)

        assert isinstance(report, RegimeReport)
        assert report.method == "volatility_percentile"
        assert len(report.regime_history) > 0
        assert report.current_regime.regime_label != ""

    def test_detect_uses_hmm_when_available(self, detector: RegimeDetector) -> None:
        """detect() prefers HMM over volatility when hmmlearn is installed."""
        returns, dates = _make_synthetic_returns()
        report = detector.detect(returns, dates)

        # If hmmlearn is installed (it should be), HMM is used
        try:
            import hmmlearn  # noqa: F401

            assert report.method == "hmm"
        except ImportError:
            assert report.method == "volatility_percentile"

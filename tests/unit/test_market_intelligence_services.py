"""Tests for v20.0 Phase 5 market intelligence services.

Covers SectorRotationDetector, CorrelationService, and DataSourceManager.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from src.market_intelligence.correlation_service import CorrelationService
from src.market_intelligence.data_source_manager import DataSourceManager
from src.market_intelligence.sector_rotation import SectorRotationDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_close_series(
    n: int = 60, start: float = 100.0, drift: float = 0.001
) -> pd.Series:
    """Generate a synthetic close price series."""
    np.random.seed(42)
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + np.random.normal(drift, 0.01)))
    return pd.Series(prices, name="close")


def _mock_stock_service(symbols: list[str] | None = None, n: int = 60) -> MagicMock:
    """Build a mock stock_service whose get_historical_data returns a DataFrame with a 'close' column."""
    svc = MagicMock()

    def _get_hist(symbol: str, period: int = 60) -> pd.DataFrame:
        np.random.seed(hash(symbol) % (2**31))
        closes = _make_close_series(max(period, 2))
        return pd.DataFrame({"close": closes})

    svc.get_historical_data.side_effect = _get_hist
    return svc


# ===========================================================================
# SectorRotationDetector
# ===========================================================================


class TestSectorRotationDetector:
    """Tests for SectorRotationDetector."""

    def test_detect_rotation_returns_structure(self):
        """detect_rotation returns dict with required keys and correct types."""
        svc = _mock_stock_service()
        detector = SectorRotationDetector(stock_service=svc)
        result = detector.detect_rotation(lookback_days=20)

        assert isinstance(result, dict)
        assert "leading_sectors" in result
        assert "lagging_sectors" in result
        assert "rotation_strength" in result
        assert "timestamp" in result

        assert isinstance(result["leading_sectors"], list)
        assert isinstance(result["lagging_sectors"], list)
        assert isinstance(result["rotation_strength"], float)
        assert isinstance(result["timestamp"], str)

    def test_get_sector_performance(self):
        """get_sector_performance returns list of dicts with expected fields."""
        svc = _mock_stock_service()
        detector = SectorRotationDetector(stock_service=svc)
        perf = detector.get_sector_performance(period="1w")

        assert isinstance(perf, list)
        assert len(perf) > 0

        first = perf[0]
        assert "sector_code" in first
        assert "sector_name" in first
        assert "return_pct" in first
        assert "rank" in first

        # Ranks should be sequential starting at 1
        ranks = [e["rank"] for e in perf]
        assert ranks == list(range(1, len(perf) + 1))

    def test_rotation_strength_range(self):
        """rotation_strength should be in [0, 1]."""
        svc = _mock_stock_service()
        detector = SectorRotationDetector(stock_service=svc)
        result = detector.detect_rotation(lookback_days=20)

        assert 0.0 <= result["rotation_strength"] <= 1.0

    def test_no_stock_service_fallback(self):
        """Without stock_service, returns default/empty data gracefully."""
        detector = SectorRotationDetector(stock_service=None)
        result = detector.detect_rotation(lookback_days=20)

        assert isinstance(result, dict)
        assert "leading_sectors" in result
        assert "lagging_sectors" in result
        assert "rotation_strength" in result
        # All returns are 0.0 when no service, so rotation_strength should be 0
        assert result["rotation_strength"] == 0.0


# ===========================================================================
# CorrelationService
# ===========================================================================


class TestCorrelationService:
    """Tests for CorrelationService."""

    def test_compute_matrix_structure(self):
        """compute_matrix returns dict with matrix, anomalies, timestamp."""
        svc = _mock_stock_service()
        cs = CorrelationService(stock_service=svc)
        result = cs.compute_matrix(
            symbols=["000001", "000002", "000003"], lookback_days=60
        )

        assert isinstance(result, dict)
        assert "matrix" in result
        assert "anomalies" in result
        assert "timestamp" in result

        matrix = result["matrix"]
        assert isinstance(matrix, dict)
        # Matrix should contain entries for the symbols
        if matrix:
            for sym, row in matrix.items():
                assert isinstance(row, dict)
                # Diagonal should be 1.0
                assert row[sym] == pytest.approx(1.0, abs=0.001)

    def test_detect_anomalies_structure(self):
        """detect_anomalies returns a list of dicts."""
        svc = _mock_stock_service()
        cs = CorrelationService(stock_service=svc)
        anomalies = cs.detect_anomalies(symbols=["000001", "000002", "000003"])

        assert isinstance(anomalies, list)
        # Each anomaly (if any) should have the right keys
        for a in anomalies:
            assert "pair" in a
            assert "baseline_corr" in a
            assert "recent_corr" in a
            assert "change" in a
            assert isinstance(a["pair"], list)
            assert len(a["pair"]) == 2

    def test_empty_symbols(self):
        """Empty symbols list returns empty matrix."""
        svc = _mock_stock_service()
        cs = CorrelationService(stock_service=svc)
        result = cs.compute_matrix(symbols=[], lookback_days=60)

        assert result["matrix"] == {}
        assert result["anomalies"] == []

    def test_no_stock_service_fallback(self):
        """Without stock_service, returns empty matrix gracefully."""
        cs = CorrelationService(stock_service=None)
        result = cs.compute_matrix(symbols=["000001", "000002"], lookback_days=60)

        assert isinstance(result, dict)
        assert result["matrix"] == {}
        assert result["anomalies"] == []
        assert "timestamp" in result


# ===========================================================================
# DataSourceManager
# ===========================================================================


class TestDataSourceManager:
    """Tests for DataSourceManager."""

    def test_get_source_status(self):
        """get_source_status returns dict with source categories."""
        mgr = DataSourceManager()
        status = mgr.get_source_status()

        assert isinstance(status, dict)
        assert "sources" in status
        assert "overall_status" in status
        assert "timestamp" in status

        sources = status["sources"]
        assert isinstance(sources, dict)
        # Should contain the default categories
        assert "market_data" in sources
        assert "news" in sources
        assert "global_market" in sources
        assert "sentiment" in sources

        # Each category is a list of provider dicts
        for category, providers in sources.items():
            assert isinstance(providers, list)
            for p in providers:
                assert "name" in p
                assert "status" in p
                assert "latency_ms" in p
                assert "error_count" in p

    def test_get_best_source(self):
        """get_best_source returns a source name string."""
        mgr = DataSourceManager()
        best = mgr.get_best_source("market_data")

        assert isinstance(best, str)
        assert len(best) > 0
        # Should be one of the configured providers
        assert best in ("tushare", "akshare", "eastmoney")

    def test_is_degraded_default(self):
        """Default state should be not degraded (all sources healthy)."""
        mgr = DataSourceManager()
        assert mgr.is_degraded() is False

    def test_report_failure_degrades(self):
        """After multiple failures, source becomes degraded."""
        mgr = DataSourceManager()

        # Initially healthy
        assert mgr.is_degraded() is False

        # Report 2 failures on a critical source to trigger degraded status
        mgr.report_failure("tushare", error="timeout")
        mgr.report_failure("tushare", error="timeout")

        # After 2 failures, status should be "degraded"
        assert mgr.is_degraded() is True

        # The source status should reflect the degradation
        status = mgr.get_source_status()
        assert status["overall_status"] == "degraded"

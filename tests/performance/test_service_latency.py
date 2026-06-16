"""Service layer latency benchmarks.

Measures latency of key service methods with mocked external dependencies
to establish internal processing overhead baselines.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# Threshold in seconds
SERVICE_LATENCY_THRESHOLD = 0.050  # 50ms for internal service logic


MOCK_OHLCV = pd.DataFrame(
    {
        "date": pd.date_range("2024-01-02", periods=50, freq="B"),
        "open": [10.0] * 50,
        "high": [10.5] * 50,
        "low": [9.5] * 50,
        "close": [10.2] * 50,
        "volume": [1000000] * 50,
        "amount": [1e7] * 50,
    }
)


class TestStockServiceLatency:
    """Benchmark StockService internal processing."""

    @pytest.mark.performance
    def test_get_watchlist_latency(self, benchmark):
        """Watchlist retrieval from config should be fast."""
        with patch("src.web.services.stock_service.load_config") as mock_cfg:
            mock_cfg.return_value = {
                "watchlist": [
                    {"symbol": f"{i:06d}", "name": f"Stock{i}", "board": "main"}
                    for i in range(50)
                ],
            }
            from src.web.services.stock_service import StockService

            svc = StockService()
            result = benchmark(svc.get_watchlist)

        assert len(result) == 50
        assert benchmark.stats["mean"] < SERVICE_LATENCY_THRESHOLD

    @pytest.mark.performance
    def test_get_indicators_summary_latency(self, benchmark):
        """Indicator summary computation should be fast."""
        with (
            patch("src.web.services.stock_service.load_config") as mock_cfg,
            patch(
                "src.web.services.stock_service.StockDataFetcher"
            ) as mock_fetcher_cls,
        ):
            mock_cfg.return_value = {"watchlist": []}
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_daily.return_value = MOCK_OHLCV.copy()
            mock_fetcher_cls.return_value = mock_fetcher

            from src.web.services.stock_service import StockService

            svc = StockService()
            result = benchmark(svc.get_indicators_summary, "000001")

        assert isinstance(result, dict)
        assert benchmark.stats["mean"] < 0.200  # Allow 200ms for indicator calc


class TestBacktestServiceLatency:
    """Benchmark BacktestService internal processing."""

    @pytest.mark.performance
    def test_list_strategies_latency(self, benchmark):
        """Strategy listing should be near-instant."""
        mock_stock_svc = MagicMock()

        from src.web.services.backtest_service import BacktestService

        svc = BacktestService(stock_service=mock_stock_svc)
        result = benchmark(svc.get_available_strategies)

        assert isinstance(result, list)
        assert benchmark.stats["mean"] < SERVICE_LATENCY_THRESHOLD

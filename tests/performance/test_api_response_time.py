"""API response time benchmarks.

Per PRD NFR-001: API endpoints should respond < 200ms p95 with mocked
external services.  Uses pytest-benchmark for statistical measurements.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# Threshold in seconds (200ms)
API_RESPONSE_THRESHOLD = 0.200


@pytest.fixture
def perf_client():
    """Minimal app with key routes for performance testing."""
    from src.web.dependencies import (
        get_global_market_fetcher,
        get_market_service,
        get_realtime_quote_manager,
        get_stock_registry,
        get_stock_service,
        get_trading_calendar,
    )
    from src.web.routes.api_v1.global_market import router as gm_router
    from src.web.routes.api_v1.market import router as market_router
    from src.web.routes.api_v1.stocks import router as stocks_router

    mock_svc = MagicMock()
    mock_svc.get_watchlist.return_value = [
        {"symbol": "000001", "name": "平安银行", "board": "main"},
    ]
    mock_svc.get_latest_price_info.return_value = {
        "close": 10.50,
        "open": 10.20,
        "high": 10.80,
        "low": 10.10,
        "change": 0.30,
        "pct_change": 2.94,
        "volume": 1500000,
    }
    mock_svc.get_indicators_summary.return_value = {"RSI_14": 55.0}
    mock_svc.get_support_resistance.return_value = []

    mock_registry = MagicMock()
    mock_registry.get_stock_info.return_value = {
        "symbol": "000001",
        "name": "平安银行",
        "board": "main",
    }

    mock_quote_mgr = MagicMock()
    mock_quote_mgr.get_quotes.return_value = pd.DataFrame(
        [
            {
                "symbol": "000001",
                "price": 10.50,
                "change": 0.30,
                "pct_change": 2.94,
                "open": 10.20,
                "high": 10.80,
                "low": 10.10,
                "prev_close": 10.20,
                "volume": 1500000,
                "amount": 1.5e7,
            }
        ]
    )

    mock_market = MagicMock()
    mock_market.get_market_indices.return_value = [
        {
            "name": "上证指数",
            "code": "sh000001",
            "price": 3100.0,
            "change": 15.0,
            "pct_change": 0.49,
        },
    ]

    mock_gm = MagicMock()
    mock_gm.fetch_global_snapshot.return_value = {
        "indices": [],
        "commodities": [],
        "currencies": [],
    }
    mock_gm.fetch_global_indices.return_value = []
    mock_gm.fetch_commodities.return_value = []
    mock_gm.fetch_currencies.return_value = []

    mock_cal = MagicMock()
    mock_cal.get_calendar_info.return_value = {
        "date": "2026-02-13",
        "is_trading_day": True,
        "current_session": "afternoon",
        "next_trading_day": "2026-02-16",
        "is_holiday_period": False,
    }

    app = FastAPI()
    app.include_router(stocks_router, prefix="/api/v1")
    app.include_router(market_router, prefix="/api/v1/market")
    app.include_router(gm_router, prefix="/api/v1/global-market")

    app.dependency_overrides[get_stock_service] = lambda: mock_svc
    app.dependency_overrides[get_stock_registry] = lambda: mock_registry
    app.dependency_overrides[get_realtime_quote_manager] = lambda: mock_quote_mgr
    app.dependency_overrides[get_market_service] = lambda: mock_market
    app.dependency_overrides[get_global_market_fetcher] = lambda: mock_gm
    app.dependency_overrides[get_trading_calendar] = lambda: mock_cal

    # Patch RealtimeQuoteManager() used directly in watchlist handler
    with patch(
        "src.web.routes.api_v1.stocks.RealtimeQuoteManager",
        return_value=mock_quote_mgr,
    ):
        client = TestClient(app)
        yield client

    app.dependency_overrides.clear()


class TestApiResponseTime:
    """Benchmark API endpoint response times."""

    @pytest.mark.performance
    def test_watchlist_response_time(self, perf_client, benchmark):
        """GET /watchlist should respond within threshold."""
        result = benchmark(perf_client.get, "/api/v1/watchlist")
        assert result.status_code == 200
        assert benchmark.stats["mean"] < API_RESPONSE_THRESHOLD

    @pytest.mark.performance
    def test_stock_detail_response_time(self, perf_client, benchmark):
        """GET /stock/{symbol} should respond within threshold."""
        result = benchmark(perf_client.get, "/api/v1/stock/000001")
        assert result.status_code == 200
        assert benchmark.stats["mean"] < API_RESPONSE_THRESHOLD

    @pytest.mark.performance
    def test_indicators_response_time(self, perf_client, benchmark):
        """GET /stock/{symbol}/indicators should respond within threshold."""
        result = benchmark(perf_client.get, "/api/v1/stock/000001/indicators")
        assert result.status_code == 200
        assert benchmark.stats["mean"] < API_RESPONSE_THRESHOLD

    @pytest.mark.performance
    def test_global_snapshot_response_time(self, perf_client, benchmark):
        """GET /global-market/snapshot should respond within threshold."""
        result = benchmark(perf_client.get, "/api/v1/global-market/snapshot")
        assert result.status_code == 200
        assert benchmark.stats["mean"] < API_RESPONSE_THRESHOLD

    @pytest.mark.performance
    def test_calendar_response_time(self, perf_client, benchmark):
        """GET /market/calendar should respond within threshold."""
        result = benchmark(perf_client.get, "/api/v1/market/calendar")
        assert result.status_code == 200
        assert benchmark.stats["mean"] < API_RESPONSE_THRESHOLD

    @pytest.mark.performance
    def test_support_resistance_response_time(self, perf_client, benchmark):
        """GET /stock/{symbol}/support-resistance should respond within threshold."""
        result = benchmark(perf_client.get, "/api/v1/stock/000001/support-resistance")
        assert result.status_code == 200
        assert benchmark.stats["mean"] < API_RESPONSE_THRESHOLD

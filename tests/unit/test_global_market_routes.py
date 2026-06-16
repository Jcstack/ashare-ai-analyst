"""Tests for global market API routes.

Per PRD v3.2 FR-GM002.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


MOCK_SNAPSHOT = {
    "indices": [
        {
            "symbol": "^GSPC",
            "name": "S&P500",
            "region": "US",
            "price": 4500.0,
            "change": 20.0,
            "pct_change": 0.45,
            "prev_close": 4480.0,
        },
    ],
    "commodities": [
        {
            "symbol": "GC=F",
            "name": "Gold",
            "unit": "USD/oz",
            "price": 2050.0,
            "change": 10.0,
            "pct_change": 0.49,
        },
    ],
    "currencies": [
        {
            "symbol": "CNY=X",
            "name": "USD/CNY",
            "price": 7.25,
            "change": 0.01,
            "pct_change": 0.14,
        },
    ],
}

MOCK_CALENDAR_INFO = {
    "date": "2026-02-13",
    "is_trading_day": True,
    "current_session": "afternoon",
    "next_trading_day": "2026-02-16",
    "is_holiday_period": False,
}


@pytest.fixture
def client():
    """FastAPI TestClient with mocked dependencies."""
    from src.web.dependencies import get_global_market_fetcher, get_trading_calendar
    from src.web.routes.api_v1.global_market import router as global_market_router
    from src.web.routes.api_v1.market import router as market_router

    mock_fetcher = MagicMock()
    mock_fetcher.fetch_global_snapshot.return_value = MOCK_SNAPSHOT
    mock_fetcher.fetch_global_indices.return_value = MOCK_SNAPSHOT["indices"]
    mock_fetcher.fetch_commodities.return_value = MOCK_SNAPSHOT["commodities"]
    mock_fetcher.fetch_currencies.return_value = MOCK_SNAPSHOT["currencies"]

    mock_cal = MagicMock()
    mock_cal.get_calendar_info.return_value = MOCK_CALENDAR_INFO

    app = FastAPI()
    app.include_router(global_market_router, prefix="/api/v1/global-market")
    app.include_router(market_router, prefix="/api/v1/market")

    app.dependency_overrides[get_global_market_fetcher] = lambda: mock_fetcher
    app.dependency_overrides[get_trading_calendar] = lambda: mock_cal

    yield TestClient(app)

    app.dependency_overrides.clear()


class TestGlobalMarketSnapshot:
    def test_snapshot_returns_all_categories(self, client):
        resp = client.get("/api/v1/global-market/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert "indices" in data
        assert "commodities" in data
        assert "currencies" in data
        assert len(data["indices"]) == 1
        assert data["indices"][0]["symbol"] == "^GSPC"

    def test_indices_endpoint(self, client):
        resp = client.get("/api/v1/global-market/indices")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "S&P500"

    def test_commodities_endpoint(self, client):
        resp = client.get("/api/v1/global-market/commodities")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Gold"

    def test_currencies_endpoint(self, client):
        resp = client.get("/api/v1/global-market/currencies")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "USD/CNY"


class TestTradingCalendarRoute:
    def test_calendar_endpoint(self, client):
        resp = client.get("/api/v1/market/calendar")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_trading_day"] is True
        assert data["current_session"] == "afternoon"
        assert data["next_trading_day"] == "2026-02-16"

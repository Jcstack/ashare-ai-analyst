"""Unit tests for src/web/routes/api_v1/agent.py — AI Agent API endpoints.

Tests GET /stock/{symbol}/ai-analysis, quick-insight, alerts,
POST /stock/{symbol}/analyze, and GET /market/ai-overview.

Per PRD v2.0 FR-AI001/AI002/AI003.
Mock strategy: Mock dependency injection singletons only.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------
MOCK_QUOTE = {
    "symbol": "000001",
    "name": "平安银行",
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

MOCK_AI_RESULT = {
    "status": "success",
    "symbol": "000001",
    "trend": "bullish",
    "signal": "buy",
    "confidence": 0.78,
    "risk_level": "medium",
    "reasoning": ["均线多头排列"],
    "target_price_range": {"low": 10.5, "high": 12.0},
    "key_factors": ["成交量放大"],
    "risk_warnings": ["大盘风险"],
    "news_sentiment": "positive",
    "generated_at": "2024-01-05 10:00:00",
    "model_used": "claude-sonnet-4-5-20250929",
}

MOCK_QUICK_INSIGHT = {
    "symbol": "000001",
    "signal": "bullish",
    "confidence": 0.70,
    "summary": "短期看多",
    "risk_badge": "low",
    "generated_at": "2024-01-05 10:00:00",
}

MOCK_MARKET_OVERVIEW = {
    "status": "success",
    "market_trend": "bullish",
    "risk_assessment": "low",
    "summary": "市场偏强",
    "key_points": ["沪指上涨"],
    "sector_outlook": {"leading": ["新能源"]},
    "generated_at": "2024-01-05 10:00:00",
}


@pytest.fixture
def client():
    """FastAPI TestClient with all agent dependencies mocked."""
    # Mock the dependency singletons
    mock_analyzer = MagicMock()
    mock_analyzer.analyze_stock_realtime.return_value = MOCK_AI_RESULT
    mock_analyzer.get_quick_insight.return_value = MOCK_QUICK_INSIGHT
    mock_analyzer.get_market_overview.return_value = MOCK_MARKET_OVERVIEW

    mock_quote_mgr = MagicMock()
    mock_quote_mgr.get_single_quote.return_value = MOCK_QUOTE

    mock_news_fetcher = MagicMock()
    mock_news_fetcher.fetch_stock_news.return_value = pd.DataFrame(
        columns=["title", "content", "datetime", "source", "url"],
    )
    mock_news_fetcher.fetch_stock_anomalies.return_value = pd.DataFrame(
        columns=["datetime", "symbol", "name", "change_type", "description"],
    )
    mock_news_fetcher.fetch_hot_rank.return_value = pd.DataFrame(
        columns=["rank", "symbol", "name", "price", "pct_change"],
    )

    mock_stock_svc = MagicMock()
    mock_stock_svc.get_indicators.return_value = {"values": {"rsi": 55.0}}
    mock_stock_svc.get_stock_detail.return_value = {
        "symbol": "000001",
        "name": "平安银行",
        "board": "main",
    }
    mock_stock_svc.get_ohlcv_dataframe.return_value = pd.DataFrame(
        {"volume": [1000000] * 30},
    )

    mock_alert_engine = MagicMock()
    mock_alert_engine.check_alerts.return_value = [
        {
            "id": "abc12345",
            "symbol": "000001",
            "name": "平安银行",
            "alert_type": "volume_spike",
            "severity": "warning",
            "title": "成交量异常放大",
            "description": "当前成交量是20日均量的2.5倍",
            "value": 2.5,
            "threshold": 2.0,
            "timestamp": "2024-01-05 10:00:00",
        },
    ]

    from src.web.dependencies import (
        get_alert_engine,
        get_news_fetcher,
        get_realtime_analyzer,
        get_realtime_quote_manager,
        get_stock_service,
    )
    from src.web.routes.api_v1.agent import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    # Use FastAPI dependency_overrides for Depends()-based injection
    app.dependency_overrides[get_realtime_analyzer] = lambda: mock_analyzer
    app.dependency_overrides[get_realtime_quote_manager] = lambda: mock_quote_mgr
    app.dependency_overrides[get_news_fetcher] = lambda: mock_news_fetcher
    app.dependency_overrides[get_stock_service] = lambda: mock_stock_svc
    app.dependency_overrides[get_alert_engine] = lambda: mock_alert_engine

    # Also patch module-level calls used by helper functions
    # (_gather_analysis_data and _safe_get_market_indices call get_xxx() directly)
    with (
        patch(
            "src.web.routes.api_v1.agent.get_realtime_quote_manager",
            return_value=mock_quote_mgr,
        ),
        patch(
            "src.web.routes.api_v1.agent.get_news_fetcher",
            return_value=mock_news_fetcher,
        ),
        patch(
            "src.web.routes.api_v1.agent.get_stock_service", return_value=mock_stock_svc
        ),
    ):
        yield TestClient(app)

    app.dependency_overrides.clear()


class TestGetAIAnalysis:
    """Tests for GET /api/v1/stock/{symbol}/ai-analysis."""

    def test_returns_200(self, client):
        """Endpoint should return 200 OK."""
        resp = client.get("/api/v1/stock/000001/ai-analysis")
        assert resp.status_code == 200

    def test_response_contains_trend(self, client):
        """Response JSON should contain trend field."""
        resp = client.get("/api/v1/stock/000001/ai-analysis")
        data = resp.json()
        assert data["trend"] == "bullish"

    def test_response_contains_symbol(self, client):
        """Response should contain the requested symbol."""
        resp = client.get("/api/v1/stock/000001/ai-analysis")
        data = resp.json()
        assert data["symbol"] == "000001"


class TestGetQuickInsight:
    """Tests for GET /api/v1/stock/{symbol}/quick-insight."""

    def test_returns_200(self, client):
        """Endpoint should return 200 OK."""
        resp = client.get("/api/v1/stock/000001/quick-insight")
        assert resp.status_code == 200

    def test_response_contains_signal(self, client):
        """Response should contain signal and summary."""
        resp = client.get("/api/v1/stock/000001/quick-insight")
        data = resp.json()
        assert "signal" in data
        assert "summary" in data


class TestTriggerFreshAnalysis:
    """Tests for POST /api/v1/stock/{symbol}/analyze."""

    def test_returns_200(self, client):
        """Endpoint should return 200 OK."""
        resp = client.post("/api/v1/stock/000001/analyze")
        assert resp.status_code == 200

    def test_response_is_ai_result(self, client):
        """Response should contain AI analysis fields."""
        resp = client.post("/api/v1/stock/000001/analyze")
        data = resp.json()
        assert data.get("status") == "success"
        assert data.get("trend") is not None


class TestGetStockAlerts:
    """Tests for GET /api/v1/stock/{symbol}/alerts."""

    def test_returns_200(self, client):
        """Endpoint should return 200 OK."""
        resp = client.get("/api/v1/stock/000001/alerts")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        """Response should be a list of alerts."""
        resp = client.get("/api/v1/stock/000001/alerts")
        data = resp.json()
        assert isinstance(data, list)

    def test_alert_has_type_and_severity(self, client):
        """Each alert should have alert_type and severity fields."""
        resp = client.get("/api/v1/stock/000001/alerts")
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["alert_type"] == "volume_spike"
        assert data[0]["severity"] == "warning"


class TestMarketAIOverview:
    """Tests for GET /api/v1/market/ai-overview."""

    def test_returns_200(self, client):
        """Endpoint should return 200 OK."""
        resp = client.get("/api/v1/market/ai-overview")
        assert resp.status_code == 200

    def test_response_contains_market_trend(self, client):
        """Response should contain market_trend field."""
        resp = client.get("/api/v1/market/ai-overview")
        data = resp.json()
        assert "market_trend" in data
        assert data["market_trend"] == "bullish"

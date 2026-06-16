"""Unit tests for src/web/routes/api_v1/news.py — News & anomaly API endpoints.

Tests GET /stock/{symbol}/news, anomalies, sentiment, and GET /market/hot-rank.

Per PRD v2.0 FR-NF001, FR-AD001.
Mock strategy: Use FastAPI dependency_overrides for proper DI mocking.
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web.dependencies import get_news_fetcher, get_sentiment_analyzer
from src.web.routes.api_v1.news import router


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------
MOCK_NEWS_DF = pd.DataFrame(
    {
        "title": ["利好消息1", "中性消息2"],
        "content": ["内容1", "内容2"],
        "datetime": ["2024-01-05 10:00", "2024-01-05 11:00"],
        "source": ["东方财富", "新浪财经"],
        "url": ["https://example.com/1", "https://example.com/2"],
    }
)

MOCK_ANOMALY_DF = pd.DataFrame(
    {
        "datetime": ["2024-01-05 14:30"],
        "symbol": ["000001"],
        "name": ["平安银行"],
        "change_type": ["大单买入"],
        "description": ["出现大额买单"],
    }
)

MOCK_HOT_RANK_DF = pd.DataFrame(
    {
        "rank": [1, 2, 3],
        "symbol": ["000001", "600519", "300750"],
        "name": ["平安银行", "贵州茅台", "宁德时代"],
        "price": [10.5, 1800.0, 200.0],
        "pct_change": [2.5, 1.0, -0.5],
    }
)

MOCK_SENTIMENT = {
    "symbol": "000001",
    "overall": "positive",
    "positive_count": 1,
    "negative_count": 0,
    "neutral_count": 1,
    "total_count": 2,
    "score": 0.4,
    "summary": "偏正面",
}


@pytest.fixture
def client():
    """FastAPI TestClient with news route dependencies overridden."""
    mock_news_fetcher = MagicMock()
    mock_news_fetcher.fetch_stock_news.return_value = MOCK_NEWS_DF.copy()
    mock_news_fetcher.fetch_stock_anomalies.return_value = MOCK_ANOMALY_DF.copy()
    mock_news_fetcher.fetch_hot_rank.return_value = MOCK_HOT_RANK_DF.copy()

    mock_sentiment = MagicMock()
    mock_sentiment.analyze_batch.return_value = MOCK_SENTIMENT.copy()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_news_fetcher] = lambda: mock_news_fetcher
    app.dependency_overrides[get_sentiment_analyzer] = lambda: mock_sentiment

    yield TestClient(app)

    app.dependency_overrides.clear()


class TestGetStockNews:
    """Tests for GET /api/v1/stock/{symbol}/news."""

    def test_returns_200(self, client):
        """Endpoint should return 200 OK."""
        resp = client.get("/api/v1/stock/000001/news")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        """Response should be a list of news items."""
        resp = client.get("/api/v1/stock/000001/news")
        data = resp.json()
        assert isinstance(data, list)

    def test_news_items_have_title(self, client):
        """Each news item should have a title field."""
        resp = client.get("/api/v1/stock/000001/news")
        data = resp.json()
        assert len(data) == 2
        assert data[0]["title"] == "利好消息1"

    def test_limit_query_param(self, client):
        """Limit parameter should restrict number of returned items."""
        resp = client.get("/api/v1/stock/000001/news?limit=1")
        data = resp.json()
        assert len(data) == 1


class TestGetStockAnomalies:
    """Tests for GET /api/v1/stock/{symbol}/anomalies."""

    def test_returns_200(self, client):
        """Endpoint should return 200 OK."""
        resp = client.get("/api/v1/stock/000001/anomalies")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        """Response should be a list of anomaly items."""
        resp = client.get("/api/v1/stock/000001/anomalies")
        data = resp.json()
        assert isinstance(data, list)

    def test_anomaly_has_change_type(self, client):
        """Anomaly items should have change_type field."""
        resp = client.get("/api/v1/stock/000001/anomalies")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["change_type"] == "大单买入"


class TestGetStockSentiment:
    """Tests for GET /api/v1/stock/{symbol}/sentiment."""

    def test_returns_200(self, client):
        """Endpoint should return 200 OK."""
        resp = client.get("/api/v1/stock/000001/sentiment")
        assert resp.status_code == 200

    def test_contains_overall_sentiment(self, client):
        """Response should contain overall sentiment."""
        resp = client.get("/api/v1/stock/000001/sentiment")
        data = resp.json()
        assert data["overall"] == "positive"

    def test_contains_counts(self, client):
        """Response should contain sentiment counts."""
        resp = client.get("/api/v1/stock/000001/sentiment")
        data = resp.json()
        assert data["positive_count"] == 1
        assert data["total_count"] == 2

    def test_contains_symbol(self, client):
        """Response should contain the requested symbol."""
        resp = client.get("/api/v1/stock/000001/sentiment")
        data = resp.json()
        assert data["symbol"] == "000001"

    def test_empty_news_returns_neutral(self):
        """When no news, sentiment should be neutral with zero counts."""
        mock_news_fetcher = MagicMock()
        mock_news_fetcher.fetch_stock_news.return_value = pd.DataFrame(
            columns=["title", "content", "datetime", "source", "url"],
        )
        mock_sentiment = MagicMock()

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_news_fetcher] = lambda: mock_news_fetcher
        app.dependency_overrides[get_sentiment_analyzer] = lambda: mock_sentiment

        test_client = TestClient(app)

        resp = test_client.get("/api/v1/stock/000001/sentiment")
        data = resp.json()
        assert data["overall"] == "neutral"
        assert data["total_count"] == 0
        # Sentiment analyzer should NOT be called when news is empty
        mock_sentiment.analyze_batch.assert_not_called()

        app.dependency_overrides.clear()


class TestGetHotRank:
    """Tests for GET /api/v1/market/hot-rank."""

    def test_returns_200(self, client):
        """Endpoint should return 200 OK."""
        resp = client.get("/api/v1/market/hot-rank")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        """Response should be a list of hot rank items."""
        resp = client.get("/api/v1/market/hot-rank")
        data = resp.json()
        assert isinstance(data, list)

    def test_items_have_rank_and_symbol(self, client):
        """Hot rank items should have rank and symbol fields."""
        resp = client.get("/api/v1/market/hot-rank")
        data = resp.json()
        assert len(data) == 3
        assert data[0]["rank"] == 1
        assert data[0]["symbol"] == "000001"

    def test_items_have_price(self, client):
        """Hot rank items should include price data."""
        resp = client.get("/api/v1/market/hot-rank")
        data = resp.json()
        assert data[1]["price"] == 1800.0

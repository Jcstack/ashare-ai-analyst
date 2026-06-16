"""E2E tests for news and sentiment endpoints.

QA cases: QA-NEWS-001~004.
"""


class TestNewsFlow:
    def test_get_stock_news(self, client):
        """QA-NEWS-001: Stock news retrieval."""
        resp = client.get("/api/v1/stock/000001/news")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "title" in data[0]

    def test_get_stock_anomalies(self, client):
        """QA-NEWS-002: Stock anomaly detection."""
        resp = client.get("/api/v1/stock/000001/anomalies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_hot_rank(self, client):
        """QA-NEWS-003: Market hot rank."""
        resp = client.get("/api/v1/market/hot-rank")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "symbol" in data[0]

    def test_get_stock_sentiment(self, client):
        """QA-NEWS-004: Stock sentiment analysis."""
        resp = client.get("/api/v1/stock/000001/sentiment")
        assert resp.status_code == 200
        data = resp.json()
        assert "symbol" in data
        assert data["symbol"] == "000001"

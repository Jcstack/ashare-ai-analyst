"""E2E tests for sentiment analysis endpoints.

QA cases: QA-SENT-001~004.
"""


class TestSentimentFlow:
    def test_resonance_events(self, client):
        """QA-SENT-001: Resonance endpoint returns a list of events."""
        resp = client.get("/api/v1/sentiment/resonance")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_sentiment_report(self, client):
        """QA-SENT-002: Sentiment report returns structured analysis."""
        resp = client.get("/api/v1/sentiment/report")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_market_pulse(self, client):
        """QA-SENT-003: Market pulse returns combined sentiment data."""
        resp = client.get("/api/v1/sentiment/market-pulse")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_cross_market(self, client):
        """QA-SENT-004: Cross-market analysis returns result with symbol."""
        resp = client.get("/api/v1/sentiment/cross-market/000001")
        assert resp.status_code == 200
        data = resp.json()
        assert "symbol" in data
        assert data["symbol"] == "000001"

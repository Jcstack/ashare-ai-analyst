"""E2E tests for AI agent endpoints.

QA cases: QA-AGENT-001~005.
"""


class TestAgentFlow:
    def test_ai_analysis(self, client):
        """QA-AGENT-001: Comprehensive AI analysis for a stock."""
        resp = client.get("/api/v1/stock/000001/ai-analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_quick_insight(self, client):
        """QA-AGENT-002: Quick AI one-liner insight."""
        resp = client.get("/api/v1/stock/000001/quick-insight")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "symbol" in data

    def test_trigger_analysis(self, client):
        """QA-AGENT-003: Force a fresh comprehensive AI analysis."""
        resp = client.post("/api/v1/stock/000001/analyze")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_market_ai_overview(self, client):
        """QA-AGENT-004: AI-powered market overview."""
        resp = client.get("/api/v1/market/ai-overview")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_chart_events(self, client):
        """QA-AGENT-005: Chart annotation events for a stock."""
        resp = client.get("/api/v1/stock/000001/chart-events")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "symbol" in data
        assert data["symbol"] == "000001"
        assert "events" in data
        assert isinstance(data["events"], list)

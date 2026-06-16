"""E2E tests for strategy lab endpoints.

QA cases: QA-STRATEGY-001~004.
"""


class TestStrategyLabFlow:
    def test_nl_create_strategy(self, client):
        """QA-STRATEGY-001: Create strategy from natural language."""
        resp = client.post(
            "/api/v1/strategy-lab/nl-create",
            json={"description": "当5日均线上穿20日均线时买入"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "strategy_key" in data

    def test_ai_optimize(self, client):
        """QA-STRATEGY-002: AI-driven parameter optimization."""
        resp = client.post(
            "/api/v1/strategy-lab/ai-optimize",
            json={"strategy_key": "ma_cross", "symbol": "000001"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_ai_attribution(self, client):
        """QA-STRATEGY-003: AI backtest attribution analysis."""
        resp = client.post(
            "/api/v1/strategy-lab/ai-attribution",
            json={"strategy_name": "ma_cross", "symbol": "000001"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_latest_signals(self, client):
        """QA-STRATEGY-004: Latest signals for a symbol."""
        resp = client.get("/api/v1/strategy-lab/latest-signals/000001")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

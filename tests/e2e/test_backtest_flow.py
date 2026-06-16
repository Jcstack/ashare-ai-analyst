"""E2E tests for backtest endpoints.

QA cases: QA-BT-001~005.
"""


class TestBacktestFlow:
    def test_list_strategies(self, client):
        """QA-BT-001: GET /api/v1/strategies returns a list of strategies."""
        resp = client.get("/api/v1/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_strategy_metadata(self, client):
        """QA-BT-002: GET /api/v1/strategies/ma_cross/metadata returns 200."""
        resp = client.get("/api/v1/strategies/ma_cross/metadata")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_run_backtest(self, client):
        """QA-BT-003: POST /api/v1/backtest with body returns result with metrics."""
        payload = {
            "symbol": "000001",
            "strategy": "ma_cross",
            "board": "main",
        }
        resp = client.post("/api/v1/backtest", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "metrics" in data

    def test_run_backtest_v2(self, client):
        """QA-BT-004: POST /api/v1/backtest/v2 returns 200."""
        payload = {
            "symbol": "000001",
            "strategy": "ma_cross",
            "board": "main",
        }
        resp = client.post("/api/v1/backtest/v2", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_interpret_backtest(self, client):
        """QA-BT-005: POST /api/v1/backtest/ai-interpret returns 200."""
        payload = {
            "symbol": "000001",
            "strategy_name": "均线交叉",
            "metrics": {
                "annual_return": 0.15,
                "sharpe": 1.2,
                "max_drawdown": -0.08,
            },
            "trades_count": 12,
            "initial_capital": 100000,
            "final_capital": 115000,
        }
        resp = client.post("/api/v1/backtest/ai-interpret", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "status" in data

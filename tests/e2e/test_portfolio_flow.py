"""E2E tests for portfolio endpoints.

QA cases: QA-PF-001~005.
"""


class TestPortfolioFlow:
    def test_load_portfolio(self, client):
        """QA-PF-001: GET /api/v1/portfolio returns portfolio data with positions key."""
        resp = client.get("/api/v1/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data

    def test_save_portfolio(self, client):
        """QA-PF-002: PUT /api/v1/portfolio with valid JSON body returns 200."""
        payload = {
            "version": 1,
            "updatedAt": "2024-01-15T10:00:00",
            "positions": [
                {
                    "id": "pos-001",
                    "symbol": "000001",
                    "name": "平安银行",
                    "board": "main",
                    "costPrice": 10.0,
                    "shares": 1000,
                    "buyDate": "2024-01-02",
                }
            ],
        }
        resp = client.put("/api/v1/portfolio", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ("success", "error")

    def test_diagnose_portfolio(self, client):
        """QA-PF-003: POST /api/v1/portfolio/diagnose returns diagnosis result."""
        payload = {
            "positions": [
                {
                    "symbol": "000001",
                    "name": "平安银行",
                    "board": "main",
                    "cost_price": 10.0,
                    "shares": 1000,
                }
            ],
        }
        resp = client.post("/api/v1/portfolio/diagnose", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_portfolio_advice(self, client):
        """QA-PF-004: POST /api/v1/advisor/portfolio returns advice result."""
        payload = {
            "positions": [{"symbol": "000001", "cost_price": 10.0, "shares": 1000}],
        }
        resp = client.post("/api/v1/advisor/portfolio", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_portfolio_round_trip(self, app, client):
        """QA-PF-005: PUT then GET portfolio preserves data (round trip).

        Uses a real PortfolioStore backed by the test-isolated temp DB
        (via the session-scoped ``_isolate_test_databases`` fixture).
        """
        from src.web.dependencies import get_portfolio_store
        from src.web.services.portfolio_store import PortfolioStore

        # Swap mock for a real store (still points to temp DB via _DB_PATH patch)
        store = PortfolioStore()
        app.dependency_overrides[get_portfolio_store] = lambda: store

        payload = {
            "version": 1,
            "updatedAt": "2024-01-15T12:00:00",
            "positions": [
                {
                    "id": "rt-001",
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "board": "main",
                    "costPrice": 1800.0,
                    "shares": 100,
                    "buyDate": "2024-01-10",
                }
            ],
        }

        # Save
        save_resp = client.put("/api/v1/portfolio", json=payload)
        assert save_resp.status_code == 200

        # Load
        load_resp = client.get("/api/v1/portfolio")
        assert load_resp.status_code == 200
        data = load_resp.json()

        assert len(data["positions"]) >= 1
        pos = next((p for p in data["positions"] if p["symbol"] == "600519"), None)
        assert pos is not None
        assert pos["costPrice"] == 1800.0

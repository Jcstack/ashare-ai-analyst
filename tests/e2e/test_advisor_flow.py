"""E2E tests for trading advisor endpoints.

QA cases: QA-ADV-001~005.
"""


class TestAdvisorFlow:
    def test_stock_advice(self, client):
        """QA-ADV-001: Stock advice returns action and confidence."""
        resp = client.get("/api/v1/advisor/stock/000001")
        assert resp.status_code == 200
        data = resp.json()
        assert "action" in data
        assert "confidence" in data

    def test_watchlist_strategy(self, client):
        """QA-ADV-002: Watchlist strategy returns items list."""
        resp = client.get("/api/v1/advisor/watchlist?symbols=000001,600519")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_portfolio_advice(self, client):
        """QA-ADV-003: Portfolio advice accepts positions and returns response."""
        resp = client.post(
            "/api/v1/advisor/portfolio",
            json={
                "positions": [
                    {"symbol": "000001", "shares": 1000, "cost": 10.0},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_holiday_impact(self, client):
        """QA-ADV-004: Holiday impact assessment returns impact_score."""
        resp = client.get("/api/v1/advisor/holiday-impact/000001")
        assert resp.status_code == 200
        data = resp.json()
        assert "impact_score" in data

    def test_reopen_briefing(self, client):
        """QA-ADV-005: Reopen briefing returns summary."""
        resp = client.get("/api/v1/advisor/reopen-briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data

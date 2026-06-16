"""E2E tests for market endpoints.

QA cases: QA-MKT-001~005.
"""


class TestMarketFlow:
    def test_get_market_indices(self, client):
        """QA-MKT-001: GET /api/v1/market/indices returns a list."""
        resp = client.get("/api/v1/market/indices")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_realtime_quotes(self, client):
        """QA-MKT-002: GET /api/v1/market/realtime?symbols=000001,600519 returns 200."""
        resp = client.get(
            "/api/v1/market/realtime",
            params={"symbols": "000001,600519"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_dragon_tiger(self, client):
        """QA-MKT-003: GET /api/v1/market/dragon-tiger returns 200."""
        resp = client.get("/api/v1/market/dragon-tiger")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_limit_up(self, client):
        """QA-MKT-004: GET /api/v1/market/limit-up returns 200."""
        resp = client.get("/api/v1/market/limit-up")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_trading_calendar(self, client):
        """QA-MKT-005: GET /api/v1/market/calendar returns trading day info."""
        resp = client.get("/api/v1/market/calendar")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_trading_day" in data

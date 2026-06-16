"""E2E tests for stock-related endpoints.

QA cases: QA-DATA-001~005.
"""


class TestStocksFlow:
    def test_get_watchlist(self, client):
        """QA-DATA-001: GET /api/v1/watchlist returns list with symbol/name."""
        resp = client.get("/api/v1/watchlist")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        first = data[0]
        assert "symbol" in first
        assert "name" in first

    def test_get_stock_detail(self, client):
        """QA-DATA-002: GET /api/v1/stock/000001 returns detail with symbol/name/close."""
        resp = client.get("/api/v1/stock/000001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "000001"
        assert "name" in data
        assert "close" in data

    def test_get_ohlcv(self, client):
        """QA-DATA-003: GET /api/v1/stock/000001/ohlcv returns OHLCV records."""
        resp = client.get("/api/v1/stock/000001/ohlcv")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        row = data[0]
        for col in ("date", "open", "high", "low", "close", "volume"):
            assert col in row, f"Missing column: {col}"

    def test_get_indicators(self, client):
        """QA-DATA-004: GET /api/v1/stock/000001/indicators returns values dict."""
        resp = client.get("/api/v1/stock/000001/indicators")
        assert resp.status_code == 200
        data = resp.json()
        assert "values" in data
        assert isinstance(data["values"], dict)

    def test_stock_search(self, client):
        """QA-DATA-005: GET /api/v1/stocks/search?q=平安 returns matching list."""
        resp = client.get("/api/v1/stocks/search", params={"q": "平安"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        first = data[0]
        assert "symbol" in first
        assert "name" in first

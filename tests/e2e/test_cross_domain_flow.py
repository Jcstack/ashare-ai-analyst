"""E2E tests for cross-domain integration flows.

QA cases: QA-CROSS-001~004.
"""


class TestCrossDomainFlow:
    def test_watchlist_to_prediction(self, client):
        """QA-CROSS-001: Fetch watchlist then predict for each symbol."""
        resp = client.get("/api/v1/watchlist")
        assert resp.status_code == 200
        watchlist = resp.json()
        assert isinstance(watchlist, list)
        assert len(watchlist) >= 1

        for item in watchlist:
            symbol = item["symbol"]
            pred_resp = client.post(f"/api/v1/predict/{symbol}")
            assert pred_resp.status_code == 200
            pred_data = pred_resp.json()
            assert isinstance(pred_data, dict)

    def test_stock_detail_full_pipeline(self, client):
        """QA-CROSS-002: Stock detail, indicators, and patterns all return 200."""
        symbol = "000001"

        detail_resp = client.get(f"/api/v1/stock/{symbol}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["symbol"] == symbol

        indicators_resp = client.get(f"/api/v1/stock/{symbol}/indicators")
        assert indicators_resp.status_code == 200
        indicators = indicators_resp.json()
        assert "values" in indicators

        patterns_resp = client.get(f"/api/v1/stock/{symbol}/patterns")
        assert patterns_resp.status_code == 200
        patterns = patterns_resp.json()
        assert isinstance(patterns, list)

    def test_advisor_with_portfolio_context(self, client):
        """QA-CROSS-003: Save portfolio then request advisor advice."""
        portfolio_data = {
            "version": 1,
            "updatedAt": "2026-02-13T12:00:00",
            "positions": [
                {
                    "id": "pos-001",
                    "symbol": "000001",
                    "name": "平安银行",
                    "board": "main",
                    "costPrice": 10.0,
                    "shares": 1000,
                    "buyDate": "2026-01-15",
                },
            ],
        }
        put_resp = client.put("/api/v1/portfolio", json=portfolio_data)
        assert put_resp.status_code == 200

        advisor_resp = client.post(
            "/api/v1/advisor/portfolio",
            json={
                "positions": [
                    {"symbol": "000001", "shares": 1000, "cost": 10.0},
                ],
            },
        )
        assert advisor_resp.status_code == 200
        advice = advisor_resp.json()
        assert isinstance(advice, dict)

    def test_market_overview_pipeline(self, client):
        """QA-CROSS-004: Market indices, realtime quotes, and AI overview all return 200."""
        indices_resp = client.get("/api/v1/market/indices")
        assert indices_resp.status_code == 200
        indices = indices_resp.json()
        assert isinstance(indices, list)

        realtime_resp = client.get("/api/v1/market/realtime")
        assert realtime_resp.status_code == 200
        quotes = realtime_resp.json()
        assert isinstance(quotes, list)

        overview_resp = client.get("/api/v1/market/ai-overview")
        assert overview_resp.status_code == 200
        overview = overview_resp.json()
        assert isinstance(overview, dict)

"""E2E tests for admin and settings endpoints.

QA cases: QA-ADMIN-001~004.
"""


class TestAdminSettingsFlow:
    def test_list_keys(self, client):
        """QA-ADMIN-001: List API keys."""
        resp = client.get("/api/v1/admin/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "provider" in data[0]

    def test_get_usage(self, client):
        """QA-ADMIN-002: Get usage dashboard data."""
        resp = client.get("/api/v1/admin/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_get_config(self, client):
        """QA-ADMIN-003: Read a configuration section."""
        resp = client.get("/api/v1/settings/config/stocks")
        assert resp.status_code == 200
        data = resp.json()
        assert "section" in data
        assert data["section"] == "stocks"
        assert "config" in data

    def test_update_watchlist(self, client):
        """QA-ADMIN-004: Update the watchlist."""
        resp = client.post(
            "/api/v1/settings/watchlist",
            json={
                "watchlist": [
                    {"symbol": "000001", "name": "平安银行", "board": "main"},
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

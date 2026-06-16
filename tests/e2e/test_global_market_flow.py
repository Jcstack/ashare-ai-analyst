"""E2E tests for global market endpoints.

QA cases: QA-GM-001~004.
"""


class TestGlobalMarketFlow:
    def test_global_snapshot(self, client):
        """QA-GM-001: Global market snapshot returns indices, commodities, currencies."""
        resp = client.get("/api/v1/global-market/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert "indices" in data
        assert "commodities" in data
        assert "currencies" in data
        assert isinstance(data["indices"], list)
        assert isinstance(data["commodities"], list)
        assert isinstance(data["currencies"], list)

    def test_global_indices(self, client):
        """QA-GM-002: Global indices endpoint returns list with symbol/name/price."""
        resp = client.get("/api/v1/global-market/indices")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        item = data[0]
        assert "symbol" in item
        assert "name" in item
        assert "price" in item

    def test_global_commodities(self, client):
        """QA-GM-003: Global commodities endpoint returns list."""
        resp = client.get("/api/v1/global-market/commodities")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_global_currencies(self, client):
        """QA-GM-004: Global currencies endpoint returns list."""
        resp = client.get("/api/v1/global-market/currencies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

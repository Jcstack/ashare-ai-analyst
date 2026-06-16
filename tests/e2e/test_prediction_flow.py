"""E2E tests for prediction endpoints.

QA cases: QA-PRED-001~005.
"""


class TestPredictionFlow:
    def test_predict_single(self, client):
        """QA-PRED-001: POST /api/v1/predict/000001 returns prediction result."""
        resp = client.post("/api/v1/predict/000001")
        assert resp.status_code == 200
        data = resp.json()
        assert "trend" in data
        assert "signal" in data
        assert "confidence" in data

    def test_predict_enhanced(self, client):
        """QA-PRED-002: POST /api/v1/predict/000001/enhanced returns 200."""
        resp = client.post(
            "/api/v1/predict/000001/enhanced",
            json={"sources": ["indicators", "fund_flow"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_predict_compare(self, client):
        """QA-PRED-003: POST /api/v1/predict/compare with symbol list returns 200."""
        resp = client.post(
            "/api/v1/predict/compare",
            json={"symbols": ["000001", "600519"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_ai_analysis(self, client):
        """QA-PRED-004: GET /api/v1/stock/000001/ai-analysis returns 200."""
        resp = client.get("/api/v1/stock/000001/ai-analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_quick_insight(self, client):
        """QA-PRED-005: GET /api/v1/stock/000001/quick-insight returns 200."""
        resp = client.get("/api/v1/stock/000001/quick-insight")
        assert resp.status_code == 200
        data = resp.json()
        assert "symbol" in data

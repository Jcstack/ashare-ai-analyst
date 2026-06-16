"""Tests for AI Trading Advisor API routes.

Per PRD v3.2 FR-TA004.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


MOCK_STOCK_ADVICE = {
    "status": "success",
    "symbol": "600519",
    "name": "贵州茅台",
    "action": "buy",
    "action_label": "买入",
    "confidence": 0.75,
    "risk_level": "medium",
    "quant_signals": {
        "technical_score": 0.7,
        "momentum_score": 0.6,
        "strategy_consensus": "看多",
        "bayesian_probability": 0.65,
    },
    "ai_reasoning": ["均线多头排列", "资金净流入"],
    "risk_warnings": ["短期涨幅过大"],
    "target_price": {"low": 1800.0, "high": 2000.0},
    "stop_loss": 1650.0,
    "disclaimer": "AI 分析仅供参考",
    "generated_at": "2026-02-13 15:30:00",
    "model_used": "test",
}

MOCK_HOLIDAY_IMPACT = {
    "status": "success",
    "symbol": "600519",
    "impact_score": 0.6,
    "impact_direction": "neutral",
    "factors": [],
    "ai_assessment": "影响有限",
    "suggested_action": "hold",
    "confidence": 0.5,
    "generated_at": "2026-02-13 15:30:00",
    "disclaimer": "AI 分析仅供参考",
}

MOCK_BRIEFING = {
    "status": "success",
    "market_outlook": "neutral",
    "confidence": 0.5,
    "summary": "市场观望",
    "key_events": ["事件1"],
    "position_impacts": [],
    "recommendations": ["控制仓位"],
    "risk_warnings": ["流动性风险"],
    "generated_at": "2026-02-13 15:30:00",
    "disclaimer": "AI 分析仅供参考",
}


@pytest.fixture
def client():
    """FastAPI TestClient with mocked AdvisorService."""
    from src.web.dependencies import get_advisor_service
    from src.web.routes.api_v1.advisor import router

    mock_svc = MagicMock()
    mock_svc.get_stock_advice.return_value = MOCK_STOCK_ADVICE
    mock_svc.get_watchlist_strategy.return_value = {
        "status": "success",
        "items": [MOCK_STOCK_ADVICE],
        "total": 1,
        "generated_at": "2026-02-13",
        "disclaimer": "AI 分析仅供参考",
    }
    mock_svc.get_portfolio_advice.return_value = {
        "status": "success",
        "positions": [],
        "total": 0,
        "generated_at": "2026-02-13",
        "disclaimer": "AI 分析仅供参考",
    }
    mock_svc.get_holiday_impact.return_value = MOCK_HOLIDAY_IMPACT
    mock_svc.get_reopen_briefing.return_value = MOCK_BRIEFING

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/advisor")
    app.dependency_overrides[get_advisor_service] = lambda: mock_svc

    yield TestClient(app)

    app.dependency_overrides.clear()


class TestAdvisorRoutes:
    def test_stock_advice(self, client):
        resp = client.get("/api/v1/advisor/stock/600519")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["action"] == "buy"
        assert data["confidence"] == 0.75
        assert data["symbol"] == "600519"

    def test_watchlist_strategy(self, client):
        resp = client.get("/api/v1/advisor/watchlist?symbols=600519,300750")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["total"] == 1

    def test_portfolio_advice(self, client):
        resp = client.post(
            "/api/v1/advisor/portfolio",
            json={
                "positions": [{"symbol": "600519", "cost_price": 1800, "shares": 100}]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_holiday_impact(self, client):
        resp = client.get("/api/v1/advisor/holiday-impact/600519")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["impact_direction"] == "neutral"

    def test_reopen_briefing(self, client):
        resp = client.get("/api/v1/advisor/reopen-briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["market_outlook"] == "neutral"


class TestAdvisorServiceSectorInfo:
    """Test that AdvisorService includes sector_info in gathered data."""

    def test_gather_stock_data_includes_sector_info(self):
        from src.web.services.advisor_service import AdvisorService

        mock_stock_svc = MagicMock()
        mock_stock_svc.get_stock_sector_info.return_value = {
            "industry": "文化传媒",
            "concepts": [{"name": "影视院线", "pct_change": 3.0}],
            "resonance": {"level": "none"},
        }
        mock_stock_svc.get_stock_detail.return_value = {"board": "main"}
        mock_stock_svc.get_indicators_summary.return_value = None
        mock_stock_svc.get_stock_with_indicators.return_value = None
        mock_stock_svc.fetcher.fetch_fund_flow.return_value = None

        svc = AdvisorService(stock_service=mock_stock_svc)
        data = svc._gather_stock_data("001330")

        assert "sector_info" in data
        assert data["sector_info"]["industry"] == "文化传媒"
        mock_stock_svc.get_stock_sector_info.assert_called_once_with("001330")

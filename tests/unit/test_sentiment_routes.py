"""Tests for sentiment API routes (FR-TN003~005, FR-GM004)."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.dependencies import get_sentiment_service


def _mock_sentiment_service():
    svc = MagicMock()
    svc.get_resonance_events.return_value = {
        "status": "success",
        "events": [
            {
                "event_id": "evt-0001",
                "title": "春节档票房突破50亿",
                "resonance_level": "L3",
                "platforms": ["eastmoney", "cls", "toutiao", "weibo", "baidu"],
                "rank_timeline": [],
                "related_stocks": ["001330"],
                "sentiment": "positive",
                "first_appeared": "2026-02-13 10:00",
                "last_updated": "2026-02-13 14:00",
                "heat_score": 0.9,
            }
        ],
        "total": 1,
        "generated_at": "2026-02-13 14:00:00",
    }
    svc.get_sentiment_report.return_value = {
        "status": "success",
        "core_trends": [
            {
                "topic": "春节档票房",
                "resonance_level": "L3",
                "sentiment": "positive",
                "related_stocks": ["001330"],
                "summary": "春节档票房创纪录",
            }
        ],
        "policy_signals": [],
        "global_linkage": {
            "us_market_summary": "美股小幅上涨",
            "commodity_impact": "",
            "forex_impact": "",
        },
        "risk_alerts": [],
        "sector_outlook": {"bullish": ["entertainment"], "bearish": [], "neutral": []},
        "overall_outlook": "整体偏积极",
        "generated_at": "2026-02-13 14:00:00",
        "disclaimer": "仅供参考",
    }
    svc.get_market_pulse.return_value = {
        "status": "success",
        "hot_events": [],
        "holdings_news": {},
        "global_snapshot": None,
        "generated_at": "2026-02-13 14:00:00",
    }
    svc.get_cross_market_analysis.return_value = {
        "symbol": "001330",
        "tags": ["entertainment"],
        "us_market": {"trend": "positive", "peers": [], "impact_score": 0.3},
        "hk_market": {"trend": "neutral", "peers": [], "impact_score": 0.0},
        "commodity_exposure": {"trend": "neutral", "peers": [], "impact_score": 0.0},
        "global_indices": {"trend": "neutral", "impact_score": 0.0},
        "combined_impact_score": 0.15,
        "impact_direction": "positive",
        "generated_at": "2026-02-13 14:00:00",
    }
    return svc


def _create_test_client():
    app = create_app()
    mock_svc = _mock_sentiment_service()
    app.dependency_overrides[get_sentiment_service] = lambda: mock_svc
    return TestClient(app), mock_svc


class TestResonanceEndpoint:
    def test_get_resonance_events(self):
        client, svc = _create_test_client()
        resp = client.get("/api/v1/sentiment/resonance?symbols=001330,600519")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["events"]) == 1
        assert data["events"][0]["resonance_level"] == "L3"

    def test_get_resonance_no_symbols(self):
        client, svc = _create_test_client()
        resp = client.get("/api/v1/sentiment/resonance")
        assert resp.status_code == 200


class TestSentimentReportEndpoint:
    def test_get_report(self):
        client, svc = _create_test_client()
        resp = client.get("/api/v1/sentiment/report?symbols=001330")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["core_trends"]) == 1
        assert data["overall_outlook"] == "整体偏积极"


class TestMarketPulseEndpoint:
    def test_get_pulse(self):
        client, svc = _create_test_client()
        resp = client.get("/api/v1/sentiment/market-pulse")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"


class TestCrossMarketEndpoint:
    def test_get_cross_market(self):
        client, svc = _create_test_client()
        resp = client.get("/api/v1/sentiment/cross-market/001330")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "001330"
        assert data["impact_direction"] == "positive"
        assert "combined_impact_score" in data

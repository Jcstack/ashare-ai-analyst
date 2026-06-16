"""Tests for Holiday Research Workbench API routes.

Per holiday research endpoints: context, notes CRUD, analyze, ask.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


MOCK_CONTEXT = {
    "status": "success",
    "symbol": "001330",
    "holiday_key": "2026-02-24",
    "news": [
        {"title": "博纳新闻", "datetime": "2026-02-13", "source": "东方财富", "url": ""}
    ],
    "concepts": [
        {"name": "影视", "pct_change": 2.5, "rank_in_concept": 3, "concept_size": 20}
    ],
    "global_market": {},
    "cross_market": {},
    "sentiment_matches": [],
    "user_notes": [],
    "calendar_info": {"is_holiday_period": True, "next_trading_day": "2026-02-24"},
}

MOCK_NOTE = {
    "id": "abc12345",
    "content": "票房3亿",
    "note_type": "box_office",
    "created_at": "2026-02-13 15:30:00",
}

MOCK_ANALYSIS = {
    "status": "success",
    "symbol": "001330",
    "business_factors": [
        {"name": "票房", "impact": "positive", "weight": 0.8, "analysis": "超预期"}
    ],
    "sector_analysis": {
        "summary": "看好",
        "key_concepts": ["影视"],
        "sector_trend": "bullish",
    },
    "peer_comparison": {"summary": "同行上涨", "us_peers": [], "hk_peers": []},
    "risk_matrix": [],
    "reopening_strategy": {
        "action": "add",
        "confidence": 0.7,
        "reasoning": "利好",
        "target_range": [10.0, 12.0],
        "stop_loss": 8.5,
    },
    "key_watch_items": ["票房走势"],
    "overall_assessment": "整体看好",
    "generated_at": "2026-02-13 15:30:00",
    "disclaimer": "AI 分析仅供参考",
}

MOCK_CONVERSATION = [
    {"role": "user", "content": "票房影响有多大", "timestamp": "2026-02-13 15:30:00"},
    {
        "role": "assistant",
        "content": "票房超预期会直接提升EPS预期...",
        "timestamp": "2026-02-13 15:30:01",
    },
]

MOCK_FOLLOWUP = {
    "status": "success",
    "question": "票房影响有多大",
    "answer": "票房超预期会直接提升EPS预期...",
    "generated_at": "2026-02-13 15:31:00",
    "disclaimer": "AI 分析仅供参考",
    "messages": MOCK_CONVERSATION,
}

MOCK_EVIDENCE = {
    "id": "ev12345",
    "content": "猫眼数据: 首日票房3.2亿",
    "evidence_type": "data_point",
    "linked_question_id": "q1",
    "impact": "bullish",
    "confidence": "high",
    "source": "猫眼专业版",
    "created_at": "2026-02-13 16:00:00",
}

MOCK_CHECKLIST = {
    "status": "success",
    "symbol": "001330",
    "questions": [
        {
            "id": "q1",
            "category": "industry_event",
            "text": "春节档票房表现如何？",
            "priority": "high",
            "data_hint": "猫眼专业版查看",
            "status": "pending",
        }
    ],
    "generated_at": "2026-02-13 16:00:00",
}

MOCK_SCENARIO_RESULT = {
    "status": "success",
    "symbol": "001330",
    "scenarios": [
        {
            "name": "乐观",
            "probability": "medium",
            "price_impact": {"direction": "up", "magnitude": "large"},
            "key_drivers": ["票房超预期"],
            "risks": [],
            "reasoning": "如果票房超预期...",
        }
    ],
    "generated_at": "2026-02-13 16:00:00",
    "disclaimer": "AI 分析仅供参考",
}


@pytest.fixture
def client():
    """FastAPI TestClient with mocked HolidayResearchService."""
    from src.web.dependencies import get_holiday_research_service
    from src.web.routes.api_v1.holiday_research import router

    mock_svc = MagicMock()
    mock_svc.collect_context.return_value = MOCK_CONTEXT
    mock_svc.get_user_notes.return_value = [MOCK_NOTE]
    mock_svc.add_user_note.return_value = MOCK_NOTE
    mock_svc.delete_user_note.return_value = True
    mock_svc.get_evidence.return_value = [MOCK_EVIDENCE]
    mock_svc.add_evidence.return_value = MOCK_EVIDENCE
    mock_svc.delete_evidence.return_value = True
    mock_svc.generate_research_questions.return_value = MOCK_CHECKLIST
    mock_svc.analyze_scenarios.return_value = MOCK_SCENARIO_RESULT
    mock_svc.analyze_comprehensive.return_value = MOCK_ANALYSIS
    mock_svc.ask_followup.return_value = MOCK_FOLLOWUP
    mock_svc.get_conversation.return_value = MOCK_CONVERSATION
    mock_svc.clear_conversation.return_value = True
    mock_svc._get_holiday_key.return_value = "2026-02-24"

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/advisor/holiday-research")
    app.dependency_overrides[get_holiday_research_service] = lambda: mock_svc

    yield TestClient(app)

    app.dependency_overrides.clear()


class TestHolidayResearchRoutes:
    def test_get_context(self, client):
        resp = client.get("/api/v1/advisor/holiday-research/001330/context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["symbol"] == "001330"
        assert len(data["news"]) == 1

    def test_add_note(self, client):
        resp = client.post(
            "/api/v1/advisor/holiday-research/001330/notes",
            json={"content": "票房3亿", "note_type": "box_office"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "票房3亿"
        assert data["note_type"] == "box_office"

    def test_delete_note(self, client):
        resp = client.delete("/api/v1/advisor/holiday-research/001330/notes/abc12345")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_analyze(self, client):
        resp = client.post("/api/v1/advisor/holiday-research/001330/analyze")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["reopening_strategy"]["action"] == "add"
        assert len(data["business_factors"]) == 1

    def test_ask_followup(self, client):
        resp = client.post(
            "/api/v1/advisor/holiday-research/001330/ask",
            json={"question": "票房影响有多大"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["question"] == "票房影响有多大"
        assert "EPS" in data["answer"]
        assert "messages" in data
        assert len(data["messages"]) == 2

    def test_get_conversation(self, client):
        resp = client.get("/api/v1/advisor/holiday-research/001330/conversation")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["role"] == "user"
        assert data[1]["role"] == "assistant"

    def test_clear_conversation(self, client):
        resp = client.delete("/api/v1/advisor/holiday-research/001330/conversation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    # --- v3.4: Evidence endpoints ---

    def test_get_evidence(self, client):
        resp = client.get("/api/v1/advisor/holiday-research/001330/evidence")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["content"] == "猫眼数据: 首日票房3.2亿"
        assert data[0]["impact"] == "bullish"

    def test_add_evidence(self, client):
        resp = client.post(
            "/api/v1/advisor/holiday-research/001330/evidence",
            json={
                "content": "票房3.2亿",
                "evidence_type": "data_point",
                "linked_question_id": "q1",
                "impact": "bullish",
                "confidence": "high",
                "source": "猫眼",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["evidence_type"] == "data_point"

    def test_delete_evidence(self, client):
        resp = client.delete("/api/v1/advisor/holiday-research/001330/evidence/ev12345")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    # --- v3.4: Research Questions ---

    def test_generate_research_questions(self, client):
        resp = client.post("/api/v1/advisor/holiday-research/001330/research-questions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["questions"]) == 1
        assert data["questions"][0]["category"] == "industry_event"

    # --- v3.4: Scenario Analysis ---

    def test_analyze_scenarios(self, client):
        resp = client.post("/api/v1/advisor/holiday-research/001330/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["scenarios"]) == 1
        assert data["scenarios"][0]["name"] == "乐观"

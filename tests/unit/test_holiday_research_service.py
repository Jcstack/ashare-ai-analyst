"""Tests for HolidayResearchService.

Covers context collection, graceful degradation, note CRUD, Redis fallback,
analysis prompt building, LLM response parsing, and follow-up Q&A.
"""

from unittest.mock import MagicMock

import pytest

from src.web.services.holiday_research_service import HolidayResearchService


@pytest.fixture
def svc():
    """Return a HolidayResearchService with mocked dependencies."""
    mock_stock_service = MagicMock()
    mock_stock_service.get_stock_detail.return_value = {
        "name": "博纳影业",
        "symbol": "001330",
        "board": "主板",
    }
    s = HolidayResearchService(
        stock_service=mock_stock_service,
        advisor_service=MagicMock(),
    )
    # Force Redis unavailable for deterministic tests
    s._redis_checked = True
    s._redis = None
    return s


class TestCollectContext:
    def test_returns_complete_structure(self, svc):
        """collect_context returns all expected keys even when data sources fail."""
        # All internal fetchers will raise because they're not mocked,
        # but the service should gracefully degrade.
        result = svc.collect_context("001330")
        assert result["status"] == "success"
        assert result["symbol"] == "001330"
        assert "news" in result
        assert "concepts" in result
        assert "global_market" in result
        assert "cross_market" in result
        assert "sentiment_matches" in result
        assert "user_notes" in result
        assert "calendar_info" in result

    def test_news_failure_returns_empty(self, svc):
        """If news fetcher fails, news should be empty list."""
        svc._news_fetcher = MagicMock()
        svc._news_fetcher.fetch_stock_news.side_effect = Exception("network error")
        news = svc._collect_news("001330")
        assert news == []

    def test_concepts_failure_returns_empty(self, svc):
        """If concept analyzer fails, concepts should be empty list."""
        svc._concept_analyzer = MagicMock()
        svc._concept_analyzer.analyze_stock_concepts.side_effect = Exception("fail")
        concepts = svc._collect_concepts("001330")
        assert concepts == []

    def test_global_market_failure_returns_empty(self, svc):
        """If global market fetcher fails, result should be empty dict."""
        svc._global_fetcher = MagicMock()
        svc._global_fetcher.fetch_global_snapshot.side_effect = Exception("fail")
        result = svc._collect_global_market()
        assert result == {}


class TestUserNotes:
    def test_notes_without_redis_returns_empty(self, svc):
        """When Redis is unavailable, get_user_notes returns empty list."""
        notes = svc.get_user_notes("001330", "2026-02-24")
        assert notes == []

    def test_add_note_returns_note(self, svc):
        """add_user_note returns a note dict even without Redis."""
        note = svc.add_user_note("001330", "2026-02-24", "票房3亿", "box_office")
        assert note["content"] == "票房3亿"
        assert note["note_type"] == "box_office"
        assert note["id"] != ""

    def test_delete_note_without_redis_returns_false(self, svc):
        """delete_user_note returns False when Redis is unavailable."""
        assert svc.delete_user_note("001330", "2026-02-24", "abc") is False

    def test_notes_crud_with_mock_redis(self, svc):
        """Full CRUD cycle with mock Redis."""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = None
        svc._redis = mock_redis
        svc._redis_checked = True

        # Add a note
        note = svc.add_user_note("001330", "2026-02-24", "test note", "observation")
        assert note["content"] == "test note"
        assert mock_redis.set.called


class TestAnalysis:
    def test_parse_analysis_valid_json(self, svc):
        """_parse_analysis correctly extracts structured fields from JSON."""
        raw = """```json
{
  "business_factors": [{"name": "春节档票房", "impact": "positive", "weight": 0.8, "analysis": "票房超预期"}],
  "sector_analysis": {"summary": "影视板块看好", "key_concepts": ["影视"], "sector_trend": "bullish"},
  "peer_comparison": {"summary": "海外同行上涨", "us_peers": [], "hk_peers": []},
  "risk_matrix": [{"risk": "票房不及预期", "probability": "medium", "impact": "high", "mitigation": "分散投资"}],
  "reopening_strategy": {"action": "add", "confidence": 0.7, "reasoning": "利好", "target_range": [10.0, 12.0], "stop_loss": 8.5},
  "key_watch_items": ["首周票房", "口碑"],
  "overall_assessment": "整体看好"
}
```"""
        result = svc._parse_analysis(raw, "001330")
        assert result["status"] == "success"
        assert result["symbol"] == "001330"
        assert len(result["business_factors"]) == 1
        assert result["business_factors"][0]["name"] == "春节档票房"
        assert result["reopening_strategy"]["action"] == "add"
        assert result["overall_assessment"] == "整体看好"

    def test_parse_analysis_invalid_json_uses_raw(self, svc):
        """_parse_analysis falls back to raw text when JSON is invalid."""
        result = svc._parse_analysis("这是一段无结构分析", "001330")
        assert result["status"] == "success"
        assert result["overall_assessment"] == "这是一段无结构分析"

    def test_build_analysis_prompt_includes_sections(self, svc):
        """_build_analysis_prompt includes all data sections."""
        context = {
            "news": [
                {
                    "title": "博纳新闻",
                    "datetime": "2026-02-13",
                    "source": "东方财富",
                    "url": "",
                }
            ],
            "concepts": [
                {
                    "name": "影视",
                    "pct_change": 2.5,
                    "rank_in_concept": 3,
                    "concept_size": 20,
                }
            ],
            "global_market": {
                "indices": [{"name": "S&P 500", "pct_change": 1.0}],
                "commodities": [{"name": "黄金", "pct_change": 0.5}],
            },
            "cross_market": {"overall_score": 0.6},
            "sentiment_matches": [
                {"title": "热点", "platform": "微博", "heat_score": 80}
            ],
            "calendar_info": {
                "next_trading_day": "2026-02-24",
                "is_holiday_period": True,
            },
        }
        notes = [{"content": "票房3亿", "note_type": "box_office"}]

        prompt = svc._build_analysis_prompt("001330", "博纳影业", context, notes)
        assert "博纳影业" in prompt
        assert "001330" in prompt
        assert "博纳新闻" in prompt
        assert "影视" in prompt
        assert "S&P 500" in prompt
        assert "票房3亿" in prompt
        assert "ticket" not in prompt  # No English in Chinese sections


# ── v3.4: Evidence ───────────────────────────────────────────────────


class TestEvidence:
    def test_evidence_without_redis_returns_empty(self, svc):
        """When Redis is unavailable, get_evidence returns empty list."""
        evidence = svc.get_evidence("001330", "2026-02-24")
        assert evidence == []

    def test_add_evidence_returns_item(self, svc):
        """add_evidence returns an evidence dict even without Redis."""
        item = svc.add_evidence(
            "001330",
            "2026-02-24",
            "票房3.2亿",
            "data_point",
            "q1",
            "bullish",
            "high",
            "猫眼",
        )
        assert item["content"] == "票房3.2亿"
        assert item["evidence_type"] == "data_point"
        assert item["linked_question_id"] == "q1"
        assert item["impact"] == "bullish"
        assert item["confidence"] == "high"
        assert item["source"] == "猫眼"
        assert item["id"] != ""

    def test_delete_evidence_without_redis_returns_false(self, svc):
        """delete_evidence returns False when Redis is unavailable."""
        assert svc.delete_evidence("001330", "2026-02-24", "abc") is False

    def test_evidence_crud_with_mock_redis(self, svc):
        """Full evidence CRUD cycle with mock Redis."""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = None
        svc._redis = mock_redis
        svc._redis_checked = True

        item = svc.add_evidence(
            "001330",
            "2026-02-24",
            "test evidence",
            "observation",
            "",
            "neutral",
            "medium",
            "",
        )
        assert item["content"] == "test evidence"
        assert mock_redis.set.called


# ── Conversation (multi-turn) ────────────────────────────────────────


class TestConversation:
    def test_conversation_without_redis_returns_empty(self, svc):
        """When Redis is unavailable, get_conversation returns empty list."""
        messages = svc.get_conversation("001330", "2026-02-24")
        assert messages == []

    def test_clear_conversation_without_redis_returns_false(self, svc):
        """clear_conversation returns False when Redis is unavailable."""
        assert svc.clear_conversation("001330", "2026-02-24") is False

    def test_conversation_crud_with_mock_redis(self, svc):
        """Full conversation CRUD cycle with mock Redis."""
        import json

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = None
        svc._redis = mock_redis
        svc._redis_checked = True

        # Initially empty
        assert svc.get_conversation("001330", "2026-02-24") == []

        # Save conversation
        msgs = [
            {
                "role": "user",
                "content": "票房怎么样?",
                "timestamp": "2026-02-14 10:00:00",
            },
            {
                "role": "assistant",
                "content": "首日3亿",
                "timestamp": "2026-02-14 10:00:01",
            },
        ]
        svc._save_conversation("001330", "2026-02-24", msgs)
        assert mock_redis.set.called
        call_args = mock_redis.set.call_args
        saved_json = json.loads(call_args[0][1])
        assert len(saved_json) == 2
        assert saved_json[0]["role"] == "user"

    def test_clear_conversation_with_mock_redis(self, svc):
        """clear_conversation deletes Redis key."""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.delete.return_value = 1
        svc._redis = mock_redis
        svc._redis_checked = True

        result = svc.clear_conversation("001330", "2026-02-24")
        assert result is True
        assert mock_redis.delete.called


# ── v3.4: Research Questions ─────────────────────────────────────────


class TestResearchQuestions:
    def test_parse_questions_valid_json(self, svc):
        """_parse_questions correctly extracts structured questions."""
        raw = """```json
{
  "questions": [
    {
      "id": "q1",
      "category": "industry_event",
      "text": "春节档票房表现如何？",
      "priority": "high",
      "data_hint": "猫眼专业版查看",
      "status": "pending"
    },
    {
      "id": "q2",
      "category": "competitor",
      "text": "竞品电影表现？",
      "priority": "medium",
      "data_hint": "灯塔专业版",
      "status": "pending"
    }
  ]
}
```"""
        questions = svc._parse_questions(raw)
        assert len(questions) == 2
        assert questions[0]["category"] == "industry_event"
        assert questions[0]["text"] == "春节档票房表现如何？"

    def test_parse_questions_invalid_json(self, svc):
        """_parse_questions returns empty list on bad JSON."""
        questions = svc._parse_questions("not valid json")
        assert questions == []


# ── v3.4: Scenario Analysis ─────────────────────────────────────────


class TestScenarioAnalysis:
    def test_parse_scenarios_valid_json(self, svc):
        """_parse_scenarios correctly extracts scenario results."""
        raw = """```json
{
  "scenarios": [
    {
      "name": "乐观",
      "probability": "medium",
      "price_impact": {"direction": "up", "magnitude": "large"},
      "key_drivers": ["票房超预期"],
      "risks": ["口碑风险"],
      "reasoning": "如果票房超预期..."
    },
    {
      "name": "悲观",
      "probability": "low",
      "price_impact": {"direction": "down", "magnitude": "small"},
      "key_drivers": ["票房不及预期"],
      "risks": [],
      "reasoning": "如果票房不及预期..."
    }
  ]
}
```"""
        scenarios = svc._parse_scenarios(raw)
        assert len(scenarios) == 2
        assert scenarios[0]["name"] == "乐观"
        assert scenarios[0]["price_impact"]["direction"] == "up"
        assert scenarios[1]["probability"] == "low"

    def test_parse_scenarios_invalid_json(self, svc):
        """_parse_scenarios returns empty list on bad JSON."""
        scenarios = svc._parse_scenarios("invalid")
        assert scenarios == []


# ── v3.4: Association Profile in Context ─────────────────────────────


class TestAssociationProfileContext:
    def test_collect_context_includes_association_profile(self, svc):
        """collect_context includes association_profile key."""
        result = svc.collect_context("001330")
        assert "association_profile" in result

    def test_parse_analysis_with_evidence_completeness(self, svc):
        """_parse_analysis extracts v3.4 fields."""
        raw = """```json
{
  "business_factors": [],
  "sector_analysis": {"summary": "", "key_concepts": [], "sector_trend": "neutral"},
  "peer_comparison": {"summary": "", "us_peers": [], "hk_peers": []},
  "risk_matrix": [],
  "reopening_strategy": {"action": "hold", "confidence": 0.5, "reasoning": "", "target_range": [], "stop_loss": null},
  "key_watch_items": [],
  "overall_assessment": "整体中性",
  "evidence_completeness": 0.75,
  "association_context": "影视传媒行业，关联概念包括影视院线"
}
```"""
        result = svc._parse_analysis(raw, "001330")
        assert result["evidence_completeness"] == 0.75
        assert result["association_context"] == "影视传媒行业，关联概念包括影视院线"

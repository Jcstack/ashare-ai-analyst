"""Unit tests for ConversationService (v11.0).

Tests cover:
- Session lifecycle (start → followup → clear)
- Context summary building
- Suggested question generation
- Position context injection
- Redis unavailability graceful degradation
- Holiday awareness
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.web.services.conversation_service import ConversationService


# --- Fixtures ---


@pytest.fixture
def mock_quote_manager():
    mgr = MagicMock()
    mgr.get_single_quote.return_value = {
        "price": 12.77,
        "change": 0.08,
        "pct_change": 0.63,
        "volume": 1234567,
        "open": 12.70,
        "high": 12.90,
        "low": 12.60,
        "name": "博纳影业",
    }
    return mgr


@pytest.fixture
def mock_trading_calendar():
    cal = MagicMock()
    cal.is_holiday_period.return_value = False
    cal.next_trading_day.return_value = "2026-02-16"
    return cal


@pytest.fixture
def mock_analysis_result():
    return {
        "status": "ok",
        "symbol": "001330",
        "action": "watch",
        "action_label": "建议观望",
        "confidence": {"score": 0.72, "label": "中等", "basis": ["技术面偏弱"]},
        "risk_level": "medium",
        "summary": "近期主力资金流出，技术面偏弱。",
        "dimensions": [
            {
                "key": "technical",
                "label": "技术面",
                "signal": "bearish",
                "score": 0.75,
                "reasoning": "均线空头排列",
            },
            {
                "key": "capital",
                "label": "资金面",
                "signal": "bearish",
                "score": 0.60,
                "reasoning": "主力资金流出",
            },
        ],
        "risk_warnings": [
            {"type": "market", "description": "短期下行风险", "data_reference": ""}
        ],
        "contrarian_check": "注意反弹可能",
        "data_references": [],
        "disclaimer": "AI 分析仅供参考",
        "model_used": "claude-3-haiku",
        "generated_at": "2026-02-14 15:00:00",
    }


@pytest.fixture
def service(mock_quote_manager, mock_trading_calendar):
    return ConversationService(
        stock_service=MagicMock(),
        realtime_analyzer=MagicMock(),
        quote_manager=mock_quote_manager,
        trading_calendar=mock_trading_calendar,
        global_market_fetcher=MagicMock(),
    )


# --- Start Conversation ---


class TestStartConversation:
    def test_returns_session_id(self, service, mock_analysis_result):
        result = service.start_conversation("001330", mock_analysis_result)
        assert result["status"] == "ok"
        assert len(result["session_id"]) == 12
        assert result["symbol"] == "001330"

    def test_returns_analysis(self, service, mock_analysis_result):
        result = service.start_conversation("001330", mock_analysis_result)
        assert result["analysis"] is not None
        assert result["analysis"]["action"] == "watch"

    def test_returns_initial_message(self, service, mock_analysis_result):
        result = service.start_conversation("001330", mock_analysis_result)
        messages = result["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"
        assert "建议观望" in messages[0]["content"]

    def test_returns_suggested_questions(self, service, mock_analysis_result):
        result = service.start_conversation("001330", mock_analysis_result)
        suggestions = result["suggested_questions"]
        assert len(suggestions) >= 1
        assert len(suggestions) <= 4

    def test_with_position(self, service, mock_analysis_result):
        position = {"cost_price": 13.00, "shares": 1000, "holding_days": 5}
        result = service.start_conversation(
            "001330", mock_analysis_result, position=position
        )
        assert result["status"] == "ok"
        # Position-aware suggestions should include holding advice
        assert any("持仓" in q or "操作" in q for q in result["suggested_questions"])

    def test_disclaimer_present(self, service, mock_analysis_result):
        result = service.start_conversation("001330", mock_analysis_result)
        assert "仅供参考" in result["disclaimer"]


# --- Continue Conversation ---


class TestContinueConversation:
    def test_no_session_returns_error(self, service):
        result = service.continue_conversation("001330", "nonexistent", "你好")
        assert result["status"] == "error"
        assert "不存在" in result.get("message", "")

    @patch.object(ConversationService, "_get_redis")
    def test_with_session(self, mock_redis_fn, service, mock_analysis_result):
        # Setup fake Redis with stored session
        fake_redis = MagicMock()
        session_data = {
            "symbol": "001330",
            "analysis": mock_analysis_result,
            "position": None,
            "messages": [
                {
                    "role": "assistant",
                    "content": "分析完成",
                    "timestamp": "2026-02-14 15:00:00",
                }
            ],
            "created_at": "2026-02-14 15:00:00",
        }
        fake_redis.get.return_value = json.dumps(session_data)
        mock_redis_fn.return_value = fake_redis

        # Mock LLM router
        mock_response = MagicMock()
        mock_response.text = "这只股票近期偏弱，建议观望。"
        mock_response.model = "claude-3-haiku"
        service._router = MagicMock()
        service._router.complete.return_value = mock_response

        result = service.continue_conversation("001330", "abc123", "该买吗？")

        assert result["status"] == "ok"
        assert len(result["messages"]) == 3  # original + user + assistant
        assert result["messages"][-1]["role"] == "assistant"
        assert "偏弱" in result["messages"][-1]["content"]

    @patch.object(ConversationService, "_get_redis")
    def test_followup_llm_failure(self, mock_redis_fn, service, mock_analysis_result):
        fake_redis = MagicMock()
        session_data = {
            "symbol": "001330",
            "analysis": mock_analysis_result,
            "position": None,
            "messages": [],
            "created_at": "2026-02-14 15:00:00",
        }
        fake_redis.get.return_value = json.dumps(session_data)
        mock_redis_fn.return_value = fake_redis

        service._router = MagicMock()
        service._router.complete.side_effect = RuntimeError("LLM down")

        result = service.continue_conversation("001330", "abc123", "该买吗？")
        assert result["status"] == "error"
        assert "不可用" in result.get("message", "")
        # User message should be removed on failure
        assert all(m["role"] != "user" for m in result["messages"])


# --- Clear Conversation ---


class TestClearConversation:
    def test_clear_ok(self, service):
        result = service.clear_conversation("001330", "session123")
        assert result["status"] == "ok"


# --- Context Summary ---


class TestBuildContextSummary:
    def test_basic_summary(self, service, mock_analysis_result):
        summary = service._build_context_summary(
            "001330",
            mock_analysis_result,
            {"price": 12.77, "pct_change": 0.63},
            None,
        )
        assert "001330" in summary
        assert "12.77" in summary
        assert "建议观望" in summary
        assert "技术面" in summary

    def test_with_position_context(self, service, mock_analysis_result):
        summary = service._build_context_summary(
            "001330",
            mock_analysis_result,
            {"price": 12.77, "pct_change": 0.63},
            {"cost_price": 13.00, "shares": 1000, "holding_days": 5},
        )
        assert "成本价" in summary
        assert "浮盈" in summary or "浮亏" in summary or "亏" in summary
        assert "持仓天数" in summary

    def test_without_quote(self, service, mock_analysis_result):
        summary = service._build_context_summary(
            "001330", mock_analysis_result, None, None
        )
        assert "001330" in summary
        # Should not crash without quote

    def test_holiday_context(self, service, mock_analysis_result):
        service._trading_calendar.is_holiday_period.return_value = True
        summary = service._build_context_summary(
            "001330", mock_analysis_result, None, None
        )
        assert "假期" in summary


# --- Suggested Questions ---


class TestSuggestedQuestions:
    def test_no_position(self, service, mock_analysis_result):
        suggestions = service._generate_suggestions(
            "001330", mock_analysis_result, None, None
        )
        assert len(suggestions) >= 1
        assert len(suggestions) <= 4

    def test_with_position(self, service, mock_analysis_result):
        suggestions = service._generate_suggestions(
            "001330",
            mock_analysis_result,
            {"cost_price": 13.00, "shares": 1000},
            None,
        )
        assert any("持仓" in q or "操作" in q for q in suggestions)

    def test_high_risk(self, service, mock_analysis_result):
        mock_analysis_result["risk_level"] = "high"
        suggestions = service._generate_suggestions(
            "001330", mock_analysis_result, None, None
        )
        assert any("风险" in q for q in suggestions)

    def test_holiday_period(self, service, mock_analysis_result):
        service._trading_calendar.is_holiday_period.return_value = True
        suggestions = service._generate_suggestions(
            "001330", mock_analysis_result, None, None
        )
        assert any("假期" in q for q in suggestions)

    def test_big_move_up(self, service, mock_analysis_result):
        suggestions = service._generate_suggestions(
            "001330",
            mock_analysis_result,
            None,
            {"pct_change": 8.5},
        )
        assert any("涨" in q for q in suggestions)

    def test_big_move_down(self, service, mock_analysis_result):
        suggestions = service._generate_suggestions(
            "001330",
            mock_analysis_result,
            None,
            {"pct_change": -6.0},
        )
        assert any("跌" in q for q in suggestions)

    def test_buy_action_no_position(self, service, mock_analysis_result):
        mock_analysis_result["action"] = "buy"
        suggestions = service._generate_suggestions(
            "001330", mock_analysis_result, None, None
        )
        assert any("建仓" in q or "买" in q for q in suggestions)


# --- Redis Graceful Degradation ---


class TestRedisUnavailable:
    def test_start_without_redis(self, mock_analysis_result, mock_quote_manager):
        svc = ConversationService(quote_manager=mock_quote_manager)
        # Should work even without Redis (no persistence)
        result = svc.start_conversation("001330", mock_analysis_result)
        assert result["status"] == "ok"

    def test_continue_without_redis(self, mock_quote_manager):
        svc = ConversationService(quote_manager=mock_quote_manager)
        result = svc.continue_conversation("001330", "abc", "hello")
        assert result["status"] == "error"  # No session found

    def test_clear_without_redis(self):
        svc = ConversationService()
        result = svc.clear_conversation("001330", "abc")
        assert result["status"] == "ok"


# --- Holiday Research Quote Fix ---


class TestHolidayResearchQuoteFix:
    """Verify that holiday_research_service now injects quotes."""

    def test_collect_quote_exists(self):
        from src.web.services.holiday_research_service import HolidayResearchService

        svc = HolidayResearchService()
        assert hasattr(svc, "_collect_quote")

    def test_collect_quote_returns_dict(self):
        from src.web.services.holiday_research_service import HolidayResearchService

        svc = HolidayResearchService()
        # With a mock quote manager
        mock_mgr = MagicMock()
        mock_mgr.get_single_quote.return_value = {
            "price": 12.77,
            "pct_change": 0.63,
            "volume": 100000,
            "open": 12.70,
            "high": 12.90,
            "low": 12.60,
        }
        svc._quote_manager = mock_mgr

        result = svc._collect_quote("001330")
        assert result["price"] == 12.77

    def test_collect_quote_failure_returns_empty(self):
        from src.web.services.holiday_research_service import HolidayResearchService

        svc = HolidayResearchService()
        mock_mgr = MagicMock()
        mock_mgr.get_single_quote.side_effect = RuntimeError("network error")
        svc._quote_manager = mock_mgr

        result = svc._collect_quote("001330")
        assert result == {}

    def test_build_analysis_prompt_includes_quote(self):
        from src.web.services.holiday_research_service import HolidayResearchService

        svc = HolidayResearchService()
        context = {
            "quote": {"price": 12.77, "pct_change": 0.63, "volume": 100000},
            "news": [],
            "concepts": [],
            "global_market": {},
            "cross_market": {},
            "sentiment_matches": [],
            "calendar_info": {},
            "association_profile": None,
        }
        prompt = svc._build_analysis_prompt("001330", "博纳影业", context, [])
        assert "实时行情" in prompt
        assert "12.77" in prompt
        assert "严禁凭空猜测价格" in prompt

    def test_build_analysis_prompt_no_quote_warning(self):
        from src.web.services.holiday_research_service import HolidayResearchService

        svc = HolidayResearchService()
        context = {
            "quote": {},
            "news": [],
            "concepts": [],
            "global_market": {},
            "cross_market": {},
            "sentiment_matches": [],
            "calendar_info": {},
            "association_profile": None,
        }
        prompt = svc._build_analysis_prompt("001330", "博纳影业", context, [])
        assert "无法获取实时行情" in prompt
        assert "请勿猜测" in prompt

    def test_build_context_summary_includes_quote(self):
        from src.web.services.holiday_research_service import HolidayResearchService

        svc = HolidayResearchService()
        context = {
            "quote": {"price": 12.77, "pct_change": 0.63},
            "news": [],
            "association_profile": None,
        }
        summary = svc._build_context_summary("001330", "博纳影业", context, [])
        assert "12.77" in summary

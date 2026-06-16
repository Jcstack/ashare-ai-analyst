"""Unit tests for Discord multi-turn conversation components."""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock

from src.discord_bot.context_builders import (
    flow_context,
    intel_context,
    market_context,
    nl_context,
    portfolio_context,
    recommend_context,
    stock_context,
)
from src.discord_bot.thread_store import ThreadMapping, ThreadStore


# =====================================================================
# ThreadStore CRUD
# =====================================================================


class TestThreadStore:
    """Test ThreadStore with a mock Redis client."""

    def _make_store(self) -> tuple[ThreadStore, MagicMock]:
        redis = MagicMock()
        return ThreadStore(redis), redis

    def _make_mapping(self, **overrides) -> ThreadMapping:
        defaults = {
            "agent_thread_id": "agent-123",
            "source_command": "stock",
            "context_summary": "个股分析: 600519",
        }
        defaults.update(overrides)
        return ThreadMapping(**defaults)

    def test_save_calls_redis_set(self):
        store, redis = self._make_store()
        mapping = self._make_mapping()
        store.save(12345, mapping)
        redis.set.assert_called_once()
        key, value = redis.set.call_args[0]
        assert key == "discord:thread_map:12345"
        data = json.loads(value)
        assert data["agent_thread_id"] == "agent-123"
        assert data["source_command"] == "stock"
        assert redis.set.call_args[1]["ex"] == 86400

    def test_get_returns_mapping(self):
        store, redis = self._make_store()
        redis.get.return_value = json.dumps(
            {
                "agent_thread_id": "agent-123",
                "source_command": "stock",
                "context_summary": "test",
                "created_at": 1000.0,
                "last_active_at": 1000.0,
                "round_count": 0,
                "ended": False,
            }
        )
        result = store.get(12345)
        assert result is not None
        assert result.agent_thread_id == "agent-123"
        assert result.round_count == 0

    def test_get_returns_none_for_missing(self):
        store, redis = self._make_store()
        redis.get.return_value = None
        assert store.get(99999) is None

    def test_get_returns_none_for_corrupt(self):
        store, redis = self._make_store()
        redis.get.return_value = "not-json"
        assert store.get(12345) is None

    def test_update_active_bumps_round_count(self):
        store, redis = self._make_store()
        redis.get.return_value = json.dumps(
            {
                "agent_thread_id": "agent-123",
                "source_command": "stock",
                "context_summary": "test",
                "created_at": 1000.0,
                "last_active_at": 1000.0,
                "round_count": 3,
                "ended": False,
            }
        )
        result = store.update_active(12345)
        assert result is not None
        assert result.round_count == 4
        assert result.last_active_at > 1000.0
        redis.set.assert_called_once()

    def test_update_active_returns_none_for_missing(self):
        store, redis = self._make_store()
        redis.get.return_value = None
        assert store.update_active(99999) is None

    def test_mark_ended(self):
        store, redis = self._make_store()
        redis.get.return_value = json.dumps(
            {
                "agent_thread_id": "agent-123",
                "source_command": "stock",
                "context_summary": "test",
                "created_at": 1000.0,
                "last_active_at": 1000.0,
                "round_count": 5,
                "ended": False,
            }
        )
        result = store.mark_ended(12345)
        assert result is not None
        assert result.ended is True

    def test_delete(self):
        store, redis = self._make_store()
        store.delete(12345)
        redis.delete.assert_called_once_with("discord:thread_map:12345")

    def test_scan_active_filters_ended(self):
        store, redis = self._make_store()
        active = json.dumps(
            {
                "agent_thread_id": "a1",
                "source_command": "stock",
                "context_summary": "active",
                "created_at": 1000.0,
                "last_active_at": 1000.0,
                "round_count": 2,
                "ended": False,
            }
        )
        ended = json.dumps(
            {
                "agent_thread_id": "a2",
                "source_command": "market",
                "context_summary": "ended",
                "created_at": 1000.0,
                "last_active_at": 1000.0,
                "round_count": 1,
                "ended": True,
            }
        )

        redis.scan.return_value = (
            0,
            ["discord:thread_map:111", "discord:thread_map:222"],
        )
        redis.get.side_effect = [active, ended]

        results = store.scan_active()
        assert len(results) == 1
        tid, m = results[0]
        assert tid == 111
        assert m.agent_thread_id == "a1"


# =====================================================================
# Context builders
# =====================================================================


class TestContextBuilders:
    def test_stock_context_basic(self):
        summary, kwargs = stock_context(
            "600519",
            {"signal": "bullish", "summary": "贵州茅台走势强劲", "risks": ["高估值"]},
            {"price": 1800.0, "pct_change": 2.5},
        )
        assert "600519" in summary
        assert "bullish" in summary
        assert kwargs["mode"] == "stock"
        assert kwargs["symbol"] == "600519"

    def test_stock_context_empty(self):
        summary, kwargs = stock_context("000001", None, None)
        assert "000001" in summary
        assert kwargs["mode"] == "stock"

    def test_recommend_context(self):
        recs = [
            {"symbol": "600519", "name": "贵州茅台", "score": 85},
            {"symbol": "000858", "name": "五粮液", "score": 80},
        ]
        summary, kwargs = recommend_context(recs, "value")
        assert "600519" in summary
        assert "value" in summary
        assert kwargs["mode"] == "market"

    def test_recommend_context_empty(self):
        summary, kwargs = recommend_context([], None)
        assert "推荐" in summary
        assert kwargs["mode"] == "market"

    def test_market_context(self):
        indices = [
            {"name": "上证指数", "price": 3200, "pct_change": 0.5},
            {"name": "深证成指", "price": 10500, "pct_change": -0.3},
        ]
        summary, kwargs = market_context(indices)
        assert "上证指数" in summary
        assert kwargs["mode"] == "market"

    def test_flow_context(self):
        data = {
            "signal": "偏多",
            "score": 72,
            "northbound": "+15.3亿",
            "interpretation": "北向资金持续流入",
        }
        summary, kwargs = flow_context(data)
        assert "偏多" in summary
        assert kwargs["mode"] == "market"

    def test_portfolio_context(self):
        data = {
            "health_score": 75,
            "total_pnl": "+5.2%",
            "positions": [
                {"symbol": "600519", "name": "贵州茅台", "pnl": "+8%"},
            ],
            "warnings": ["集中度过高"],
        }
        summary, kwargs = portfolio_context(data)
        assert "600519" in summary
        assert kwargs["mode"] == "portfolio"
        assert "600519" in kwargs["matched_portfolio_symbols"]

    def test_intel_context(self):
        items = [
            {"id": "i1", "title": "央行降准"},
            {"id": "i2", "title": "新能源政策"},
        ]
        summary, kwargs = intel_context(items, "政策")
        assert "央行降准" in summary
        assert "政策" in summary
        assert kwargs["intel_item_ids"] == ["i1", "i2"]

    def test_nl_context_delegates_stock(self):
        result_data = {
            "analysis": {"signal": "neutral", "summary": "test", "risks": []},
            "quote": {"price": 10},
        }
        summary, kwargs = nl_context(
            "stock_analysis", {"symbol": "000001"}, result_data
        )
        assert "000001" in summary
        assert kwargs["mode"] == "stock"

    def test_nl_context_fallback(self):
        summary, kwargs = nl_context("agent_qa", {"question": "什么是ETF"}, None)
        assert "什么是ETF" in summary
        assert kwargs["mode"] == "general"


# =====================================================================
# End keyword matching
# =====================================================================


class TestEndKeywords:
    """Test the end-keyword regex from agent_commands."""

    _END_KEYWORDS = re.compile(r"^(结束|结束对话|关闭|bye|end)$", re.IGNORECASE)

    def test_chinese_end(self):
        assert self._END_KEYWORDS.match("结束")
        assert self._END_KEYWORDS.match("结束对话")
        assert self._END_KEYWORDS.match("关闭")

    def test_english_end(self):
        assert self._END_KEYWORDS.match("bye")
        assert self._END_KEYWORDS.match("end")
        assert self._END_KEYWORDS.match("BYE")
        assert self._END_KEYWORDS.match("End")

    def test_non_end(self):
        assert not self._END_KEYWORDS.match("继续")
        assert not self._END_KEYWORDS.match("结束了吗")
        assert not self._END_KEYWORDS.match("hello")
        assert not self._END_KEYWORDS.match("end this")


# =====================================================================
# ThreadMapping dataclass
# =====================================================================


class TestThreadMapping:
    def test_defaults(self):
        m = ThreadMapping(
            agent_thread_id="t1",
            source_command="ask",
            context_summary="test",
        )
        assert m.round_count == 0
        assert m.ended is False
        assert m.created_at > 0
        assert m.last_active_at > 0

    def test_serialization_roundtrip(self):
        from dataclasses import asdict

        m = ThreadMapping(
            agent_thread_id="t1",
            source_command="stock",
            context_summary="个股分析",
            created_at=1000.0,
            last_active_at=1000.0,
            round_count=3,
            ended=False,
        )
        data = json.dumps(asdict(m))
        restored = ThreadMapping(**json.loads(data))
        assert restored.agent_thread_id == m.agent_thread_id
        assert restored.round_count == m.round_count

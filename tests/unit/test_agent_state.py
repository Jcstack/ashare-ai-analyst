"""Tests for AgentState — persistent agent state across heartbeats."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.agent_loop.agent_state import AgentDecision, AgentState


class TestAgentStateDefaults:
    """Test fresh state initialization."""

    def test_fresh_state_defaults(self):
        state = AgentState(date="20260401")
        assert state.date == "20260401"
        assert state.heartbeat_count == 0
        assert state.last_heartbeat == ""
        assert state.decisions == []
        assert state.research_queue == []
        assert state.watched_stocks == []
        assert state.findings == []
        assert state.market_assessment == ""
        assert state.next_focus == ""
        assert state.conviction_log == {}
        assert state.yesterday_outcomes == []
        assert state.lessons == []
        assert state.executed_missions == set()


class TestAgentStateSaveLoad:
    """Test Redis save/load roundtrip."""

    def _mock_redis(self) -> MagicMock:
        """Create a mock Redis with in-memory get/set."""
        store: dict[str, str] = {}
        redis = MagicMock()
        redis.get = MagicMock(side_effect=lambda k: store.get(k))
        redis.set = MagicMock(side_effect=lambda k, v, **kw: store.__setitem__(k, v))
        return redis

    def test_save_load_roundtrip(self):
        redis = self._mock_redis()
        state = AgentState(date="20260401")
        state.heartbeat_count = 3
        state.last_heartbeat = "10:30"
        state.add_decision(
            AgentDecision(
                timestamp="10:25",
                action="buy",
                symbol="600519",
                summary="茅台突破前高",
                confidence=0.8,
            )
        )
        state.findings.append("大盘放量上涨")
        state.executed_missions.add("morning_plan")
        state.executed_missions.add("portfolio_watch")
        state.save(redis)

        loaded = AgentState.load(redis, "20260401")
        assert loaded.heartbeat_count == 3
        assert loaded.last_heartbeat == "10:30"
        assert len(loaded.decisions) == 1
        assert loaded.decisions[0].symbol == "600519"
        assert loaded.decisions[0].confidence == 0.8
        assert "大盘放量上涨" in loaded.findings
        assert loaded.executed_missions == {"morning_plan", "portfolio_watch"}

    def test_load_missing_key_returns_fresh(self):
        redis = self._mock_redis()
        loaded = AgentState.load(redis, "20260402")
        assert loaded.date == "20260402"
        assert loaded.heartbeat_count == 0
        assert loaded.executed_missions == set()

    def test_load_redis_failure_returns_fresh(self):
        redis = MagicMock()
        redis.get = MagicMock(side_effect=Exception("connection refused"))
        loaded = AgentState.load(redis, "20260401")
        assert loaded.date == "20260401"
        assert loaded.heartbeat_count == 0


class TestAgentStateDecisions:
    """Test decision tracking."""

    def test_add_decision(self):
        state = AgentState(date="20260401")
        decision = AgentDecision(
            timestamp="14:35",
            action="sell",
            symbol="000001",
            summary="平安银行到达止损位",
            confidence=0.9,
        )
        state.add_decision(decision)
        assert len(state.decisions) == 1
        assert state.decisions[0].action == "sell"
        assert state.decisions[0].symbol == "000001"

    def test_get_decisions_summary_empty(self):
        state = AgentState(date="20260401")
        assert state.get_decisions_summary() == "今日尚无决策"

    def test_get_decisions_summary_filled(self):
        state = AgentState(date="20260401")
        state.add_decision(
            AgentDecision(
                timestamp="10:00",
                action="buy",
                symbol="600519",
                summary="突破买入",
                confidence=0.75,
            )
        )
        state.add_decision(
            AgentDecision(
                timestamp="14:30",
                action="sell",
                symbol="000001",
                summary="止损卖出",
                confidence=0.85,
                executed=True,
            )
        )
        summary = state.get_decisions_summary()
        assert "600519" in summary
        assert "000001" in summary
        assert "待执行" in summary
        assert "已执行" in summary


class TestConvictionScore:
    """Test conviction scoring."""

    def test_conviction_score_bullish(self):
        state = AgentState(date="20260401")
        state.add_conviction("600519", "资金持续流入", "bullish", weight=2.0)
        state.add_conviction("600519", "涨停封板坚固", "bullish", weight=1.5)
        assert state.get_conviction_score("600519") == pytest.approx(3.5)

    def test_conviction_score_bearish(self):
        state = AgentState(date="20260401")
        state.add_conviction("000001", "资金流出", "bearish", weight=1.0)
        state.add_conviction("000001", "破位下跌", "bearish", weight=2.0)
        assert state.get_conviction_score("000001") == pytest.approx(-3.0)

    def test_conviction_score_mixed(self):
        state = AgentState(date="20260401")
        state.add_conviction("600519", "资金流入", "bullish", weight=2.0)
        state.add_conviction("600519", "大盘承压", "bearish", weight=1.0)
        assert state.get_conviction_score("600519") == pytest.approx(1.0)

    def test_conviction_score_unknown_symbol(self):
        state = AgentState(date="20260401")
        assert state.get_conviction_score("999999") == 0.0


class TestExecutedMissionsPersistence:
    """Test executed_missions survives save/load."""

    def test_executed_missions_persistence(self):
        store: dict[str, str] = {}
        redis = MagicMock()
        redis.get = MagicMock(side_effect=lambda k: store.get(k))
        redis.set = MagicMock(side_effect=lambda k, v, **kw: store.__setitem__(k, v))

        state = AgentState(date="20260401")
        state.executed_missions = {"morning_plan", "decision_window", "close_review"}
        state.save(redis)

        # Verify serialized as list
        saved_data = json.loads(store["agent:state:20260401"])
        assert isinstance(saved_data["executed_missions"], list)
        assert set(saved_data["executed_missions"]) == {
            "morning_plan",
            "decision_window",
            "close_review",
        }

        # Reload and verify
        loaded = AgentState.load(redis, "20260401")
        assert loaded.executed_missions == {
            "morning_plan",
            "decision_window",
            "close_review",
        }

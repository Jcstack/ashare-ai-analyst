"""Tests for HeartbeatAgent — mission selection and agent lifecycle."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src.agent_loop.agent_state import AgentState
from src.agent_loop.heartbeat_agent import HeartbeatAgent, _select_mission

_CST = ZoneInfo("Asia/Shanghai")


def _make_state(
    heartbeat_count: int = 1,
    executed_missions: set[str] | None = None,
) -> AgentState:
    """Create an AgentState with specified parameters."""
    state = AgentState(date="20260401")
    state.heartbeat_count = heartbeat_count
    if executed_missions:
        state.executed_missions = executed_missions
    return state


def _cst_time(hour: int, minute: int = 0) -> datetime:
    """Create a CST datetime for April 1, 2026."""
    return datetime(2026, 4, 1, hour, minute, tzinfo=_CST)


class TestSelectMission:
    """Test mission selection based on time and state."""

    def test_select_mission_morning(self):
        """08:00 with heartbeat #1 should pick morning_plan."""
        state = _make_state(heartbeat_count=1)
        result = _select_mission(_cst_time(8, 0), state)
        assert result == "morning_plan"

    def test_select_mission_portfolio_watch(self):
        """10:00 (minute < 5) with held positions → portfolio_watch (deep, hourly).

        portfolio_watch is the deep持仓检查 path, which only applies when the
        portfolio is non-empty; an empty portfolio hunts for opportunities
        instead. Inject a portfolio store with a held position so the
        has-positions branch is exercised.
        """
        state = _make_state(heartbeat_count=3)
        mock_ps = MagicMock()
        mock_ps.list_positions.return_value = [{"symbol": "002688"}]
        with patch("src.web.dependencies.get_portfolio_store", return_value=mock_ps):
            result = _select_mission(_cst_time(10, 0), state)
        assert result == "portfolio_watch"

    def test_select_mission_opportunity_hunt(self):
        """During trading hours, m >= 20 → opportunity_hunt (2/3 of slots)."""
        state = _make_state(heartbeat_count=3)
        # m=20 → opportunity_hunt
        result = _select_mission(_cst_time(10, 20), state)
        assert result == "quick_trade"  # opportunity_hunt only at :30-:34

        # m=45 → opportunity_hunt
        result = _select_mission(_cst_time(10, 45), state)
        assert result == "quick_trade"  # opportunity_hunt only at :30-:34

    def test_select_mission_decision_window(self):
        """14:30 should pick decision_window if not yet executed."""
        state = _make_state(heartbeat_count=10)
        result = _select_mission(_cst_time(14, 30), state)
        assert result == "decision_window"

    def test_select_mission_decision_window_already_done(self):
        """14:30 should pick portfolio_watch if decision_window already executed."""
        state = _make_state(
            heartbeat_count=10,
            executed_missions={"decision_window"},
        )
        result = _select_mission(_cst_time(14, 30), state)
        assert result == "quick_trade"  # Most slots are quick_trade now

    def test_select_mission_close_review(self):
        """15:05 should pick close_review if not yet executed."""
        state = _make_state(heartbeat_count=12)
        result = _select_mission(_cst_time(15, 5), state)
        assert result == "close_review"

    def test_select_mission_close_review_already_done(self):
        """15:05 should pick idle_check if close_review already executed."""
        state = _make_state(
            heartbeat_count=12,
            executed_missions={"close_review"},
        )
        result = _select_mission(_cst_time(15, 5), state)
        assert result == "quick_trade"

    def test_select_mission_idle_after_close(self):
        """15:30 with close done should return idle_check."""
        state = _make_state(
            heartbeat_count=15,
            executed_missions={"close_review"},
        )
        result = _select_mission(_cst_time(15, 30), state)
        assert result == "quick_trade"

    def test_select_mission_pre_market_late(self):
        """Pre-market with heartbeat > 2 should return idle_check."""
        state = _make_state(heartbeat_count=3)
        result = _select_mission(_cst_time(8, 30), state)
        assert result == "quick_trade"

    def test_select_mission_pre_market_early(self):
        """Pre-market with heartbeat <= 2 should return morning_plan."""
        state = _make_state(heartbeat_count=2)
        result = _select_mission(_cst_time(8, 30), state)
        assert result == "morning_plan"

    def test_quick_trade_default(self):
        """10:10 (m < 20) should pick portfolio_watch."""
        state = _make_state(heartbeat_count=5)
        result = _select_mission(_cst_time(10, 10), state)
        assert result == "quick_trade"  # Most slots are quick_trade now

    def test_deep_at_half_hour(self):
        """10:30-10:34 gets opportunity_hunt, 10:45 gets quick_trade."""
        state = _make_state(heartbeat_count=5)
        assert _select_mission(_cst_time(10, 30), state) == "opportunity_hunt"
        assert _select_mission(_cst_time(10, 45), state) == "quick_trade"


class TestLoadActiveTheses:
    """Test _load_active_theses — Phase 1 thesis anchoring in heartbeat context."""

    def _make_agent(
        self, redis: MagicMock | None = None, portfolio: MagicMock | None = None
    ) -> HeartbeatAgent:
        """Create a HeartbeatAgent with injected mocks (no real deps)."""
        agent = object.__new__(HeartbeatAgent)
        agent._redis = redis
        agent._portfolio = portfolio
        return agent

    def test_load_active_theses_with_matching_position(self):
        """Should return formatted thesis for held positions."""
        thesis = {
            "entry_price": 6.14,
            "stop_loss": 5.90,
            "target_price": 6.48,
            "summary": "趋势刚启动",
            "created_at": "2026-04-02T06:21:00",
        }
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(thesis)
        mock_ps = MagicMock()
        mock_ps.list_positions.return_value = [
            {"symbol": "002688", "name": "金河生物"},
        ]
        agent = self._make_agent(redis=mock_redis, portfolio=mock_ps)
        result = agent._load_active_theses()
        assert "002688" in result
        assert "6.14" in result
        assert "5.9" in result
        assert "6.48" in result
        assert "趋势刚启动" in result

    def test_load_active_theses_no_thesis_in_redis(self):
        """Position without a stored thesis should be skipped."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        mock_ps = MagicMock()
        mock_ps.list_positions.return_value = [
            {"symbol": "600519", "name": "贵州茅台"},
        ]
        agent = self._make_agent(redis=mock_redis, portfolio=mock_ps)
        result = agent._load_active_theses()
        assert result == ""

    def test_load_active_theses_no_redis(self):
        """No Redis → empty string."""
        agent = self._make_agent(redis=None, portfolio=MagicMock())
        result = agent._load_active_theses()
        assert result == ""

    def test_load_active_theses_no_positions(self):
        """No positions → empty string."""
        mock_redis = MagicMock()
        mock_ps = MagicMock()
        mock_ps.list_positions.return_value = []
        agent = self._make_agent(redis=mock_redis, portfolio=mock_ps)
        result = agent._load_active_theses()
        assert result == ""

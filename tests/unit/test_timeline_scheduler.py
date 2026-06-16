"""Tests for TimelineScheduler.

Per PRD v3.2 FR-SS001.
"""

from unittest.mock import MagicMock, patch

import pytest

from openclaw.timeline_scheduler import ScheduleProfile, TimelineScheduler


@pytest.fixture
def scheduler():
    """Create a TimelineScheduler with mock config."""
    with patch("openclaw.timeline_scheduler.load_config") as mock_cfg:
        mock_cfg.return_value = {
            "timeline": {
                "profiles": {
                    "trading_day": {"default": True},
                    "holiday": {
                        "default": False,
                        "tasks": {
                            "task_fetch_global_snapshot": True,
                        },
                    },
                    "after_hours": {
                        "default": True,
                        "tasks": {
                            "task_sentiment_scan": False,
                        },
                    },
                },
            },
        }
        yield TimelineScheduler()


class TestCurrentProfile:
    def test_trading_day_during_morning(self, scheduler):
        """Should return TRADING_DAY during morning session."""
        from src.data.trading_calendar import MarketSession

        mock_cal = MagicMock()
        mock_cal.current_session.return_value = MarketSession.MORNING
        mock_cal.is_trading_day.return_value = True
        mock_cal.is_holiday_period.return_value = False
        scheduler._calendar = mock_cal

        assert scheduler.current_profile() == ScheduleProfile.TRADING_DAY

    def test_holiday_when_closed_and_holiday_period(self, scheduler):
        """Should return HOLIDAY when closed and in holiday period."""
        from src.data.trading_calendar import MarketSession

        mock_cal = MagicMock()
        mock_cal.current_session.return_value = MarketSession.CLOSED
        mock_cal.is_trading_day.return_value = False
        mock_cal.is_holiday_period.return_value = True
        scheduler._calendar = mock_cal

        assert scheduler.current_profile() == ScheduleProfile.HOLIDAY

    def test_override_takes_priority(self, scheduler):
        """Manual override should override calendar detection."""
        from src.data.trading_calendar import MarketSession

        mock_cal = MagicMock()
        mock_cal.current_session.return_value = MarketSession.MORNING
        scheduler._calendar = mock_cal

        scheduler.set_override(ScheduleProfile.HOLIDAY)
        assert scheduler.current_profile() == ScheduleProfile.HOLIDAY

    def test_clear_override(self, scheduler):
        """Clearing override should resume auto-detection."""
        from src.data.trading_calendar import MarketSession

        mock_cal = MagicMock()
        mock_cal.current_session.return_value = MarketSession.MORNING
        mock_cal.is_trading_day.return_value = True
        scheduler._calendar = mock_cal

        scheduler.set_override(ScheduleProfile.HOLIDAY)
        scheduler.set_override(None)
        assert scheduler.current_profile() == ScheduleProfile.TRADING_DAY

    def test_after_hours_profile(self, scheduler):
        """Should return AFTER_HOURS when in after-hours session."""
        from src.data.trading_calendar import MarketSession

        mock_cal = MagicMock()
        mock_cal.current_session.return_value = MarketSession.AFTER_HOURS
        scheduler._calendar = mock_cal

        assert scheduler.current_profile() == ScheduleProfile.AFTER_HOURS

    def test_pre_market_profile(self, scheduler):
        """Should return PRE_MARKET during pre-market session."""
        from src.data.trading_calendar import MarketSession

        mock_cal = MagicMock()
        mock_cal.current_session.return_value = MarketSession.PRE_MARKET
        scheduler._calendar = mock_cal

        assert scheduler.current_profile() == ScheduleProfile.PRE_MARKET


class TestShouldExecute:
    def test_trading_day_allows_all(self, scheduler):
        """All tasks should execute on trading day (default=True)."""
        from src.data.trading_calendar import MarketSession

        mock_cal = MagicMock()
        mock_cal.current_session.return_value = MarketSession.MORNING
        mock_cal.is_trading_day.return_value = True
        scheduler._calendar = mock_cal

        assert scheduler.should_execute("task_fetch_all") is True
        assert scheduler.should_execute("task_sentiment_scan") is True

    def test_holiday_blocks_most_tasks(self, scheduler):
        """Holiday profile should block tasks (default=False) except whitelisted."""
        from src.data.trading_calendar import MarketSession

        mock_cal = MagicMock()
        mock_cal.current_session.return_value = MarketSession.CLOSED
        mock_cal.is_trading_day.return_value = False
        mock_cal.is_holiday_period.return_value = True
        scheduler._calendar = mock_cal

        # Whitelisted
        assert scheduler.should_execute("task_fetch_global_snapshot") is True
        # Not whitelisted, default=False
        assert scheduler.should_execute("task_fetch_all") is False

    def test_after_hours_blocks_sentiment(self, scheduler):
        """After-hours should block sentiment scan but allow others."""
        from src.data.trading_calendar import MarketSession

        mock_cal = MagicMock()
        mock_cal.current_session.return_value = MarketSession.AFTER_HOURS
        scheduler._calendar = mock_cal

        assert scheduler.should_execute("task_sentiment_scan") is False
        assert scheduler.should_execute("task_fetch_all") is True  # default=True

    def test_no_config_allows_all(self):
        """With no timeline config, all tasks should execute."""
        with patch("openclaw.timeline_scheduler.load_config") as mock_cfg:
            mock_cfg.return_value = {}
            s = TimelineScheduler()

            from src.data.trading_calendar import MarketSession

            mock_cal = MagicMock()
            mock_cal.current_session.return_value = MarketSession.MORNING
            mock_cal.is_trading_day.return_value = True
            s._calendar = mock_cal

            assert s.should_execute("any_task") is True


class TestGetStatus:
    def test_returns_expected_keys(self, scheduler):
        """get_status should return all expected fields."""
        from src.data.trading_calendar import MarketSession

        mock_cal = MagicMock()
        mock_cal.current_session.return_value = MarketSession.MORNING
        mock_cal.is_trading_day.return_value = True
        mock_cal.is_holiday_period.return_value = False
        mock_cal.next_trading_day.return_value = MagicMock(
            isoformat=lambda: "2026-02-16"
        )
        scheduler._calendar = mock_cal

        status = scheduler.get_status()
        assert "current_profile" in status
        assert "override" in status
        assert "is_trading_day" in status
        assert "current_session" in status
        assert "is_holiday_period" in status
        assert "next_trading_day" in status
        assert status["override"] is None

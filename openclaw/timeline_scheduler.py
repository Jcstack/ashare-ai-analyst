"""Timeline scheduler for intelligent task scheduling based on trading calendar.

Determines the current schedule profile (trading day, holiday, etc.) and
provides guards for Celery tasks to skip execution during non-applicable
periods.

Per PRD v3.2 FR-SS001: Timeline scheduling engine.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("openclaw.timeline_scheduler")


class ScheduleProfile(str, Enum):
    """Schedule profile that determines which tasks should run."""

    TRADING_DAY = "trading_day"
    HOLIDAY = "holiday"
    PRE_MARKET = "pre_market"
    AFTER_HOURS = "after_hours"


class TimelineScheduler:
    """Controls task execution based on current market calendar state.

    Does NOT replace Celery Beat. Instead, each task calls
    ``should_execute()`` at its entry point as a guard.
    """

    def __init__(self) -> None:
        self._config = self._load_config()
        self._override: ScheduleProfile | None = None
        self._calendar = None  # lazy
        logger.info("TimelineScheduler initialized")

    def _load_config(self) -> dict[str, Any]:
        try:
            config = load_config("openclaw")
            return config.get("timeline", {})
        except FileNotFoundError:
            logger.warning("config/openclaw.yaml not found; using default timeline")
            return {}

    def _get_calendar(self):
        if self._calendar is None:
            from src.data.trading_calendar import TradingCalendar

            self._calendar = TradingCalendar()
        return self._calendar

    def current_profile(self) -> ScheduleProfile:
        """Determine the current schedule profile.

        Priority: manual override > calendar-based detection.
        """
        if self._override is not None:
            return self._override

        from src.data.trading_calendar import MarketSession

        cal = self._get_calendar()
        session = cal.current_session()

        if session == MarketSession.CLOSED:
            if cal.is_holiday_period():
                return ScheduleProfile.HOLIDAY
            # Closed but not holiday — could be overnight or weekend
            if cal.is_trading_day():
                return ScheduleProfile.AFTER_HOURS
            return ScheduleProfile.HOLIDAY

        if session == MarketSession.PRE_MARKET:
            return ScheduleProfile.PRE_MARKET

        if session == MarketSession.AFTER_HOURS:
            return ScheduleProfile.AFTER_HOURS

        return ScheduleProfile.TRADING_DAY

    def should_execute(self, task_name: str) -> bool:
        """Check if a task should execute under the current profile.

        Reads ``timeline.profiles.<profile>.tasks`` from config to
        determine which tasks are enabled/disabled for each profile.
        If no config exists, defaults to True (always execute).
        """
        profile = self.current_profile()
        profiles_config = self._config.get("profiles", {})
        profile_cfg = profiles_config.get(profile.value, {})
        tasks_cfg = profile_cfg.get("tasks", {})

        if not tasks_cfg:
            # No config = always execute
            return True

        # Check if task is explicitly listed
        if task_name in tasks_cfg:
            return bool(tasks_cfg[task_name])

        # Check default for this profile
        return bool(profile_cfg.get("default", True))

    def set_override(self, profile: ScheduleProfile | None) -> None:
        """Manually override the current schedule profile.

        Pass None to clear the override and resume automatic detection.
        """
        self._override = profile
        if profile is None:
            logger.info("Schedule override cleared — resuming auto-detection")
        else:
            logger.info("Schedule override set to: %s", profile.value)

    def get_status(self) -> dict[str, Any]:
        """Return the current scheduler status for the admin API."""
        cal = self._get_calendar()
        return {
            "current_profile": self.current_profile().value,
            "override": self._override.value if self._override else None,
            "is_trading_day": cal.is_trading_day(),
            "current_session": cal.current_session().value,
            "is_holiday_period": cal.is_holiday_period(),
            "next_trading_day": cal.next_trading_day().isoformat(),
        }

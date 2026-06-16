"""Pydantic models for scheduler API endpoints.

Per PRD v3.2 FR-SS004.
"""

from __future__ import annotations

from pydantic import BaseModel


class SchedulerStatus(BaseModel):
    """Current scheduler status."""

    current_profile: str
    override: str | None
    is_trading_day: bool
    current_session: str
    is_holiday_period: bool
    next_trading_day: str


class TaskConfig(BaseModel):
    """Individual task configuration within a plan."""

    name: str
    enabled: bool
    description: str = ""


class SchedulePlan(BaseModel):
    """A schedule plan (e.g. trading_day, holiday)."""

    name: str
    label: str
    default_enabled: bool
    tasks: list[TaskConfig]


class SchedulePlansResult(BaseModel):
    """All schedule plans."""

    plans: list[SchedulePlan]


class CalendarDay(BaseModel):
    """Single day in the calendar view."""

    date: str
    is_trading_day: bool
    is_weekend: bool
    is_holiday: bool
    day_of_week: int


class CalendarResult(BaseModel):
    """30-day calendar view."""

    days: list[CalendarDay]
    today: str
    next_trading_day: str


class UpdatePlanRequest(BaseModel):
    """Request to update task configs within a plan."""

    tasks: dict[str, bool]


class SentinelConfig(BaseModel):
    """Sentinel configuration (data sources + notifications)."""

    data_sources: dict
    notifications: dict


class NotificationChannelConfig(BaseModel):
    """Configuration for a notification channel."""

    type: str
    enabled: bool
    events: list[str] = []

"""Tests for Intelligence Hub trading-day-aware refresh scheduler."""

from __future__ import annotations

import time
from datetime import date, datetime

from src.intelligence_hub.scheduler import RefreshScheduler


class MockCalendar:
    """Minimal TradingCalendar mock for scheduler tests."""

    def __init__(self, is_trading: bool = True) -> None:
        self._is_trading = is_trading

    def is_trading_day(self, d: date | None = None) -> bool:
        return self._is_trading


class TestTradingDayIntervals:
    """Verify correct intervals during different trading-day windows."""

    def test_trading_day_pre_open_interval(self) -> None:
        sched = RefreshScheduler(trading_calendar=MockCalendar(is_trading=True))
        # 08:00 on a trading day -> pre_open (120s)
        now = datetime(2026, 2, 16, 8, 0)
        assert sched.get_refresh_interval(now) == 120

    def test_trading_day_trading_hours_interval(self) -> None:
        sched = RefreshScheduler(trading_calendar=MockCalendar(is_trading=True))
        # 10:30 on a trading day -> trading_hours (300s)
        now = datetime(2026, 2, 16, 10, 30)
        assert sched.get_refresh_interval(now) == 300

    def test_trading_day_after_hours_interval(self) -> None:
        sched = RefreshScheduler(trading_calendar=MockCalendar(is_trading=True))
        # 17:00 on a trading day -> after_hours (600s)
        now = datetime(2026, 2, 16, 17, 0)
        assert sched.get_refresh_interval(now) == 600

    def test_off_hours_night_interval(self) -> None:
        sched = RefreshScheduler(trading_calendar=MockCalendar(is_trading=True))
        # 22:00 on a trading day -> off_hours (1800s)
        now = datetime(2026, 2, 16, 22, 0)
        assert sched.get_refresh_interval(now) == 1800


class TestNonTradingDay:
    """Non-trading days should always return off_hours interval."""

    def test_non_trading_day_interval(self) -> None:
        sched = RefreshScheduler(trading_calendar=MockCalendar(is_trading=False))
        # Even at 10:30 (normally trading hours) -> off_hours
        now = datetime(2026, 2, 15, 10, 30)
        assert sched.get_refresh_interval(now) == 1800


class TestNoCalendar:
    """Without a TradingCalendar, fallback to trading_hours default."""

    def test_no_calendar_returns_default(self) -> None:
        sched = RefreshScheduler(trading_calendar=None)
        assert sched.get_refresh_interval() == 300


class TestShouldRefresh:
    """Verify the should_refresh elapsed-time check."""

    def test_should_refresh_true(self) -> None:
        sched = RefreshScheduler(trading_calendar=MockCalendar(is_trading=True))
        now = datetime(2026, 2, 16, 10, 30)  # trading_hours -> 300s
        # Last refresh was 400 seconds ago -> should refresh
        last_refresh = time.time() - 400
        assert sched.should_refresh(last_refresh, now) is True

    def test_should_refresh_false(self) -> None:
        sched = RefreshScheduler(trading_calendar=MockCalendar(is_trading=True))
        now = datetime(2026, 2, 16, 10, 30)  # trading_hours -> 300s
        # Last refresh was 100 seconds ago -> should not refresh
        last_refresh = time.time() - 100
        assert sched.should_refresh(last_refresh, now) is False


class TestCustomConfig:
    """Config overrides should merge with defaults."""

    def test_custom_intervals_override(self) -> None:
        sched = RefreshScheduler(
            trading_calendar=MockCalendar(is_trading=True),
            config={"intervals": {"pre_open": 60}},
        )
        now = datetime(2026, 2, 16, 8, 0)
        assert sched.get_refresh_interval(now) == 60

    def test_custom_intervals_preserve_others(self) -> None:
        sched = RefreshScheduler(
            trading_calendar=MockCalendar(is_trading=True),
            config={"intervals": {"pre_open": 60}},
        )
        # trading_hours should still be default 300
        now = datetime(2026, 2, 16, 10, 30)
        assert sched.get_refresh_interval(now) == 300

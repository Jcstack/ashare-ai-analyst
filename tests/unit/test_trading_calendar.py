"""Tests for TradingCalendar service.

Per PRD v3.2 FR-HS001.
"""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.data.trading_calendar import MarketSession, TradingCalendar


def _make_trading_dates(weekday_only: bool = True, holidays: set[date] | None = None):
    """Build a (dates, covered_years) tuple for 2025-2027 (Mon-Fri minus holidays)."""
    holidays = holidays or set()
    result: set[date] = set()
    d = date(2025, 1, 1)
    end = date(2027, 12, 31)
    while d <= end:
        if weekday_only and d.weekday() < 5 and d not in holidays:
            result.add(d)
        d += timedelta(days=1)
    return result, {2025, 2026, 2027}


@pytest.fixture
def calendar():
    """Create a TradingCalendar with mocked calendar sources and default config."""
    with (
        patch("src.data.trading_calendar.load_config") as mock_cfg,
        patch("src.data.trading_calendar._load_akshare_trading_dates") as mock_ak,
        patch("src.data.trading_calendar._load_adata_trading_dates") as mock_adata,
    ):
        mock_cfg.return_value = {
            "sessions": {
                "pre_market": {"start": "09:15", "end": "09:30"},
                "morning": {"start": "09:30", "end": "11:30"},
                "lunch_break": {"start": "11:30", "end": "13:00"},
                "afternoon": {"start": "13:00", "end": "15:00"},
                "after_hours": {"start": "15:00", "end": "17:00"},
            },
            "overrides": {},
            "holiday_period_threshold": 3,
        }
        mock_ak.return_value = _make_trading_dates()
        mock_adata.return_value = (set(), set())
        yield TradingCalendar()


class TestIsTradingDay:
    def test_weekday_is_trading(self, calendar):
        """Monday should be a trading day."""
        assert calendar.is_trading_day(date(2026, 2, 9)) is True

    def test_weekend_is_not_trading(self, calendar):
        """Saturday should not be a trading day."""
        assert calendar.is_trading_day(date(2026, 2, 14)) is False

    def test_override_forces_trading(self, calendar):
        """Manual override should take priority over adata."""
        d = date(2026, 1, 1)
        calendar._overrides = {d: True}
        # Even though it's a holiday, override says trading
        assert calendar.is_trading_day(d) is True

    def test_override_forces_non_trading(self, calendar):
        """Manual override can force a weekday to be non-trading."""
        d = date(2026, 2, 9)  # Monday
        calendar._overrides = {d: False}
        assert calendar.is_trading_day(d) is False

    def test_default_today(self, calendar):
        """Calling with no argument uses today."""
        result = calendar.is_trading_day()
        assert isinstance(result, bool)

    def test_holiday_not_trading(self):
        """Weekdays in the holiday set should not be trading days."""
        holidays = {date(2026, 2, 16), date(2026, 2, 17)}
        with (
            patch("src.data.trading_calendar.load_config") as mock_cfg,
            patch("src.data.trading_calendar._load_akshare_trading_dates") as mock_ak,
            patch("src.data.trading_calendar._load_adata_trading_dates") as mock_adata,
        ):
            mock_cfg.return_value = {
                "overrides": {},
                "holiday_period_threshold": 3,
            }
            mock_ak.return_value = _make_trading_dates(holidays=holidays)
            mock_adata.return_value = (set(), set())
            cal = TradingCalendar()
            assert cal.is_trading_day(date(2026, 2, 16)) is False
            assert cal.is_trading_day(date(2026, 2, 17)) is False
            # But the next day (Wed) is trading
            assert cal.is_trading_day(date(2026, 2, 18)) is True

    def test_fallback_when_all_sources_empty(self):
        """When all sources fail, fall back to weekday heuristic."""
        with (
            patch("src.data.trading_calendar.load_config") as mock_cfg,
            patch("src.data.trading_calendar._load_akshare_trading_dates") as mock_ak,
            patch("src.data.trading_calendar._load_adata_trading_dates") as mock_adata,
        ):
            mock_cfg.return_value = {"overrides": {}, "holiday_period_threshold": 3}
            mock_ak.return_value = (set(), set())
            mock_adata.return_value = (set(), set())
            cal = TradingCalendar()
            # Weekday → True (heuristic)
            assert cal.is_trading_day(date(2026, 2, 9)) is True
            # Weekend → False (heuristic)
            assert cal.is_trading_day(date(2026, 2, 14)) is False


class TestCurrentSession:
    def test_morning_session(self, calendar):
        """10:00 on a trading day should be MORNING."""
        dt = datetime(2026, 2, 9, 10, 0, 0)
        assert calendar.current_session(dt) == MarketSession.MORNING

    def test_afternoon_session(self, calendar):
        """14:00 on a trading day should be AFTERNOON."""
        dt = datetime(2026, 2, 9, 14, 0, 0)
        assert calendar.current_session(dt) == MarketSession.AFTERNOON

    def test_pre_market(self, calendar):
        """09:20 on a trading day should be PRE_MARKET."""
        dt = datetime(2026, 2, 9, 9, 20, 0)
        assert calendar.current_session(dt) == MarketSession.PRE_MARKET

    def test_lunch_break(self, calendar):
        """12:00 on a trading day should be LUNCH_BREAK."""
        dt = datetime(2026, 2, 9, 12, 0, 0)
        assert calendar.current_session(dt) == MarketSession.LUNCH_BREAK

    def test_after_hours(self, calendar):
        """16:00 on a trading day should be AFTER_HOURS."""
        dt = datetime(2026, 2, 9, 16, 0, 0)
        assert calendar.current_session(dt) == MarketSession.AFTER_HOURS

    def test_closed_on_weekend(self, calendar):
        """Any time on weekend should be CLOSED."""
        dt = datetime(2026, 2, 14, 10, 0, 0)  # Saturday
        assert calendar.current_session(dt) == MarketSession.CLOSED

    def test_closed_early_morning(self, calendar):
        """03:00 on a trading day should be CLOSED."""
        dt = datetime(2026, 2, 9, 3, 0, 0)
        assert calendar.current_session(dt) == MarketSession.CLOSED


class TestNextTradingDay:
    def test_next_after_friday(self, calendar):
        """Next trading day after Friday should be Monday."""
        friday = date(2026, 2, 13)  # Friday
        result = calendar.next_trading_day(friday)
        assert result == date(2026, 2, 16)  # Monday

    def test_next_after_weekday(self, calendar):
        """Next trading day after Monday should be Tuesday."""
        monday = date(2026, 2, 9)
        result = calendar.next_trading_day(monday)
        assert result == date(2026, 2, 10)  # Tuesday

    def test_next_skips_holidays(self):
        """Next trading day should skip holiday weekdays."""
        holidays = {
            date(2026, 2, 16),
            date(2026, 2, 17),
            date(2026, 2, 18),
            date(2026, 2, 19),
            date(2026, 2, 20),
            date(2026, 2, 23),
        }
        with (
            patch("src.data.trading_calendar.load_config") as mock_cfg,
            patch("src.data.trading_calendar._load_akshare_trading_dates") as mock_ak,
            patch("src.data.trading_calendar._load_adata_trading_dates") as mock_adata,
        ):
            mock_cfg.return_value = {"overrides": {}, "holiday_period_threshold": 3}
            mock_ak.return_value = _make_trading_dates(holidays=holidays)
            mock_adata.return_value = (set(), set())
            cal = TradingCalendar()
            # After Fri Feb 13, next is Tue Feb 24 (skipping all holidays)
            assert cal.next_trading_day(date(2026, 2, 13)) == date(2026, 2, 24)


class TestIsHolidayPeriod:
    def test_regular_weekend_not_holiday(self, calendar):
        """A regular 2-day weekend is NOT a holiday period (threshold=3)."""
        saturday = date(2026, 2, 14)
        assert calendar.is_holiday_period(saturday) is False

    def test_long_holiday_is_detected(self):
        """3+ consecutive non-trading days = holiday period."""
        holidays = {
            date(2026, 2, 16),
            date(2026, 2, 17),
            date(2026, 2, 18),
        }
        with (
            patch("src.data.trading_calendar.load_config") as mock_cfg,
            patch("src.data.trading_calendar._load_akshare_trading_dates") as mock_ak,
            patch("src.data.trading_calendar._load_adata_trading_dates") as mock_adata,
        ):
            mock_cfg.return_value = {"overrides": {}, "holiday_period_threshold": 3}
            mock_ak.return_value = _make_trading_dates(holidays=holidays)
            mock_adata.return_value = (set(), set())
            cal = TradingCalendar()
            # Feb 14 Sat + Feb 15 Sun + Feb 16 Mon (holiday) = 3+ non-trading
            assert cal.is_holiday_period(date(2026, 2, 16)) is True
            # A trading day is not in a holiday period
            assert cal.is_holiday_period(date(2026, 2, 13)) is False


class TestGetCalendarInfo:
    def test_returns_expected_keys(self, calendar):
        """get_calendar_info should return all expected fields."""
        info = calendar.get_calendar_info(date(2026, 2, 9))
        assert "date" in info
        assert "is_trading_day" in info
        assert "current_session" in info
        assert "next_trading_day" in info
        assert "is_holiday_period" in info

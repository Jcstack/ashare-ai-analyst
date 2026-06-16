"""Tests for TradingCalendar holiday enrichment.

Validates:
- Known holiday dates → is_trading_day() == False
- Makeup days (补班日) → is_trading_day() == True
- Emergency closure overrides
- Full priority chain: emergency > override > adata > known_holidays > weekday
- get_holiday_name() / get_holiday_period_info() correctness
- Holiday-on-weekend: get_market_session() and get_market_status_for_ui()
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest


@pytest.fixture()
def calendar_no_adata():
    """TradingCalendar with all sources disabled (tests known_holidays + weekday fallback)."""
    with (
        patch(
            "src.data.trading_calendar._load_akshare_trading_dates",
            return_value=(set(), set()),
        ),
        patch(
            "src.data.trading_calendar._load_adata_trading_dates",
            return_value=(set(), set()),
        ),
    ):
        from src.data.trading_calendar import TradingCalendar

        return TradingCalendar()


@pytest.fixture()
def calendar_with_adata():
    """TradingCalendar with a small set of exchange dates for priority chain testing."""
    # Simulate exchange data saying 2026-02-16 (Spring Festival) IS a trading day (wrong).
    # The known_holidays should NOT override exchange data in the priority chain,
    # but emergency_closures and overrides should.
    fake_dates = {
        date(2026, 2, 16),  # wrongly says this is trading
        date(2026, 3, 2),  # normal Monday
        date(2026, 3, 3),
    }
    with (
        patch(
            "src.data.trading_calendar._load_akshare_trading_dates",
            return_value=(fake_dates, {2026}),
        ),
        patch(
            "src.data.trading_calendar._load_adata_trading_dates",
            return_value=(set(), set()),
        ),
    ):
        from src.data.trading_calendar import TradingCalendar

        return TradingCalendar()


class TestKnownHolidays:
    """Known holiday dates should be non-trading days."""

    def test_spring_festival_2026_is_not_trading(self, calendar_no_adata):
        # 2026-02-17 is a Spring Festival date
        assert calendar_no_adata.is_trading_day(date(2026, 2, 17)) is False

    def test_new_year_2026_is_not_trading(self, calendar_no_adata):
        assert calendar_no_adata.is_trading_day(date(2026, 1, 1)) is False

    def test_national_day_2025_is_not_trading(self, calendar_no_adata):
        assert calendar_no_adata.is_trading_day(date(2025, 10, 1)) is False

    def test_labor_day_2025_is_not_trading(self, calendar_no_adata):
        assert calendar_no_adata.is_trading_day(date(2025, 5, 1)) is False

    def test_normal_weekday_is_trading(self, calendar_no_adata):
        # 2026-03-02 is a Monday, not a holiday
        assert calendar_no_adata.is_trading_day(date(2026, 3, 2)) is True

    def test_weekend_is_not_trading(self, calendar_no_adata):
        # 2026-03-01 is a Sunday
        assert calendar_no_adata.is_trading_day(date(2026, 3, 1)) is False


class TestMakeupDays:
    """Makeup days (补班日) should be trading days even though they're weekends."""

    def test_spring_festival_no_makeup_2026(self, calendar_no_adata):
        # 2026 Spring Festival has no makeup days (per SSE notice)
        # Feb 14 (Sat) and Feb 15 (Sun) are normal weekends
        assert calendar_no_adata.is_trading_day(date(2026, 2, 14)) is False
        assert calendar_no_adata.is_trading_day(date(2026, 2, 15)) is False
        # Feb 24 (Tue) is first trading day after holiday
        assert calendar_no_adata.is_trading_day(date(2026, 2, 24)) is True

    def test_labor_day_no_makeup_2026(self, calendar_no_adata):
        # 2026 Labor Day has no makeup days (per SSE notice)
        # Apr 26 (Sun) is a normal weekend
        assert calendar_no_adata.is_trading_day(date(2026, 4, 26)) is False
        # May 6 (Wed) is first trading day after holiday
        assert calendar_no_adata.is_trading_day(date(2026, 5, 6)) is True


class TestEmergencyClosure:
    """Emergency closures should override everything."""

    def test_emergency_blocks_trading(self, calendar_no_adata):
        # A normal weekday should be trading
        d = date(2026, 3, 2)
        assert calendar_no_adata.is_trading_day(d) is True

        # Add emergency closure
        calendar_no_adata.add_emergency_closure(d, "台风红色预警")
        assert calendar_no_adata.is_trading_day(d) is False
        assert calendar_no_adata.is_emergency_closure(d) is True
        assert calendar_no_adata.get_emergency_reason(d) == "台风红色预警"

    def test_emergency_overrides_adata(self, calendar_with_adata):
        # adata says 2026-03-02 is trading, but emergency should block it
        d = date(2026, 3, 2)
        assert calendar_with_adata.is_trading_day(d) is True

        calendar_with_adata.add_emergency_closure(d, "熔断")
        assert calendar_with_adata.is_trading_day(d) is False


class TestPriorityChain:
    """Full priority chain: emergency > override > adata > known_holidays > weekday."""

    def test_adata_takes_priority_over_known_holidays(self, calendar_with_adata):
        # adata says 2026-02-16 IS trading (even though it's Spring Festival).
        # Since adata is higher priority than known_holidays, it should be True.
        assert calendar_with_adata.is_trading_day(date(2026, 2, 16)) is True

    def test_override_takes_priority_over_adata(self, calendar_with_adata):
        # adata says 2026-03-02 is trading, but manual override says no
        d = date(2026, 3, 2)
        calendar_with_adata._overrides[d] = False
        assert calendar_with_adata.is_trading_day(d) is False

    def test_emergency_takes_priority_over_override(self, calendar_with_adata):
        d = date(2026, 3, 3)
        # Override says trading
        calendar_with_adata._overrides[d] = True
        assert calendar_with_adata.is_trading_day(d) is True

        # Emergency overrides even the override
        calendar_with_adata.add_emergency_closure(d, "系统故障")
        assert calendar_with_adata.is_trading_day(d) is False


class TestGetHolidayName:
    """get_holiday_name() returns Chinese name for holiday dates."""

    def test_spring_festival_name(self, calendar_no_adata):
        assert calendar_no_adata.get_holiday_name(date(2026, 2, 17)) == "春节"

    def test_new_year_name(self, calendar_no_adata):
        assert calendar_no_adata.get_holiday_name(date(2026, 1, 1)) == "元旦"

    def test_non_holiday_returns_none(self, calendar_no_adata):
        assert calendar_no_adata.get_holiday_name(date(2026, 3, 2)) is None


class TestGetHolidayPeriodInfo:
    """get_holiday_period_info() returns period info with dates and days remaining."""

    def test_spring_festival_period(self, calendar_no_adata):
        info = calendar_no_adata.get_holiday_period_info(date(2026, 2, 17))
        assert info is not None
        assert info["name"] == "春节"
        assert "start_date" in info
        assert "end_date" in info
        assert "next_trading_day" in info
        assert info["days_remaining"] >= 0

    def test_non_holiday_returns_none(self, calendar_no_adata):
        info = calendar_no_adata.get_holiday_period_info(date(2026, 3, 2))
        assert info is None

    def test_national_day_period_2025(self, calendar_no_adata):
        info = calendar_no_adata.get_holiday_period_info(date(2025, 10, 1))
        assert info is not None
        assert "国庆" in info["name"]

    def test_spring_festival_weekend_before_in_period(self, calendar_no_adata):
        """Weekend dates adjacent before the holiday should be detected (Feb 14 Sat, Feb 15 Sun)."""
        for d in [date(2026, 2, 14), date(2026, 2, 15)]:
            info = calendar_no_adata.get_holiday_period_info(d)
            assert info is not None, f"{d} should be in Spring Festival period"
            assert info["name"] == "春节"

    def test_spring_festival_weekend_within_in_period(self, calendar_no_adata):
        """Weekend dates inside the holiday range should be detected (Feb 21 Sat, Feb 22 Sun)."""
        for d in [date(2026, 2, 21), date(2026, 2, 22)]:
            info = calendar_no_adata.get_holiday_period_info(d)
            assert info is not None, f"{d} should be in Spring Festival period"
            assert info["name"] == "春节"

    def test_spring_festival_period_boundaries(self, calendar_no_adata):
        """The extended range should be Feb 14 (Sat) to Feb 23 (Mon)."""
        info = calendar_no_adata.get_holiday_period_info(date(2026, 2, 14))
        assert info is not None
        assert info["start_date"] == "2026-02-16"  # original start from dates list
        assert info["end_date"] == "2026-02-23"
        assert info["next_trading_day"] == "2026-02-24"

    def test_date_outside_period_returns_none(self, calendar_no_adata):
        """Feb 13 (Fri) is not in the Spring Festival period."""
        info = calendar_no_adata.get_holiday_period_info(date(2026, 2, 13))
        assert info is None

        """Feb 24 (Tue) is the next trading day, not in the period."""
        info = calendar_no_adata.get_holiday_period_info(date(2026, 2, 24))
        assert info is None


class TestGetCalendarInfo:
    """get_calendar_info() returns enriched dict with holiday fields."""

    def test_holiday_fields_present(self, calendar_no_adata):
        info = calendar_no_adata.get_calendar_info(date(2026, 2, 17))
        assert "holiday_name" in info
        assert info["holiday_name"] == "春节"
        assert "holiday_end_date" in info
        assert "days_until_open" in info
        assert info["days_until_open"] >= 0
        assert "is_emergency_closure" in info
        assert info["is_emergency_closure"] is False

    def test_normal_day_has_null_holiday_fields(self, calendar_no_adata):
        info = calendar_no_adata.get_calendar_info(date(2026, 3, 2))
        assert info["holiday_name"] is None
        assert info["is_emergency_closure"] is False
        assert info["days_until_open"] == 0

    def test_emergency_closure_field(self, calendar_no_adata):
        d = date(2026, 3, 2)
        calendar_no_adata.add_emergency_closure(d, "临时停牌")
        info = calendar_no_adata.get_calendar_info(d)
        assert info["is_emergency_closure"] is True
        assert info["is_trading_day"] is False


class TestRefresh:
    """refresh() re-fetches adata and re-reads YAML config."""

    def test_refresh_returns_summary(self, calendar_no_adata):
        result = calendar_no_adata.refresh()
        assert "trading_dates_before" in result
        assert "trading_dates_after" in result
        assert "new_emergencies" in result

    def test_refresh_preserves_runtime_emergencies(self, calendar_no_adata):
        d = date(2026, 3, 2)
        calendar_no_adata.add_emergency_closure(d, "台风")
        assert calendar_no_adata.is_emergency_closure(d) is True

        # After refresh, runtime-injected emergency should still be present
        calendar_no_adata.refresh()
        assert calendar_no_adata.is_emergency_closure(d) is True
        assert calendar_no_adata.get_emergency_reason(d) == "台风"


class TestMarketSessionHolidayOnWeekend:
    """get_market_session() should show holiday info on weekends within holiday periods."""

    def test_weekend_in_spring_festival_shows_holiday_label(self, calendar_no_adata):
        """Feb 21 (Sat) during Spring Festival should show holiday, not generic weekend."""
        from src.utils.market_hours import CST, get_market_session

        now = datetime(2026, 2, 21, 10, 0, 0, tzinfo=CST)
        with patch(
            "src.data.trading_calendar.TradingCalendar", return_value=calendar_no_adata
        ):
            result = get_market_session(now)
        assert result["session"] == "non_trading"
        assert "春节" in result["label"]
        assert result["is_trading"] is False

    def test_weekend_in_spring_festival_includes_next_trading_day(
        self, calendar_no_adata
    ):
        """Holiday weekend description should mention next trading day."""
        from src.utils.market_hours import CST, get_market_session

        now = datetime(2026, 2, 14, 10, 0, 0, tzinfo=CST)
        with patch(
            "src.data.trading_calendar.TradingCalendar", return_value=calendar_no_adata
        ):
            result = get_market_session(now)
        assert "春节" in result["label"]
        assert "2026-02-24" in result["description"]

    def test_normal_weekend_still_shows_weekend(self, calendar_no_adata):
        """A regular weekend (not adjacent to holiday) should still show generic weekend label."""
        from src.utils.market_hours import CST, get_market_session

        # Mar 7 (Sat) — no holiday
        now = datetime(2026, 3, 7, 10, 0, 0, tzinfo=CST)
        with patch(
            "src.data.trading_calendar.TradingCalendar", return_value=calendar_no_adata
        ):
            result = get_market_session(now)
        assert result["label"] == "非交易日（周末）"


class TestMarketStatusUIHolidayOnWeekend:
    """get_market_status_for_ui() should return holiday status on weekends within holiday periods."""

    def test_weekend_in_holiday_returns_holiday_status(self, calendar_no_adata):
        """Feb 21 (Sat) during Spring Festival should return status='holiday'."""
        from src.utils.market_hours import CST, get_market_status_for_ui

        now = datetime(2026, 2, 21, 10, 0, 0, tzinfo=CST)
        with patch(
            "src.data.trading_calendar.TradingCalendar", return_value=calendar_no_adata
        ):
            result = get_market_status_for_ui(now)
        assert result["status"] == "holiday"
        assert "春节" in result["label"]
        assert result["holiday_info"] is not None
        assert result["holiday_info"]["name"] == "春节"

    def test_weekend_before_holiday_returns_holiday_status(self, calendar_no_adata):
        """Feb 14 (Sat) adjacent to Spring Festival should return status='holiday'."""
        from src.utils.market_hours import CST, get_market_status_for_ui

        now = datetime(2026, 2, 14, 10, 0, 0, tzinfo=CST)
        with patch(
            "src.data.trading_calendar.TradingCalendar", return_value=calendar_no_adata
        ):
            result = get_market_status_for_ui(now)
        assert result["status"] == "holiday"
        assert result["holiday_info"] is not None
        assert result["holiday_info"]["name"] == "春节"

    def test_normal_weekend_returns_closed(self, calendar_no_adata):
        """A regular weekend should return status='closed', not 'holiday'."""
        from src.utils.market_hours import CST, get_market_status_for_ui

        now = datetime(2026, 3, 7, 10, 0, 0, tzinfo=CST)
        with patch(
            "src.data.trading_calendar.TradingCalendar", return_value=calendar_no_adata
        ):
            result = get_market_status_for_ui(now)
        assert result["status"] == "closed"
        assert result["holiday_info"] is None

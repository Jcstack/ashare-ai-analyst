"""Trading calendar service for A-share market.

Determines whether a given date is a trading day, what the current
market session is, and whether we are in a holiday period.

Fetches actual trading dates from akshare (EastMoney index history)
as the primary source, with adata as fallback.  Manual overrides in
config/calendar.yaml take highest priority.

Priority chain for is_trading_day():
  emergency_closures > manual overrides > exchange data (akshare/adata) > known_holidays > weekday heuristic

Per PRD v3.2 FR-HS001: Trading calendar service.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("data.trading_calendar")


class MarketSession(str, Enum):
    """Current market session phase."""

    PRE_MARKET = "pre_market"
    MORNING = "morning"
    LUNCH_BREAK = "lunch_break"
    AFTERNOON = "afternoon"
    AFTER_HOURS = "after_hours"
    CLOSED = "closed"


def _load_akshare_trading_dates(years: list[int]) -> tuple[set[date], set[int]]:
    """Load trading dates from akshare via SSE index history (EastMoney).

    Uses the Shanghai Composite Index (000001) daily history — each row
    represents a confirmed trading day.  This is fast, reliable, and
    covers all years that have actual market data.

    Returns (trading_dates, covered_years).
    """
    import akshare as ak

    start_year = min(years)
    end_year = max(years)
    start_date = f"{start_year}0101"
    end_date = f"{end_year}1231"

    result: set[date] = set()
    covered: set[int] = set()
    try:
        from src.data.eastmoney_proxy import em_api_call

        df = em_api_call(
            ak.stock_zh_index_daily_em,
            symbol="sh000001",
            start_date=start_date,
            end_date=end_date,
        )
        for d_str in df["date"]:
            d = date.fromisoformat(str(d_str))
            if d.year in years:
                result.add(d)
                covered.add(d.year)
        logger.info(
            "Loaded %d trading dates from akshare (years %s)", len(result), covered
        )
    except Exception as exc:
        logger.warning("akshare trading calendar failed: %s", exc)
    return result, covered


def _load_adata_trading_dates(
    years: list[int], timeout_per_year: int = 5
) -> tuple[set[date], set[int]]:
    """Load trading dates from adata (SZSE data source, fallback).

    Returns a tuple of (trading_dates, covered_years) where covered_years
    contains only years that returned actual data.  Each year request is
    guarded by a per-year timeout to avoid hanging on unavailable years.
    """
    import concurrent.futures

    from adata.stock.info.trade_calendar import TradeCalendar as AdataCalendar

    result: set[date] = set()
    covered: set[int] = set()
    tc = AdataCalendar()

    def _fetch_year(tc_inst, yr):
        from src.data.fetcher import _bypass_proxy

        with _bypass_proxy():
            return tc_inst.trade_calendar(year=yr)

    pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="adata-cal"
    )
    for year in years:
        try:
            future = pool.submit(_fetch_year, tc, year)
            df = future.result(timeout=timeout_per_year)
            trading = df[df["trade_status"] == 1]["trade_date"]
            year_dates = {date.fromisoformat(str(d_str)) for d_str in trading}
            if year_dates:
                result |= year_dates
                covered.add(year)
            else:
                logger.warning("adata returned no data for %d", year)
        except (concurrent.futures.TimeoutError, TimeoutError):
            logger.warning("adata calendar timed out for %d", year)
            future.cancel()
        except Exception:
            logger.warning("adata calendar failed for %d", year)
    pool.shutdown(wait=False, cancel_futures=True)
    return result, covered


class TradingCalendar:
    """A-share trading calendar backed by exchange data with manual overrides.

    Source chain: akshare (EastMoney index history) → adata (SZSE) → weekday heuristic.
    """

    def __init__(self) -> None:
        self._config = self._load_config()
        self._overrides: dict[date, bool] = self._parse_overrides()
        self._sessions = self._parse_sessions()
        self._trading_dates: set[date] = self._load_trading_dates()

        # Holiday/emergency data
        self._known_non_trading: set[date] = set()
        self._known_makeup_trading: set[date] = set()
        self._holiday_name_map: dict[date, str] = {}
        self._holiday_ranges: list[dict] = []
        self._emergency_closures: dict[date, str] = {}
        self._parse_known_holidays()
        self._parse_emergency_closures()

        logger.info(
            "TradingCalendar initialized (%d trading dates, %d overrides, "
            "%d holiday dates, %d makeup days, %d emergencies)",
            len(self._trading_dates),
            len(self._overrides),
            len(self._known_non_trading),
            len(self._known_makeup_trading),
            len(self._emergency_closures),
        )

    def _load_config(self) -> dict:
        try:
            return load_config("calendar")
        except FileNotFoundError:
            logger.warning("config/calendar.yaml not found; using defaults")
            return {}

    def _parse_overrides(self) -> dict[date, bool]:
        raw = self._config.get("overrides") or {}
        result: dict[date, bool] = {}
        for date_str, is_trading in raw.items():
            try:
                d = date.fromisoformat(str(date_str))
                result[d] = bool(is_trading)
            except (ValueError, TypeError):
                logger.warning("Invalid override date: %s", date_str)
        return result

    def _parse_sessions(self) -> dict[str, tuple[time, time]]:
        raw = self._config.get("sessions", {})
        result: dict[str, tuple[time, time]] = {}
        for name, cfg in raw.items():
            try:
                start = time.fromisoformat(cfg["start"])
                end = time.fromisoformat(cfg["end"])
                result[name] = (start, end)
            except (KeyError, ValueError, TypeError):
                logger.warning("Invalid session config: %s", name)
        if not result:
            # Defaults
            result = {
                "pre_market": (time(9, 15), time(9, 30)),
                "morning": (time(9, 30), time(11, 30)),
                "lunch_break": (time(11, 30), time(13, 0)),
                "afternoon": (time(13, 0), time(15, 0)),
                "after_hours": (time(15, 0), time(17, 0)),
            }
        return result

    def _load_trading_dates(self) -> set[date]:
        """Load trading dates via akshare → adata fallback chain."""
        current_year = date.today().year
        years = [current_year - 1, current_year, current_year + 1]

        # Primary: akshare (EastMoney index history — real exchange data)
        dates, covered = _load_akshare_trading_dates(years)

        # Fallback: adata for any years akshare didn't cover
        missing = [y for y in years if y not in covered]
        if missing:
            adata_dates, adata_covered = _load_adata_trading_dates(missing)
            dates |= adata_dates
            covered |= adata_covered

        self._covered_years = covered
        # Track the latest date we have authoritative data for.
        # Dates beyond this must fall through to heuristic/known_holidays.
        self._max_covered_date = max(dates) if dates else None
        if not dates:
            logger.warning(
                "All calendar sources failed; falling back to weekday heuristic"
            )
        return dates

    def _parse_known_holidays(self) -> None:
        """Parse known_holidays config into lookup structures."""
        raw = self._config.get("known_holidays") or {}
        for _key, holiday in raw.items():
            name = holiday.get("name", "")
            dates_raw = holiday.get("dates") or []
            makeup_raw = holiday.get("makeup_days") or []

            holiday_dates: list[date] = []
            for d_str in dates_raw:
                try:
                    d = date.fromisoformat(str(d_str))
                    self._known_non_trading.add(d)
                    self._holiday_name_map[d] = name
                    holiday_dates.append(d)
                except (ValueError, TypeError):
                    logger.warning("Invalid holiday date: %s", d_str)

            for d_str in makeup_raw:
                try:
                    d = date.fromisoformat(str(d_str))
                    self._known_makeup_trading.add(d)
                except (ValueError, TypeError):
                    logger.warning("Invalid makeup date: %s", d_str)

            if holiday_dates:
                self._holiday_ranges.append(
                    {
                        "name": name,
                        "dates": sorted(holiday_dates),
                    }
                )

    def _parse_emergency_closures(self) -> None:
        """Parse emergency_closures config."""
        raw = self._config.get("emergency_closures") or []
        for entry in raw:
            try:
                d = date.fromisoformat(str(entry["date"]))
                reason = str(entry.get("reason", "紧急停牌"))
                self._emergency_closures[d] = reason
            except (KeyError, ValueError, TypeError):
                logger.warning("Invalid emergency closure entry: %s", entry)

    def is_trading_day(self, d: date | None = None) -> bool:
        """Check if the given date is an A-share trading day.

        Priority: emergency > manual overrides > exchange data > known_holidays > weekday heuristic.
        """
        if d is None:
            d = date.today()

        # Emergency closures — highest priority
        if d in self._emergency_closures:
            return False

        # Manual override
        if d in self._overrides:
            return self._overrides[d]

        # Exchange trading dates (akshare / adata)
        # Only trust for dates up to the last known trading date;
        # future dates must fall through to known_holidays / heuristic.
        if (
            self._trading_dates
            and self._max_covered_date
            and d <= self._max_covered_date
        ):
            return d in self._trading_dates

        # Known holidays: makeup days are trading days, holiday dates are not
        if d in self._known_makeup_trading:
            return True
        if d in self._known_non_trading:
            return False

        # Fallback: weekdays are trading days (only if adata unavailable)
        return d.weekday() < 5

    def current_session(self, now: datetime | None = None) -> MarketSession:
        """Determine the current market session phase."""
        if now is None:
            now = datetime.now()

        if not self.is_trading_day(now.date()):
            return MarketSession.CLOSED

        t = now.time()

        session_map = {
            "pre_market": MarketSession.PRE_MARKET,
            "morning": MarketSession.MORNING,
            "lunch_break": MarketSession.LUNCH_BREAK,
            "afternoon": MarketSession.AFTERNOON,
            "after_hours": MarketSession.AFTER_HOURS,
        }

        for name, session_enum in session_map.items():
            bounds = self._sessions.get(name)
            if bounds and bounds[0] <= t < bounds[1]:
                return session_enum

        return MarketSession.CLOSED

    def next_trading_day(self, after: date | None = None) -> date:
        """Find the next trading day strictly after the given date."""
        if after is None:
            after = date.today()

        d = after + timedelta(days=1)
        # Cap at 30 iterations to avoid infinite loop
        for _ in range(30):
            if self.is_trading_day(d):
                return d
            d += timedelta(days=1)

        # Fallback: return next weekday
        return d

    def is_holiday_period(self, d: date | None = None) -> bool:
        """Check if the given date is within a holiday period.

        A holiday period is defined as >= N consecutive non-trading days
        (configured by ``holiday_period_threshold``, default 3).
        """
        if d is None:
            d = date.today()

        threshold = self._config.get("holiday_period_threshold", 3)

        # Count consecutive non-trading days around the date
        consecutive = 0
        check = d
        while not self.is_trading_day(check) and consecutive < threshold:
            consecutive += 1
            check -= timedelta(days=1)

        if consecutive >= threshold:
            return True

        # Also check forward
        consecutive = 0
        check = d
        while not self.is_trading_day(check) and consecutive < threshold:
            consecutive += 1
            check += timedelta(days=1)

        return consecutive >= threshold

    def get_holiday_name(self, d: date | None = None) -> str | None:
        """Return the Chinese holiday name for the given date, or None."""
        if d is None:
            d = date.today()
        return self._holiday_name_map.get(d)

    def get_holiday_period_info(self, d: date | None = None) -> dict | None:
        """Return holiday period info if the date falls within a known holiday.

        Returns:
            Dict with name, start_date, end_date, next_trading_day, days_remaining
            or None if not in a holiday period.
        """
        if d is None:
            d = date.today()

        # Find which holiday range contains this date (including weekends adjacent)
        for hr in self._holiday_ranges:
            dates = hr["dates"]
            start = dates[0]
            end = dates[-1]

            # Extend range backward to include adjacent weekends
            range_start = start
            while (range_start - timedelta(days=1)).weekday() >= 5:
                range_start -= timedelta(days=1)

            # Extend range forward to include adjacent weekends
            range_end = end
            while (range_end + timedelta(days=1)).weekday() >= 5:
                range_end += timedelta(days=1)

            if range_start <= d <= range_end:
                ntd = self.next_trading_day(range_end)
                days_remaining = (ntd - d).days
                return {
                    "name": hr["name"],
                    "start_date": start.isoformat(),
                    "end_date": range_end.isoformat(),
                    "next_trading_day": ntd.isoformat(),
                    "days_remaining": max(0, days_remaining),
                }

        # Check if current date is a known holiday date directly
        if d in self._holiday_name_map:
            name = self._holiday_name_map[d]
            ntd = self.next_trading_day(d)
            return {
                "name": name,
                "start_date": d.isoformat(),
                "end_date": d.isoformat(),
                "next_trading_day": ntd.isoformat(),
                "days_remaining": (ntd - d).days,
            }

        return None

    def add_emergency_closure(self, d: date, reason: str) -> None:
        """Add a runtime emergency closure (e.g. circuit breaker, typhoon)."""
        self._emergency_closures[d] = reason
        logger.warning("Emergency closure added: %s — %s", d.isoformat(), reason)

    def is_emergency_closure(self, d: date | None = None) -> bool:
        """Check if the given date is an emergency closure."""
        if d is None:
            d = date.today()
        return d in self._emergency_closures

    def get_emergency_reason(self, d: date | None = None) -> str | None:
        """Return the emergency closure reason, or None."""
        if d is None:
            d = date.today()
        return self._emergency_closures.get(d)

    def refresh(self) -> dict:
        """Re-fetch trading dates and re-read YAML emergency_closures.

        Called by the daily calendar refresh task to pick up:
        - Updated trading dates from akshare/adata
        - Manually added emergency_closures in config/calendar.yaml

        Returns a summary of what changed.
        """
        old_count = len(self._trading_dates)
        old_emergencies = set(self._emergency_closures.keys())

        # Re-fetch adata
        new_dates = self._load_trading_dates()
        if new_dates:
            self._trading_dates = new_dates

        # Re-read config for emergency_closures (preserving runtime-injected ones)
        try:
            fresh_config = self._load_config()
            runtime_emergencies = {
                d: r
                for d, r in self._emergency_closures.items()
                if d not in old_emergencies
                or self._emergency_closures[d]
                != (self._config.get("emergency_closures") or {}).get(d.isoformat(), "")
            }
            self._config = fresh_config
            self._parse_emergency_closures()
            # Merge back runtime-injected closures
            self._emergency_closures.update(runtime_emergencies)
        except Exception:
            logger.warning("Failed to reload config during refresh")

        new_count = len(self._trading_dates)
        new_emergencies = set(self._emergency_closures.keys())
        added = new_emergencies - old_emergencies

        logger.info(
            "TradingCalendar refreshed: %d→%d trading dates, %d new emergencies",
            old_count,
            new_count,
            len(added),
        )
        return {
            "trading_dates_before": old_count,
            "trading_dates_after": new_count,
            "new_emergencies": len(added),
        }

    def get_calendar_info(self, d: date | None = None) -> dict:
        """Return a summary dict suitable for the /market/calendar API."""
        if d is None:
            d = date.today()

        now = datetime.now()
        ntd = self.next_trading_day(d)

        # Holiday info
        holiday_name = self.get_holiday_name(d)
        holiday_info = self.get_holiday_period_info(d)
        holiday_end_date = holiday_info["end_date"] if holiday_info else None
        days_until_open = (ntd - d).days if not self.is_trading_day(d) else 0

        return {
            "date": d.isoformat(),
            "is_trading_day": self.is_trading_day(d),
            "current_session": self.current_session(now).value,
            "next_trading_day": ntd.isoformat(),
            "is_holiday_period": self.is_holiday_period(d),
            "holiday_name": holiday_name,
            "holiday_end_date": holiday_end_date,
            "days_until_open": days_until_open,
            "is_emergency_closure": self.is_emergency_closure(d),
        }

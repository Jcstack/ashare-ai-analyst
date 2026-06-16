"""Trading-day-aware refresh scheduler.

Part of v23.0 Phase 2. Determines optimal refresh intervals based on
current market session to balance freshness vs resource usage.

Interval logic:
- Trading day pre-open (07:00-09:15): 120s  (high-freq for overnight news)
- Trading hours (09:15-15:00):        300s  (normal)
- Trading day after-hours (15:00-20:00): 600s (lower freq)
- Non-trading day or night:           1800s  (30min)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.trading_calendar import TradingCalendar

logger = logging.getLogger(__name__)

# Default intervals in seconds per session
_DEFAULT_INTERVALS: dict[str, int] = {
    "pre_open": 120,  # 07:00-09:15 trading day
    "trading_hours": 300,  # 09:15-15:00
    "after_hours": 600,  # 15:00-20:00 trading day
    "off_hours": 1800,  # night or non-trading day
}


class RefreshScheduler:
    """Determines appropriate refresh intervals based on trading session.

    Uses TradingCalendar to check if the current date is a trading day,
    then maps the time of day to the correct interval bucket.

    If no TradingCalendar is provided, defaults to ``trading_hours`` interval.
    """

    def __init__(
        self,
        trading_calendar: TradingCalendar | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._calendar = trading_calendar
        cfg = config or {}
        self._intervals: dict[str, int] = {
            **_DEFAULT_INTERVALS,
            **cfg.get("intervals", {}),
        }

    def get_refresh_interval(self, now: datetime | None = None) -> int:
        """Return the appropriate refresh interval in seconds for the current time.

        Args:
            now: The current datetime. Defaults to ``datetime.now()`` if not given.

        Returns:
            Refresh interval in seconds.
        """
        if self._calendar is None:
            return self._intervals["trading_hours"]

        if now is None:
            now = datetime.now()

        if not self._calendar.is_trading_day(now.date()):
            return self._intervals["off_hours"]

        # Convert to minutes since midnight for easy range comparison
        time_val = now.hour * 60 + now.minute

        if time_val < 7 * 60:  # before 07:00
            return self._intervals["off_hours"]
        if time_val < 9 * 60 + 15:  # 07:00-09:15
            return self._intervals["pre_open"]
        if time_val < 15 * 60:  # 09:15-15:00
            return self._intervals["trading_hours"]
        if time_val < 20 * 60:  # 15:00-20:00
            return self._intervals["after_hours"]
        return self._intervals["off_hours"]  # after 20:00

    def should_refresh(
        self, last_refresh_time: float, now: datetime | None = None
    ) -> bool:
        """Check if enough time has elapsed since last refresh.

        Args:
            last_refresh_time: Unix timestamp of the last refresh.
            now: The current datetime (for interval calculation).

        Returns:
            True if the elapsed time exceeds the current interval.
        """
        interval = self.get_refresh_interval(now)
        return (time.time() - last_refresh_time) >= interval

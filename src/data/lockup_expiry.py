"""Lock-up expiry (限售解禁) fetcher via EastMoney datacenter API.

Tracks when restricted shares become tradeable — a reliable predictor of
sell pressure. Major unlocks (>5% of total shares or >10 billion yuan)
frequently trigger significant price drops.

Data source: datacenter-web.eastmoney.com (direct API, not AKShare wrapper).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.data.circuit_breaker import CircuitBreaker
from src.data.eastmoney_datacenter import EastMoneyDatacenter
from src.utils.logger import get_logger

logger = get_logger("data.lockup_expiry")

__all__ = ["LockupExpiry", "LockupExpiryFetcher"]

_CACHE_TTL = 3600  # 1 hour — lock-up dates don't change frequently

# Holder type classification from Chinese labels
_HOLDER_TYPE_MAP: dict[str, str] = {
    "首发原股东限售股份": "founder",
    "首发一般股份": "founder",
    "首发战略配售股份": "placement",
    "定向增发机构配售股份": "institution",
    "股权激励限售股份": "incentive",
    "追加承诺限售股份": "commitment",
}


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


@dataclass
class LockupExpiry:
    """A single lock-up expiry event."""

    symbol: str
    name: str
    unlock_date: str  # YYYY-MM-DD
    shares_unlocked: int  # number of shares
    shares_pct_of_total: float  # % of total shares
    shares_market_value_wan: float  # market value in 万元
    holder_name: str  # who's unlocking
    holder_type: str  # founder|institution|placement|incentive|commitment|other
    days_until_unlock: int  # computed, negative = already unlocked

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "unlock_date": self.unlock_date,
            "shares_unlocked": self.shares_unlocked,
            "pct_of_total": self.shares_pct_of_total,
            "market_value_wan": self.shares_market_value_wan,
            "holder_name": self.holder_name,
            "holder_type": self.holder_type,
            "days_until_unlock": self.days_until_unlock,
        }


class LockupExpiryFetcher:
    """Fetch lock-up expiry data from EastMoney datacenter.

    Usage::

        fetcher = LockupExpiryFetcher()
        upcoming = await fetcher.fetch_upcoming(days=30)
        for_stock = await fetcher.fetch_for_symbol("601318", days=90)
    """

    # EastMoney datacenter report for restricted share circulation
    _REPORT_NAME = "RPT_LIFT_STAGE"
    _SORT_COLUMN = "FREE_DATE"

    def __init__(self) -> None:
        self._dc = EastMoneyDatacenter()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._circuit = CircuitBreaker(
            "lockup_expiry", failure_threshold=3, recovery_timeout=300.0
        )

    def _get_cache(self, key: str) -> Any | None:
        if key in self._cache:
            expire_ts, val = self._cache[key]
            if time.time() < expire_ts:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time() + _CACHE_TTL, val)

    def _parse_row(self, row: dict[str, Any]) -> LockupExpiry | None:
        """Parse a single datacenter row into LockupExpiry."""
        symbol = str(row.get("SECURITY_CODE", ""))
        if not symbol or len(symbol) != 6:
            return None

        name = str(row.get("SECURITY_NAME_ABBR", ""))

        # Parse unlock date
        free_date_raw = row.get("FREE_DATE", "")
        if not free_date_raw:
            return None
        try:
            if "T" in str(free_date_raw):
                unlock_dt = datetime.fromisoformat(str(free_date_raw).split("T")[0])
            else:
                unlock_dt = datetime.strptime(str(free_date_raw)[:10], "%Y-%m-%d")
            unlock_date = unlock_dt.strftime("%Y-%m-%d")
            days_until = (unlock_dt - datetime.now()).days
        except (ValueError, TypeError):
            return None

        shares = _safe_int(row.get("CURRENT_FREE_SHARES", row.get("ABLE_FREE_SHARES")))
        pct = _safe_float(row.get("FREE_RATIO", row.get("TOTAL_RATIO", 0)))
        market_value = _safe_float(row.get("LIFT_MARKET_CAP", 0))
        # Convert to 万元 if in yuan
        if market_value > 1_000_000:
            market_value = market_value / 10_000

        holder_name = str(row.get("HOLDER_NAME", row.get("LIMITED_HOLDER_NAME", "")))
        share_type = str(row.get("FREE_SHARES_TYPE", row.get("RESTRICTED_TYPE", "")))
        holder_type = _HOLDER_TYPE_MAP.get(share_type, "other")

        return LockupExpiry(
            symbol=symbol,
            name=name,
            unlock_date=unlock_date,
            shares_unlocked=shares,
            shares_pct_of_total=pct,
            shares_market_value_wan=market_value,
            holder_name=holder_name,
            holder_type=holder_type,
            days_until_unlock=days_until,
        )

    def fetch_upcoming_sync(self, days: int = 30) -> list[LockupExpiry]:
        """Fetch upcoming lock-up expiry events.

        Args:
            days: Look ahead window in days.

        Returns:
            List of upcoming lock-up events, sorted by unlock date.
        """
        cache_key = f"upcoming_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit.state == "open":
            logger.debug("Circuit breaker open, skipping lockup query")
            return []

        today = datetime.now()
        end = today + timedelta(days=days)
        filter_str = f"(FREE_DATE>='{today:%Y-%m-%d}')(FREE_DATE<='{end:%Y-%m-%d}')"

        try:
            df = self._dc.query_all_pages(
                self._REPORT_NAME,
                max_pages=3,
                page_size=50,
                sort_columns=self._SORT_COLUMN,
                sort_types="1",  # ascending by date
                filter_str=filter_str,
            )

            if df.empty:
                self._circuit._on_success()
                result: list[LockupExpiry] = []
                self._set_cache(cache_key, result)
                return result

            results: list[LockupExpiry] = []
            for _, row in df.iterrows():
                entry = self._parse_row(row.to_dict())
                if entry:
                    results.append(entry)

            self._circuit._on_success()
            self._set_cache(cache_key, results)
            logger.info(
                "Fetched %d upcoming lock-up events (next %d days)", len(results), days
            )
            return results

        except Exception as exc:
            logger.warning("Lock-up expiry fetch failed: %s", exc)
            self._circuit._on_failure()
            return []

    def fetch_for_symbol_sync(self, symbol: str, days: int = 90) -> list[LockupExpiry]:
        """Fetch lock-up expiry events for a specific stock.

        Args:
            symbol: 6-digit stock code.
            days: Look ahead + behind window.

        Returns:
            List of lock-up events, sorted by unlock date.
        """
        cache_key = f"symbol_{symbol}_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit.state == "open":
            return []

        today = datetime.now()
        start = today - timedelta(days=30)  # include recent past
        end = today + timedelta(days=days)
        filter_str = (
            f'(SECURITY_CODE="{symbol}")'
            f"(FREE_DATE>='{start:%Y-%m-%d}')"
            f"(FREE_DATE<='{end:%Y-%m-%d}')"
        )

        try:
            df = self._dc.query(
                self._REPORT_NAME,
                page_size=50,
                sort_columns=self._SORT_COLUMN,
                sort_types="1",
                filter_str=filter_str,
            )

            results: list[LockupExpiry] = []
            if not df.empty:
                for _, row in df.iterrows():
                    entry = self._parse_row(row.to_dict())
                    if entry:
                        results.append(entry)

            self._circuit._on_success()
            self._set_cache(cache_key, results)
            return results

        except Exception as exc:
            logger.warning("Lock-up expiry fetch for %s failed: %s", symbol, exc)
            self._circuit._on_failure()
            return []

    @staticmethod
    def is_major_unlock(expiry: LockupExpiry) -> bool:
        """Check if this is a major unlock event.

        Major = >5% of total shares OR >10亿 market value.
        """
        return (
            expiry.shares_pct_of_total > 5.0 or expiry.shares_market_value_wan > 100_000
        )

    def get_unlock_summary(
        self, symbol: str, entries: list[LockupExpiry]
    ) -> str | None:
        """Get a one-line summary for a stock's upcoming unlock.

        Returns:
            String like "30日内解禁2.3%(约5.2亿元), 15天后" or None.
        """
        upcoming = [
            e for e in entries if e.symbol == symbol and e.days_until_unlock >= 0
        ]
        if not upcoming:
            return None

        nearest = min(upcoming, key=lambda e: e.days_until_unlock)
        total_pct = sum(e.shares_pct_of_total for e in upcoming)
        total_value = sum(e.shares_market_value_wan for e in upcoming)

        value_str = (
            f"{total_value / 10000:.1f}亿元"
            if total_value >= 10000
            else f"{total_value:.0f}万元"
        )
        return f"30日内解禁{total_pct:.1f}%(约{value_str}), {nearest.days_until_unlock}天后"

    # -- Async wrappers -------------------------------------------------------

    async def fetch_upcoming(self, days: int = 30) -> list[LockupExpiry]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_upcoming_sync, days)

    async def fetch_for_symbol(self, symbol: str, days: int = 90) -> list[LockupExpiry]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.fetch_for_symbol_sync, symbol, days
        )

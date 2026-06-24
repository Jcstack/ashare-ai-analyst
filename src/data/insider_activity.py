"""Insider activity (增减持) fetcher via EastMoney datacenter API.

Tracks major shareholder and executive share changes — a strong signal
of insider sentiment. Net buying by directors/majors is bullish;
sustained selling often precedes bad news.

Data source: datacenter-web.eastmoney.com (direct API).
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.data.circuit_breaker import CircuitBreaker
from src.data.eastmoney_datacenter import EastMoneyDatacenter
from src.utils.logger import get_logger

logger = get_logger("data.insider_activity")

__all__ = ["InsiderActivity", "InsiderActivityFetcher"]

_CACHE_TTL = 1800  # 30 minutes — insider trades reported after the fact

_HOLDER_TYPE_MAP: dict[str, str] = {
    "高管": "senior_mgmt",
    "董事": "director",
    "监事": "supervisor",
    "股东": "major_shareholder",
}


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) else f
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
class InsiderActivity:
    """A single insider trading record (增减持)."""

    symbol: str
    name: str
    holder_name: str
    holder_type: str  # director|supervisor|senior_mgmt|major_shareholder
    direction: str  # increase|decrease
    change_shares: int
    change_pct: float  # % of total shares
    avg_price: float
    total_amount_wan: float
    start_date: str
    end_date: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "holder": self.holder_name,
            "holder_type": self.holder_type,
            "direction": self.direction,
            "shares": self.change_shares,
            "pct": self.change_pct,
            "avg_price": self.avg_price,
            "amount_wan": self.total_amount_wan,
            "start": self.start_date,
            "end": self.end_date,
        }


class InsiderActivityFetcher:
    """Fetch insider trading (增减持) data from EastMoney datacenter.

    Usage::

        fetcher = InsiderActivityFetcher()
        recent = await fetcher.fetch_recent(days=30)
        for_stock = await fetcher.fetch_for_symbol("601318", days=90)
        direction = fetcher.net_direction_sync("601318", days=90)
    """

    _REPORT_NAME = "RPT_EXECUTIVE_HOLD_DETAILS"
    _SORT_COLUMN = "CHANGE_DATE"

    def __init__(self) -> None:
        self._dc = EastMoneyDatacenter()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._circuit = CircuitBreaker(
            "insider_activity", failure_threshold=3, recovery_timeout=300.0
        )

    def _get_cache(self, key: str) -> Any | None:
        if key in self._cache:
            expire_ts, val = self._cache[key]
            if time.time() < expire_ts:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time() + _CACHE_TTL, val)

    def _parse_date(self, raw: Any) -> str:
        if not raw:
            return ""
        try:
            s = str(raw)
            if "T" in s:
                return s.split("T")[0]
            return s[:10]
        except (ValueError, TypeError):
            return ""

    def _parse_row(self, row: dict[str, Any]) -> InsiderActivity | None:
        symbol = str(row.get("SECURITY_CODE", ""))
        if not symbol or len(symbol) != 6:
            return None

        name = str(row.get("SECURITY_NAME", row.get("SECURITY_NAME_ABBR", "")))
        holder_name = str(row.get("PERSON_NAME", row.get("HOLDER_NAME", "")))

        # Determine holder type from POSITION_NAME (e.g., "高级管理人员", "董事")
        holder_type_raw = str(
            row.get("POSITION_NAME", row.get("PERSON_DSC", row.get("HOLDER_TYPE", "")))
        )
        holder_type = "major_shareholder"
        for cn, en in _HOLDER_TYPE_MAP.items():
            if cn in holder_type_raw:
                holder_type = en
                break

        # Direction — CHANGE_SHARES is negative for sells
        change_raw = _safe_float(row.get("CHANGE_SHARES", row.get("CHANGE_NUM", 0)))
        direction = "increase" if change_raw > 0 else "decrease"

        change_shares = abs(_safe_int(row.get("CHANGE_SHARES", row.get("CHANGE_NUM"))))
        change_pct = abs(_safe_float(row.get("CHANGE_RATIO")))
        avg_price = _safe_float(row.get("AVERAGE_PRICE", row.get("AVG_PRICE")))
        total_amount = abs(_safe_float(row.get("CHANGE_AMOUNT")))
        # API returns yuan, convert to 万
        if abs(total_amount) > 100:
            total_amount = total_amount / 10_000

        start_date = self._parse_date(row.get("START_DATE", row.get("CHANGE_DATE")))
        end_date = self._parse_date(row.get("CHANGE_DATE"))

        return InsiderActivity(
            symbol=symbol,
            name=name,
            holder_name=holder_name,
            holder_type=holder_type,
            direction=direction,
            change_shares=change_shares,
            change_pct=change_pct,
            avg_price=avg_price,
            total_amount_wan=total_amount,
            start_date=start_date,
            end_date=end_date,
        )

    def fetch_recent_sync(self, days: int = 30) -> list[InsiderActivity]:
        """Fetch recent insider activity across all stocks."""
        cache_key = f"recent_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit.state == "open":
            return []

        end = datetime.now()
        start = end - timedelta(days=days)
        filter_str = f"(CHANGE_DATE>='{start:%Y-%m-%d}')(CHANGE_DATE<='{end:%Y-%m-%d}')"

        try:
            df = self._dc.query_all_pages(
                self._REPORT_NAME,
                max_pages=3,
                page_size=50,
                sort_columns=self._SORT_COLUMN,
                sort_types="-1",
                filter_str=filter_str,
            )

            results: list[InsiderActivity] = []
            if not df.empty:
                for _, row in df.iterrows():
                    entry = self._parse_row(row.to_dict())
                    if entry:
                        results.append(entry)

            self._circuit._on_success()
            self._set_cache(cache_key, results)
            logger.info(
                "Fetched %d insider activity records (last %d days)", len(results), days
            )
            return results

        except Exception as exc:
            logger.warning("Insider activity fetch failed: %s", exc)
            self._circuit._on_failure()
            return []

    def fetch_for_symbol_sync(
        self, symbol: str, days: int = 90
    ) -> list[InsiderActivity]:
        """Fetch insider activity for a specific stock."""
        cache_key = f"symbol_{symbol}_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit.state == "open":
            return []

        end = datetime.now()
        start = end - timedelta(days=days)
        filter_str = (
            f'(SECURITY_CODE="{symbol}")'
            f"(CHANGE_DATE>='{start:%Y-%m-%d}')"
            f"(CHANGE_DATE<='{end:%Y-%m-%d}')"
        )

        try:
            df = self._dc.query(
                self._REPORT_NAME,
                page_size=50,
                sort_columns=self._SORT_COLUMN,
                sort_types="-1",
                filter_str=filter_str,
            )

            results: list[InsiderActivity] = []
            if not df.empty:
                for _, row in df.iterrows():
                    entry = self._parse_row(row.to_dict())
                    if entry:
                        results.append(entry)

            self._circuit._on_success()
            self._set_cache(cache_key, results)
            return results

        except Exception as exc:
            logger.warning("Insider activity fetch for %s failed: %s", symbol, exc)
            self._circuit._on_failure()
            return []

    def net_direction_sync(self, symbol: str, days: int = 90) -> str:
        """Determine net insider direction for a stock.

        Returns:
            "increase" | "decrease" | "neutral"
        """
        activities = self.fetch_for_symbol_sync(symbol, days)
        if not activities:
            return "neutral"

        net_amount = 0.0
        for a in activities:
            if a.direction == "increase":
                net_amount += a.total_amount_wan
            else:
                net_amount -= a.total_amount_wan

        if net_amount > 100:  # > 100万 net buy
            return "increase"
        elif net_amount < -100:  # > 100万 net sell
            return "decrease"
        return "neutral"

    # -- Async wrappers -------------------------------------------------------

    async def fetch_recent(self, days: int = 30) -> list[InsiderActivity]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_recent_sync, days)

    async def fetch_for_symbol(
        self, symbol: str, days: int = 90
    ) -> list[InsiderActivity]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.fetch_for_symbol_sync, symbol, days
        )

    async def net_direction(self, symbol: str, days: int = 90) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.net_direction_sync, symbol, days)

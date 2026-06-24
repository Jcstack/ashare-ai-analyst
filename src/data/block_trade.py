"""Block trade (大宗交易) fetcher via EastMoney datacenter API.

Block trades are large off-exchange transactions that reveal institutional
activity. Repeated block buys at a discount signal accumulation; block
sells at a premium may indicate distribution.

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

logger = get_logger("data.block_trade")

__all__ = ["BlockTrade", "BlockTradeFetcher"]

_CACHE_TTL = 600  # 10 minutes


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


@dataclass
class BlockTrade:
    """A single block trade record."""

    symbol: str
    name: str
    trade_date: str  # YYYY-MM-DD
    price: float
    close_price: float  # same-day closing price
    discount_pct: float  # (price - close) / close * 100, negative = discount
    volume_wan_shares: float
    amount_wan: float  # total amount in 万元
    buyer_seat: str  # buyer brokerage seat
    seller_seat: str  # seller brokerage seat
    is_institution: bool  # inferred from seat name

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "date": self.trade_date,
            "price": self.price,
            "close": self.close_price,
            "discount_pct": self.discount_pct,
            "volume_wan": self.volume_wan_shares,
            "amount_wan": self.amount_wan,
            "buyer": self.buyer_seat,
            "seller": self.seller_seat,
            "institution": self.is_institution,
        }


# Keywords that indicate institutional seats
_INSTITUTION_KEYWORDS = ["机构专用", "保险", "基金", "信托", "QFII", "社保"]


class BlockTradeFetcher:
    """Fetch block trade data from EastMoney datacenter.

    Usage::

        fetcher = BlockTradeFetcher()
        recent = await fetcher.fetch_recent(days=5)
        for_stock = await fetcher.fetch_for_symbol("601318", days=30)
    """

    _REPORT_NAME = "RPT_DATA_BLOCKTRADE"
    _SORT_COLUMN = "TRADE_DATE"

    def __init__(self) -> None:
        self._dc = EastMoneyDatacenter()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._circuit = CircuitBreaker(
            "block_trade", failure_threshold=3, recovery_timeout=300.0
        )

    def _get_cache(self, key: str) -> Any | None:
        if key in self._cache:
            expire_ts, val = self._cache[key]
            if time.time() < expire_ts:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time() + _CACHE_TTL, val)

    @staticmethod
    def _is_institution_seat(seat_name: str) -> bool:
        if not seat_name:
            return False
        return any(kw in seat_name for kw in _INSTITUTION_KEYWORDS)

    def _parse_row(self, row: dict[str, Any]) -> BlockTrade | None:
        symbol = str(row.get("SECURITY_CODE", ""))
        if not symbol or len(symbol) != 6:
            return None

        name = str(row.get("SECURITY_NAME_ABBR", ""))

        trade_date_raw = row.get("TRADE_DATE", "")
        try:
            if "T" in str(trade_date_raw):
                trade_date = str(trade_date_raw).split("T")[0]
            else:
                trade_date = str(trade_date_raw)[:10]
        except (ValueError, TypeError):
            trade_date = ""

        price = _safe_float(row.get("DEAL_PRICE"))
        close_price = _safe_float(row.get("CLOSE_PRICE"))
        discount_pct = _safe_float(row.get("PREMIUM_RATIO"))

        volume = _safe_float(row.get("DEAL_VOLUME", row.get("DEAL_VOL")))
        amount = _safe_float(row.get("DEAL_AMT"))
        # Normalize to 万
        if volume > 100_000:
            volume = volume / 10_000
        if amount > 100_000:
            amount = amount / 10_000

        buyer = str(row.get("BUYER_NAME", row.get("BUYER_CODE", "")))
        seller = str(row.get("SELLER_NAME", row.get("SELLER_CODE", "")))
        is_inst = self._is_institution_seat(buyer) or self._is_institution_seat(seller)

        return BlockTrade(
            symbol=symbol,
            name=name,
            trade_date=trade_date,
            price=price,
            close_price=close_price,
            discount_pct=discount_pct,
            volume_wan_shares=volume,
            amount_wan=amount,
            buyer_seat=buyer,
            seller_seat=seller,
            is_institution=is_inst,
        )

    def fetch_recent_sync(self, days: int = 5) -> list[BlockTrade]:
        """Fetch recent block trades across all stocks."""
        cache_key = f"recent_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit.state == "open":
            return []

        end = datetime.now()
        start = end - timedelta(days=days)
        filter_str = f"(TRADE_DATE>='{start:%Y-%m-%d}')(TRADE_DATE<='{end:%Y-%m-%d}')"

        try:
            df = self._dc.query_all_pages(
                self._REPORT_NAME,
                max_pages=3,
                page_size=50,
                sort_columns=self._SORT_COLUMN,
                sort_types="-1",
                filter_str=filter_str,
            )

            results: list[BlockTrade] = []
            if not df.empty:
                for _, row in df.iterrows():
                    entry = self._parse_row(row.to_dict())
                    if entry:
                        results.append(entry)

            self._circuit._on_success()
            self._set_cache(cache_key, results)
            logger.info("Fetched %d block trades (last %d days)", len(results), days)
            return results

        except Exception as exc:
            logger.warning("Block trade fetch failed: %s", exc)
            self._circuit._on_failure()
            return []

    def fetch_for_symbol_sync(self, symbol: str, days: int = 30) -> list[BlockTrade]:
        """Fetch block trades for a specific stock."""
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
            f"(TRADE_DATE>='{start:%Y-%m-%d}')"
            f"(TRADE_DATE<='{end:%Y-%m-%d}')"
        )

        try:
            df = self._dc.query(
                self._REPORT_NAME,
                page_size=50,
                sort_columns=self._SORT_COLUMN,
                sort_types="-1",
                filter_str=filter_str,
            )

            results: list[BlockTrade] = []
            if not df.empty:
                for _, row in df.iterrows():
                    entry = self._parse_row(row.to_dict())
                    if entry:
                        results.append(entry)

            self._circuit._on_success()
            self._set_cache(cache_key, results)
            return results

        except Exception as exc:
            logger.warning("Block trade fetch for %s failed: %s", symbol, exc)
            self._circuit._on_failure()
            return []

    def detect_accumulation(self, symbol: str, days: int = 30) -> dict[str, Any]:
        """Detect accumulation signal from block trade patterns.

        Accumulation = multiple block buys at a discount over a period.

        Returns:
            Dict with net_amount_wan, avg_discount, trade_count, is_accumulating.
        """
        trades = self.fetch_for_symbol_sync(symbol, days)
        if not trades:
            return {
                "net_amount_wan": 0.0,
                "avg_discount": 0.0,
                "trade_count": 0,
                "is_accumulating": False,
            }

        total_amount = sum(t.amount_wan for t in trades)
        discounts = [t.discount_pct for t in trades if t.discount_pct != 0]
        avg_discount = sum(discounts) / len(discounts) if discounts else 0.0
        inst_count = sum(1 for t in trades if t.is_institution)

        # Accumulation heuristic: net buying + avg discount + institutional presence
        is_accumulating = (
            avg_discount < -1.0  # buying at >1% discount
            and len(trades) >= 3  # multiple trades
            and inst_count >= 1  # at least one institutional participant
        )

        return {
            "net_amount_wan": total_amount,
            "avg_discount": avg_discount,
            "trade_count": len(trades),
            "institutional_count": inst_count,
            "is_accumulating": is_accumulating,
        }

    # -- Async wrappers -------------------------------------------------------

    async def fetch_recent(self, days: int = 5) -> list[BlockTrade]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_recent_sync, days)

    async def fetch_for_symbol(self, symbol: str, days: int = 30) -> list[BlockTrade]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.fetch_for_symbol_sync, symbol, days
        )

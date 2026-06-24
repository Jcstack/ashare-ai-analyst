"""Dragon Tiger Board (龙虎榜) data fetcher via AKShare.

Provides institutional and hot money (游资) trading activity for stocks
that triggered exchange disclosure rules (limit up/down, unusual volume,
consecutive deviation, etc).

The Dragon Tiger Board is one of the most important transparency mechanisms
in A-share trading — it reveals which brokerage seats (营业部) are buying
and selling stocks with unusual price/volume activity.  Identifying known
hot money (游资) seats vs institutional seats provides critical intelligence
for short-term momentum and reversal signals.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from src.data.eastmoney_proxy import em_api_call
from src.utils.logger import get_logger

logger = get_logger("data.dragon_tiger")

__all__ = ["DragonTigerEntry", "DragonTigerFetcher"]

# Cache TTL (seconds)
_CACHE_TTL = 300  # 5 minutes


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert value to float, returning *default* for None/NaN/errors."""
    if val is None:
        return default
    try:
        import math

        f = float(val)
        return default if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


def _safe_str(val: Any) -> str:
    """Convert to string, returning '' for None/NaN."""
    if val is None:
        return ""
    s = str(val)
    return "" if s.lower() == "nan" else s


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class DragonTigerEntry:
    """A single Dragon Tiger Board disclosure entry."""

    symbol: str
    name: str
    date: str  # YYYY-MM-DD
    reason: str  # trigger reason (涨幅偏离/换手率达到/连续三个交易日)
    buy_total_wan: float  # total buy amount (万元)
    sell_total_wan: float  # total sell amount (万元)
    net_buy_wan: float  # net = buy - sell
    top_buyers: list[dict[str, Any]] = field(default_factory=list)
    # [{name: "营业部名", amount_wan: float, pct: float}]
    top_sellers: list[dict[str, Any]] = field(default_factory=list)
    is_institution: bool = False  # whether any institutional seat appears
    hot_money_names: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


class DragonTigerFetcher:
    """Fetch 龙虎榜 data from AKShare (EastMoney source).

    Uses AKShare's ``stock_lhb_detail_em()`` for per-stock detail and
    ``stock_lhb_jgstatistic_em()`` for institutional statistics.

    Usage::

        fetcher = DragonTigerFetcher()
        recent = await fetcher.fetch_recent(days=5)
        history = await fetcher.fetch_for_symbol("601668", days=30)
    """

    # Well-known hot money (游资) brokerage seat names.
    # These are retail-famous seats known for aggressive short-term trading.
    HOT_MONEY_SEATS: list[str] = [
        # 赵老哥 (Zhao Laoge) — legendary hot money trader
        "华鑫证券上海宛平南路",
        # 拉萨帮 (Lhasa Gang) — cluster of Eastern Wealth seats in Lhasa
        "东方财富证券拉萨团结路第二",
        "东方财富证券拉萨东环路第二",
        "东方财富证券拉萨金珠西路",
        # 上海帮 (Shanghai Gang)
        "国泰君安上海江苏路",
        "中信证券上海溧阳路",
        "华泰证券上海武定路",
        "中信建投上海黄浦区",
        # 佛山帮 (Foshan Gang)
        "国信证券深圳泰然九路",
        # 宁波帮 (Ningbo Gang) — known aggressive style
        "银河证券宁波柳汀街",
        "华鑫证券宁波翠柏路",
        # 深圳帮 (Shenzhen Gang)
        "华泰证券深圳益田路荣超商务中心",
        "中信证券深圳总部",
        # 成都帮 (Chengdu Gang)
        "华西证券成都南一环路",
        # Other notable hot money seats
        "东方证券上海浦东新区",
        "招商证券深圳蛇口工业七路",
        "光大证券佛山绿景路",
        "中泰证券深圳欢乐海岸",
        "国盛证券宁波桑田路",
        "财通证券杭州体育场路",
    ]

    # Partial match prefixes — some seats appear with varying suffixes
    HOT_MONEY_PREFIXES: list[str] = [
        "东方财富证券拉萨",
        "华鑫证券上海宛平南路",
    ]

    def __init__(self) -> None:
        self._last_request_ts: float = 0.0
        # In-memory cache: key -> (expire_ts, data)
        self._cache: dict[str, tuple[float, Any]] = {}

    def _polite_sleep(self, interval: float = 0.5) -> None:
        """Synchronous rate-limit wait."""
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request_ts = time.monotonic()

    def _get_cache(self, key: str) -> Any | None:
        """Get cached value if not expired."""
        if key in self._cache:
            expire_ts, val = self._cache[key]
            if time.time() < expire_ts:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        """Cache a value with TTL."""
        self._cache[key] = (time.time() + _CACHE_TTL, val)

    def identify_hot_money(self, seat_name: str) -> bool:
        """Check if a trading seat is known hot money (游资).

        Checks exact match first, then prefix match.

        Args:
            seat_name: Brokerage seat name (营业部名称).

        Returns:
            True if the seat is a known hot money trader.
        """
        if not seat_name:
            return False
        if seat_name in self.HOT_MONEY_SEATS:
            return True
        return any(seat_name.startswith(prefix) for prefix in self.HOT_MONEY_PREFIXES)

    def _parse_detail_df(self, df: pd.DataFrame) -> list[DragonTigerEntry]:
        """Parse raw AKShare LHB detail DataFrame into DragonTigerEntry list.

        The DataFrame from ``stock_lhb_detail_em()`` has columns like:
        序号, 代码, 名称, 上榜日期, 解读, 收盘价, 涨跌幅, 龙虎榜净买额,
        龙虎榜买入额, 龙虎榜卖出额, 龙虎榜成交额, 市场总成交额,
        净买额占总成交比, 成交额占总成交比, 换手率, 流通市值, 上榜原因
        """
        if df is None or df.empty:
            return []

        entries: list[DragonTigerEntry] = []

        for _, row in df.iterrows():
            symbol = _safe_str(row.get("代码"))
            if not symbol:
                continue

            name = _safe_str(row.get("名称"))
            date_val = row.get("上榜日期")
            if isinstance(date_val, pd.Timestamp):
                date_str = date_val.strftime("%Y-%m-%d")
            else:
                date_str = _safe_str(date_val)

            reason = _safe_str(row.get("上榜原因"))
            buy_total = _safe_float(row.get("龙虎榜买入额")) / 10000  # 元 -> 万元
            sell_total = _safe_float(row.get("龙虎榜卖出额")) / 10000
            net_buy = _safe_float(row.get("龙虎榜净买额")) / 10000

            entries.append(
                DragonTigerEntry(
                    symbol=symbol,
                    name=name,
                    date=date_str,
                    reason=reason,
                    buy_total_wan=round(buy_total, 2),
                    sell_total_wan=round(sell_total, 2),
                    net_buy_wan=round(net_buy, 2),
                )
            )

        return entries

    def _fetch_detail_sync(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Synchronous fetch of LHB detail for a date range."""
        try:
            import akshare as ak

            self._polite_sleep()
            df = em_api_call(
                ak.stock_lhb_detail_em,
                start_date=start_date,
                end_date=end_date,
            )
            if df is not None and not df.empty:
                return df
        except Exception as exc:
            logger.warning(
                "LHB detail fetch failed (%s to %s): %s",
                start_date,
                end_date,
                exc,
            )
        return pd.DataFrame()

    def _fetch_stock_detail_sync(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Fetch LHB detail for a specific stock (synchronous)."""
        try:
            import akshare as ak

            self._polite_sleep()
            # stock_lhb_stock_statistic_em gives per-stock LHB history
            df = em_api_call(
                ak.stock_lhb_stock_statistic_em,
                symbol="近一月",
            )
            if df is not None and not df.empty:
                # Filter to our target symbol
                code_col = None
                for col in ["代码", "股票代码"]:
                    if col in df.columns:
                        code_col = col
                        break
                if code_col:
                    df = df[df[code_col].astype(str) == symbol]
                return df
        except Exception as exc:
            logger.warning("LHB stock detail fetch failed for %s: %s", symbol, exc)
        return pd.DataFrame()

    def _enrich_with_seats(self, entries: list[DragonTigerEntry]) -> None:
        """Enrich entries with top buyer/seller seat information.

        Uses ``stock_lhb_jgstatistic_em`` for institutional statistics
        to identify institutional presence. Also flags known hot money seats.
        """
        try:
            import akshare as ak

            self._polite_sleep()
            inst_df = em_api_call(
                ak.stock_lhb_jgstatistic_em,
                symbol="近一月",
            )
        except Exception as exc:
            logger.debug("Institutional stats fetch failed: %s", exc)
            inst_df = None

        # Build a set of symbols with institutional activity
        inst_symbols: set[str] = set()
        if inst_df is not None and not inst_df.empty:
            for col in ["代码", "股票代码"]:
                if col in inst_df.columns:
                    inst_symbols.update(inst_df[col].astype(str).tolist())
                    break

        for entry in entries:
            entry.is_institution = entry.symbol in inst_symbols

            # Check top buyers/sellers for hot money
            hot_names: list[str] = []
            for seat_list in [entry.top_buyers, entry.top_sellers]:
                for seat in seat_list:
                    seat_name = seat.get("name", "")
                    if self.identify_hot_money(seat_name):
                        hot_names.append(seat_name)
            entry.hot_money_names = list(set(hot_names))

    async def fetch_recent(self, days: int = 5) -> list[DragonTigerEntry]:
        """Fetch recent Dragon Tiger Board data.

        Args:
            days: Number of days to look back (default 5 trading days).

        Returns:
            List of DragonTigerEntry sorted by date descending.
        """
        cache_key = f"recent_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days + 3)).strftime("%Y%m%d")

        try:
            # Run sync AKShare call in executor to avoid blocking
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(
                None, self._fetch_detail_sync, start_date, end_date
            )
            entries = self._parse_detail_df(df)

            if entries:
                # Enrich with institutional/hot money data
                await loop.run_in_executor(None, self._enrich_with_seats, entries)

            # Sort by date descending
            entries.sort(key=lambda e: e.date, reverse=True)

            self._set_cache(cache_key, entries)
            logger.info(
                "Dragon Tiger: fetched %d entries for last %d days",
                len(entries),
                days,
            )
            return entries

        except Exception as exc:
            logger.error("Dragon Tiger fetch_recent failed: %s", exc)
            return []

    async def fetch_for_symbol(
        self, symbol: str, days: int = 30
    ) -> list[DragonTigerEntry]:
        """Fetch Dragon Tiger Board history for a specific symbol.

        Args:
            symbol: 6-digit stock code (e.g. "601668").
            days: Number of days to look back (default 30).

        Returns:
            List of DragonTigerEntry for this symbol, sorted by date descending.
        """
        cache_key = f"symbol_{symbol}_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days + 3)).strftime("%Y%m%d")

        try:
            loop = asyncio.get_running_loop()

            # Try stock-specific API first
            df = await loop.run_in_executor(
                None, self._fetch_stock_detail_sync, symbol, start_date, end_date
            )

            # Fallback: fetch all recent and filter
            if df is None or df.empty:
                df = await loop.run_in_executor(
                    None, self._fetch_detail_sync, start_date, end_date
                )
                if df is not None and not df.empty:
                    for col in ["代码", "股票代码"]:
                        if col in df.columns:
                            df = df[df[col].astype(str) == symbol]
                            break

            entries = self._parse_detail_df(df)
            if entries:
                await loop.run_in_executor(None, self._enrich_with_seats, entries)

            entries.sort(key=lambda e: e.date, reverse=True)

            self._set_cache(cache_key, entries)
            logger.info("Dragon Tiger for %s: fetched %d entries", symbol, len(entries))
            return entries

        except Exception as exc:
            logger.error("Dragon Tiger fetch_for_symbol failed for %s: %s", symbol, exc)
            return []

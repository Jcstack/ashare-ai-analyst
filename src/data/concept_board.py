"""Concept board data service for A-share stocks.

Per PRD v3.3 FR-CS001: fetches concept board listings, constituent stocks,
per-stock concept associations (via East Money F10 CoreConception API),
and concept board historical OHLCV data.  All results are cached in-memory
with configurable TTL.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

import pandas as pd
import requests

from src.utils.logger import get_logger

logger = get_logger("data.concept_board")

# ---------------------------------------------------------------------------
# Proxy bypass (same pattern as fetcher.py)
# ---------------------------------------------------------------------------

_NOISE_CONCEPT_NAMES = frozenset(
    {
        "最近多板",
        "昨日高振幅",
        "昨日高换手",
        "昨日连板",
        "融资融券",
        "沪股通",
        "深股通",
        "MSCI中国",
    }
)

_PROXY_KEYS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)


@contextmanager
def _bypass_proxy() -> Iterator[None]:
    """Temporarily disable proxies for AKShare / HTTP calls."""
    import os

    saved: dict[str, str] = {}
    for key in _PROXY_KEYS:
        val = os.environ.pop(key, None)
        if val is not None:
            saved[key] = val
    old_np = os.environ.get("NO_PROXY")
    old_np_l = os.environ.get("no_proxy")
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    try:
        yield
    finally:
        os.environ.update(saved)
        if old_np is not None:
            os.environ["NO_PROXY"] = old_np
        else:
            os.environ.pop("NO_PROXY", None)
        if old_np_l is not None:
            os.environ["no_proxy"] = old_np_l
        else:
            os.environ.pop("no_proxy", None)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ConceptBoardItem:
    """A single concept board with real-time performance."""

    code: str
    name: str
    pct_change: float = 0.0
    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    amount: float = 0.0
    zt_count: int = 0  # real limit-up count (cross-matched with limit pool)
    dt_count: int = 0  # real limit-down count (cross-matched with limit pool)


@dataclass
class ConstituentStock:
    """A stock within a concept board."""

    symbol: str
    name: str
    price: float | None = None
    pct_change: float | None = None
    amount: float | None = None
    amplitude: float | None = None


@dataclass
class StockConceptItem:
    """A concept associated with a specific stock, enriched with board data."""

    code: str
    name: str
    pct_change: float = 0.0
    amount: float = 0.0
    up_count: int = 0
    down_count: int = 0
    stock_rank_pct: float | None = None  # stock's percentile rank within board
    zt_count: int = 0  # real limit-up count (cross-matched with limit pool)
    dt_count: int = 0  # real limit-down count (cross-matched with limit pool)


@dataclass
class StockConceptsResult:
    """All concepts for a single stock."""

    symbol: str
    industry: str = ""
    concepts: list[StockConceptItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ConceptBoardService:
    """Concept board data service with TTL caching.

    Provides four main data access methods:

    * ``fetch_concept_list()`` – all concept boards with live performance
    * ``fetch_concept_constituents(board_code)`` – stocks in a concept
    * ``fetch_stock_concepts(symbol)`` – concepts for one stock (reverse lookup)
    * ``fetch_concept_history(board_code, period, days)`` – historical OHLCV
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._concept_list_ttl = 300.0  # 5 min
        self._constituents_ttl = 300.0  # 5 min
        self._stock_concepts_ttl = 600.0  # 10 min
        self._history_ttl = 1800.0  # 30 min
        self._http_session: requests.Session | None = None
        self._akshare_push2_ok: bool | None = None  # None=untested

    # ---- concept list -------------------------------------------------------

    def fetch_concept_list(self) -> list[ConceptBoardItem]:
        """Return all concept boards with real-time performance.

        Tries AKShare first, falls back to direct East Money HTTP API.
        """
        cached = self._get_cached("concept_list", self._concept_list_ttl)
        if cached is not None:
            return cached

        items = self._fetch_concept_list_akshare()
        if not items:
            items = self._fetch_concept_list_em_direct()
        if items:
            self._set_cached("concept_list", items)
        return items

    def _fetch_concept_list_akshare(self) -> list[ConceptBoardItem]:
        """Fetch concept board list via AKShare."""
        if self._akshare_push2_ok is False:
            return []

        import akshare as ak

        from src.data.eastmoney_proxy import em_api_call

        try:
            df = em_api_call(ak.stock_board_concept_name_em)
        except Exception as exc:
            logger.warning("AKShare concept list failed: %s", exc)
            self._akshare_push2_ok = False
            return []

        if df is None or df.empty:
            return []

        self._akshare_push2_ok = True
        items: list[ConceptBoardItem] = []
        for _, row in df.iterrows():
            items.append(
                ConceptBoardItem(
                    code=str(row.get("板块代码", "")),
                    name=str(row.get("板块名称", "")),
                    pct_change=_safe_float(row.get("涨跌幅")),
                    up_count=_safe_int(row.get("上涨家数")),
                    down_count=_safe_int(row.get("下跌家数")),
                    amount=_safe_float(row.get("总市值")),
                )
            )
        return items

    def _fetch_concept_list_em_direct(self) -> list[ConceptBoardItem]:
        """Fallback: fetch concept board list via EastMoneyClient (curl_cffi)."""
        try:
            from src.data.eastmoney_client import get_eastmoney_client

            client = get_eastmoney_client()
            raw = client.fetch_concept_boards()
            if not raw:
                return []

            items: list[ConceptBoardItem] = []
            for row in raw:
                name = row.get("name", "")
                if not name:
                    continue
                items.append(
                    ConceptBoardItem(
                        code=row.get("code", ""),
                        name=name,
                        pct_change=_safe_float(row.get("pct_change")),
                        up_count=_safe_int(row.get("up_count")),
                        down_count=_safe_int(row.get("down_count")),
                        amount=_safe_float(row.get("lead_pct")),
                    )
                )
            logger.info(
                "EastMoney client fallback returned %d concept boards", len(items)
            )
            return items
        except Exception as exc:
            logger.warning("EastMoney client concept list fallback failed: %s", exc)
            return []

    # ---- industry board list -------------------------------------------------

    def fetch_industry_list(self) -> list[ConceptBoardItem]:
        """Return all industry boards with real-time performance.

        Industry boards are a separate classification from concept boards.
        Tries AKShare first, falls back to EastMoneyClient.
        """
        cached = self._get_cached("industry_list", self._concept_list_ttl)
        if cached is not None:
            return cached

        items = self._fetch_industry_list_akshare()
        if not items:
            items = self._fetch_industry_list_em_direct()
        if items:
            self._set_cached("industry_list", items)
        return items

    def _fetch_industry_list_akshare(self) -> list[ConceptBoardItem]:
        """Fetch industry board list via AKShare."""
        if self._akshare_push2_ok is False:
            return []

        import akshare as ak

        from src.data.eastmoney_proxy import em_api_call

        try:
            df = em_api_call(ak.stock_board_industry_name_em)
        except Exception as exc:
            logger.warning("AKShare industry list failed: %s", exc)
            self._akshare_push2_ok = False
            return []

        if df is None or df.empty:
            return []

        items: list[ConceptBoardItem] = []
        for _, row in df.iterrows():
            items.append(
                ConceptBoardItem(
                    code=str(row.get("板块代码", "")),
                    name=str(row.get("板块名称", "")),
                    pct_change=_safe_float(row.get("涨跌幅")),
                    up_count=_safe_int(row.get("上涨家数")),
                    down_count=_safe_int(row.get("下跌家数")),
                    amount=_safe_float(row.get("总市值")),
                )
            )
        return items

    def _fetch_industry_list_em_direct(self) -> list[ConceptBoardItem]:
        """Fallback: fetch industry board list via EastMoneyClient (curl_cffi)."""
        try:
            from src.data.eastmoney_client import get_eastmoney_client

            client = get_eastmoney_client()
            raw = client.fetch_industry_boards()
            if not raw:
                return []

            items: list[ConceptBoardItem] = []
            for row in raw:
                name = row.get("name", "")
                if not name:
                    continue
                items.append(
                    ConceptBoardItem(
                        code=row.get("code", ""),
                        name=name,
                        pct_change=_safe_float(row.get("pct_change")),
                        up_count=_safe_int(row.get("up_count")),
                        down_count=_safe_int(row.get("down_count")),
                        amount=_safe_float(row.get("total_market_cap")),
                    )
                )
            logger.info(
                "EastMoney client fallback returned %d industry boards", len(items)
            )
            return items
        except Exception as exc:
            logger.warning("EastMoney client industry list fallback failed: %s", exc)
            return []

    # ---- constituents -------------------------------------------------------

    def fetch_concept_constituents(self, board_code: str) -> list[ConstituentStock]:
        """Return constituent stocks for a concept board.

        Tries AKShare first, falls back to EastMoneyClient.
        """
        cache_key = f"cons_{board_code}"
        cached = self._get_cached(cache_key, self._constituents_ttl)
        if cached is not None:
            return cached

        items = self._fetch_constituents_akshare(board_code)
        if not items:
            items = self._fetch_constituents_em_direct(board_code)
        if items:
            self._set_cached(cache_key, items)
        return items

    def _fetch_constituents_akshare(
        self, board_code: str
    ) -> list[ConstituentStock]:
        """Fetch constituents via AKShare."""
        if self._akshare_push2_ok is False:
            return []

        import akshare as ak

        from src.data.eastmoney_proxy import em_api_call

        try:
            df = em_api_call(ak.stock_board_concept_cons_em, symbol=board_code)
        except Exception as exc:
            logger.debug("AKShare constituents failed for %s: %s", board_code, exc)
            self._akshare_push2_ok = False
            return []

        if df is None or df.empty:
            return []

        items: list[ConstituentStock] = []
        for _, row in df.iterrows():
            items.append(
                ConstituentStock(
                    symbol=str(row.get("代码", "")),
                    name=str(row.get("名称", "")),
                    price=_safe_float_or_none(row.get("最新价")),
                    pct_change=_safe_float_or_none(row.get("涨跌幅")),
                    amount=_safe_float_or_none(row.get("成交额")),
                    amplitude=_safe_float_or_none(row.get("振幅")),
                )
            )
        return items

    def _fetch_constituents_em_direct(
        self, board_code: str
    ) -> list[ConstituentStock]:
        """Fallback: fetch constituents via EastMoneyClient (curl_cffi)."""
        try:
            from src.data.eastmoney_client import get_eastmoney_client

            client = get_eastmoney_client()
            raw = client.fetch_board_constituents(board_code)
            if not raw:
                return []

            items: list[ConstituentStock] = []
            for row in raw:
                symbol = row.get("symbol", "")
                if not symbol:
                    continue
                items.append(
                    ConstituentStock(
                        symbol=symbol,
                        name=row.get("name", ""),
                        price=row.get("price"),
                        pct_change=row.get("pct_change"),
                        amount=row.get("amount"),
                        amplitude=row.get("amplitude"),
                    )
                )
            return items
        except Exception as exc:
            logger.warning(
                "EastMoney client constituents fallback failed for %s: %s",
                board_code,
                exc,
            )
            return []

    # ---- stock → concepts (reverse lookup) ----------------------------------

    def fetch_stock_concepts(self, symbol: str) -> StockConceptsResult:
        """Return all concept boards a stock belongs to.

        Uses East Money F10 CoreConception HTTP API for concept names,
        then joins with ``fetch_concept_list()`` for live performance.
        Also fetches industry from ``stock_individual_info_em``.
        """
        cache_key = f"stock_concepts_{symbol}"
        cached = self._get_cached(cache_key, self._stock_concepts_ttl)
        if cached is not None:
            return cached

        result = StockConceptsResult(symbol=symbol)

        # 1) Fetch industry
        result.industry = self._fetch_industry(symbol)

        # 2) Fetch concept info via CoreConception API
        concept_infos = self._fetch_core_conception(symbol)
        if not concept_infos:
            self._set_cached(cache_key, result)
            return result

        # 3) Join with concept + industry lists for live performance data.
        # F10 API returns both concept (BK prefix) and industry (numeric)
        # boards, so we need to search both lists.
        all_boards = self.fetch_concept_list() + self.fetch_industry_list()
        # Build dual-key lookup: by code and by name
        code_map: dict[str, ConceptBoardItem] = {}
        name_map: dict[str, ConceptBoardItem] = {}
        for c in all_boards:
            if c.code:
                code_map[c.code] = c
            name_map[c.name] = c

        for ci in concept_infos:
            # Try code match first (more reliable), then name match.
            # F10 API returns numeric codes (e.g. "1222") while the concept
            # list uses BK-prefixed codes (e.g. "BK1222"), so try both.
            raw_code = ci.get("code", "")
            board = None
            if raw_code:
                board = code_map.get(raw_code) or code_map.get(f"BK{raw_code}")
            if board is None:
                board = name_map.get(ci["name"])
            if board:
                result.concepts.append(
                    StockConceptItem(
                        code=board.code,
                        name=board.name,
                        pct_change=board.pct_change,
                        amount=board.amount,
                        up_count=board.up_count,
                        down_count=board.down_count,
                    )
                )
            else:
                # Concept exists in F10 but not in today's listing
                result.concepts.append(
                    StockConceptItem(code=ci.get("code", ""), name=ci["name"])
                )

        # Sort by absolute pct_change descending (most active first)
        result.concepts.sort(key=lambda c: abs(c.pct_change), reverse=True)

        self._set_cached(cache_key, result)
        return result

    def _fetch_core_conception(self, symbol: str) -> list[dict[str, str]]:
        """Fetch concept info from East Money F10 CoreConception API.

        Returns list of ``{"name": ..., "code": ...}`` dicts.
        """
        market = "SH" if symbol.startswith(("6", "9")) else "SZ"
        url = (
            "https://emweb.securities.eastmoney.com"
            f"/PC_HSF10/CoreConception/PageAjax?code={market}{symbol}"
        )
        try:
            session = self._get_http_session()
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("CoreConception API failed for %s: %s", symbol, exc)
            return []

        # API returns {"ssbk": [...], "hxtc": [...]} (dict) or legacy list
        if isinstance(data, dict):
            items = data.get("ssbk", [])
        elif isinstance(data, list):
            items = data
        else:
            return []

        if not isinstance(items, list):
            return []

        result: list[dict[str, str]] = []
        for item in items:
            if isinstance(item, dict):
                # Filter IS_PRECISE="0" (broad industry tags like 传媒/深股通)
                # Keep IS_PRECISE="1" (precise) AND IS_PRECISE=None/missing
                # (legitimate concepts like 影视院线/影视动漫制作)
                if item.get("IS_PRECISE") == "0":
                    continue
                name = item.get("BOARD_NAME") or item.get("HY_BOARD_NAME", "")
                code = item.get("BOARD_CODE", "")
                if not name or name in _NOISE_CONCEPT_NAMES:
                    continue
                result.append({"name": name, "code": code})
        return result

    def _fetch_industry(self, symbol: str) -> str:
        """Fetch industry classification from stock_individual_info_em."""
        import akshare as ak

        from src.data.eastmoney_proxy import em_api_call

        try:
            df = em_api_call(ak.stock_individual_info_em, symbol=symbol)
            if df is not None and not df.empty:
                item_col = df.columns[0]
                value_col = df.columns[1]
                for _, row in df.iterrows():
                    if "行业" in str(row[item_col]):
                        return str(row[value_col])
        except Exception as exc:
            logger.debug("Failed to fetch industry for %s: %s", symbol, exc)
        return ""

    # ---- history ------------------------------------------------------------

    def fetch_concept_history(
        self,
        board_code: str,
        period: str = "daily",
        days: int = 60,
    ) -> list[dict[str, Any]]:
        """Return historical OHLCV for a concept board.

        Uses ``akshare.stock_board_concept_hist_em()``.
        """
        cache_key = f"hist_{board_code}_{period}_{days}"
        cached = self._get_cached(cache_key, self._history_ttl)
        if cached is not None:
            return cached

        if self._akshare_push2_ok is False:
            return []

        import akshare as ak
        from datetime import datetime, timedelta

        from src.data.eastmoney_proxy import em_api_call

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        try:
            df = em_api_call(
                ak.stock_board_concept_hist_em,
                symbol=board_code,
                start_date=start_date,
                end_date=end_date,
                period=period,
            )
        except Exception as exc:
            logger.warning("Failed to fetch history for %s: %s", board_code, exc)
            self._akshare_push2_ok = False
            return []

        if df is None or df.empty:
            return []

        records: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            records.append(
                {
                    "date": str(row.get("日期", "")),
                    "open": _safe_float(row.get("开盘")),
                    "close": _safe_float(row.get("收盘")),
                    "high": _safe_float(row.get("最高")),
                    "low": _safe_float(row.get("最低")),
                    "volume": _safe_float(row.get("成交量")),
                    "amount": _safe_float(row.get("成交额")),
                    "pct_change": _safe_float(row.get("涨跌幅")),
                }
            )
        self._set_cached(cache_key, records)
        return records

    # ---- limit-up/down enrichment ------------------------------------------

    def enrich_with_limit_counts(
        self, concepts: list[StockConceptItem]
    ) -> list[StockConceptItem]:
        """Cross-match concept constituents with limit-up/down pools.

        For each concept in the list, fetches constituents and intersects
        with today's limit-up (涨停) and limit-down (跌停) pools to
        compute real ``zt_count`` and ``dt_count``.

        Results are cached internally (TTL 5 min via constituent cache).

        Args:
            concepts: List of stock concepts to enrich.

        Returns:
            The same list, mutated in-place with zt_count/dt_count populated.
        """
        if not concepts:
            return concepts

        # Fetch limit pools (cached per day in fetcher)
        zt_symbols = self._get_limit_pool_symbols("up")
        dt_symbols = self._get_limit_pool_symbols("down")

        if not zt_symbols and not dt_symbols:
            return concepts

        for concept in concepts:
            if not concept.code:
                continue
            constituents = self.fetch_concept_constituents(concept.code)
            constituent_symbols = {c.symbol for c in constituents}
            concept.zt_count = len(constituent_symbols & zt_symbols)
            concept.dt_count = len(constituent_symbols & dt_symbols)

        return concepts

    def _get_limit_pool_symbols(self, direction: str) -> set[str]:
        """Get today's limit-up or limit-down symbols as a set.

        Args:
            direction: "up" or "down".

        Returns:
            Set of 6-digit symbol strings.
        """
        cache_key = f"limit_pool_{direction}"
        cached = self._get_cached(cache_key, 300.0)  # 5 min
        if cached is not None:
            return cached

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        try:
            if direction == "up":
                df = fetcher.fetch_limit_up_pool()
            else:
                df = fetcher.fetch_limit_down_pool()
        except Exception as exc:
            logger.warning("Failed to fetch limit-%s pool: %s", direction, exc)
            return set()

        if df is None or df.empty:
            return set()

        symbols: set[str] = set()
        if "symbol" in df.columns:
            symbols = set(df["symbol"].astype(str).str.strip())

        self._set_cached(cache_key, symbols)
        return symbols

    # ---- internal helpers ---------------------------------------------------

    def _get_http_session(self) -> requests.Session:
        if self._http_session is None:
            s = requests.Session()
            s.trust_env = False
            s.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://emweb.securities.eastmoney.com/",
                }
            )
            self._http_session = s
        return self._http_session

    def _get_cached(self, key: str, ttl: float) -> Any | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < ttl:
                return data
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        self._cache[key] = (time.time(), data)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_float_or_none(val: Any) -> float | None:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return default
        return int(val)
    except (TypeError, ValueError):
        return default

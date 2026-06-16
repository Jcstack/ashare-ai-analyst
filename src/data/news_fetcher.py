"""Stock news, anomalies, and hot-rank data fetcher.

Wraps AKShare functions that use datacenter-web.eastmoney.com (verified
working through Surge proxy).

Per PRD v2.0 FR-NF001/NF002, FR-AD001.
"""

import time
from typing import Any

import akshare as ak
import pandas as pd

from src.data._column_maps import (
    ANOMALY_COLUMN_MAP,
    HOT_RANK_COLUMN_MAP,
    NEWS_COLUMN_MAP,
)
from src.data.source_router import DataSourceRouter, SourceDomain
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("data.news_fetcher")

# ak.stock_changes_em(symbol=...) expects an anomaly *category* name,
# NOT a stock code.  Each call returns all stocks matching that category.
_DEFAULT_ANOMALY_CATEGORIES: list[str] = [
    "大笔买入",
    "大笔卖出",
    "封涨停板",
    "封跌停板",
    "火箭发射",
    "高台跳水",
]

_ANOMALY_EMPTY_COLUMNS: list[str] = [
    "datetime",
    "symbol",
    "name",
    "sector",
    "description",
    "change_type",
]

_PROXY_KEYS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)


class NewsFetcher:
    """Fetches stock news, anomalies, and hot rankings via AKShare.

    All endpoints use datacenter-web.eastmoney.com which works through
    proxy configurations.

    Args:
        config_name: Config file name for settings.
        source_router: Optional pre-configured DataSourceRouter.
    """

    def __init__(
        self,
        config_name: str = "agent",
        source_router: DataSourceRouter | None = None,
    ) -> None:
        config = load_config(config_name)
        news_cfg = config.get("news", {})
        self._max_items: int = news_cfg.get("max_items_per_stock", 20)
        self._hot_rank_limit: int = news_cfg.get("hot_rank_limit", 50)
        self._cache_ttl: float = float(news_cfg.get("cache_ttl_seconds", 300))
        self._source_router = source_router or DataSourceRouter()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._last_request_ts: float = 0.0

    def fetch_stock_news(self, symbol: str) -> pd.DataFrame:
        """Fetch recent news for a stock.

        Args:
            symbol: 6-digit stock code.

        Returns:
            DataFrame with columns: title, content, datetime, source, url.
        """
        cache_key = f"news_{symbol}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        self._rate_limit_wait()
        try:
            df = self._call_akshare(self._safe_stock_news_em, symbol=symbol)
            if df is not None and not df.empty:
                df = df.rename(columns=NEWS_COLUMN_MAP)
                df = df.head(self._max_items)
                self._source_router.record_success(
                    SourceDomain.EASTMONEY_DATACENTER,
                )
            else:
                df = pd.DataFrame(
                    columns=["title", "content", "datetime", "source", "url"],
                )
        except Exception as exc:
            logger.warning("Failed to fetch news for %s: %s", symbol, exc)
            self._source_router.record_failure(
                SourceDomain.EASTMONEY_DATACENTER,
            )
            df = pd.DataFrame(
                columns=["title", "content", "datetime", "source", "url"],
            )

        self._set_cached(cache_key, df)
        return df

    @staticmethod
    def _safe_stock_news_em(symbol: str) -> pd.DataFrame:
        """Wrapper around ak.stock_news_em that handles pyarrow regex bug.

        AKShare 1.18.x uses ``str.replace(r"\\u3000", …, regex=True)`` which
        fails with the pyarrow string backend (ArrowInvalid: invalid escape
        sequence \\u).  We temporarily switch to the python string backend
        for this call.
        """
        import pyarrow as pa

        from src.data.eastmoney_proxy import em_api_call

        opt = pd.get_option("mode.string_storage")
        try:
            pd.set_option("mode.string_storage", "python")
            return em_api_call(ak.stock_news_em, symbol=symbol)
        except (pa.lib.ArrowInvalid, Exception) as exc:
            if "ArrowInvalid" in type(exc).__name__ or "escape" in str(exc):
                # Retry with object dtype fallback
                pd.set_option("mode.string_storage", "python")
                return em_api_call(ak.stock_news_em, symbol=symbol)
            raise
        finally:
            if opt is not None:
                pd.set_option("mode.string_storage", opt)

    def fetch_market_anomalies(
        self,
        categories: list[str] | None = None,
    ) -> pd.DataFrame:
        """Fetch market-wide anomalies across multiple categories.

        ``ak.stock_changes_em(symbol=...)`` expects an anomaly **category
        name** (e.g. ``"大笔买入"``, ``"封涨停板"``), NOT a stock code.
        Each call returns every stock that triggered that anomaly type.

        Args:
            categories: Anomaly category names to scan.
                Defaults to :data:`_DEFAULT_ANOMALY_CATEGORIES`.

        Returns:
            Combined DataFrame with columns: datetime, symbol, name,
            sector, description, change_type.
        """
        cache_key = "market_anomalies"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Anomaly data is only available during/shortly after trading hours
        try:
            from src.utils.market_hours import is_a_share_trading_open
            if not is_a_share_trading_open():
                return pd.DataFrame(columns=_ANOMALY_EMPTY_COLUMNS)
        except ImportError:
            pass

        if categories is None:
            categories = _DEFAULT_ANOMALY_CATEGORIES

        frames: list[pd.DataFrame] = []
        for category in categories:
            self._rate_limit_wait()
            try:
                df = self._call_akshare(ak.stock_changes_em, symbol=category)
                if df is not None and not df.empty:
                    df = df.rename(columns=ANOMALY_COLUMN_MAP)
                    df["change_type"] = category
                    frames.append(df)
                    self._source_router.record_success(
                        SourceDomain.EASTMONEY_DATACENTER,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to fetch anomalies for category '%s': %s",
                    category,
                    exc,
                )

        if frames:
            result = pd.concat(frames, ignore_index=True)
        else:
            result = pd.DataFrame(columns=_ANOMALY_EMPTY_COLUMNS)

        self._set_cached(cache_key, result)
        return result

    def fetch_stock_anomalies(self, symbol: str) -> pd.DataFrame:
        """Fetch unusual trading activity for a single stock.

        Internally calls :meth:`fetch_market_anomalies` (cached) and
        filters by *symbol*.  Exchange prefixes (``SZ``, ``SH``, ``BJ``)
        are stripped automatically.

        Args:
            symbol: Stock code, optionally with exchange prefix.

        Returns:
            DataFrame with anomaly rows for this stock only.
        """
        clean = symbol
        if len(symbol) > 6 and symbol[:2] in ("SZ", "SH", "BJ"):
            clean = symbol[2:]

        all_anomalies = self.fetch_market_anomalies()
        if all_anomalies.empty:
            return pd.DataFrame(columns=_ANOMALY_EMPTY_COLUMNS)

        mask = all_anomalies["symbol"].astype(str) == clean
        return all_anomalies[mask].reset_index(drop=True)

    def fetch_hot_rank(self) -> pd.DataFrame:
        """Fetch hot stock rankings.

        Returns:
            DataFrame with hot rank columns.
        """
        cache_key = "hot_rank"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        self._rate_limit_wait()
        try:
            df = self._call_akshare(ak.stock_hot_rank_em)
            if df is not None and not df.empty:
                df = df.rename(columns=HOT_RANK_COLUMN_MAP)
                df = df.head(self._hot_rank_limit)
                self._source_router.record_success(
                    SourceDomain.EASTMONEY_DATACENTER,
                )
            else:
                df = pd.DataFrame(
                    columns=[
                        "rank",
                        "symbol",
                        "name",
                        "price",
                        "pct_change",
                    ],
                )
        except Exception as exc:
            logger.warning("Failed to fetch hot rank: %s", exc)
            self._source_router.record_failure(
                SourceDomain.EASTMONEY_DATACENTER,
            )
            df = pd.DataFrame(
                columns=["rank", "symbol", "name", "price", "pct_change"],
            )

        self._set_cached(cache_key, df)
        return df

    def _call_akshare(self, func, **kwargs) -> pd.DataFrame:
        """Call an AKShare function via em_api_call (proxy-patch gateway).

        Args:
            func: AKShare function to call.
            **kwargs: Arguments to pass to the function.

        Returns:
            DataFrame result, or None on connection failure.
        """
        from src.data.eastmoney_proxy import em_api_call

        return em_api_call(func, **kwargs)

    def _rate_limit_wait(self) -> None:
        """Enforce AKShare rate limit (>= 0.5s between requests)."""
        now = time.time()
        if now - self._last_request_ts < 0.5:
            time.sleep(0.5 - (now - self._last_request_ts))
        self._last_request_ts = time.time()

    def _get_cached(self, key: str) -> pd.DataFrame | None:
        """Get cached data if TTL has not expired.

        Args:
            key: Cache key.

        Returns:
            Cached DataFrame or None if expired/missing.
        """
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return data
        return None

    def _set_cached(self, key: str, data: pd.DataFrame) -> None:
        """Store data in cache with current timestamp.

        Args:
            key: Cache key.
            data: DataFrame to cache.
        """
        self._cache[key] = (time.time(), data)

    def fetch_stock_research(self, symbol: str) -> dict[str, Any]:
        """Aggregate research data for a stock: news + fund holdings + analyst data.

        Per PRD v2.4 FR-RI003/RI004.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict with keys: news (list), fund_holdings (list), analyst_ratings (list).
        """
        result: dict[str, Any] = {
            "symbol": symbol,
            "news": [],
            "fund_holdings": [],
            "analyst_ratings": [],
        }

        # News
        try:
            news_df = self.fetch_stock_news(symbol)
            if not news_df.empty:
                result["news"] = news_df.head(20).to_dict(orient="records")
        except Exception as exc:
            logger.warning("Research: news fetch failed for %s: %s", symbol, exc)

        # Institutional holdings (机构持仓)
        try:
            from src.data._column_maps import INSTITUTE_HOLD_COLUMN_MAP

            # Determine latest available quarter (e.g. "20243" = 2024 Q3)
            import datetime

            now = datetime.date.today()
            year = now.year
            q = (now.month - 1) // 3  # 0-based quarter of current month
            if q == 0:
                # Q1 not yet reported, use previous year Q3
                quarter_str = f"{year - 1}3"
            else:
                quarter_str = f"{year}{q}"

            self._rate_limit_wait()
            df = self._call_akshare(
                ak.stock_institute_hold_detail,
                stock=symbol,
                quarter=quarter_str,
            )
            if df is not None and not df.empty:
                rename_map = {
                    k: v
                    for k, v in INSTITUTE_HOLD_COLUMN_MAP.items()
                    if k in df.columns
                }
                df = df.rename(columns=rename_map)
                result["fund_holdings"] = df.head(20).to_dict(orient="records")
        except Exception as exc:
            logger.warning(
                "Research: fund holdings fetch failed for %s: %s", symbol, exc
            )

        # Analyst ratings (分析师评级)
        try:
            from src.data._column_maps import ANALYST_RANK_COLUMN_MAP

            self._rate_limit_wait()
            df = self._call_akshare(ak.stock_analyst_rank_em)
            if df is not None and not df.empty:
                rename_map = {
                    k: v for k, v in ANALYST_RANK_COLUMN_MAP.items() if k in df.columns
                }
                df = df.rename(columns=rename_map)
                # Extract latest rating from dynamic year column
                rating_cols = [c for c in df.columns if "最新个股评级-股票名称" in c]
                if rating_cols:
                    df = df.rename(columns={rating_cols[0]: "latest_rating"})
                result["analyst_ratings"] = df.head(20).to_dict(orient="records")
        except Exception as exc:
            logger.warning("Research: analyst rank fetch failed: %s", exc)

        return result

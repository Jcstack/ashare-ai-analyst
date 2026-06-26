"""AKShare-based data fetcher for the A-share analysis system.

Provides config-driven stock data collection with caching, retry logic,
and polite request intervals. All parameters are loaded from
config/stocks.yaml -- no hardcoded stock codes, dates, or params.

Per PRD FR-D001: Config-driven data collection via AKShare.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

import re

import akshare as ak
import pandas as pd
import requests as _requests

try:
    import adata as _adata

    _HAS_ADATA = True
except ImportError:
    _HAS_ADATA = False

from src.data._column_maps import (
    ANALYST_RANK_COLUMN_MAP,
    DRAGON_TIGER_COLUMN_MAP,
    DRAGON_TIGER_SEAT_COLUMN_MAP,
    DRAGON_TIGER_STOCK_STATS_COLUMN_MAP,
    FUND_FLOW_COLUMN_MAP,
    FUND_FLOW_DETAIL_COLUMN_MAP,
    FUND_FLOW_RANK_COLUMN_MAP,
    FUND_HOLD_COLUMN_MAP,
    FUNDAMENTAL_COLUMN_MAP,
    FUNDAMENTAL_METRIC_NAME_MAP,
    INDEX_COLUMN_MAP,
    LIMIT_DOWN_COLUMN_MAP,
    LIMIT_UP_COLUMN_MAP,
    MARGIN_COLUMN_MAP,
    NORTHBOUND_COLUMN_MAP,
    OHLCV_COLUMN_MAP,
    REALTIME_SPOT_COLUMN_MAP,
    SEAT_TYPE_PATTERNS,
    SSE_INDEX_PREFIXES,
    SZSE_INDEX_PREFIXES,
)
from src.data.source_router import SourceDomain, get_source_router
from src.utils.config import get_data_dir, load_config
from src.utils.logger import get_logger


class DataCollectionError(Exception):
    """Raised when data collection fails after all retries."""

    pass


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
    """Temporarily disable all proxies so AKShare connects directly.

    Removes proxy env vars and sets NO_PROXY=* to override any
    system-level proxy configuration that requests/urllib3 may detect.
    """
    saved: dict[str, str] = {}
    for key in _PROXY_KEYS:
        val = os.environ.pop(key, None)
        if val is not None:
            saved[key] = val
    old_no_proxy = os.environ.get("NO_PROXY")
    old_no_proxy_lower = os.environ.get("no_proxy")
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    try:
        yield
    finally:
        os.environ.update(saved)
        if old_no_proxy is not None:
            os.environ["NO_PROXY"] = old_no_proxy
        else:
            os.environ.pop("NO_PROXY", None)
        if old_no_proxy_lower is not None:
            os.environ["no_proxy"] = old_no_proxy_lower
        else:
            os.environ.pop("no_proxy", None)


class StockDataFetcher:
    """Config-driven A-share data fetcher backed by AKShare.

    Handles daily OHLCV, fundamentals, index data, northbound flow,
    and margin data.  Implements caching (parquet), retry with
    exponential backoff, and polite request intervals as specified
    in config/stocks.yaml.

    Attributes:
        config: Parsed stocks.yaml configuration dictionary.
        logger: Module-level logger instance.
    """

    def __init__(self, config_path: str = "stocks") -> None:
        """Initialize the fetcher by loading configuration.

        Args:
            config_path: Config file name without extension, resolved
                by ``load_config`` to ``config/<name>.yaml``.
        """
        self.config: dict[str, Any] = load_config(config_path)
        self.logger = get_logger("data.fetcher")
        # Shared health tracker (single source of truth across all data sources).
        self._source_router = get_source_router(config_path)

        # Unpack frequently-used config sections
        self._daily_cfg: dict[str, Any] = self.config.get("data_collection", {}).get(
            "daily", {}
        )
        self._cache_cfg: dict[str, Any] = self.config.get("cache", {})
        self._request_cfg: dict[str, Any] = self.config.get("request", {})
        self._market_cfg: dict[str, Any] = self.config.get("data_collection", {}).get(
            "market", {}
        )
        self._fundamental_cfg: dict[str, Any] = self.config.get(
            "data_collection", {}
        ).get("fundamental", {})

        # Track the last request timestamp for rate-limiting
        self._last_request_ts: float = 0.0

        # Lazy trading calendar (initialized on first cache freshness check)
        self.__trading_cal: Any = None

    @property
    def _trading_cal(self):
        """Lazily initialize TradingCalendar for cache freshness checks."""
        if self.__trading_cal is None:
            from src.data.trading_calendar import TradingCalendar

            self.__trading_cal = TradingCalendar()
        return self.__trading_cal

    def _expected_latest_trading_day(self, now: datetime | None = None) -> date:
        """Return the expected latest trading day that data sources should have.

        Time-aware logic:
        - During trading hours (before 15:00): previous trading day
          (today's data isn't finalized yet).
        - After market close (15:00+) on a trading day: today.
        - Non-trading day (weekend/holiday): most recent past trading day.

        Args:
            now: Current datetime (default: ``datetime.now()``).

        Returns:
            The ``date`` that the most recent available data should cover.
        """
        if now is None:
            now = datetime.now()
        today = now.date()

        from src.data.trading_calendar import MarketSession

        session = self._trading_cal.current_session(now)
        is_today_trading = self._trading_cal.is_trading_day(today)

        if is_today_trading:
            if (
                session
                in (
                    MarketSession.AFTER_HOURS,
                    MarketSession.CLOSED,
                )
                and now.hour >= 15
            ):
                # After market close — today's data should be available
                return today
            else:
                # During trading hours or before open — previous day's data
                return self._trading_cal.prev_trading_day(today)
        else:
            # Weekend / holiday — most recent past trading day
            return self._trading_cal.prev_trading_day(today)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def __init_qmt_adapter(self):
        """Lazily initialize QMT adapter reference from DI container."""
        if not hasattr(self, "_qmt"):
            self._qmt = None
            try:
                from src.web.dependencies import get_qmt_adapter

                self._qmt = get_qmt_adapter()
            except Exception:
                pass

    def _check_data_freshness(self, df: pd.DataFrame, symbol: str, source: str) -> bool:
        """Check if fetched data has up-to-date rows.

        Uses the trading calendar to determine the expected latest trading
        day (time-aware) and allows a tolerance of
        ``staleness_max_trading_days`` (default 1) trading days for data
        publication delay.

        Returns:
            ``True`` if data is fresh enough, ``False`` if stale.
        """
        if df.empty or "date" not in df.columns:
            return False
        last_date = pd.to_datetime(df["date"].iloc[-1]).date()
        tolerance = int(self._cache_cfg.get("staleness_max_trading_days", 1))
        expected = self._expected_latest_trading_day()
        # Allow tolerance trading days of delay from the expected date
        cutoff = self._trading_cal.prev_trading_day(d=expected, n=tolerance)
        if last_date < cutoff:
            self.logger.warning(
                "%s data stale for %s (last=%s, expected=%s, cutoff=%s)",
                source,
                symbol,
                last_date.isoformat(),
                expected.isoformat(),
                cutoff.isoformat(),
            )
            return False
        return True

    def _record_source(self, domain: SourceDomain, ok: bool) -> None:
        """Record a source success/failure into the shared health router.

        Defensive: health bookkeeping must never break a data fetch, so any
        error here is swallowed. Only called on a fresh success or a hard
        failure — stale data is data lag, not a source failure, so it is not
        recorded.
        """
        try:
            if ok:
                self._source_router.record_success(domain)
            else:
                self._source_router.record_failure(domain)
        except Exception:
            self.logger.debug("source health record skipped", exc_info=True)

    def fetch_daily_ohlcv(
        self,
        symbol: str,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """Fetch daily OHLCV data for a single A-share stock.

        Source chain: QMT (local) → EastMoney (direct+proxy) → Tencent → adata.
        Each source is checked for data freshness using the trading calendar.
        If all sources return stale data, the freshest result is returned
        with a critical warning logged.

        Args:
            symbol: 6-digit stock code (e.g. ``"000001"``).
                    Exchange suffixes (.SZ/.SH) are stripped automatically.
            start_date: Start date ``YYYYMMDD``. Falls back to config value.
            end_date: End date ``YYYYMMDD``. Empty string means today.

        Returns:
            DataFrame with English column names (date, open, high, low,
            close, volume, amount, ...).

        Raises:
            DataCollectionError: If the request fails after all retries.
        """
        # Strip exchange prefix/suffix: sh600026→600026, 000001.SZ→000001
        import re as _re

        symbol = _re.sub(r"\.(SZ|SH|BJ)$", "", symbol, flags=_re.IGNORECASE)
        if len(symbol) > 6 and symbol[:2].lower() in ("sh", "sz", "bj"):
            symbol = symbol[2:]

        start = start_date or self._daily_cfg.get("start_date", "20240101")
        end = end_date or self._daily_cfg.get("end_date", "")
        adjust = self._daily_cfg.get("adjust", "qfq")

        cache_path = self._get_cache_path(symbol, "daily")
        if self._is_cache_valid(cache_path):
            self.logger.info("Cache hit for daily OHLCV: %s", symbol)
            return self._load_cache(cache_path)

        self.logger.info(
            "Fetching daily OHLCV for %s (%s ~ %s, adjust=%s)",
            symbol,
            start,
            end or "today",
            adjust,
        )

        # Track best stale result across sources so we can return the
        # freshest data even when all sources are behind.
        best_stale: pd.DataFrame | None = None
        best_stale_date: Any = None

        def _track_stale(df: pd.DataFrame) -> None:
            nonlocal best_stale, best_stale_date
            if df is not None and not df.empty and "date" in df.columns:
                ld = pd.to_datetime(df["date"].iloc[-1])
                if best_stale_date is None or ld > best_stale_date:
                    best_stale = df
                    best_stale_date = ld

        # QMT primary source (local data, zero network latency)
        self.__init_qmt_adapter()
        if self._qmt and self._qmt.is_available():
            try:
                df = self._qmt.get_daily_ohlcv(symbol, start, end)
                if df is not None and not df.empty:
                    if self._check_data_freshness(df, symbol, "QMT"):
                        self._record_source(SourceDomain.QMT, True)
                        self._save_cache(df, cache_path)
                        return df
                    _track_stale(df)
            except Exception as exc:
                self._record_source(SourceDomain.QMT, False)
                self.logger.warning(
                    "QMT daily OHLCV failed for %s: %s, trying EastMoney",
                    symbol,
                    exc,
                )

        # EastMoney secondary source (ak.stock_zh_a_hist via em_api_call)
        # Handles direct-first-then-proxy-patch-fallback internally.
        try:
            kwargs: dict[str, Any] = {
                "symbol": symbol,
                "period": "daily",
                "start_date": start,
                "adjust": adjust,
            }
            if end:
                kwargs["end_date"] = end

            df = self._request_with_retry(
                ak.stock_zh_a_hist, use_em_proxy=True, **kwargs
            )
            df = df.rename(columns=OHLCV_COLUMN_MAP)
            if self._check_data_freshness(df, symbol, "EastMoney"):
                self._record_source(SourceDomain.EASTMONEY_PUSH2, True)
                self._save_cache(df, cache_path)
                return df
            _track_stale(df)
        except DataCollectionError:
            self._record_source(SourceDomain.EASTMONEY_PUSH2, False)
            self.logger.warning(
                "EastMoney source failed for %s, trying Tencent fallback",
                symbol,
            )

        # Fallback source 1: Tencent (ak.stock_zh_a_hist_tx)
        try:
            tx_symbol = self._to_tx_symbol(symbol)
            tx_kwargs: dict[str, Any] = {
                "symbol": tx_symbol,
                "start_date": start,
                "end_date": end or datetime.now().strftime("%Y%m%d"),
            }
            if adjust == "qfq":
                tx_kwargs["adjust"] = "qfq"

            df = self._request_with_retry(ak.stock_zh_a_hist_tx, **tx_kwargs)

            # Normalize columns: Tencent returns 'amount' as volume in lots
            if "volume" not in df.columns and "amount" in df.columns:
                df = df.rename(columns={"amount": "volume"})

            if self._check_data_freshness(df, symbol, "Tencent"):
                self._record_source(SourceDomain.TENCENT, True)
                self._save_cache(df, cache_path)
                return df
            _track_stale(df)
        except DataCollectionError:
            self._record_source(SourceDomain.TENCENT, False)
            self.logger.warning(
                "Tencent source failed for %s, trying adata fallback",
                symbol,
            )

        # Fallback source 2: adata (multi-source fusion, proxy-friendly)
        try:
            df = self._fetch_daily_via_adata(symbol, start, end, adjust, cache_path)
            if self._check_data_freshness(df, symbol, "adata"):
                self._record_source(SourceDomain.ADATA, True)
                return df  # _fetch_daily_via_adata already saves cache
            _track_stale(df)
        except DataCollectionError:
            self._record_source(SourceDomain.ADATA, False)
            self.logger.warning("adata source also failed for %s", symbol)

        # All sources returned stale data — use the freshest one but warn
        if best_stale is not None:
            self.logger.critical(
                "ALL sources returned stale data for %s (freshest=%s). "
                "Trading decisions based on this data may be inaccurate!",
                symbol,
                best_stale_date,
            )
            self._save_cache(best_stale, cache_path)
            return best_stale

        raise DataCollectionError(
            f"All data sources failed for {symbol} — no data available"
        )

    def fetch_fundamental(self, symbol: str) -> pd.DataFrame:
        """Fetch basic financial metrics for a single A-share stock.

        Uses ``ak.stock_individual_info_em(symbol)`` to retrieve
        fundamental data including PE_TTM, PB, total market value,
        revenue, and net profit.  The set of metrics to include is
        driven by ``data_collection.fundamental.metrics`` in config.

        Args:
            symbol: 6-digit stock code (e.g. ``"000001"``).

        Returns:
            DataFrame with columns: metric, value.  Rows are filtered
            to only the metrics specified in config (e.g. pe_ttm, pb,
            total_mv, revenue, net_profit).

        Raises:
            DataCollectionError: If the request fails after all retries.
        """
        cache_path = self._get_cache_path(symbol, "fundamental")
        if self._is_cache_valid(cache_path):
            self.logger.info("Cache hit for fundamental: %s", symbol)
            return self._load_cache(cache_path)

        self.logger.info("Fetching fundamental data for %s", symbol)
        df = self._request_with_retry(
            ak.stock_individual_info_em, use_em_proxy=True, symbol=symbol
        )
        df = df.rename(columns=FUNDAMENTAL_COLUMN_MAP)

        # Filter to configured metrics if available
        configured_metrics = self._fundamental_cfg.get("metrics", [])
        if configured_metrics and "metric" in df.columns:
            df["metric_key"] = df["metric"].map(FUNDAMENTAL_METRIC_NAME_MAP)
            df = df[df["metric_key"].isin(configured_metrics)].copy()
            df = df.drop(columns=["metric_key"])

        self._save_cache(df, cache_path)
        return df

    def fetch_index(
        self,
        index_code: str,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """Fetch daily data for a market index.

        Uses ``ak.stock_zh_index_daily_em`` to retrieve index OHLCV.
        Supports SSE (000001), SZSE (399001), ChiNext (399006), and
        STAR (000688) indices.

        Args:
            index_code: 6-digit index code (e.g. ``"000001"`` for SHCOMP).
            start_date: Start date ``YYYYMMDD``. Falls back to config value.
            end_date: End date ``YYYYMMDD``. Empty string means today.

        Returns:
            DataFrame with columns: date, open, high, low, close, volume.

        Raises:
            DataCollectionError: If the request fails after all retries.
        """
        cache_path = self._get_cache_path(index_code, "index")
        if self._is_cache_valid(cache_path):
            self.logger.info("Cache hit for index: %s", index_code)
            return self._load_cache(cache_path)

        prefixed_code = self._resolve_index_prefix(index_code)
        self.logger.info("Fetching index data for %s", prefixed_code)

        df = self._request_with_retry(
            ak.stock_zh_index_daily_em, use_em_proxy=True, symbol=prefixed_code
        )
        df = df.rename(columns=INDEX_COLUMN_MAP)
        df = self._filter_by_date(df, start_date, end_date)

        self._save_cache(df, cache_path)
        return df

    def fetch_northbound(self) -> pd.DataFrame:
        """Fetch northbound (北向资金) capital flow history.

        Uses ``ak.stock_hsgt_hist_em(symbol="北向")`` to retrieve daily
        northbound capital flow data including net buy, buy, and sell
        amounts.

        Returns:
            DataFrame with columns: date, net_buy_amount,
            daily_quota_balance, cumulative_net_buy.

        Raises:
            DataCollectionError: If the request fails after all retries.
        """
        cache_path = self._get_cache_path("northbound", "market")
        if self._is_cache_valid(cache_path):
            self.logger.info("Cache hit for northbound flow")
            return self._load_cache(cache_path)

        self.logger.info("Fetching northbound capital flow data")
        df = self._request_with_retry(
            ak.stock_hsgt_hist_em, use_em_proxy=True, symbol="北向资金"
        )
        df = df.rename(columns=NORTHBOUND_COLUMN_MAP)

        self._save_cache(df, cache_path)
        return df

    def fetch_margin_data(self) -> pd.DataFrame:
        """Fetch margin trading (融资融券) summary data.

        Uses ``ak.macro_china_market_margin_sh`` (SH) and
        ``ak.macro_china_market_margin_sz`` (SZ) and sums them
        to get aggregate A-share margin trading statistics.

        Returns:
            DataFrame with columns: date, margin_balance, short_balance.

        Raises:
            DataCollectionError: If the request fails after all retries.
        """
        cache_path = self._get_cache_path("margin", "market")
        if self._is_cache_valid(cache_path):
            self.logger.info("Cache hit for margin data")
            return self._load_cache(cache_path)

        self.logger.info("Fetching margin trading data (SH+SZ)")
        sh = self._request_with_retry(
            ak.macro_china_market_margin_sh, use_em_proxy=True
        )
        sh = sh.rename(columns=MARGIN_COLUMN_MAP)

        try:
            sz = self._request_with_retry(
                ak.macro_china_market_margin_sz, use_em_proxy=True
            )
            sz = sz.rename(columns=MARGIN_COLUMN_MAP)
            # Merge on date and sum numeric columns
            if "date" in sh.columns and "date" in sz.columns:
                sh["date"] = pd.to_datetime(sh["date"]).dt.strftime("%Y-%m-%d")
                sz["date"] = pd.to_datetime(sz["date"]).dt.strftime("%Y-%m-%d")
                merged = sh.merge(sz, on="date", how="outer", suffixes=("_sh", "_sz"))
                for col in ("margin_balance", "short_balance", "total_margin_balance"):
                    sh_col = f"{col}_sh"
                    sz_col = f"{col}_sz"
                    if sh_col in merged.columns and sz_col in merged.columns:
                        merged[col] = merged[sh_col].fillna(0) + merged[sz_col].fillna(
                            0
                        )
                df = (
                    merged[
                        [
                            c
                            for c in [
                                "date",
                                "margin_balance",
                                "short_balance",
                                "total_margin_balance",
                            ]
                            if c in merged.columns
                        ]
                    ]
                    .sort_values("date")
                    .reset_index(drop=True)
                )
            else:
                df = sh
        except Exception:
            self.logger.warning("SZ margin fetch failed, using SH only")
            if "date" in sh.columns:
                sh["date"] = pd.to_datetime(sh["date"]).dt.strftime("%Y-%m-%d")
            df = sh

        self._save_cache(df, cache_path)
        return df

    def fetch_all_watchlist(self) -> dict[str, pd.DataFrame]:
        """Fetch daily OHLCV for every stock on the watchlist + portfolio.

        Reads from SQLite ``WatchlistService`` (the live watchlist) and
        merges in any portfolio positions so held stocks are always
        fetched.  Falls back to ``config/stocks.yaml`` only if both
        SQLite sources are empty.

        Respects the ``request.interval_seconds`` setting between
        consecutive network calls to avoid overwhelming the data source.

        Returns:
            Dictionary mapping symbol codes to their OHLCV DataFrames.
        """
        watchlist: list[dict[str, str]] = []

        # 1. Read from SQLite WatchlistService (primary source)
        try:
            from src.web.services.watchlist_service import WatchlistService

            wl_svc = WatchlistService()
            watchlist = wl_svc.list_all()
        except Exception as exc:
            self.logger.warning("Could not read SQLite watchlist: %s", exc)

        # 2. Merge portfolio positions so held stocks are always fetched
        try:
            from src.web.services.portfolio_store import PortfolioStore

            store = PortfolioStore(capital_service=None)
            positions = store.list_positions()
            existing_symbols = {item["symbol"] for item in watchlist}
            for pos in positions:
                sym = pos.get("symbol", "")
                if sym and sym not in existing_symbols:
                    watchlist.append(
                        {
                            "symbol": sym,
                            "name": pos.get("name", sym),
                            "board": pos.get("board", "main"),
                        }
                    )
                    existing_symbols.add(sym)
        except Exception as exc:
            self.logger.warning(
                "Could not read portfolio positions for watchlist merge: %s", exc
            )

        # 3. Fallback to YAML config if both SQLite sources are empty
        if not watchlist:
            watchlist = self.config.get("watchlist", [])

        if not watchlist:
            self.logger.warning("Watchlist is empty; nothing to fetch")
            return {}

        results: dict[str, pd.DataFrame] = {}
        interval = self._request_cfg.get("interval_seconds", 0.5)

        for idx, entry in enumerate(watchlist):
            symbol = entry["symbol"]
            name = entry.get("name", symbol)
            self.logger.info(
                "Watchlist [%d/%d] Fetching %s (%s)",
                idx + 1,
                len(watchlist),
                symbol,
                name,
            )
            try:
                df = self.fetch_daily_ohlcv(symbol)
                results[symbol] = df
            except DataCollectionError:
                self.logger.error(
                    "Failed to fetch data for %s (%s); skipping",
                    symbol,
                    name,
                )
            # Polite interval between requests (skip after last item)
            if idx < len(watchlist) - 1:
                time.sleep(interval)

        self.logger.info(
            "Watchlist fetch complete: %d/%d succeeded",
            len(results),
            len(watchlist),
        )
        return results

    def fetch_realtime_quotes(
        self,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Fetch real-time quotes for A-share stocks using Sina source.

        Uses ``ak.stock_zh_a_spot()`` which returns current market data
        for all A-shares including price, change, volume.  Results can be
        filtered to a subset of symbols.

        Args:
            symbols: Optional list of 6-digit stock codes to filter.
                If ``None``, returns all A-share quotes.

        Returns:
            DataFrame with columns: symbol, name, price, change,
            pct_change, open, high, low, prev_close, volume, amount.

        Raises:
            DataCollectionError: If the request fails after all retries.
        """
        self.logger.info("Fetching real-time quotes (Sina source)")
        df = self._request_with_retry(ak.stock_zh_a_spot, use_em_proxy=True)
        df = df.rename(columns=REALTIME_SPOT_COLUMN_MAP)

        # Normalize symbol: strip exchange prefix (sh/sz) if present
        if "symbol" in df.columns:
            df["symbol"] = (
                df["symbol"].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True)
            )

        if symbols:
            df = df[df["symbol"].isin(symbols)].copy()

        # Keep only mapped columns that exist
        keep_cols = [c for c in REALTIME_SPOT_COLUMN_MAP.values() if c in df.columns]
        return df[keep_cols].reset_index(drop=True)

    def fetch_dragon_tiger(
        self,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """Fetch dragon-tiger list data.

        Uses ``ak.stock_lhb_detail_em()`` to retrieve institutional
        trading activity on stocks with abnormal price movements.

        Args:
            start_date: Start date ``YYYYMMDD``. Defaults to today.
            end_date: End date ``YYYYMMDD``. Defaults to today.

        Returns:
            DataFrame with columns: rank, symbol, name, date, reason,
            close, pct_change, net_buy, buy_amount, sell_amount, etc.

        Raises:
            DataCollectionError: If the request fails after all retries.
        """
        today = datetime.now().strftime("%Y%m%d")
        start = start_date or today
        end = end_date or today

        cache_path = self._get_cache_path(f"lhb_{start}_{end}", "market")
        if self._is_cache_valid(cache_path):
            self.logger.info("Cache hit for dragon-tiger list")
            return self._load_cache(cache_path)

        self.logger.info("Fetching dragon-tiger list (%s ~ %s)", start, end)
        df = self._request_with_retry(
            ak.stock_lhb_detail_em,
            use_em_proxy=True,
            start_date=start,
            end_date=end,
        )
        df = df.rename(columns=DRAGON_TIGER_COLUMN_MAP)

        # Keep only mapped columns that exist
        keep_cols = [c for c in DRAGON_TIGER_COLUMN_MAP.values() if c in df.columns]
        df = df[keep_cols].reset_index(drop=True)

        self._save_cache(df, cache_path)
        return df

    def fetch_limit_up_pool(self, date: str = "") -> pd.DataFrame:
        """Fetch limit-up pool data.

        Uses ``ak.stock_zt_pool_em()`` to retrieve stocks that hit
        the daily price limit.

        Args:
            date: Date ``YYYYMMDD``. Defaults to today.

        Returns:
            DataFrame with columns: rank, symbol, name, pct_change,
            price, amount, turnover, seal_amount, first_seal_time,
            last_seal_time, break_count, consecutive, industry.

        Raises:
            DataCollectionError: If the request fails after all retries.
        """
        target_date = date or datetime.now().strftime("%Y%m%d")

        cache_path = self._get_cache_path(f"zt_{target_date}", "market")
        if self._is_cache_valid(cache_path):
            self.logger.info("Cache hit for limit-up pool")
            return self._load_cache(cache_path)

        self.logger.info("Fetching limit-up pool for %s", target_date)
        df = self._request_with_retry(
            ak.stock_zt_pool_em, use_em_proxy=True, date=target_date
        )
        df = df.rename(columns=LIMIT_UP_COLUMN_MAP)

        # Keep only mapped columns that exist
        keep_cols = [c for c in LIMIT_UP_COLUMN_MAP.values() if c in df.columns]
        df = df[keep_cols].reset_index(drop=True)

        self._save_cache(df, cache_path)
        return df

    def fetch_limit_down_pool(self, date: str = "") -> pd.DataFrame:
        """Fetch limit-down (跌停) pool data.

        Uses ``ak.stock_zt_pool_dtgc_em()`` to retrieve stocks that hit
        the daily lower price limit.

        Args:
            date: Date ``YYYYMMDD``. Defaults to today.

        Returns:
            DataFrame with columns: rank, symbol, name, pct_change,
            price, amount, etc.

        Raises:
            DataCollectionError: If the request fails after all retries.
        """
        target_date = date or datetime.now().strftime("%Y%m%d")

        cache_path = self._get_cache_path(f"dt_{target_date}", "market")
        if self._is_cache_valid(cache_path):
            self.logger.info("Cache hit for limit-down pool")
            return self._load_cache(cache_path)

        self.logger.info("Fetching limit-down pool for %s", target_date)
        df = self._request_with_retry(
            ak.stock_zt_pool_dtgc_em, use_em_proxy=True, date=target_date
        )
        df = df.rename(columns=LIMIT_DOWN_COLUMN_MAP)

        # Keep only mapped columns that exist
        keep_cols = [c for c in LIMIT_DOWN_COLUMN_MAP.values() if c in df.columns]
        df = df[keep_cols].reset_index(drop=True)

        self._save_cache(df, cache_path)
        return df

    def fetch_dragon_tiger_seats(self, symbol: str) -> pd.DataFrame:
        """Fetch dragon-tiger seat details for a specific stock.

        Uses ``ak.stock_lhb_stock_detail_date_em()`` to find the most recent
        dragon-tiger date, then ``ak.stock_lhb_stock_detail_em()`` to get
        buy and sell seat-level details for that date.

        Args:
            symbol: 6-digit stock code.

        Returns:
            DataFrame with seat_name, buy_amount, sell_amount, net_amount,
            and seat_type columns.  Returns empty DataFrame on error.
        """
        self.logger.info("Fetching dragon-tiger seat details for %s", symbol)
        try:
            # Get dates when this stock appeared on dragon tiger
            dates_df = self._request_with_retry(
                ak.stock_lhb_stock_detail_date_em, use_em_proxy=True, symbol=symbol
            )
            if dates_df.empty:
                return pd.DataFrame()

            # Use the most recent date
            latest_date = str(dates_df.iloc[0]["交易日"]).replace("-", "")[:8]
            self.logger.info("Dragon-tiger latest date for %s: %s", symbol, latest_date)

            # Fetch buy and sell seats
            frames = []
            for flag in ("买入", "卖出"):
                try:
                    df = self._request_with_retry(
                        ak.stock_lhb_stock_detail_em,
                        use_em_proxy=True,
                        symbol=symbol,
                        date=latest_date,
                        flag=flag,
                    )
                    if not df.empty:
                        df = df.rename(columns=DRAGON_TIGER_SEAT_COLUMN_MAP)
                        frames.append(df)
                except Exception:
                    pass

            if not frames:
                return pd.DataFrame()

            # Combine and deduplicate (same seat may appear in both buy/sell)
            combined = pd.concat(frames, ignore_index=True)
            # Keep the first occurrence per seat_name (they have the same data)
            if "seat_name" in combined.columns:
                combined = combined.drop_duplicates(subset=["seat_name"], keep="first")
                combined["seat_type"] = combined["seat_name"].apply(
                    self._classify_seat_type
                )

            keep_cols = [
                c
                for c in [
                    "seat_name",
                    "buy_amount",
                    "sell_amount",
                    "net_amount",
                    "seat_type",
                ]
                if c in combined.columns
            ]
            return combined[keep_cols].reset_index(drop=True)
        except Exception as exc:
            self.logger.warning(
                "Dragon-tiger seats unavailable for %s: %s", symbol, exc
            )
            return pd.DataFrame()

    def fetch_dragon_tiger_stock_stats(self, symbol: str) -> pd.DataFrame:
        """Fetch dragon-tiger historical statistics for a specific stock.

        Uses ``ak.stock_lhb_stock_statistic_em(symbol='近三月')`` to fetch
        all stocks' aggregate stats, then filters by symbol.

        Args:
            symbol: 6-digit stock code.

        Returns:
            DataFrame with appearances, net_amount, inst_net_amount etc.
            Returns empty DataFrame on error.
        """
        self.logger.info("Fetching dragon-tiger stock stats for %s", symbol)
        try:
            df = self._request_with_retry(
                ak.stock_lhb_stock_statistic_em, use_em_proxy=True, symbol="近三月"
            )
            df = df.rename(columns=DRAGON_TIGER_STOCK_STATS_COLUMN_MAP)

            # Filter by symbol
            if "symbol" in df.columns:
                df = df[df["symbol"].astype(str).str.strip() == symbol.strip()]

            if df.empty:
                return pd.DataFrame()

            return df.reset_index(drop=True)
        except Exception as exc:
            self.logger.warning(
                "Dragon-tiger stats unavailable for %s: %s", symbol, exc
            )
            return pd.DataFrame()

    @staticmethod
    def _classify_seat_type(seat_name: str) -> str:
        """Classify a trading seat by name pattern.

        Returns one of: '机构', '知名游资', '普通营业部'.
        """
        if not isinstance(seat_name, str):
            return "普通营业部"
        for pattern, seat_type in SEAT_TYPE_PATTERNS.items():
            if pattern in seat_name:
                return seat_type
        return "普通营业部"

    # ------------------------------------------------------------------
    # Private helpers -- retry, cache, utilities
    # ------------------------------------------------------------------

    def _fetch_daily_via_adata(
        self,
        symbol: str,
        start: str,
        end: str,
        adjust: str,
        cache_path: Path,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV via adata as a last-resort fallback.

        Args:
            symbol: 6-digit stock code.
            start: Start date ``YYYYMMDD``.
            end: End date ``YYYYMMDD``.
            adjust: Adjustment type (qfq/hfq/none).
            cache_path: Path for caching the result.

        Returns:
            DataFrame with standard English columns.

        Raises:
            DataCollectionError: If adata is unavailable or returns no data.
        """
        if not _HAS_ADATA:
            raise DataCollectionError(
                f"All AKShare sources failed for {symbol} and adata is not installed"
            )

        self.logger.info("Fetching daily OHLCV via adata for %s", symbol)

        # adata uses YYYY-MM-DD format and int adjust_type
        start_fmt = (
            f"{start[:4]}-{start[4:6]}-{start[6:8]}" if len(start) == 8 else start
        )
        end_fmt = f"{end[:4]}-{end[4:6]}-{end[6:8]}" if len(end) == 8 and end else None
        adjust_map = {"qfq": 1, "hfq": 2, "none": 0}
        adjust_type = adjust_map.get(adjust, 1)

        try:
            df = _adata.stock.market.get_market(
                stock_code=symbol,
                start_date=start_fmt,
                end_date=end_fmt,
                k_type=1,  # daily
                adjust_type=adjust_type,
            )
        except Exception as exc:
            raise DataCollectionError(
                f"adata fetch failed for {symbol}: {exc}"
            ) from exc

        if df is None or df.empty:
            raise DataCollectionError(f"adata returned empty data for {symbol}")

        # Map adata columns to our standard schema
        col_map = {
            "trade_date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
            "change_pct": "pct_change",
            "change": "change",
            "turnover_ratio": "turnover",
            "pre_close": "prev_close",
        }
        df = df.rename(columns=col_map)
        keep = [c for c in col_map.values() if c in df.columns]
        df = df[keep].copy()

        self._save_cache(df, cache_path)
        return df

    def _request_with_retry(
        self,
        func: Callable[..., pd.DataFrame],
        *,
        use_em_proxy: bool = False,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Execute *func* with retry and exponential backoff.

        Enforces the minimum request interval, then calls the provided
        callable up to ``max_retries`` times.  Each retry waits
        ``base_delay * 2^attempt`` seconds.

        Args:
            func: Callable (typically an AKShare function) returning a
                DataFrame.
            use_em_proxy: When *True*, route through
                :func:`~src.data.eastmoney_proxy.em_api_call` (direct
                first, then proxy-patch fallback) instead of simply
                stripping proxy env vars.  Use for EastMoney endpoints.
            **kwargs: Keyword arguments forwarded to *func*.

        Returns:
            The DataFrame produced by *func*.

        Raises:
            DataCollectionError: If all retry attempts are exhausted.
        """
        max_retries: int = self._request_cfg.get("max_retries", 3)
        base_delay: float = self._request_cfg.get("retry_delay_seconds", 2)
        interval: float = self._request_cfg.get("interval_seconds", 0.5)

        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)

        last_exception: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                self._last_request_ts = time.monotonic()
                if use_em_proxy:
                    from src.data.eastmoney_proxy import em_api_call

                    result = em_api_call(func, **kwargs)
                    if result is not None:
                        return result
                    raise ConnectionError(
                        f"em_api_call returned None for "
                        f"{getattr(func, '__name__', func)}"
                    )
                with _bypass_proxy():
                    return func(**kwargs)
            except Exception as exc:
                last_exception = exc
                func_name = getattr(func, "__name__", str(func))
                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))
                    self.logger.warning(
                        "Retry %d/%d for %s failed (%s). "
                        "Waiting %.1fs before next attempt.",
                        attempt,
                        max_retries,
                        func_name,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    self.logger.error(
                        "All %d retries exhausted for %s: %s",
                        max_retries,
                        func_name,
                        exc,
                    )

        func_name = getattr(func, "__name__", str(func))
        raise DataCollectionError(
            f"Data collection failed for {func_name} after "
            f"{max_retries} retries: {last_exception}"
        )

    def _get_cache_path(self, symbol: str, datatype: str) -> Path:
        """Build the cache file path for a given symbol and data type.

        Args:
            symbol: Stock/index code or descriptive key (e.g. ``"margin"``).
            datatype: Category label such as ``"daily"``, ``"index"``,
                or ``"market"``.

        Returns:
            Absolute ``Path`` to the parquet cache file.
        """
        cache_dir_name: str = self._cache_cfg.get("directory", "data/raw")
        subdir = (
            cache_dir_name.replace("data/", "", 1)
            if "/" in cache_dir_name
            else cache_dir_name
        )
        cache_dir: Path = get_data_dir(subdir)
        today = datetime.now().strftime("%Y%m%d")
        return cache_dir / f"{symbol}_{datatype}_{today}.parquet"

    def _is_cache_valid(self, cache_path: Path) -> bool:
        """Check whether a cache file exists, is within TTL, AND is fresh.

        Validates both file age (mtime < ttl_hours) and data freshness
        using the trading calendar: the last date in a ``date`` column must
        be within ``staleness_max_trading_days`` trading days of today.
        This prevents returning stale data after holidays or source outages
        when the file was rewritten but the source had no new data.

        Args:
            cache_path: Path to the parquet cache file.

        Returns:
            ``True`` if cache file exists, its age < TTL, and the data
            inside is not stale.
        """
        if not self._cache_cfg.get("enabled", True):
            return False
        if not cache_path.exists():
            return False
        ttl_hours: int = self._cache_cfg.get("ttl_hours", 12)
        if ttl_hours <= 0:
            return True
        file_mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
        if (datetime.now() - file_mtime) >= timedelta(hours=ttl_hours):
            return False

        # Data-level freshness: use trading calendar to check if the last
        # date in the data is within tolerance of the expected latest day.
        tolerance = int(self._cache_cfg.get("staleness_max_trading_days", 1))
        try:
            cached_df = pd.read_parquet(cache_path)
            if "date" in cached_df.columns and not cached_df.empty:
                last_date = pd.to_datetime(cached_df["date"].iloc[-1]).date()
                expected = self._expected_latest_trading_day()
                cutoff = self._trading_cal.prev_trading_day(d=expected, n=tolerance)
                if last_date < cutoff:
                    self.logger.info(
                        "Cache data stale (last=%s, expected=%s, cutoff=%s): %s",
                        last_date.isoformat(),
                        expected.isoformat(),
                        cutoff.isoformat(),
                        cache_path.name,
                    )
                    return False
        except Exception:
            pass  # If parquet read fails, fall through to valid

        return True

    def _save_cache(self, df: pd.DataFrame, cache_path: Path) -> None:
        """Persist a DataFrame to parquet cache."""
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path, index=False)
        self.logger.debug("Saved cache: %s", cache_path)

    def _load_cache(self, cache_path: Path) -> pd.DataFrame:
        """Load a DataFrame from a parquet cache file."""
        self.logger.debug("Loading cache: %s", cache_path)
        return pd.read_parquet(cache_path)

    # ------------------------------------------------------------------
    # Static / class-level utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _to_tx_symbol(symbol: str) -> str:
        """Convert 6-digit stock code to Tencent-style prefixed symbol.

        Shanghai stocks (6xxxxx) get ``sh`` prefix; Shenzhen (0xxxxx, 3xxxxx)
        get ``sz`` prefix.

        Args:
            symbol: 6-digit stock code (e.g. ``"600519"``).

        Returns:
            Prefixed symbol (e.g. ``"sh600519"``).
        """
        if symbol.startswith("6"):
            return f"sh{symbol}"
        return f"sz{symbol}"

    @staticmethod
    def _resolve_index_prefix(index_code: str) -> str:
        """Map a bare 6-digit index code to its exchange-prefixed form.

        SSE indices (上证) get an ``sh`` prefix; SZSE (深证) get ``sz``.

        Args:
            index_code: 6-digit index code (e.g. ``"000001"``).

        Returns:
            Prefixed code string (e.g. ``"sh000001"``).
        """
        if index_code.startswith(SSE_INDEX_PREFIXES):
            return f"sh{index_code}"
        if index_code.startswith(SZSE_INDEX_PREFIXES):
            return f"sz{index_code}"
        return f"sh{index_code}"

    @staticmethod
    def _filter_by_date(
        df: pd.DataFrame,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """Filter a DataFrame by date range if date boundaries are given.

        Looks for a ``date`` column (case-insensitive).  If not found,
        the DataFrame is returned unmodified.

        Args:
            df: Source DataFrame with a date-like column.
            start_date: Lower bound ``YYYYMMDD`` (inclusive). Empty to skip.
            end_date: Upper bound ``YYYYMMDD`` (inclusive). Empty to skip.

        Returns:
            Filtered (or original) DataFrame.
        """
        if not start_date and not end_date:
            return df

        date_col: str | None = None
        for col in df.columns:
            if col.lower() in ("date", "day", "日期"):
                date_col = col
                break
        if date_col is None:
            return df

        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col])
        if start_date:
            df = df[df[date_col] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df[date_col] <= pd.to_datetime(end_date)]
        return df.reset_index(drop=True)

    # ------------------------------------------------------------------
    # In-memory TTL cache + convenience helpers for fund-flow methods
    # ------------------------------------------------------------------

    _mem_cache: dict[str, tuple[pd.DataFrame, float]] = {}

    def _get_cache(self, key: str) -> pd.DataFrame | None:
        """Return cached DataFrame if still within TTL, else ``None``."""
        entry = self._mem_cache.get(key)
        if entry is None:
            return None
        df, expires = entry
        if time.monotonic() > expires:
            del self._mem_cache[key]
            return None
        return df

    def _set_cache(self, key: str, df: pd.DataFrame, ttl: int = 600) -> None:
        """Store a DataFrame in the in-memory cache with a TTL (seconds)."""
        self._mem_cache[key] = (df, time.monotonic() + ttl)

    def _polite_sleep(self) -> None:
        """Enforce the minimum request interval between consecutive API calls."""
        interval: float = self._request_cfg.get("interval_seconds", 0.5)
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request_ts = time.monotonic()

    # ------------------------------------------------------------------
    # Fund flow / Holdings / Analyst — FR-SR001, FR-RI001, FR-RI002
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_flow_values(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        """Scale down fund-flow values that are absurdly large.

        The adata Baidu source multiplies raw API values by 1e8, but the
        Baidu API itself sometimes returns values in units of 万 (1e4),
        producing results ~1e4× too large.  When any target column has an
        absolute value exceeding 5e10 (500 亿 — impossible for a single
        stock's daily fund flow), divide all flow columns by 1e4.
        """
        present = [c for c in columns if c in df.columns]
        if not present:
            return df
        max_abs = df[present].abs().max().max()
        if max_abs > 5e10:
            logger = get_logger("fetcher")
            logger.warning(
                "Fund-flow values abnormally large (max %.2e), "
                "dividing by 1e4 to normalize",
                max_abs,
            )
            df[present] = df[present] / 1e4
        return df

    # ------------------------------------------------------------------
    # Baidu finance API helper (bypasses adata's stale cookies)
    # ------------------------------------------------------------------

    @staticmethod
    def _baidu_cn_to_yuan(text: str) -> float:
        """Convert Baidu fund-flow string like ``'-2.61亿'`` to yuan float."""
        units = {"亿": 1e8, "万": 1e4}
        m = re.match(
            r"([+-]?\d+(?:\.\d+)?)\s*(亿|万|元)?",
            text.replace(",", "").replace("+", ""),
        )
        if not m:
            return 0.0
        num = float(m.group(1))
        if text.startswith("-"):
            num = -abs(num)
        unit = m.group(2)
        return num * units.get(unit, 1)

    def _fetch_fund_flow_baidu(
        self, symbol: str, rows: int = 20
    ) -> pd.DataFrame | None:
        """Fetch daily fund-flow directly from Baidu finance API.

        Bypasses adata's hardcoded (stale) cookies; uses minimal headers.
        Returns standardised DataFrame or None on any failure.
        """
        url = (
            "https://finance.pae.baidu.com/vapi/v1/fundsortlist"
            f"?code={symbol}&market=ab&finance_type=stock&tab=day"
            f"&from=history&date={datetime.now().strftime('%Y%m%d')}"
            f"&pn=0&rn={rows}&finClientType=pc"
        )
        try:
            with _bypass_proxy():
                resp = _requests.get(url, timeout=10, proxies={})
            if resp.status_code != 200 or not resp.text:
                return None
            content = resp.json().get("Result", {}).get("content", [])
            if not content:
                return None
        except Exception as exc:
            self.logger.warning("Baidu fund flow API failed for %s: %s", symbol, exc)
            return None

        data = []
        for row in content:
            data.append(
                {
                    "date": row["date"].replace("/", "-"),
                    "main_net": self._baidu_cn_to_yuan(row.get("extMainIn", "0")),
                    "super_large_net": self._baidu_cn_to_yuan(
                        row.get("superNetIn", "0")
                    ),
                    "large_net": self._baidu_cn_to_yuan(row.get("largeNetIn", "0")),
                    "medium_net": self._baidu_cn_to_yuan(row.get("mediumNetIn", "0")),
                    "small_net": self._baidu_cn_to_yuan(row.get("littleNetIn", "0")),
                }
            )
        return pd.DataFrame(data)

    def fetch_fund_flow(self, symbol: str) -> pd.DataFrame:
        """Fetch individual stock fund flow data.

        Source chain (degradation) — prioritises industry-standard EastMoney:
        1. AKShare ``stock_individual_fund_flow`` (东方财富) — industry standard.
        2. adata ``get_capital_flow`` (东财 proxy-friendly backup).
        3. Baidu finance API — last resort, algorithm opaque.

        All paths tag the result with a ``_source`` column for traceability.

        Args:
            symbol: 6-digit stock code.

        Returns:
            DataFrame with standardised English column names, most recent 20 rows.
        """
        cache_key = f"fund_flow_{symbol}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        # --- Primary: AKShare per-stock historical (东方财富, industry standard) ---
        market = "sh" if symbol.startswith(("6", "5")) else "sz"
        try:
            from src.data.eastmoney_proxy import em_api_call

            self._polite_sleep()
            df = em_api_call(ak.stock_individual_fund_flow, stock=symbol, market=market)
            if df is not None and not df.empty:
                rename_map = {
                    k: v for k, v in FUND_FLOW_COLUMN_MAP.items() if k in df.columns
                }
                df = df.rename(columns=rename_map)
                df["_source"] = "eastmoney"
                df = df.tail(20).reset_index(drop=True)
                self._set_cache(cache_key, df, ttl=300)
                return df
        except Exception as exc:
            self.logger.warning(
                "AKShare fund flow failed for %s: %s, trying adata", symbol, exc
            )

        # --- Fallback 1: adata EastMoney daily fund flow ---
        if _HAS_ADATA:
            try:
                import adata as _ad

                with _bypass_proxy():
                    adf = _ad.stock.market.get_capital_flow(stock_code=symbol)
                if adf is not None and not adf.empty:
                    df = pd.DataFrame(
                        {
                            "date": adf["trade_date"].astype(str).str[:10],
                            "main_net": adf["main_net_inflow"].astype(float),
                            "super_large_net": adf["max_net_inflow"].astype(float),
                            "large_net": adf["lg_net_inflow"].astype(float),
                            "medium_net": adf["mid_net_inflow"].astype(float),
                            "small_net": adf["sm_net_inflow"].astype(float),
                        }
                    )
                    flow_cols = [
                        "main_net",
                        "super_large_net",
                        "large_net",
                        "medium_net",
                        "small_net",
                    ]
                    df = self._normalize_flow_values(df, flow_cols)
                    df["_source"] = "eastmoney_adata"
                    df = df.tail(20).reset_index(drop=True)
                    self._set_cache(cache_key, df, ttl=300)
                    return df
            except Exception as exc:
                self.logger.warning("adata fund flow failed for %s: %s", symbol, exc)

        # --- Fallback 2: Baidu finance API (last resort) ---
        df = self._fetch_fund_flow_baidu(symbol)
        if df is not None and not df.empty:
            df["_source"] = "baidu"
            df = df.tail(20).reset_index(drop=True)
            self._set_cache(cache_key, df, ttl=300)
            return df

        return pd.DataFrame()

    def fetch_intraday_fund_flow_series(
        self, symbol: str, sample_minutes: int = 30
    ) -> list[dict]:
        """Fetch intraday fund-flow time series (sampled at *sample_minutes* intervals).

        Returns a list of dicts with ``time``, ``main_net``, and per-order-size
        breakdowns so the LLM can see the capital-flow trajectory across the
        trading day — not just the latest snapshot.

        Source chain:
        1. EastMoney push2 API via em_api_call (minute-level kline).
        2. adata ``get_capital_flow_min`` fallback.

        Args:
            symbol: 6-digit stock code.
            sample_minutes: Interval in minutes for sampling (default 30).

        Returns:
            List of dicts ordered by time, each containing:
            ``time`` (HH:MM), ``main_net``, ``super_large_net``, ``large_net``,
            ``medium_net``, ``small_net``.  Empty list on failure.
        """
        cache_key = f"fund_flow_series_{symbol}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        min_df = self._fetch_fund_flow_min_eastmoney(symbol)

        # Fallback to adata if EastMoney direct failed
        if min_df is None or min_df.empty:
            min_df = self._fetch_fund_flow_min_adata(symbol)

        if min_df is None or min_df.empty:
            return []

        # Ensure we have a time column
        time_col = None
        for col in ("trade_time", "trade_date"):
            if col in min_df.columns:
                time_col = col
                break
        if time_col is None:
            return []

        # Parse timestamps and sample at intervals
        min_df = min_df.copy()
        min_df["_ts"] = pd.to_datetime(min_df[time_col], errors="coerce")
        min_df = min_df.dropna(subset=["_ts"]).sort_values("_ts")
        if min_df.empty:
            return []

        # Sample: keep first, then every sample_minutes, plus last
        sampled_indices = [0]
        last_kept = min_df["_ts"].iloc[0]
        interval = pd.Timedelta(minutes=sample_minutes)
        for i in range(1, len(min_df)):
            if min_df["_ts"].iloc[i] - last_kept >= interval:
                sampled_indices.append(i)
                last_kept = min_df["_ts"].iloc[i]
        # Always include the last row (latest data point)
        if sampled_indices[-1] != len(min_df) - 1:
            sampled_indices.append(len(min_df) - 1)

        sampled = min_df.iloc[sampled_indices]

        result = []
        for _, row in sampled.iterrows():
            result.append(
                {
                    "time": row["_ts"].strftime("%H:%M"),
                    "main_net": float(row.get("main_net_inflow", 0)),
                    "super_large_net": float(row.get("max_net_inflow", 0)),
                    "large_net": float(row.get("lg_net_inflow", 0)),
                    "medium_net": float(row.get("mid_net_inflow", 0)),
                    "small_net": float(row.get("sm_net_inflow", 0)),
                }
            )
        self._set_cache(cache_key, result, ttl=120)
        return result

    def _fetch_fund_flow_min_eastmoney(self, symbol: str) -> pd.DataFrame | None:
        """Fetch minute-level fund flow directly from EastMoney push2 API.

        Uses em_api_call for proxy-patch fallback.  Returns a DataFrame with
        columns: trade_time, main_net_inflow, sm_net_inflow, mid_net_inflow,
        lg_net_inflow, max_net_inflow.
        """
        import requests as _requests

        from src.data.eastmoney_proxy import em_api_call

        cid = 1 if symbol.startswith("6") else 0

        def _call() -> dict:
            url = (
                f"https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
                f"?lmt=0&klt=1"
                f"&fields1=f1,f2,f3,f7"
                f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,"
                f"f61,f62,f63,f64,f65"
                f"&secid={cid}.{symbol}"
            )
            resp = _requests.get(url, timeout=15)
            return resp.json()

        try:
            self._polite_sleep()
            data = em_api_call(_call)
            if not isinstance(data, dict):
                return None
            inner = data.get("data")
            if not inner or "klines" not in inner:
                return None
            klines = inner["klines"]
            if not klines:
                return None

            columns = [
                "trade_time",
                "main_net_inflow",
                "sm_net_inflow",
                "mid_net_inflow",
                "lg_net_inflow",
                "max_net_inflow",
            ]
            rows = []
            for line in klines:
                parts = line.split(",")
                if len(parts) >= 6:
                    rows.append(parts[:6])
            if not rows:
                return None

            df = pd.DataFrame(rows, columns=columns)
            df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")
            for c in columns[1:]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df
        except Exception as exc:
            self.logger.warning(
                "EastMoney push2 minute fund flow failed for %s: %s",
                symbol,
                exc,
            )
            return None

    def _fetch_fund_flow_min_adata(self, symbol: str) -> pd.DataFrame | None:
        """Fallback: fetch minute-level fund flow via adata library."""
        if not _HAS_ADATA:
            return None

        import adata as _ad

        for source_name, source_fn in [
            ("default", _ad.stock.market.get_capital_flow_min),
            ("baidu", _ad.stock.market.baidu_capital_flow.get_capital_flow_min),
        ]:
            try:
                with _bypass_proxy():
                    min_df = source_fn(stock_code=symbol)
                if min_df is not None and not min_df.empty:
                    return min_df
            except Exception as exc:
                self.logger.warning(
                    "adata %s minute fund flow failed for %s: %s",
                    source_name,
                    symbol,
                    exc,
                )
        return None

    def fetch_intraday_fund_flow(self, symbol: str) -> pd.DataFrame:
        """Fetch today's real-time fund-flow for a stock.

        Source chain — em_api_call first, adata fallback, Baidu last resort:
        1. AKShare rank API ``stock_individual_fund_flow_rank`` via em_api_call (东财).
        2. adata ``get_capital_flow_min`` — minute-level real-time (东财).
        3. Baidu finance API — last resort.

        All paths tag the result with a ``_source`` column.

        Args:
            symbol: 6-digit stock code.

        Returns:
            DataFrame with at most 1 row (today's fund-flow), or empty.
        """
        cache_key = f"fund_flow_intraday_{symbol}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        # --- Primary: AKShare market-wide rank API via em_api_call (东财) ---
        market_cache_key = "fund_flow_rank_today"
        market_df = self._get_cache(market_cache_key)
        rank_failed = False
        if market_df is None:
            try:
                from src.data.eastmoney_proxy import em_api_call

                self._polite_sleep()
                market_df = em_api_call(
                    ak.stock_individual_fund_flow_rank, indicator="今日"
                )
            except Exception as exc:
                self.logger.warning("Fund flow rank API unreachable: %s", exc)
                rank_failed = True

            if not rank_failed and market_df is not None and not market_df.empty:
                rename_map = {
                    k: v
                    for k, v in FUND_FLOW_RANK_COLUMN_MAP.items()
                    if k in market_df.columns
                }
                market_df = market_df.rename(columns=rename_map)
                self._set_cache(market_cache_key, market_df, ttl=60)
            else:
                rank_failed = True

        if not rank_failed and market_df is not None:
            if "symbol" in market_df.columns:
                row = market_df[
                    market_df["symbol"].astype(str).str.strip() == symbol.strip()
                ]
                if not row.empty:
                    result = row.head(1).copy()
                    # AKShare rank API indicator="今日" returns today's data
                    result["date"] = datetime.now().strftime("%Y-%m-%d")
                    result["_source"] = "eastmoney_rank"
                    self._set_cache(cache_key, result, ttl=60)
                    return result

        # --- Fallback 1: adata real-time minute fund flow (东财) ---
        if _HAS_ADATA:
            import adata as _ad

            for source_name, source_fn in [
                ("default", _ad.stock.market.get_capital_flow_min),
                ("baidu", _ad.stock.market.baidu_capital_flow.get_capital_flow_min),
            ]:
                try:
                    with _bypass_proxy():
                        min_df = source_fn(stock_code=symbol)
                    if min_df is not None and not min_df.empty:
                        last = min_df.iloc[-1]
                        # Extract actual date from data source (not datetime.now())
                        # adata min returns last trading day's data outside trading hours
                        actual_date = str(
                            last.get("trade_time", last.get("trade_date", ""))
                        )[:10] or datetime.now().strftime("%Y-%m-%d")
                        result = pd.DataFrame(
                            [
                                {
                                    "date": actual_date,
                                    "main_net": float(last.get("main_net_inflow", 0)),
                                    "super_large_net": float(
                                        last.get("max_net_inflow", 0)
                                    ),
                                    "large_net": float(last.get("lg_net_inflow", 0)),
                                    "medium_net": float(last.get("mid_net_inflow", 0)),
                                    "small_net": float(last.get("sm_net_inflow", 0)),
                                    "_source": "eastmoney_adata",
                                }
                            ]
                        )
                        flow_cols = [
                            "main_net",
                            "super_large_net",
                            "large_net",
                            "medium_net",
                            "small_net",
                        ]
                        result = self._normalize_flow_values(result, flow_cols)
                        self._set_cache(cache_key, result, ttl=60)
                        return result
                except Exception as exc:
                    self.logger.warning(
                        "adata %s minute fund flow failed for %s: %s",
                        source_name,
                        symbol,
                        exc,
                    )

        # --- Fallback 2: Baidu API direct (last resort) ---
        baidu_df = self._fetch_fund_flow_baidu(symbol, rows=1)
        if baidu_df is not None and not baidu_df.empty:
            result = baidu_df.head(1).copy()
            # Baidu API returns "today" data; date from response is used when available
            if "date" not in result.columns or result["date"].iloc[0] in ("", None):
                result["date"] = datetime.now().strftime("%Y-%m-%d")
            result["_source"] = "baidu"
            self._set_cache(cache_key, result, ttl=60)
            return result

        return pd.DataFrame()

    def fetch_fund_flow_detail(self, symbol: str) -> pd.DataFrame:
        """Fetch per-category inflow/outflow detail for a stock.

        Source chain — em_api_call first, adata fallback, Baidu last resort:
        1. AKShare ``stock_fund_flow_individual`` via em_api_call (东财 JS-based).
        2. adata ``get_capital_flow_min`` (东财) — minute-level, compute
           inflow/outflow from positive/negative minutes.
        3. Baidu finance API — last resort.

        All paths tag the result with a ``_source`` column.

        Args:
            symbol: 6-digit stock code.

        Returns:
            DataFrame with at most 1 row containing inflow/outflow/net,
            or empty DataFrame on failure.
        """
        cache_key = f"fund_flow_detail_{symbol}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        # --- Primary: AKShare JS-based market detail via em_api_call (东财) ---
        market_cache_key = "fund_flow_detail_market"
        market_df = self._get_cache(market_cache_key)
        if market_df is None:
            last_exc = None
            from src.data.eastmoney_proxy import em_api_call

            for attempt in range(2):
                try:
                    self._polite_sleep()
                    market_df = em_api_call(
                        ak.stock_fund_flow_individual, symbol="即时"
                    )
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt == 0:
                        self.logger.warning(
                            "Fund flow detail fetch failed (attempt 1): %s, retrying",
                            exc,
                        )
                        time.sleep(1)

            if market_df is None or (hasattr(market_df, "empty") and market_df.empty):
                self.logger.warning(
                    "Fund flow detail fetch failed after retries: %s", last_exc
                )
            else:
                rename_map = {
                    k: v
                    for k, v in FUND_FLOW_DETAIL_COLUMN_MAP.items()
                    if k in market_df.columns
                }
                market_df = market_df.rename(columns=rename_map)
                if "symbol" in market_df.columns:
                    market_df["symbol"] = (
                        market_df["symbol"].astype(str).str.strip().str.zfill(6)
                    )
                self._set_cache(market_cache_key, market_df, ttl=60)

        if market_df is not None and "symbol" in market_df.columns:
            row = market_df[
                market_df["symbol"].astype(str).str.strip() == symbol.strip()
            ]
            if not row.empty:
                result = row.head(1).copy()
                result["_source"] = "eastmoney"
                self._set_cache(cache_key, result, ttl=60)
                return result

        # --- Fallback 1: adata minute fund flow → compute inflow/outflow (东财) ---
        if _HAS_ADATA:
            import adata as _ad

            for source_name, source_fn in [
                ("default", _ad.stock.market.get_capital_flow_min),
                ("baidu", _ad.stock.market.baidu_capital_flow.get_capital_flow_min),
            ]:
                try:
                    with _bypass_proxy():
                        min_df = source_fn(stock_code=symbol)
                    if min_df is not None and not min_df.empty:
                        last = min_df.iloc[-1]
                        # Use only main-force components (超大单+大单).
                        main_components = [
                            float(last.get("max_net_inflow", 0)),
                            float(last.get("lg_net_inflow", 0)),
                        ]
                        inflow = sum(v for v in main_components if v > 0)
                        outflow = -sum(v for v in main_components if v < 0)
                        net = sum(main_components)
                        result = pd.DataFrame(
                            [
                                {
                                    "symbol": symbol,
                                    "inflow": inflow,
                                    "outflow": outflow,
                                    "net": net,
                                    "_source": "eastmoney_adata",
                                }
                            ]
                        )
                        result = self._normalize_flow_values(
                            result, ["inflow", "outflow", "net"]
                        )
                        self._set_cache(cache_key, result, ttl=60)
                        return result
                except Exception as exc:
                    self.logger.warning(
                        "adata %s fund flow detail failed for %s: %s",
                        source_name,
                        symbol,
                        exc,
                    )

        # --- Fallback 2: Baidu API direct → compute inflow/outflow ---
        baidu_df = self._fetch_fund_flow_baidu(symbol, rows=1)
        if baidu_df is not None and not baidu_df.empty:
            row = baidu_df.iloc[0]
            main_components = [
                float(row.get("super_large_net", 0)),
                float(row.get("large_net", 0)),
            ]
            inflow = sum(v for v in main_components if v > 0)
            outflow = -sum(v for v in main_components if v < 0)
            net = sum(main_components)
            result = pd.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "inflow": inflow,
                        "outflow": outflow,
                        "net": net,
                        "_source": "baidu",
                    }
                ]
            )
            result = self._normalize_flow_values(result, ["inflow", "outflow", "net"])
            self._set_cache(cache_key, result, ttl=60)
            return result

        return pd.DataFrame()

    def fetch_valuation_indicator(self, symbol: str) -> dict[str, Any]:
        """Fetch valuation indicators (PE_TTM, PB, PS_TTM).

        Uses ``ak.stock_zh_valuation_comparison_em`` (EastMoney) to fetch
        the latest valuation snapshot in a single call.  Wrapped with
        ``em_api_call`` for automatic proxy-patch activation.

        The old ``stock_a_lg_indicator`` was removed from AKShare ≥1.18.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict with pe_ttm, pb, ps_ttm keys (subset present on success).
            Returns empty dict on failure.
        """
        cache_key = f"valuation_{symbol}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        self.logger.info("Fetching valuation indicators for %s", symbol)

        # stock_zh_valuation_comparison_em expects "SZ000001" / "SH600519" format
        prefix = "SH" if symbol.startswith(("6", "9")) else "SZ"
        em_symbol = f"{prefix}{symbol}"

        try:
            from src.data.eastmoney_proxy import em_api_call

            self._polite_sleep()
            df = em_api_call(ak.stock_zh_valuation_comparison_em, symbol=em_symbol)
        except Exception as exc:
            self.logger.warning(
                "Valuation indicator fetch failed for %s: %s", symbol, exc
            )
            return {}

        if df is None or df.empty:
            return {}

        # First row is the target stock; extract valuation fields
        row = df.iloc[0]
        field_map = {
            "pe_ttm": "市盈率-TTM",
            "pb": "市净率-MRQ",
            "ps_ttm": "市销率-TTM",
        }
        result: dict[str, Any] = {}
        for key, col in field_map.items():
            if col in row.index:
                try:
                    result[key] = float(row[col])
                except (TypeError, ValueError):
                    pass

        if not result:
            self.logger.warning(
                "Valuation indicator fetch failed for %s: no data in response",
                symbol,
            )
            return {}

        self._set_cache(cache_key, result, ttl=3600)  # type: ignore[arg-type]
        return result

    def fetch_fund_holdings(self, symbol: str, date: str = "") -> pd.DataFrame:
        """Fetch fund holding details for a stock.

        Uses AKShare ``stock_report_fund_hold_detail``.

        Args:
            symbol: 6-digit stock code.
            date: Optional report date ``YYYYMMDD``.

        Returns:
            DataFrame with standardised English column names.
        """
        cache_key = f"fund_hold_{symbol}_{date}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        try:
            from src.data.eastmoney_proxy import em_api_call

            self._polite_sleep()
            if date:
                df = em_api_call(
                    ak.stock_report_fund_hold_detail, symbol=symbol, date=date
                )
            else:
                df = em_api_call(ak.stock_report_fund_hold_detail, symbol=symbol)
        except Exception as exc:
            self.logger.warning("Fund holdings fetch failed for %s: %s", symbol, exc)
            return pd.DataFrame()

        if df.empty:
            return df

        rename_map = {k: v for k, v in FUND_HOLD_COLUMN_MAP.items() if k in df.columns}
        df = df.rename(columns=rename_map)
        self._set_cache(cache_key, df, ttl=3600)
        return df

    def fetch_analyst_rank(self) -> pd.DataFrame:
        """Fetch top analyst rankings.

        Uses AKShare ``stock_analyst_rank_em``.

        Returns:
            DataFrame with standardised English column names.
        """
        cache_key = "analyst_rank"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        try:
            from src.data.eastmoney_proxy import em_api_call

            self._polite_sleep()
            df = em_api_call(ak.stock_analyst_rank_em)
        except Exception as exc:
            self.logger.warning("Analyst rank fetch failed: %s", exc)
            return pd.DataFrame()

        if df.empty:
            return df

        rename_map = {
            k: v for k, v in ANALYST_RANK_COLUMN_MAP.items() if k in df.columns
        }
        df = df.rename(columns=rename_map)
        self._set_cache(cache_key, df, ttl=3600)
        return df

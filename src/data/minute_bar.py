"""Minute-level OHLCV bar fetcher for A-share intraday analysis.

Fetches 5-minute (or 1/15/30/60) OHLCV bars from AKShare with
multi-source fallback: EastMoney → Sina → empty DataFrame.

Uses Redis for short-TTL caching (60s) to avoid hammering upstream APIs
during rapid polling cycles.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("data.minute_bar")

# Valid minute bar periods
_VALID_PERIODS = {"1", "5", "15", "30", "60"}

# Exchange prefix pattern (sh/sz/bj) — strip to get bare 6-digit code
_EXCHANGE_PREFIX_RE = re.compile(r"^(sh|sz|bj)", re.IGNORECASE)

# Standard output columns
_OUTPUT_COLUMNS = ["datetime", "open", "high", "low", "close", "volume", "amount"]

# EastMoney column mapping (Chinese → English)
_EM_COLUMN_MAP: dict[str, str] = {
    "时间": "datetime",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}

# Sina column mapping
_SINA_COLUMN_MAP: dict[str, str] = {
    "day": "datetime",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
}


def _normalize_symbol(sym: str) -> str:
    """Strip exchange prefix (sh/sz/bj) to get bare 6-digit code."""
    return _EXCHANGE_PREFIX_RE.sub("", sym)


def _sina_symbol(code: str) -> str:
    """Convert bare 6-digit code to Sina-style prefix: sh600519, sz000001."""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    return f"{prefix}{code}"


def _empty_df() -> pd.DataFrame:
    """Return an empty DataFrame with standard columns."""
    return pd.DataFrame(columns=_OUTPUT_COLUMNS)


class MinuteBarFetcher:
    """Fetch intraday minute-level OHLCV bars from AKShare.

    Primary: ak.stock_zh_a_hist_min_em (EastMoney minute bars)
    Fallback: ak.stock_zh_a_minute (Sina minute bars, legacy)

    Args:
        redis_client: Optional Redis client for caching. If None, caching
            is disabled and all calls go directly to upstream APIs.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._cache_ttl: int = 60  # seconds
        self._last_request_ts: float = 0.0

    def fetch(self, symbol: str, period: str = "5", days: int = 1) -> pd.DataFrame:
        """Fetch minute bars for a single symbol.

        Args:
            symbol: Stock code like "600519" or "sz000001".
            period: "1", "5", "15", "30", "60" (minutes).
            days: Number of trading days to fetch (1-5).

        Returns:
            DataFrame with columns: [datetime, open, high, low, close, volume, amount]
            Sorted by datetime ascending. Empty DataFrame if fetch fails.
        """
        symbol = _normalize_symbol(symbol)
        period = str(period)
        days = max(1, min(days, 5))

        if period not in _VALID_PERIODS:
            logger.warning("Invalid period '%s', falling back to '5'", period)
            period = "5"

        # Check Redis cache
        cached = self._get_cache(symbol, period)
        if cached is not None:
            return cached

        # Primary: EastMoney
        df = self._fetch_eastmoney(symbol, period, days)
        if df is not None and not df.empty:
            self._set_cache(symbol, period, df)
            return df

        # Fallback: Sina
        df = self._fetch_sina(symbol, period)
        if df is not None and not df.empty:
            self._set_cache(symbol, period, df)
            return df

        logger.warning("All minute bar sources failed for %s", symbol)
        return _empty_df()

    def fetch_batch(
        self,
        symbols: list[str],
        period: str = "5",
        days: int = 1,
    ) -> dict[str, pd.DataFrame]:
        """Batch fetch for multiple symbols using ThreadPoolExecutor.

        Args:
            symbols: List of stock codes.
            period: Minute bar period.
            days: Number of trading days.

        Returns:
            Dict mapping symbol → DataFrame. Missing symbols get empty DataFrame.
        """
        symbols = [_normalize_symbol(s) for s in symbols]
        results: dict[str, pd.DataFrame] = {}

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_sym = {
                executor.submit(self.fetch, sym, period, days): sym for sym in symbols
            }
            for future in as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    results[sym] = future.result()
                except Exception as exc:
                    logger.warning("Batch fetch failed for %s: %s", sym, exc)
                    results[sym] = _empty_df()

        return results

    def get_today_bars(self, symbol: str, period: str = "5") -> pd.DataFrame:
        """Convenience: fetch only today's bars.

        Args:
            symbol: Stock code.
            period: Minute bar period.

        Returns:
            DataFrame with today's minute bars only.
        """
        return self.fetch(symbol, period=period, days=1)

    # ------------------------------------------------------------------
    # Private: data sources
    # ------------------------------------------------------------------

    def _polite_sleep(self, interval: float = 0.3) -> None:
        """Rate limiting between upstream requests."""
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request_ts = time.monotonic()

    def _fetch_eastmoney(
        self, symbol: str, period: str, days: int
    ) -> pd.DataFrame | None:
        """Fetch minute bars from EastMoney via AKShare."""
        try:
            import akshare as ak

            from src.data.eastmoney_proxy import em_api_call
        except ImportError:
            logger.debug("akshare not available for EastMoney minute bars")
            return None

        try:
            self._polite_sleep()

            # Build date range for the request
            now = datetime.now()
            start_date = now.strftime("%Y-%m-%d 09:30:00")
            end_date = now.strftime("%Y-%m-%d 15:00:00")

            raw = em_api_call(
                ak.stock_zh_a_hist_min_em,
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
            )

            if raw is None or raw.empty:
                logger.debug("EastMoney minute bars empty for %s", symbol)
                return None

            # Rename Chinese columns
            df = raw.rename(columns=_EM_COLUMN_MAP)

            # Ensure standard columns exist
            for col in _OUTPUT_COLUMNS:
                if col not in df.columns:
                    df[col] = None

            df = df[_OUTPUT_COLUMNS].copy()

            # Convert numeric columns
            for col in ["open", "high", "low", "close", "volume", "amount"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df = df.sort_values("datetime").reset_index(drop=True)
            return df

        except Exception as exc:
            logger.warning("EastMoney minute bar fetch failed for %s: %s", symbol, exc)
            return None

    def _fetch_sina(self, symbol: str, period: str) -> pd.DataFrame | None:
        """Fetch minute bars from Sina via AKShare (legacy fallback)."""
        try:
            import akshare as ak
        except ImportError:
            logger.debug("akshare not available for Sina minute bars")
            return None

        try:
            self._polite_sleep()

            sina_sym = _sina_symbol(symbol)
            raw = ak.stock_zh_a_minute(symbol=sina_sym, period=period)

            if raw is None or raw.empty:
                logger.debug("Sina minute bars empty for %s", symbol)
                return None

            df = raw.rename(columns=_SINA_COLUMN_MAP)

            # Sina may not have 'amount' column
            for col in _OUTPUT_COLUMNS:
                if col not in df.columns:
                    df[col] = None

            df = df[_OUTPUT_COLUMNS].copy()

            for col in ["open", "high", "low", "close", "volume", "amount"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df = df.sort_values("datetime").reset_index(drop=True)
            return df

        except Exception as exc:
            logger.warning("Sina minute bar fetch failed for %s: %s", symbol, exc)
            return None

    # ------------------------------------------------------------------
    # Private: Redis cache
    # ------------------------------------------------------------------

    def _cache_key(self, symbol: str, period: str) -> str:
        """Build Redis cache key."""
        today = datetime.now().strftime("%Y%m%d")
        return f"minute_bar:{symbol}:{period}:{today}"

    def _get_cache(self, symbol: str, period: str) -> pd.DataFrame | None:
        """Retrieve cached minute bars from Redis."""
        if self._redis is None:
            return None
        try:
            import json

            key = self._cache_key(symbol, period)
            raw = self._redis.get(key)
            if raw is None:
                return None
            data = json.loads(raw)
            df = pd.DataFrame(data)
            if df.empty:
                return None
            logger.debug("Cache hit for %s (period=%s)", symbol, period)
            return df
        except Exception:
            return None

    def _set_cache(self, symbol: str, period: str, df: pd.DataFrame) -> None:
        """Store minute bars in Redis with TTL."""
        if self._redis is None:
            return
        try:
            import json

            key = self._cache_key(symbol, period)
            payload = df.to_dict(orient="records")
            self._redis.setex(key, self._cache_ttl, json.dumps(payload, default=str))
        except Exception as exc:
            logger.debug("Failed to cache minute bars: %s", exc)

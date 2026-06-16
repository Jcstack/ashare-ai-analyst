"""Global market data fetcher using Yahoo Finance.

Provides real-time snapshots for international indices, commodities,
and currencies. Data is cached in memory with configurable TTL.

Per PRD v3.2 FR-GM001: Global market data collection.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from src.data.circuit_breaker import CircuitBreaker
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("data.global_market")


class GlobalMarketFetcher:
    """Fetch global market data via yfinance with in-memory caching."""

    def __init__(self) -> None:
        self._config = self._load_config()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._yf = None  # lazy import
        self._cache_ttl: float = self._config.get("cache_ttl", 300)
        self._rate_limit: float = self._config.get("rate_limit_interval", 2.0)
        self._last_call: float = 0.0
        self._circuit = CircuitBreaker(
            "yfinance", failure_threshold=5, recovery_timeout=120.0
        )
        logger.info("GlobalMarketFetcher initialized (TTL=%ds)", self._cache_ttl)

    def _load_config(self) -> dict:
        try:
            return load_config("global_market")
        except FileNotFoundError:
            logger.warning("config/global_market.yaml not found; using defaults")
            return {}

    def _ensure_yfinance(self):
        """Lazy-import yfinance to avoid startup cost."""
        if self._yf is None:
            try:
                import yfinance

                self._yf = yfinance
            except ImportError:
                logger.error("yfinance not installed — pip install yfinance")
                raise
        return self._yf

    def _rate_limit_wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._rate_limit:
            time.sleep(self._rate_limit - elapsed)
        self._last_call = time.monotonic()

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.monotonic() - ts < self._cache_ttl:
                return data
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        self._cache[key] = (time.monotonic(), data)

    def _fetch_tickers(
        self, symbols: list[str], *, max_retries: int = 2
    ) -> dict[str, dict]:
        """Fetch current price data for a list of yfinance symbols.

        Implements retry with exponential backoff per audit recommendation #1
        and circuit breaker per recommendation #5.
        """
        # Circuit breaker: fail fast when service is consistently down
        if self._circuit.state == "open":
            logger.debug("yfinance circuit breaker is open — returning empty")
            return {}

        yf = self._ensure_yfinance()

        for attempt in range(max_retries + 1):
            self._rate_limit_wait()
            t0 = time.monotonic()
            results: dict[str, dict] = {}
            try:
                tickers = yf.Tickers(" ".join(symbols))
                for sym in symbols:
                    try:
                        ticker = tickers.tickers.get(sym)
                        if ticker is None:
                            continue
                        info = ticker.fast_info
                        last_price = getattr(info, "last_price", None)
                        prev_close = getattr(info, "previous_close", None)
                        if last_price is not None:
                            change = last_price - prev_close if prev_close else 0.0
                            pct_change = (
                                (change / prev_close * 100) if prev_close else 0.0
                            )
                            results[sym] = {
                                "price": round(last_price, 2),
                                "change": round(change, 2),
                                "pct_change": round(pct_change, 2),
                                "prev_close": (
                                    round(prev_close, 2) if prev_close else None
                                ),
                            }
                    except Exception as e:
                        logger.warning("Failed to fetch %s: %s", sym, e)

                elapsed = (time.monotonic() - t0) * 1000
                logger.debug(
                    "yfinance fetch: %d/%d symbols in %.0fms",
                    len(results),
                    len(symbols),
                    elapsed,
                )
                self._circuit._on_success()
                return results

            except Exception as e:
                elapsed = (time.monotonic() - t0) * 1000
                if attempt < max_retries:
                    backoff = 2**attempt
                    logger.warning(
                        "yfinance batch fetch failed (attempt %d/%d, %.0fms): %s — "
                        "retrying in %ds",
                        attempt + 1,
                        max_retries + 1,
                        elapsed,
                        e,
                        backoff,
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        "yfinance batch fetch failed after %d attempts (%.0fms): %s",
                        max_retries + 1,
                        elapsed,
                        e,
                    )
                    self._circuit._on_failure()

        return {}

    def fetch_global_indices(self) -> list[dict]:
        """Fetch global stock market indices."""
        cached = self._get_cached("indices")
        if cached is not None:
            return cached

        index_config = self._config.get("indices", [])
        if not index_config:
            return []

        symbols = [item["symbol"] for item in index_config]
        raw = self._fetch_tickers(symbols)

        result = []
        for item in index_config:
            sym = item["symbol"]
            data = raw.get(sym, {})
            result.append(
                {
                    "symbol": sym,
                    "name": item["name"],
                    "region": item.get("region", ""),
                    "price": data.get("price"),
                    "change": data.get("change"),
                    "pct_change": data.get("pct_change"),
                    "prev_close": data.get("prev_close"),
                }
            )

        self._set_cached("indices", result)
        return result

    def fetch_commodities(self) -> list[dict]:
        """Fetch commodity prices (gold, oil, etc.)."""
        cached = self._get_cached("commodities")
        if cached is not None:
            return cached

        commodity_config = self._config.get("commodities", [])
        if not commodity_config:
            return []

        symbols = [item["symbol"] for item in commodity_config]
        raw = self._fetch_tickers(symbols)

        result = []
        for item in commodity_config:
            sym = item["symbol"]
            data = raw.get(sym, {})
            result.append(
                {
                    "symbol": sym,
                    "name": item["name"],
                    "unit": item.get("unit", ""),
                    "price": data.get("price"),
                    "change": data.get("change"),
                    "pct_change": data.get("pct_change"),
                }
            )

        self._set_cached("commodities", result)
        return result

    def fetch_currencies(self) -> list[dict]:
        """Fetch currency exchange rates."""
        cached = self._get_cached("currencies")
        if cached is not None:
            return cached

        currency_config = self._config.get("currencies", [])
        if not currency_config:
            return []

        symbols = [item["symbol"] for item in currency_config]
        raw = self._fetch_tickers(symbols)

        result = []
        for item in currency_config:
            sym = item["symbol"]
            data = raw.get(sym, {})
            result.append(
                {
                    "symbol": sym,
                    "name": item["name"],
                    "price": data.get("price"),
                    "change": data.get("change"),
                    "pct_change": data.get("pct_change"),
                }
            )

        self._set_cached("currencies", result)
        return result

    def fetch_global_snapshot(self) -> dict:
        """Fetch a complete global market snapshot (indices + commodities + currencies)."""
        cached = self._get_cached("snapshot")
        if cached is not None:
            return cached

        result = {
            "indices": self.fetch_global_indices(),
            "commodities": self.fetch_commodities(),
            "currencies": self.fetch_currencies(),
        }

        self._set_cached("snapshot", result)
        return result

    def fetch_bond_yields(self) -> dict[str, float]:
        """Fetch US Treasury bond yields.

        Uses yfinance tickers:
        - ^TNX: 10-Year Treasury yield
        - ^IRX: 13-Week Treasury yield (proxy for 2Y)

        Returns:
            Dict with ``US_10Y`` and ``US_2Y`` keys (values in percent),
            or empty dict on failure.
        """
        cached = self._get_cached("bond_yields")
        if cached is not None:
            return cached

        try:
            raw = self._fetch_tickers(["^TNX", "^IRX"])
            result: dict[str, float] = {}

            tnx = raw.get("^TNX", {})
            if tnx.get("price") is not None:
                result["US_10Y"] = round(float(tnx["price"]), 4)

            irx = raw.get("^IRX", {})
            if irx.get("price") is not None:
                result["US_2Y"] = round(float(irx["price"]), 4)

            self._set_cached("bond_yields", result)
            return result
        except Exception as e:
            logger.error("Failed to fetch bond yields: %s", e)
            return {}

    def fetch_index_history(self, symbol: str, period: str = "1mo") -> pd.DataFrame:
        """Fetch historical data for a global index.

        Args:
            symbol: yfinance symbol (e.g., "^GSPC").
            period: yfinance period string (e.g., "1mo", "3mo", "1y").

        Returns:
            DataFrame with OHLCV data.
        """
        yf = self._ensure_yfinance()
        self._rate_limit_wait()

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period)
            return df
        except Exception as e:
            logger.error("Failed to fetch history for %s: %s", symbol, e)
            return pd.DataFrame()

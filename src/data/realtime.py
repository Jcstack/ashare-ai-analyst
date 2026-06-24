"""Reliable real-time quote manager with multi-source fallback.

Provides rate-limited, cached real-time stock quotes using a prioritized
fallback chain: QMT -> Xueqiu -> Sina (hq.sinajs.cn) -> adata.

Per PRD v2.0 FR-RT001: Multi-source quote manager with fallback chain.
"""

import math
import re
import time
from typing import Any

import pandas as pd
import requests as _requests

from src.data.source_router import DataSourceRouter, SourceDomain
from src.utils.config import load_config
from src.utils.logger import get_logger

try:
    import adata as _adata

    _HAS_ADATA = True
except ImportError:
    _HAS_ADATA = False

logger = get_logger("data.realtime")

# Exchange prefix pattern (sh/sz/bj) — strip to get bare 6-digit code
_EXCHANGE_PREFIX_RE = re.compile(r"^(sh|sz|bj)", re.IGNORECASE)
# Exchange suffix pattern (.SZ/.SH/.BJ)
_EXCHANGE_SUFFIX_RE = re.compile(r"\.(SZ|SH|BJ)$", re.IGNORECASE)


def _normalize_symbol(sym: str) -> str:
    """Strip exchange prefix/suffix to get bare 6-digit code."""
    sym = _EXCHANGE_SUFFIX_RE.sub("", sym)
    return _EXCHANGE_PREFIX_RE.sub("", sym)


# hq.sinajs.cn response field indices (comma-separated in var hq_str_xxNNNNNN="...")
_SINA_HQ_FIELDS = {
    0: "name",
    1: "open",
    2: "prev_close",
    3: "price",
    4: "high",
    5: "low",
    8: "volume",
    9: "amount",
}


class RealtimeQuoteManager:
    """Manages real-time stock quotes with caching, rate limiting, and fallback.

    Features:
    - In-memory TTL cache (default 5s)
    - Token bucket rate limiter (2 req/sec for Sina)
    - Batch splitting (max 50 symbols per Sina call)
    - Fallback chain: QMT -> Sina -> Xueqiu -> adata

    Args:
        config_name: Config file name for loading settings.
        source_router: Optional pre-configured DataSourceRouter.
        qmt_adapter: Optional QmtDataAdapter for QMT data source.
    """

    def __init__(
        self,
        config_name: str = "stocks",
        source_router: DataSourceRouter | None = None,
        qmt_adapter: Any | None = None,
    ) -> None:
        load_config(config_name)  # validate config exists
        agent_config = load_config("agent")
        rt_cfg = agent_config.get("realtime", {})

        self._cache_ttl: float = float(rt_cfg.get("cache_ttl_seconds", 5))
        self._batch_size: int = rt_cfg.get("batch_size", 50)
        self._rate_limit: float = 1.0 / rt_cfg.get("rate_limit_per_second", 2)
        self._source_router = source_router or DataSourceRouter(config_name)
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._last_request_ts: float = 0.0
        self._xueqiu_session: _requests.Session | None = None
        self._qmt = qmt_adapter

    def get_quotes(self, symbols: list[str]) -> pd.DataFrame:
        """Get real-time quotes for multiple symbols.

        Uses cache when available, batches uncached symbols for API calls.

        Args:
            symbols: List of 6-digit stock codes.

        Returns:
            DataFrame with columns: symbol, name, price, change, pct_change,
            open, high, low, prev_close, volume, amount.
        """
        # Normalize: strip exchange prefixes (sh600010 → 600010)
        symbols = [_normalize_symbol(s) for s in symbols]

        now = time.time()
        cached_results: list[dict[str, Any]] = []
        uncached: list[str] = []
        stale_fallbacks: dict[str, dict[str, Any]] = {}

        for sym in symbols:
            if sym in self._cache:
                ts, data = self._cache[sym]
                if now - ts < self._cache_ttl:
                    cached_results.append(data)
                    continue
                else:
                    stale_fallbacks[sym] = data
            uncached.append(sym)

        if uncached:
            fresh = self._fetch_quotes_with_fallback(uncached)
            fetched_syms = {rec["symbol"] for rec in fresh}
            for rec in fresh:
                self._cache[rec["symbol"]] = (now, rec)
            cached_results.extend(fresh)

            # Stale fallback for symbols that failed to fetch fresh data
            for sym in uncached:
                if sym not in fetched_syms and sym in stale_fallbacks:
                    logger.warning("Using stale quote for %s", sym)
                    cached_results.append(stale_fallbacks[sym])

        if not cached_results:
            return pd.DataFrame(
                columns=[
                    "symbol",
                    "name",
                    "price",
                    "change",
                    "pct_change",
                    "open",
                    "high",
                    "low",
                    "prev_close",
                    "volume",
                    "amount",
                ]
            )

        return pd.DataFrame(cached_results)

    def get_single_quote(self, symbol: str) -> dict[str, Any]:
        """Get real-time quote for a single symbol.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict with quote fields.
        """
        symbol = _normalize_symbol(symbol)
        df = self.get_quotes([symbol])
        if df.empty:
            return {"symbol": symbol, "name": "", "price": None}
        return df.iloc[0].to_dict()

    def _fetch_quotes_with_fallback(
        self,
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch quotes using source priority with fallback.

        Priority: EastMoney push2 (fastest, most reliable) → QMT → Sina → Xueqiu → adata.
        """
        # EastMoney push2 — try first, outside source_router loop for speed
        try:
            result = self._fetch_eastmoney_batch(symbols)
            if result:
                self._source_router.record_success(SourceDomain.EASTMONEY_PUSH2)
                return result
        except Exception as exc:
            logger.warning("EastMoney push2 realtime failed: %s", exc)
            self._source_router.record_failure(SourceDomain.EASTMONEY_PUSH2)

        sources = self._source_router.get_realtime_sources()

        for source in sources:
            try:
                if source == SourceDomain.QMT:
                    if self._qmt is None or not self._qmt.is_available():
                        continue
                    result = self._qmt.get_realtime_quotes(symbols)
                elif source == SourceDomain.SINA:
                    result = self._fetch_sina_batch(symbols)
                elif source == SourceDomain.XUEQIU:
                    result = self._fetch_xueqiu_individual(symbols)
                elif source == SourceDomain.ADATA:
                    result = self._fetch_adata_batch(symbols)
                else:
                    continue

                if result:
                    self._source_router.record_success(source)
                    return result
            except Exception as exc:
                logger.warning("Source %s failed: %s", source.value, exc)
                self._source_router.record_failure(source)

        logger.warning(
            "All realtime sources failed for %d symbols",
            len(symbols),
        )
        return []

    def _fetch_eastmoney_batch(
        self,
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch quotes from EastMoney push2 via EastMoneyClient.

        Uses the batch quote API — single HTTP request for all symbols.
        Direct access (~0.1s), no AKShare monkey-patch dependency.
        """
        try:
            from src.data.eastmoney_client import get_eastmoney_client

            client = get_eastmoney_client()
        except Exception:
            return []

        return client.fetch_batch_quotes(symbols)

    def _ensure_sina_session(self) -> _requests.Session:
        """Lazily initialize a Sina hq.sinajs.cn session."""
        if not hasattr(self, "_sina_session") or self._sina_session is None:
            session = _requests.Session()
            session.trust_env = False  # bypass system proxy (Surge etc.)
            session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://finance.sina.com.cn",
                }
            )
            self._sina_session = session
        return self._sina_session

    def _fetch_sina_batch(
        self,
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch quotes from Sina hq.sinajs.cn (per-symbol, fast).

        Uses the lightweight hq.sinajs.cn API instead of the heavy
        vip.stock.finance.sina.com.cn full-market pull (which is blocked).
        """
        all_results: list[dict[str, Any]] = []
        batches = [
            symbols[i : i + self._batch_size]
            for i in range(0, len(symbols), self._batch_size)
        ]

        session = self._ensure_sina_session()

        for batch in batches:
            self._rate_limit_wait()

            # Build Sina symbol list: 6xxxxx→sh6xxxxx, others→sz.
            # Only accept 6-digit numeric A-share codes; this also prevents
            # any untrusted value from tainting the request URL (SSRF).
            sina_syms = []
            for sym in batch:
                if not re.fullmatch(r"\d{6}", sym):
                    continue
                prefix = "sh" if sym.startswith(("6", "9")) else "sz"
                sina_syms.append(f"{prefix}{sym}")

            if not sina_syms:
                continue

            url = f"https://hq.sinajs.cn/list={','.join(sina_syms)}"
            try:
                resp = session.get(url, timeout=(3, 8))
                resp.encoding = "gbk"
                if resp.status_code != 200:
                    logger.warning("Sina hq returned %d", resp.status_code)
                    return []
            except Exception as exc:
                logger.warning("Sina hq.sinajs.cn request failed: %s", exc)
                return []

            # Parse: var hq_str_sh600010="name,open,prev_close,price,...";
            for line in resp.text.strip().split("\n"):
                match = re.match(r'var hq_str_([a-z]{2})(\d{6})="(.+)";', line.strip())
                if not match:
                    continue
                sym = match.group(2)
                fields = match.group(3).split(",")
                if len(fields) < 10 or not fields[3]:
                    continue  # empty quote (suspended etc.)

                record: dict[str, Any] = {"symbol": sym}
                for idx, key in _SINA_HQ_FIELDS.items():
                    if idx < len(fields):
                        val = fields[idx]
                        if key == "name":
                            record[key] = val
                        else:
                            try:
                                record[key] = float(val) if val else None
                            except ValueError:
                                record[key] = None

                # Compute change and pct_change
                price = record.get("price")
                prev = record.get("prev_close")
                if price and prev and prev > 0:
                    record["change"] = round(price - prev, 4)
                    record["pct_change"] = round((price - prev) / prev * 100, 2)

                all_results.append(record)

        return all_results

    def _ensure_xueqiu_session(self) -> _requests.Session:
        """Lazily initialize a Xueqiu session with cookie."""
        if self._xueqiu_session is not None:
            return self._xueqiu_session

        session = _requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
        )
        # Bypass proxy for Xueqiu
        session.trust_env = False
        # Fetch landing page to obtain cookie
        try:
            session.get("https://xueqiu.com/", timeout=(3, 5))
        except Exception as exc:
            logger.debug("Xueqiu cookie prefetch failed: %s", exc)
        self._xueqiu_session = session
        return session

    def _fetch_xueqiu_individual(
        self,
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch quotes from Xueqiu using a shared session for TCP reuse."""
        session = self._ensure_xueqiu_session()

        xq_field_map = {
            "current": "price",
            "chg": "change",
            "percent": "pct_change",
            "open": "open",
            "high": "high",
            "low": "low",
            "last_close": "prev_close",
            "volume": "volume",
            "amount": "amount",
            "name": "name",
        }

        # Build comma-separated Xueqiu symbol list
        xq_symbols = []
        sym_lookup: dict[str, str] = {}
        for sym in symbols:
            xq_sym = f"SH{sym}" if sym.startswith(("6", "9")) else f"SZ{sym}"
            xq_symbols.append(xq_sym)
            sym_lookup[xq_sym] = sym

        self._rate_limit_wait()
        url = "https://stock.xueqiu.com/v5/stock/realtime/quotec.json"
        params = {"symbol": ",".join(xq_symbols)}

        try:
            resp = session.get(url, params=params, timeout=(3, 8))
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.warning("Xueqiu batch fetch failed: %s", exc)
            return []

        results: list[dict[str, Any]] = []
        for item in body.get("data", []):
            xq_sym = item.get("symbol", "")
            sym = sym_lookup.get(xq_sym)
            if sym is None:
                continue
            record: dict[str, Any] = {"symbol": sym}
            for xq_key, our_key in xq_field_map.items():
                if xq_key in item:
                    record[our_key] = item[xq_key]
            # Clean NaN values (same as Sina/adata paths)
            for k, v in record.items():
                if isinstance(v, float) and math.isnan(v):  # NaN check
                    record[k] = None
            results.append(record)

        return results

    def _fetch_adata_batch(
        self,
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch quotes from adata multi-source library (proxy-friendly fallback).

        adata uses Sina+Tencent fusion internally with its own retry logic,
        making it resilient when direct AKShare calls are blocked by proxy.

        Args:
            symbols: List of 6-digit stock codes.

        Returns:
            List of quote dicts.
        """
        if not _HAS_ADATA:
            logger.warning("adata not installed, skipping adata source")
            return []

        self._rate_limit_wait()
        df = _adata.stock.market.list_market_current(code_list=symbols)
        if df is None or df.empty:
            return []

        # Map adata columns to our standard schema
        col_map = {
            "stock_code": "symbol",
            "short_name": "name",
            "price": "price",
            "change": "change",
            "change_pct": "pct_change",
            "volume": "volume",
            "amount": "amount",
        }
        df = df.rename(columns=col_map)
        keep = [c for c in col_map.values() if c in df.columns]
        df = df[keep]

        records = df.to_dict(orient="records")
        for rec in records:
            for k, v in rec.items():
                if isinstance(v, float) and math.isnan(v):  # NaN check
                    rec[k] = None
        return records

    def _rate_limit_wait(self) -> None:
        """Enforce rate limiting between requests."""
        now = time.time()
        elapsed = now - self._last_request_ts
        if elapsed < self._rate_limit:
            time.sleep(self._rate_limit - elapsed)
        self._last_request_ts = time.time()

    def clear_cache(self) -> None:
        """Clear the in-memory quote cache."""
        self._cache.clear()

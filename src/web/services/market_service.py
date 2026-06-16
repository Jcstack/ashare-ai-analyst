"""Service layer for market data — indices, realtime quotes.

Encapsulates multi-source fallback logic for market indices and
realtime quote management, moving mutable cache state out of
route handlers.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import requests as _requests

from src.utils.logger import get_logger

logger = get_logger("web.market_service")


def _fetch_em_main_indices() -> pd.DataFrame:
    """Fetch 沪深重要指数 via 48.push2 (bypasses broken 33.push2 in AKShare).

    AKShare's ``stock_zh_index_spot_em("沪深重要指数")`` internally uses
    ``33.push2.eastmoney.com`` which is unreachable through the proxy gateway.
    This function calls the same API on ``48.push2`` which works correctly.

    The ``requests.get()`` call goes through the globally-patched
    ``requests.Session.request`` so akshare-proxy-patch injects auth
    headers/proxy automatically.
    """
    resp = _requests.get(
        "https://48.push2.eastmoney.com/api/qt/clist/get",
        params={
            "pn": "1",
            "pz": "100",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "dect": "1",
            "wbp2u": "|0|0|0|web",
            "fid": "",
            "fs": "b:MK0010",
            "fields": "f2,f3,f4,f12,f14",
        },
        timeout=8,
    )
    resp.raise_for_status()
    items = resp.json().get("data", {}).get("diff", [])
    if not items:
        return pd.DataFrame()
    df = pd.DataFrame(items)
    df.rename(
        columns={
            "f2": "最新价",
            "f3": "涨跌幅",
            "f4": "涨跌额",
            "f12": "代码",
            "f14": "名称",
        },
        inplace=True,
    )
    return df


# Target indices: exact name → prefixed code.
# Exact matching avoids false hits like "上证高新" for "上证指数".
_TARGET_INDICES: dict[str, str] = {
    "上证指数": "sh000001",
    "深证成指": "sz399001",
    "创业板指": "sz399006",
    "科创50": "sh000688",
}

# Display order (same as frontend fallbackNames)
_INDEX_DISPLAY_ORDER = ["上证指数", "深证成指", "创业板指", "科创50"]

# Known index codes for Xueqiu fallback (XQ symbol -> (display_name, prefixed_code))
# NOTE: 科创50 = 000688 (not 000680 which is 科创综指)
_XQ_INDEX_MAP = {
    "SH000001": ("上证指数", "sh000001"),
    "SZ399001": ("深证成指", "sz399001"),
    "SZ399006": ("创业板指", "sz399006"),
    "SH000688": ("科创50", "sh000688"),
}

# Seed values ensure we never return empty on cold start (FR-DR002)
_SEED_INDICES: list[dict] = [
    {"name": n, "code": _TARGET_INDICES[n], "price": 0, "change": 0, "pct_change": 0}
    for n in _INDEX_DISPLAY_ORDER
]


class MarketService:
    """Encapsulates market index and realtime quote logic.

    Holds in-memory cache for last-good indices and delegates
    to RealtimeQuoteManager for quote fetching.
    """

    def __init__(self, quote_manager: Any = None) -> None:
        self._quote_manager = quote_manager
        self._last_good_indices: list[dict] = []

    def get_market_indices(self) -> list[dict]:
        """Get major A-share market indices with multi-source fallback.

        Source chain: EastMoney (48.push2) → Sina → Xueqiu → cached → seed.
        Ensures indices are never empty on cold start (FR-DR002).
        """
        from src.data.eastmoney_proxy import em_api_call

        result: list[dict] = []

        # Source 1: EastMoney 48.push2 (preferred — proxy-patched, ~1s)
        try:
            df = em_api_call(_fetch_em_main_indices)
            if df is not None and not df.empty:
                result = self._parse_em_indices(df)
            if result:
                logger.debug("Indices fetched from EastMoney: %d items", len(result))
        except Exception as exc:
            logger.warning("EastMoney index source failed: %s", exc)

        # Source 2: Sina fallback (wrapped in em_api_call for graceful error handling)
        if not result:
            try:
                import akshare as ak

                df = em_api_call(ak.stock_zh_index_spot_sina)
                if df is not None and not df.empty:
                    result = self._parse_sina_indices(df)
                if result:
                    logger.debug(
                        "Indices fetched from Sina fallback: %d items", len(result)
                    )
            except Exception as exc:
                logger.warning("Sina index source also failed: %s", exc)

        # Source 3: Xueqiu batch API (uses same session as realtime quotes)
        if not result and self._quote_manager is not None:
            try:
                session = self._quote_manager._ensure_xueqiu_session()
                url = "https://stock.xueqiu.com/v5/stock/realtime/quotec.json"
                params = {"symbol": ",".join(_XQ_INDEX_MAP.keys())}
                resp = session.get(url, params=params, timeout=(3, 5))
                resp.raise_for_status()
                body = resp.json()
                for item in body.get("data", []):
                    xq_sym = item.get("symbol", "")
                    if xq_sym in _XQ_INDEX_MAP:
                        display_name, code = _XQ_INDEX_MAP[xq_sym]
                        result.append(
                            {
                                "name": display_name,
                                "code": code,
                                "price": float(item.get("current", 0)),
                                "change": float(item.get("chg", 0)),
                                "pct_change": float(item.get("percent", 0)),
                            }
                        )
                if result:
                    logger.debug(
                        "Indices fetched from Xueqiu fallback: %d items", len(result)
                    )
            except Exception as exc:
                logger.warning("Xueqiu index source also failed: %s", exc)

        # Fill partial results from cache
        if result and len(result) < len(_TARGET_INDICES) and self._last_good_indices:
            result_names = {r["name"] for r in result}
            for cached in self._last_good_indices:
                if cached["name"] not in result_names:
                    result.append(cached)

        # Update cache on success
        if result:
            self._last_good_indices = result
            return result

        # Fallback: cached data from a previous successful fetch
        if self._last_good_indices:
            logger.info(
                "Returning cached indices (%d items)", len(self._last_good_indices)
            )
            return self._last_good_indices

        # Last resort: seed values (price=0 signals stale to frontend)
        logger.warning("All index sources failed, returning seed values")
        return list(_SEED_INDICES)

    def get_realtime_quotes(self, symbols: list[str]) -> list[dict]:
        """Fetch realtime quotes via RealtimeQuoteManager.

        Args:
            symbols: List of 6-digit stock codes.

        Returns:
            List of quote dicts, or empty list on failure.
        """
        if not self._quote_manager:
            return []

        try:
            df = self._quote_manager.get_quotes(symbols)
            from src.web.utils import sanitize_records

            return sanitize_records(df.to_dict(orient="records"))
        except Exception:
            logger.warning("Realtime quotes unavailable (all sources failed)")
            return []

    @staticmethod
    def _parse_index_df(df: pd.DataFrame, source: str) -> list[dict]:
        """Parse target indices from an AKShare index DataFrame.

        Uses exact name matching against _TARGET_INDICES to avoid
        false positives (e.g. "上证高新" for "上证指数").

        Works for both Sina and EM sources — column names are the same.
        """
        required_cols = {"名称", "最新价", "涨跌额", "涨跌幅"}
        missing = required_cols - set(df.columns)
        if missing:
            logger.warning(
                "%s index DataFrame missing columns %s. Available: %s",
                source,
                missing,
                list(df.columns),
            )
            return []

        # Build name→row lookup for our targets only
        name_set = set(_TARGET_INDICES.keys())
        matched = df[df["名称"].isin(name_set)]

        result: list[dict] = []
        seen: set[str] = set()
        # Iterate in display order for stable output
        for name in _INDEX_DISPLAY_ORDER:
            rows = matched[matched["名称"] == name]
            if rows.empty:
                continue
            row = rows.iloc[0]
            result.append(
                {
                    "name": name,
                    "code": _TARGET_INDICES[name],
                    "price": float(row["最新价"]),
                    "change": float(row["涨跌额"]),
                    "pct_change": float(row["涨跌幅"]),
                }
            )
            seen.add(name)

        if seen and seen != name_set:
            logger.debug(
                "%s: found %d/%d target indices (missing: %s)",
                source,
                len(seen),
                len(name_set),
                name_set - seen,
            )

        return result

    # Keep backward-compatible method names for existing callers
    @staticmethod
    def _parse_sina_indices(df: pd.DataFrame) -> list[dict]:
        """Parse indices from ak.stock_zh_index_spot_sina result."""
        return MarketService._parse_index_df(df, "Sina")

    @staticmethod
    def _parse_em_indices(df: pd.DataFrame) -> list[dict]:
        """Parse indices from ak.stock_zh_index_spot_em result."""
        return MarketService._parse_index_df(df, "EastMoney")

"""Sector-level capital flow data fetcher for A-share market.

Fetches industry (申万一级) and concept board fund flow rankings
using AKShare sector flow APIs.

Per PRD v26.0 FR-CF002: Sector capital flow data collection service.
"""

from __future__ import annotations

import time
from typing import Any

import akshare as ak
import pandas as pd

from src.data.fetcher import _bypass_proxy
from src.utils.logger import get_logger

logger = get_logger("data.sector_flow")

# Chinese → English column mapping for sector flow ranking
# Note: AKShare prefixes columns with the period indicator (今日/3日/5日/10日).
# We strip the prefix before applying this map — see _strip_period_prefix().
_SECTOR_FLOW_COLUMN_MAP: dict[str, str] = {
    "名称": "sector_name",
    "行业": "sector_name",
    "概念": "sector_name",
    "涨跌幅": "change_pct",
    "主力净流入-净额": "net_inflow",
    "主力净流入-净占比": "main_net_inflow",
    "超大单净流入-净额": "huge_inflow",
    "大单净流入-净额": "large_inflow",
    "中单净流入-净额": "mid_inflow",
    "小单净流入-净额": "small_inflow",
    "换手率": "turnover",
}

# Period mapping: API parameter → AKShare indicator
_PERIOD_MAP: dict[str, str] = {
    "today": "今日",
    "3d": "3日",
    "5d": "5日",
    "10d": "10日",
}

# Period prefixes that AKShare prepends to column names
_PERIOD_PREFIXES: tuple[str, ...] = ("今日", "3日", "5日", "10日")


def _strip_period_prefix(columns: list[str]) -> dict[str, str]:
    """Build a rename map that strips period prefixes from column names.

    AKShare returns columns like '今日涨跌幅', '3日主力净流入-净额', etc.
    This strips the prefix so our standard column map can apply.
    """
    rename: dict[str, str] = {}
    for col in columns:
        for prefix in _PERIOD_PREFIXES:
            if col.startswith(prefix):
                rename[col] = col[len(prefix) :]
                break
    return rename


class SectorFlowFetcher:
    """Fetches sector-level capital flow data.

    Collects industry and concept board fund flow rankings,
    complementing the macro-level data in MacroFlowFetcher.
    """

    def __init__(self) -> None:
        self.logger = logger
        self._last_request_ts: float = 0.0
        # In-memory cache: key → (timestamp, value)
        self._cache: dict[str, tuple[float, Any]] = {}

    def _polite_sleep(self, interval: float = 0.5) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request_ts = time.monotonic()

    def _get_mem_cache(self, key: str, ttl: int = 600) -> Any | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.monotonic() - ts < ttl:
                return val
        return None

    def _set_mem_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.monotonic(), val)

    # ------------------------------------------------------------------
    # Industry sector flow (申万一级行业)
    # ------------------------------------------------------------------

    def fetch_industry_flow(self, period: str = "today") -> pd.DataFrame:
        """Fetch industry (申万一级) sector fund flow ranking.

        Uses ``ak.stock_sector_fund_flow_rank(indicator=...)`` to retrieve
        industry-level capital flow data.

        Args:
            period: One of "today", "3d", "5d", "10d".

        Returns:
            DataFrame with columns: sector_name, change_pct, net_inflow,
            main_net_inflow, huge_inflow, large_inflow, mid_inflow,
            small_inflow, turnover.
        """
        cache_key = f"industry_flow_{period}"
        cached = self._get_mem_cache(cache_key, ttl=600)
        if cached is not None:
            return cached

        indicator = _PERIOD_MAP.get(period, "今日")
        self.logger.info("Fetching industry sector flow (indicator=%s)", indicator)

        try:
            from src.data.eastmoney_proxy import em_api_call

            self._polite_sleep()
            raw = em_api_call(ak.stock_sector_fund_flow_rank, indicator=indicator)

            if raw is None or raw.empty:
                self.logger.warning("Industry sector flow returned empty data")
                return pd.DataFrame()

            # Strip period prefix (今日/3日/5日/10日) then apply standard map
            df = raw.rename(columns=_strip_period_prefix(list(raw.columns)))
            rename_map = {
                k: v for k, v in _SECTOR_FLOW_COLUMN_MAP.items() if k in df.columns
            }
            df = df.rename(columns=rename_map)

            # Convert numeric columns, coerce errors to NaN
            numeric_cols = [
                "change_pct",
                "net_inflow",
                "main_net_inflow",
                "huge_inflow",
                "large_inflow",
                "mid_inflow",
                "small_inflow",
                "turnover",
            ]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

            self._set_mem_cache(cache_key, df)
            return df
        except Exception as exc:
            self.logger.warning("Industry sector flow fetch failed: %s", exc)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Concept board flow (概念板块)
    # ------------------------------------------------------------------

    def fetch_concept_flow(self, period: str = "today") -> pd.DataFrame:
        """Fetch concept board fund flow ranking.

        Uses ``ak.stock_sector_fund_flow_rank(sector_type='概念资金流')``
        to retrieve concept-level capital flow data.

        Args:
            period: One of "today", "3d", "5d", "10d".

        Returns:
            DataFrame with columns: sector_name, change_pct, net_inflow,
            main_net_inflow, huge_inflow, large_inflow, mid_inflow,
            small_inflow, turnover.
        """
        cache_key = f"concept_flow_{period}"
        cached = self._get_mem_cache(cache_key, ttl=600)
        if cached is not None:
            return cached

        indicator = _PERIOD_MAP.get(period, "今日")
        self.logger.info("Fetching concept board flow (indicator=%s)", indicator)

        try:
            from src.data.eastmoney_proxy import em_api_call

            self._polite_sleep()
            raw = em_api_call(
                ak.stock_sector_fund_flow_rank,
                indicator=indicator,
                sector_type="概念资金流",
            )

            if raw is None or raw.empty:
                self.logger.warning("Concept board flow returned empty data")
                return pd.DataFrame()

            # Strip period prefix (今日/3日/5日/10日) then apply standard map
            df = raw.rename(columns=_strip_period_prefix(list(raw.columns)))
            rename_map = {
                k: v for k, v in _SECTOR_FLOW_COLUMN_MAP.items() if k in df.columns
            }
            df = df.rename(columns=rename_map)

            # Convert numeric columns, coerce errors to NaN
            numeric_cols = [
                "change_pct",
                "net_inflow",
                "main_net_inflow",
                "huge_inflow",
                "large_inflow",
                "mid_inflow",
                "small_inflow",
                "turnover",
            ]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

            self._set_mem_cache(cache_key, df)
            return df
        except Exception as exc:
            self.logger.warning("Concept board flow fetch failed: %s", exc)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Heatmap data
    # ------------------------------------------------------------------

    def fetch_heatmap_data(self) -> list[dict]:
        """Combine industry flow into heatmap-friendly format.

        Fetches today's industry flow and normalises net_inflow to a
        [-1, 1] range for colour mapping.

        Returns:
            List of dicts, each with: name, net_inflow, change_pct,
            turnover, color_value.
        """
        cache_key = "heatmap_data"
        cached = self._get_mem_cache(cache_key, ttl=600)
        if cached is not None:
            return cached

        df = self.fetch_industry_flow(period="today")
        if df.empty:
            return []

        items: list[dict] = []
        # Compute max absolute net_inflow for normalisation
        net_col = "net_inflow"
        if net_col not in df.columns:
            return []

        max_abs = df[net_col].abs().max()
        if max_abs == 0 or pd.isna(max_abs):
            max_abs = 1.0  # avoid division by zero

        for _, row in df.iterrows():
            net = float(row.get(net_col, 0))
            item = {
                "name": str(row.get("sector_name", "")),
                "net_inflow": round(net, 2),
                "change_pct": round(float(row.get("change_pct", 0)), 2),
                "turnover": round(float(row.get("turnover", 0)), 2),
                "color_value": round(net / max_abs, 4),
            }
            items.append(item)

        self._set_mem_cache(cache_key, items)
        return items

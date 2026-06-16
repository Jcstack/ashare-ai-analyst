"""Macro-level capital flow data fetcher for A-share market.

Fetches southbound capital (港股通), ETF net flow, and aggregates with
existing northbound/margin data from StockDataFetcher.

Per PRD v26.0 FR-CF001: Macro capital flow data collection service.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import math

import akshare as ak
import pandas as pd

from src.data.fetcher import DataCollectionError, StockDataFetcher, _bypass_proxy
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("data.macro_flow")


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert value to float, returning *default* for None/NaN/errors."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


# Key broad-based ETFs for tracking institutional flow
_TRACKED_ETFS: list[dict[str, str]] = [
    {"symbol": "510300", "name": "沪深300ETF"},
    {"symbol": "510500", "name": "中证500ETF"},
    {"symbol": "159915", "name": "创业板ETF"},
    {"symbol": "588000", "name": "科创50ETF"},
    {"symbol": "510050", "name": "上证50ETF"},
]


_NORTHBOUND_SUSPENSION_NOTICE = (
    "自2024年8月起，交易所不再每日披露北向资金明细数据。"
    "北向资金流向仅可获取汇总快照，历史趋势数据不可用。"
    "请勿过度依赖北向资金指标做投资决策。"
)


@dataclass
class MacroFlowSnapshot:
    """Single-day macro capital flow snapshot."""

    date: str = ""
    northbound_net: float = 0.0
    southbound_net: float = 0.0
    margin_balance: float = 0.0
    margin_balance_change: float = 0.0
    etf_net_flow: float = 0.0
    environment_score: float = 0.0
    signal: str = "neutral"
    warnings: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class MacroFlowFetcher:
    """Fetches macro-level capital flow data for A-share market.

    Collects southbound capital and ETF net flow data, complementing
    the existing northbound/margin data in StockDataFetcher.
    """

    def __init__(self) -> None:
        self.logger = logger
        try:
            self._config: dict[str, Any] = load_config("capital_flow")
        except Exception:
            self._config = {}
        self._fetcher = StockDataFetcher()
        self._last_request_ts: float = 0.0
        # In-memory cache
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
    # HSGT summary (today's snapshot from stock_hsgt_fund_flow_summary_em)
    # ------------------------------------------------------------------

    def _fetch_hsgt_summary(self, direction: str = "北向") -> pd.DataFrame:
        """Fetch today's HSGT summary via stock_hsgt_fund_flow_summary_em.

        Args:
            direction: "北向" for northbound or "南向" for southbound.

        Returns:
            DataFrame with columns: date, net_buy_amount.
        """
        try:
            from src.data.eastmoney_proxy import em_api_call

            self._polite_sleep()
            raw = em_api_call(ak.stock_hsgt_fund_flow_summary_em)
            if raw is None or raw.empty:
                return pd.DataFrame()

            # Filter rows by direction (资金方向 column)
            if "资金方向" in raw.columns:
                filtered = raw[raw["资金方向"] == direction]
            else:
                return pd.DataFrame()

            if filtered.empty:
                return pd.DataFrame()

            # Sum net_buy across channels (沪股通+深股通 for 北向, 港股通沪+港股通深 for 南向)
            total_net = pd.to_numeric(filtered["成交净买额"], errors="coerce").sum()
            date_str = str(filtered.iloc[0].get("交易日", ""))

            return pd.DataFrame([{"date": date_str, "net_buy_amount": total_net}])
        except Exception as exc:
            self.logger.warning("HSGT summary fetch (%s) failed: %s", direction, exc)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Southbound capital (南向资金 / 港股通)
    # ------------------------------------------------------------------

    def fetch_southbound(self, days: int = 60) -> pd.DataFrame:
        """Fetch southbound (南向资金) capital flow history.

        Uses ``ak.stock_hsgt_hist_em(symbol="南向")`` for aggregate
        southbound flow, or individual channels as fallback.

        Returns:
            DataFrame with columns: date, net_buy_amount (亿元).
        """
        cache_key = f"southbound_{days}"
        cached = self._get_mem_cache(cache_key, ttl=3600)
        if cached is not None:
            return cached

        self.logger.info("Fetching southbound capital flow data")
        df = pd.DataFrame()

        try:
            from src.data.eastmoney_proxy import em_api_call

            self._polite_sleep()
            raw = em_api_call(ak.stock_hsgt_hist_em, symbol="南向资金")
            if raw is not None and not raw.empty:
                # 当日资金流入 became NaN after Aug 2024; 当日成交净买额 has data
                col_map = {
                    "日期": "date",
                    "当日成交净买额": "net_buy_amount",
                    "当日余额": "balance",
                    "历史累计净买额": "cumulative",
                }
                df = raw.rename(
                    columns={k: v for k, v in col_map.items() if k in raw.columns}
                )
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                # Drop rows with NaN net_buy_amount
                if "net_buy_amount" in df.columns:
                    df = df.dropna(subset=["net_buy_amount"])
                if not df.empty:
                    df = df.tail(days)
        except Exception as exc:
            self.logger.warning("Southbound fetch failed: %s", exc)

        # Fallback: today's summary if hist is empty
        if df.empty:
            df = self._fetch_hsgt_summary(direction="南向")

        self._set_mem_cache(cache_key, df)
        return df

    # ------------------------------------------------------------------
    # ETF net flow (ETF 净申购)
    # ------------------------------------------------------------------

    def fetch_etf_net_flow(self, days: int = 60) -> pd.DataFrame:
        """Fetch ETF net flow data for major broad-based ETFs.

        Tracks shares outstanding changes as a proxy for net subscriptions.

        Returns:
            DataFrame with columns: date, etf_net_flow (亿元 estimated).
        """
        cache_key = f"etf_net_flow_{days}"
        cached = self._get_mem_cache(cache_key, ttl=3600)
        if cached is not None:
            return cached

        self.logger.info("Fetching ETF net flow data")
        all_flows: list[pd.DataFrame] = []

        for etf in _TRACKED_ETFS:
            try:
                from src.data.eastmoney_proxy import em_api_call

                self._polite_sleep()
                raw = em_api_call(
                    ak.fund_etf_hist_em,
                    symbol=etf["symbol"],
                    period="daily",
                    adjust="",
                )
                if raw is None or raw.empty:
                    continue

                col_map = {
                    "日期": "date",
                    "收盘": "close",
                    "成交额": "amount",
                }
                edf = raw.rename(
                    columns={k: v for k, v in col_map.items() if k in raw.columns}
                )
                if "date" in edf.columns and "amount" in edf.columns:
                    edf["date"] = pd.to_datetime(edf["date"]).dt.strftime("%Y-%m-%d")
                    edf = edf[["date", "amount"]].tail(days)
                    edf = edf.rename(columns={"amount": f"amount_{etf['symbol']}"})
                    all_flows.append(edf)
            except Exception as exc:
                self.logger.warning("ETF %s fetch failed: %s", etf["symbol"], exc)

        if not all_flows:
            result = pd.DataFrame(columns=["date", "etf_net_flow"])
            self._set_mem_cache(cache_key, result)
            return result

        merged = all_flows[0]
        for extra in all_flows[1:]:
            merged = merged.merge(extra, on="date", how="outer")

        amount_cols = [c for c in merged.columns if c.startswith("amount_")]
        merged["etf_net_flow"] = merged[amount_cols].sum(axis=1) / 1e8  # 转亿元
        result = merged[["date", "etf_net_flow"]].dropna(subset=["date"]).copy()
        result = result.sort_values("date").reset_index(drop=True)

        self._set_mem_cache(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Aggregated macro snapshot
    # ------------------------------------------------------------------

    def fetch_northbound(self, days: int = 60) -> pd.DataFrame:
        """Fetch northbound (北向资金) capital flow.

        Tries StockDataFetcher first (parquet-cached history), then filters
        out rows with NaN net_buy_amount. If no recent data remains (> 30 days
        old), falls back to stock_hsgt_fund_flow_summary_em for today's snapshot.

        Note: China stopped reporting daily northbound data after Aug 2024.
        The summary API may return 0 for northbound but provides today's date.
        """
        try:
            df = self._fetcher.fetch_northbound()
            if df is not None and not df.empty:
                # Drop rows where net_buy_amount is NaN (post-Aug-2024 data gap)
                if "net_buy_amount" in df.columns:
                    df = df.dropna(subset=["net_buy_amount"])
                if not df.empty:
                    # Check if data is recent (within 30 days)
                    if "date" in df.columns:
                        last_date = pd.to_datetime(df["date"].iloc[-1])
                        age_days = (datetime.now() - last_date).days
                        if age_days <= 30:
                            return df.tail(days)
                        self.logger.info(
                            "Northbound hist data stale (last=%s, %d days old)",
                            last_date.strftime("%Y-%m-%d"),
                            age_days,
                        )
        except (DataCollectionError, Exception) as exc:
            self.logger.warning("Northbound hist fetch failed: %s", exc)

        # Fallback: today's summary (stock_hsgt_fund_flow_summary_em)
        return self._fetch_hsgt_summary(direction="北向")

    def fetch_margin(self, days: int = 60) -> pd.DataFrame:
        """Proxy to StockDataFetcher.fetch_margin_data with slicing.

        Converts margin_balance from raw yuan to 亿元 for consistency
        with northbound/southbound (also in 亿元).
        """
        try:
            df = self._fetcher.fetch_margin_data()
            if df is not None and not df.empty:
                # Convert yuan → 亿元 for consistency with other channels
                if "margin_balance" in df.columns:
                    df["margin_balance"] = (
                        pd.to_numeric(df["margin_balance"], errors="coerce").fillna(0)
                        / 1e8
                    )
                return df.tail(days)
        except (DataCollectionError, Exception) as exc:
            self.logger.warning("Margin fetch failed: %s", exc)
        return pd.DataFrame()

    def get_latest_snapshot(self) -> MacroFlowSnapshot:
        """Build a MacroFlowSnapshot from the latest available data.

        Returns:
            MacroFlowSnapshot with all 4 channels populated (best-effort).
        """
        cache_key = "macro_snapshot"
        cached = self._get_mem_cache(cache_key, ttl=300)
        if cached is not None:
            return cached

        snapshot = MacroFlowSnapshot()
        dates_seen: list[str] = []

        # Northbound
        nb = self.fetch_northbound(days=5)
        if not nb.empty and "net_buy_amount" in nb.columns:
            latest = nb.iloc[-1]
            snapshot.northbound_net = _safe_float(latest.get("net_buy_amount"))
            dt = str(latest.get("date", ""))
            if dt:
                dates_seen.append(dt)

        # Southbound
        sb = self.fetch_southbound(days=5)
        if not sb.empty and "net_buy_amount" in sb.columns:
            latest = sb.iloc[-1]
            snapshot.southbound_net = _safe_float(latest.get("net_buy_amount"))
            dt = str(latest.get("date", ""))
            if dt:
                dates_seen.append(dt)

        # Margin
        mg = self.fetch_margin(days=5)
        if not mg.empty and "margin_balance" in mg.columns:
            snapshot.margin_balance = _safe_float(mg.iloc[-1].get("margin_balance"))
            if len(mg) >= 2:
                prev = _safe_float(mg.iloc[-2].get("margin_balance"))
                snapshot.margin_balance_change = snapshot.margin_balance - prev

        # ETF
        etf = self.fetch_etf_net_flow(days=5)
        if not etf.empty and "etf_net_flow" in etf.columns:
            snapshot.etf_net_flow = _safe_float(etf.iloc[-1].get("etf_net_flow"))
            dt = str(etf.iloc[-1].get("date", ""))
            if dt:
                dates_seen.append(dt)

        # Use the most recent date from all channels
        snapshot.date = max(dates_seen) if dates_seen else ""
        snapshot.updated_at = datetime.now().isoformat()

        # Add northbound data suspension warning
        # Since Aug 2024, daily northbound disclosure stopped.
        # If northbound_net is 0 or data is from summary API, warn.
        nb_is_limited = nb.empty or len(nb) <= 1
        if nb_is_limited:
            snapshot.warnings.append(_NORTHBOUND_SUSPENSION_NOTICE)

        self._set_mem_cache(cache_key, snapshot)
        return snapshot

    def get_macro_history(self, days: int = 30) -> list[MacroFlowSnapshot]:
        """Build daily MacroFlowSnapshot list for the last N days.

        Merges northbound, southbound, margin, and ETF data by date.
        """
        cache_key = f"macro_history_{days}"
        cached = self._get_mem_cache(cache_key, ttl=600)
        if cached is not None:
            return cached

        nb = self.fetch_northbound(days=days)
        sb = self.fetch_southbound(days=days)
        mg = self.fetch_margin(days=days)
        etf = self.fetch_etf_net_flow(days=days)

        # Collect all unique dates
        dates: set[str] = set()
        for df in [nb, sb, mg, etf]:
            if not df.empty and "date" in df.columns:
                dates.update(df["date"].astype(str).tolist())

        if not dates:
            return []

        # Build lookup dicts
        def _to_dict(df: pd.DataFrame, key_col: str, val_col: str) -> dict[str, float]:
            if df.empty or key_col not in df.columns or val_col not in df.columns:
                return {}
            return dict(zip(df[key_col].astype(str), df[val_col].astype(float)))

        nb_map = _to_dict(nb, "date", "net_buy_amount")
        sb_map = _to_dict(sb, "date", "net_buy_amount")
        mg_map = _to_dict(mg, "date", "margin_balance")
        etf_map = _to_dict(etf, "date", "etf_net_flow")

        # Build margin change map
        mg_sorted = sorted(mg_map.items()) if mg_map else []
        mg_change: dict[str, float] = {}
        for i, (dt, bal) in enumerate(mg_sorted):
            prev_bal = mg_sorted[i - 1][1] if i > 0 else bal
            mg_change[dt] = bal - prev_bal

        snapshots: list[MacroFlowSnapshot] = []
        for dt in sorted(dates):
            s = MacroFlowSnapshot(
                date=dt,
                northbound_net=nb_map.get(dt, 0.0),
                southbound_net=sb_map.get(dt, 0.0),
                margin_balance=mg_map.get(dt, 0.0),
                margin_balance_change=mg_change.get(dt, 0.0),
                etf_net_flow=etf_map.get(dt, 0.0),
            )
            snapshots.append(s)

        self._set_mem_cache(cache_key, snapshots)
        return snapshots

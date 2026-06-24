"""Real-time sector capital flow rotation tracker.

Tracks intraday sector-level capital flow to identify rotation patterns:
which sectors are receiving/losing capital, momentum shifts, and
money flowing from one sector to another.

Complements the daily SectorFlowFetcher with higher-frequency snapshots
suitable for intraday trading decisions.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("data.intraday_sector_flow")

# Column mapping for AKShare sector flow ranking (Chinese → English)
_SECTOR_FLOW_COLUMN_MAP: dict[str, str] = {
    "名称": "sector",
    "行业": "sector",
    "概念": "sector",
    "涨跌幅": "change_pct",
    "主力净流入-净额": "net_inflow",
    "超大单净流入-净额": "huge_inflow",
    "大单净流入-净额": "large_inflow",
    "主力净流入-净占比": "main_net_ratio",
    "领涨股票": "leader_stock",
    "最新价": "leader_price",
    "涨跌幅.1": "leader_change",
}

# Period prefixes that AKShare prepends to column names
_PERIOD_PREFIXES: tuple[str, ...] = ("今日", "5日", "10日")


def _strip_period_prefix(columns: list[str]) -> dict[str, str]:
    """Build a rename map that strips period prefixes from column names."""
    rename: dict[str, str] = {}
    for col in columns:
        for prefix in _PERIOD_PREFIXES:
            if col.startswith(prefix):
                rename[col] = col[len(prefix) :]
                break
    return rename


class IntradaySectorFlowTracker:
    """Track real-time sector capital flow rotation.

    Uses AKShare sector flow data to identify:
    - Which sectors are receiving/losing capital NOW
    - Sector momentum changes (acceleration/deceleration)
    - Rotation patterns (money leaving sector A → entering sector B)

    Args:
        redis_client: Optional Redis client for caching and snapshot
            history. If None, uses in-memory storage only.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._cache_ttl: int = 120  # seconds
        self._last_request_ts: float = 0.0
        # In-memory cache: key → (timestamp, value)
        self._mem_cache: dict[str, tuple[float, Any]] = {}
        # Previous snapshot for rotation detection
        self._prev_snapshot: list[dict] | None = None

    def _polite_sleep(self, interval: float = 0.5) -> None:
        """Rate limiting between upstream requests."""
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request_ts = time.monotonic()

    def fetch_current_flow(self) -> list[dict]:
        """Fetch current sector flow rankings.

        Returns list sorted by net_inflow descending:
        [
            {
                "sector": str,           # sector name
                "net_inflow": float,     # in 亿元
                "change_pct": float,     # sector index change %
                "leader_stock": str,     # 领涨股
                "leader_change": float,  # leader stock change %
                "rank_change": int,      # rank change vs last snapshot
            },
            ...
        ]
        """
        # Check cache
        cached = self._get_cache("current_flow")
        if cached is not None:
            return cached

        try:
            import akshare as ak

            from src.data.eastmoney_proxy import em_api_call
        except ImportError:
            logger.warning("akshare not available for sector flow")
            return []

        try:
            self._polite_sleep()
            raw = em_api_call(
                ak.stock_sector_fund_flow_rank,
                indicator="今日",
            )

            if raw is None or raw.empty:
                logger.debug("Sector flow ranking returned empty data")
                return []

            # Strip period prefix then apply column map
            df = raw.rename(columns=_strip_period_prefix(list(raw.columns)))
            rename_map = {
                k: v for k, v in _SECTOR_FLOW_COLUMN_MAP.items() if k in df.columns
            }
            df = df.rename(columns=rename_map)

            # Convert numeric columns
            for col in [
                "net_inflow",
                "change_pct",
                "huge_inflow",
                "large_inflow",
                "main_net_ratio",
                "leader_change",
            ]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

            # Convert net_inflow from 元 to 亿元 if values look like raw yuan
            if "net_inflow" in df.columns:
                max_val = df["net_inflow"].abs().max()
                if max_val > 1e8:
                    df["net_inflow"] = df["net_inflow"] / 1e8

            # Sort by net_inflow descending
            if "net_inflow" in df.columns:
                df = df.sort_values("net_inflow", ascending=False)

            # Build result list with rank info
            current_flow: list[dict] = []
            prev_ranks = self._get_prev_ranks()

            for rank, (_, row) in enumerate(df.iterrows(), 1):
                sector = str(row.get("sector", ""))
                if not sector:
                    continue

                prev_rank = prev_ranks.get(sector, rank)
                rank_change = prev_rank - rank  # positive = improved

                item = {
                    "sector": sector,
                    "net_inflow": round(float(row.get("net_inflow", 0)), 4),
                    "change_pct": round(float(row.get("change_pct", 0)), 2),
                    "leader_stock": str(row.get("leader_stock", "")),
                    "leader_change": round(float(row.get("leader_change", 0)), 2),
                    "rank_change": rank_change,
                }
                current_flow.append(item)

            # Store current as previous for next comparison
            self._store_snapshot(current_flow)
            self._set_cache("current_flow", current_flow)

            return current_flow

        except Exception as exc:
            logger.warning("Sector flow fetch failed: %s", exc)
            return []

    def detect_rotation(self) -> dict:
        """Detect sector rotation patterns by comparing current vs previous snapshot.

        A rotation is detected when sectors significantly change rank position,
        indicating capital flowing from declining sectors to rising ones.

        Returns:
            Dict with keys:
            - rotating_in: sectors gaining capital/rank
            - rotating_out: sectors losing capital/rank
            - timestamp: when detection was performed
        """
        current = self.fetch_current_flow()

        result: dict[str, Any] = {
            "rotating_in": [],
            "rotating_out": [],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        if not current:
            return result

        # Threshold for significant rotation: rank change >= 5 positions
        for item in current:
            rank_change = item.get("rank_change", 0)
            net_inflow = item.get("net_inflow", 0)

            if rank_change >= 5 and net_inflow > 0:
                result["rotating_in"].append(
                    {
                        "sector": item["sector"],
                        "net_inflow": item["net_inflow"],
                        "rank_improvement": rank_change,
                    }
                )
            elif rank_change <= -5 and net_inflow < 0:
                result["rotating_out"].append(
                    {
                        "sector": item["sector"],
                        "net_outflow": abs(item["net_inflow"]),
                        "rank_decline": abs(rank_change),
                    }
                )

        # Sort by magnitude
        result["rotating_in"].sort(key=lambda x: x["rank_improvement"], reverse=True)
        result["rotating_out"].sort(key=lambda x: x["rank_decline"], reverse=True)

        if result["rotating_in"] or result["rotating_out"]:
            logger.info(
                "Rotation detected: %d sectors in, %d sectors out",
                len(result["rotating_in"]),
                len(result["rotating_out"]),
            )

        return result

    def get_sector_momentum(self, sector: str) -> dict:
        """Get momentum metrics for a specific sector.

        Compares current flow against historical snapshots to measure
        acceleration or deceleration of capital flow.

        Args:
            sector: Sector name (Chinese).

        Returns:
            Dict with momentum metrics including current flow, rank,
            trend direction, and flow acceleration.
        """
        current = self.fetch_current_flow()

        result: dict[str, Any] = {
            "sector": sector,
            "net_inflow": 0.0,
            "rank": 0,
            "trend": "neutral",
            "flow_acceleration": 0.0,
        }

        # Find sector in current flow
        for rank, item in enumerate(current, 1):
            if item.get("sector") == sector:
                result["net_inflow"] = item["net_inflow"]
                result["rank"] = rank
                result["trend"] = (
                    "inflow"
                    if item["net_inflow"] > 0
                    else "outflow"
                    if item["net_inflow"] < 0
                    else "neutral"
                )
                # Acceleration: positive rank_change indicates improving momentum
                rank_change = item.get("rank_change", 0)
                if rank_change > 0:
                    result["flow_acceleration"] = round(rank_change / 10.0, 2)
                elif rank_change < 0:
                    result["flow_acceleration"] = round(rank_change / 10.0, 2)
                break

        return result

    # ------------------------------------------------------------------
    # Private: caching and snapshot storage
    # ------------------------------------------------------------------

    def _get_cache(self, key: str) -> Any | None:
        """Get value from cache (Redis or in-memory)."""
        if self._redis is not None:
            try:
                cache_key = f"sector_flow_cache:{key}"
                raw = self._redis.get(cache_key)
                if raw:
                    return json.loads(raw)
            except Exception:
                pass

        if key in self._mem_cache:
            ts, val = self._mem_cache[key]
            if time.monotonic() - ts < self._cache_ttl:
                return val
        return None

    def _set_cache(self, key: str, value: Any) -> None:
        """Store value in cache."""
        self._mem_cache[key] = (time.monotonic(), value)

        if self._redis is not None:
            try:
                cache_key = f"sector_flow_cache:{key}"
                self._redis.setex(cache_key, self._cache_ttl, json.dumps(value))
            except Exception as exc:
                logger.debug("Redis cache set failed: %s", exc)

    def _store_snapshot(self, flow: list[dict]) -> None:
        """Store current snapshot as previous for rotation detection."""
        self._prev_snapshot = flow

        if self._redis is not None:
            try:
                key = "sector_flow_prev_snapshot"
                self._redis.setex(key, 600, json.dumps(flow))
            except Exception as exc:
                logger.debug("Redis snapshot store failed: %s", exc)

    def _get_prev_ranks(self) -> dict[str, int]:
        """Get sector ranks from previous snapshot."""
        prev = self._prev_snapshot

        # Try Redis if no in-memory snapshot
        if prev is None and self._redis is not None:
            try:
                raw = self._redis.get("sector_flow_prev_snapshot")
                if raw:
                    prev = json.loads(raw)
            except Exception:
                pass

        if not prev:
            return {}

        return {
            item["sector"]: rank
            for rank, item in enumerate(prev, 1)
            if "sector" in item
        }

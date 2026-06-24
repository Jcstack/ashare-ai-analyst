"""Intraday pattern and minute-bar API endpoints.

Provides real-time access to intraday anomaly patterns and 5-min OHLCV bars
for MCP tool consumption by the research analyst.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from src.web.dependencies import get_minute_bar_fetcher, get_redis

router = APIRouter(tags=["intraday"])


logger = logging.getLogger(__name__)


@router.get("/stock/{symbol}/intraday-patterns")
async def get_intraday_patterns(
    symbol: str,
    redis_client=Depends(get_redis),
) -> dict:
    """Get detected intraday patterns for a stock from Redis cache.

    Patterns are written by the intraday_pipeline Celery tasks during
    trading hours. Returns empty list if no patterns found.
    """
    today = datetime.now().strftime("%Y%m%d")
    key = f"intraday_pattern:{today}:{symbol}"

    patterns: list[dict] = []
    if redis_client is not None:
        try:
            raw = await asyncio.to_thread(redis_client.get, key)
            if raw:
                patterns = json.loads(raw)
        except Exception as exc:
            logger.warning("Failed to read intraday patterns for %s: %s", symbol, exc)

    return {
        "symbol": symbol,
        "date": today,
        "patterns": patterns,
    }


@router.get("/stock/{symbol}/minute-bars")
async def get_minute_bars(
    symbol: str,
    period: str = Query("5", description="Bar period: 1, 5, 15, 30, 60"),
    days: int = Query(1, ge=1, le=5, description="Trading days to fetch"),
    fetcher=Depends(get_minute_bar_fetcher),
) -> dict:
    """Get minute-level OHLCV bars for a stock.

    Uses MinuteBarFetcher with EastMoney → Sina fallback and Redis caching.
    """
    df = await asyncio.to_thread(fetcher.fetch, symbol, period, days)

    bars: list[dict] = []
    if df is not None and not df.empty:
        bars = df.to_dict(orient="records")
        # Ensure serializable (NaN → None, datetime → str)
        for bar in bars:
            for k, v in bar.items():
                if isinstance(v, float) and (v != v):  # NaN check
                    bar[k] = None
                elif hasattr(v, "isoformat"):
                    bar[k] = str(v)

    return {
        "symbol": symbol,
        "period": period,
        "bars": bars,
    }


@router.get("/market/intraday-overview")
async def get_intraday_overview(
    redis_client=Depends(get_redis),
) -> dict:
    """Get market-wide intraday pattern overview.

    Scans all intraday_pattern:{today}:* keys in Redis and aggregates
    by pattern type, severity, and alerts for portfolio stocks.
    """
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"intraday_pattern:{today}:"

    pattern_counts: dict[str, int] = {}
    severity_sums: dict[str, float] = {}
    total_stocks = 0
    top_alerts: list[dict] = []

    if redis_client is not None:
        try:
            keys = await asyncio.to_thread(redis_client.keys, f"{prefix}*")
            total_stocks = len(keys)

            for key in keys:
                raw = await asyncio.to_thread(redis_client.get, key)
                if not raw:
                    continue
                try:
                    patterns = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                symbol = key.replace(prefix, "")

                for p in patterns:
                    pt = p.get("pattern_type", "unknown")
                    sev = p.get("severity", 0.0)
                    pattern_counts[pt] = pattern_counts.get(pt, 0) + 1
                    severity_sums[pt] = severity_sums.get(pt, 0.0) + sev

                    # Collect high-severity alerts
                    if sev >= 0.6:
                        top_alerts.append(
                            {
                                "symbol": symbol,
                                "pattern_type": pt,
                                "severity": sev,
                                "direction": p.get("direction", ""),
                                "description": p.get("description", ""),
                            }
                        )

        except Exception as exc:
            logger.warning("Failed to scan intraday patterns: %s", exc)

    # Sort alerts by severity descending, limit to top 20
    top_alerts.sort(key=lambda a: a.get("severity", 0), reverse=True)
    top_alerts = top_alerts[:20]

    # Build pattern summary
    pattern_summary = []
    for pt, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
        avg_severity = severity_sums.get(pt, 0.0) / max(count, 1)
        pattern_summary.append(
            {
                "pattern_type": pt,
                "count": count,
                "avg_severity": round(avg_severity, 3),
            }
        )

    return {
        "date": today,
        "total_stocks_with_patterns": total_stocks,
        "pattern_summary": pattern_summary,
        "top_alerts": top_alerts,
    }

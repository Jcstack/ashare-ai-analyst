#!/usr/bin/env python3
"""Data source health check — verifies connectivity and data quality.

Usage:
    python scripts/health_check.py

Output:
    JSON report to stdout with per-source status.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any


def check_source(name: str, fn: Any) -> dict[str, Any]:
    """Run a health check function and return a status dict."""
    start = time.perf_counter()
    try:
        result = fn()
        elapsed = (time.perf_counter() - start) * 1000
        return {
            "source": name,
            "status": "ok",
            "latency_ms": round(elapsed, 1),
            **result,
        }
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            "source": name,
            "status": "error",
            "latency_ms": round(elapsed, 1),
            "error": str(exc),
        }


def check_akshare() -> dict[str, Any]:
    """Check AKShare stock list endpoint."""
    import akshare as ak

    df = ak.stock_zh_a_spot_em()
    return {"sample_count": len(df), "columns": list(df.columns[:5])}


def check_sina_realtime() -> dict[str, Any]:
    """Check Sina real-time quote."""
    from src.data.realtime import RealtimeQuoteManager

    mgr = RealtimeQuoteManager()
    result = mgr.get_quotes(["600519"])
    count = len(result) if isinstance(result, list) else 1 if result else 0
    return {"sample_count": count}


def check_global_market() -> dict[str, Any]:
    """Check Yahoo Finance global market data."""
    from src.data.global_market import GlobalMarketFetcher

    fetcher = GlobalMarketFetcher()
    snapshot = fetcher.get_snapshot()
    count = len(snapshot) if isinstance(snapshot, dict) else 0
    return {"sample_count": count}


def check_concept_board() -> dict[str, Any]:
    """Check East Money concept board (push2)."""
    from src.data.concept_board import ConceptBoardService

    svc = ConceptBoardService()
    concepts = svc.fetch_concept_list()
    count = len(concepts) if isinstance(concepts, (list, dict)) else 0
    return {"sample_count": count}


def check_trading_calendar() -> dict[str, Any]:
    """Check trading calendar."""
    from datetime import date

    from src.data.trading_calendar import TradingCalendar

    cal = TradingCalendar()
    is_trading = cal.is_trading_day(date.today())
    return {"is_trading_today": is_trading}


def check_redis() -> dict[str, Any]:
    """Check Redis connectivity."""
    import redis

    from src.utils.config import load_config

    config = load_config("openclaw")
    broker = config.get("celery", {}).get("broker_url", "redis://redis:6379/0")
    r = redis.from_url(broker, decode_responses=True, socket_timeout=3)
    r.ping()
    return {"connected": True}


def main() -> None:
    checks = [
        ("akshare", check_akshare),
        ("sina_realtime", check_sina_realtime),
        ("global_market_yahoo", check_global_market),
        ("concept_board_push2", check_concept_board),
        ("trading_calendar", check_trading_calendar),
        ("redis", check_redis),
    ]

    results = []
    for name, fn in checks:
        result = check_source(name, fn)
        results.append(result)
        status_icon = "✓" if result["status"] == "ok" else "✗"
        print(
            f"  {status_icon} {name}: {result['status']} ({result['latency_ms']:.0f}ms)",
            file=sys.stderr,
        )

    ok_count = sum(1 for r in results if r["status"] == "ok")
    total = len(results)
    print(f"\n  {ok_count}/{total} sources healthy\n", file=sys.stderr)

    # JSON report to stdout
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

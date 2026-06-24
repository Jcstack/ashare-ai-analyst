"""Review API endpoints.

Provides daily/weekly performance review data and Bayesian calibration
health for the AI investor agent.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends

from src.web.dependencies import get_portfolio_store, get_redis, get_trade_service
from src.web.services.portfolio_store import PortfolioStore
from src.web.services.trade_service import TradeService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["review"])


def _safe_redis_json(redis_client, key: str) -> dict:
    """Read a JSON blob from Redis, returning empty dict on any failure."""
    if not redis_client:
        return {}
    try:
        raw = redis_client.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        logger.debug("Failed to read %s from Redis", key, exc_info=True)
    return {}


def _build_daily_review(
    trade_svc: TradeService,
    portfolio_store: PortfolioStore,
    redis_client,
) -> dict:
    """Build daily review data from trades, portfolio, and cached analytics."""
    today_str = date.today().isoformat()

    # Fetch cached review data (populated by the trading loop's review step)
    cached = _safe_redis_json(redis_client, f"review:daily:{today_str}")
    if cached:
        return cached

    # Fallback: build minimal review from trades + decision journal
    decisions: list[dict] = []
    try:
        trades = trade_svc.list_trades(limit=20)
        for t in trades:
            t_dict = t if isinstance(t, dict) else t.model_dump()
            trade_date = t_dict.get("executed_at", t_dict.get("created_at", ""))
            if isinstance(trade_date, str) and trade_date.startswith(today_str):
                sym = t_dict.get("symbol", "")
                decisions.append(
                    {
                        "id": t_dict.get("id", sym),
                        "symbol": sym,
                        "stock_name": t_dict.get("stock_name", sym),
                        "action": t_dict.get("action", ""),
                        "result": "pending",
                        "pnl": None,
                        "reason": t_dict.get("reasoning", ""),
                        "source": "trade",
                    }
                )
    except Exception:
        logger.debug("Failed to fetch trades for daily review", exc_info=True)

    # Also include decision journal entries (from autonomous loop + agent chat)
    try:
        import sqlite3
        from pathlib import Path

        db = Path("data/agent.db")
        if db.exists():
            conn = sqlite3.connect(str(db))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT symbol, action, confidence, timestamp, key_evidence "
                "FROM decision_journal WHERE timestamp >= ? ORDER BY timestamp",
                (today_str,),
            ).fetchall()
            seen = {d["symbol"] + d["action"] for d in decisions}
            for r in rows:
                key = r["symbol"] + r["action"]
                if key not in seen:
                    evidence = r["key_evidence"] or ""
                    decisions.append(
                        {
                            "id": r["symbol"] + "-" + r["action"],
                            "symbol": r["symbol"],
                            "stock_name": r["symbol"],
                            "action": r["action"],
                            "result": "pending",
                            "pnl": None,
                            "reason": evidence[:100] if evidence else "",
                            "confidence": r["confidence"],
                            "source": "decision_journal",
                        }
                    )
                    seen.add(key)
            conn.close()
    except Exception:
        logger.debug("Failed to fetch decision_journal for review", exc_info=True)

    # Fetch cached signal accuracy and Bayesian updates
    accuracy = _safe_redis_json(redis_client, "review:signal_accuracy")
    bayesian = _safe_redis_json(redis_client, "review:bayesian_updates")
    missed = _safe_redis_json(redis_client, "review:missed_opportunities")

    return {
        "date": today_str,
        "pnl": {
            "daily": 0,
            "daily_pct": 0.0,
            "weekly": 0,
            "monthly": 0,
        },
        "decisions": decisions,
        "signal_accuracy": accuracy.get("accuracy", {"30d": 0.0, "7d": 0.0}),
        "brier_score": accuracy.get("brier_score", 0.0),
        "missed_opportunities": missed.get("items", []),
        "bayesian_updates": bayesian.get("updates", []),
    }


def _build_weekly_review(
    trade_svc: TradeService,
    redis_client,
) -> dict:
    """Build weekly review data."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    # Fetch cached weekly review
    cached = _safe_redis_json(redis_client, f"review:weekly:{week_start.isoformat()}")
    if cached:
        return cached

    # Fallback: minimal weekly data
    decisions: list[dict] = []
    try:
        trades = trade_svc.list_trades(limit=100)
        for t in trades:
            t_dict = t if isinstance(t, dict) else t.model_dump()
            trade_date = t_dict.get("executed_at", t_dict.get("created_at", ""))
            if isinstance(trade_date, str) and trade_date >= week_start.isoformat():
                decisions.append(
                    {
                        "symbol": t_dict.get("stock_name", t_dict.get("symbol", "")),
                        "action": t_dict.get("action", ""),
                        "result": "pending",
                        "pnl": None,
                        "reason": "",
                    }
                )
    except Exception:
        logger.debug("Failed to fetch trades for weekly review", exc_info=True)

    return {
        "week_start": week_start.isoformat(),
        "week_end": today.isoformat(),
        "pnl": {"weekly": 0, "weekly_pct": 0.0},
        "decisions": decisions,
        "win_rate": 0.0,
        "total_trades": len(decisions),
    }


@router.get("/review/daily")
async def daily_review(
    trade_svc: TradeService = Depends(get_trade_service),
    portfolio_store: PortfolioStore = Depends(get_portfolio_store),
    redis_client=Depends(get_redis),
) -> dict:
    """Return today's performance review data.

    Includes P&L, trade decisions, signal accuracy, Brier score,
    missed opportunities, and Bayesian belief updates.
    """
    return _build_daily_review(trade_svc, portfolio_store, redis_client)


@router.get("/review/weekly")
async def weekly_review(
    trade_svc: TradeService = Depends(get_trade_service),
    redis_client=Depends(get_redis),
) -> dict:
    """Return this week's performance review data."""
    return _build_weekly_review(trade_svc, redis_client)


@router.get("/review/calibration")
async def calibration_health(
    redis_client=Depends(get_redis),
) -> dict:
    """Return Bayesian calibration table health.

    Shows current likelihood ratios, update history, and reliability metrics
    for each signal type tracked by the Bayesian belief system.
    """
    cached = _safe_redis_json(redis_client, "review:calibration")
    if cached:
        return cached

    # Default calibration structure when no data is cached
    return {
        "signal_types": [],
        "overall_brier_score": 0.0,
        "calibration_curve": [],
        "last_updated": None,
    }

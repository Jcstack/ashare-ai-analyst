"""Bootstrap API endpoint.

Single endpoint that returns everything needed for initial UI render,
reducing the number of requests on app load.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends

from src.web.dependencies import (
    get_action_queue_service,
    get_capital_service,
    get_portfolio_store,
    get_redis,
)
from src.web.services.action_queue_service import ActionQueueService
from src.web.services.capital_service import CapitalService
from src.web.services.portfolio_store import PortfolioStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bootstrap"])


def _get_market_status() -> str:
    """Return simplified market status string for bootstrap."""
    try:
        from src.utils.market_hours import get_market_status_for_ui

        info = get_market_status_for_ui()
        status = info.get("status", "closed")
        # Map detailed statuses to simplified ones
        mapping = {
            "pre_market": "pre_market",
            "call_auction": "pre_market",
            "trading": "trading",
            "lunch_break": "trading",
            "post_market": "post_market",
            "closed": "closed",
            "holiday": "closed",
            "emergency": "closed",
        }
        return mapping.get(status, "closed")
    except Exception:
        logger.debug("Failed to get market status", exc_info=True)
        return "closed"


def _get_regime_data(redis_client) -> dict:
    """Fetch regime data from SharedBeliefState Redis hash, with safe defaults."""
    default = {
        "sentiment_phase": "unknown",
        "sentiment_phase_cn": "未知",
        "hmm_state": "unknown",
        "hmm_probability": 0.0,
        "risk_budget_remaining": 0.03,
    }
    if not redis_client:
        return default

    try:
        import json

        # SharedBeliefState persists to HSET belief_state {regime, risk_budget, ...}
        raw_regime = redis_client.hget("belief_state", "regime")
        raw_risk = redis_client.hget("belief_state", "risk_budget")

        result = dict(default)
        if raw_regime:
            regime = json.loads(raw_regime)
            result["sentiment_phase"] = regime.get("sentiment_phase", "unknown")
            result["sentiment_phase_cn"] = regime.get("sentiment_phase_cn", "未知")
            result["hmm_state"] = regime.get("hmm_state", "unknown")
            result["hmm_probability"] = regime.get("hmm_probability", 0.0)
        if raw_risk:
            risk = json.loads(raw_risk)
            result["risk_budget_remaining"] = risk.get("remaining_pct", 0.03)
        return result
    except Exception:
        logger.debug("Failed to read belief_state from Redis", exc_info=True)
    return default


def _build_portfolio_summary(
    store: PortfolioStore, capital_svc: CapitalService
) -> dict:
    """Build portfolio summary from existing services."""
    positions = store.list_positions()
    try:
        balance = capital_svc.get_balance()
    except Exception:
        balance = 0.0

    # Calculate basic metrics
    total_cost = sum(p["cost_price"] * p["shares"] for p in positions)
    total_value = total_cost + balance  # Approximate — no realtime prices in bootstrap
    cash_pct = balance / total_value if total_value > 0 else 1.0

    camel_positions = []
    for p in positions:
        camel_positions.append(
            {
                "id": p["id"],
                "symbol": p["symbol"],
                "name": p["name"],
                "board": p["board"],
                "costPrice": p["cost_price"],
                "shares": p["shares"],
                "buyDate": p["buy_date"],
                "note": p["note"],
            }
        )

    return {
        "total_value": round(total_value, 2),
        "cash": round(balance, 2),
        "cash_pct": round(cash_pct, 4),
        "positions": camel_positions,
        "daily_pnl": 0,
        "daily_pnl_pct": 0.0,
    }


def _get_unread_count() -> int:
    """Get unread message count. Returns 0 if message store is unavailable."""
    try:
        from src.web.dependencies import get_message_store

        store = get_message_store()
        return store.count_unread()
    except Exception:
        return 0


def _get_recent_messages() -> list[dict]:
    """Get last 10 messages. Returns empty list if message store is unavailable."""
    try:
        from src.web.dependencies import get_message_store

        store = get_message_store()
        items, _total = store.list_messages(page=1, per_page=10)
        return items
    except Exception:
        return []


@router.get("/bootstrap")
async def bootstrap(
    store: PortfolioStore = Depends(get_portfolio_store),
    capital_svc: CapitalService = Depends(get_capital_service),
    action_svc: ActionQueueService = Depends(get_action_queue_service),
    redis_client=Depends(get_redis),
) -> dict:
    """Return all data needed for initial UI render.

    Aggregates portfolio, pending actions, unread messages, regime info,
    and market status into a single response.
    """
    # Run independent fetches concurrently
    portfolio = await asyncio.to_thread(_build_portfolio_summary, store, capital_svc)
    pending_actions = await asyncio.to_thread(action_svc.list_pending)
    regime = await asyncio.to_thread(_get_regime_data, redis_client)
    market_status = await asyncio.to_thread(_get_market_status)
    unread_count = await asyncio.to_thread(_get_unread_count)
    recent_messages = await asyncio.to_thread(_get_recent_messages)

    return {
        "portfolio": portfolio,
        "action_queue": [a.to_dict() for a in pending_actions],
        "unread_count": unread_count,
        "regime": regime,
        "recent_messages": recent_messages,
        "market_status": market_status,
    }

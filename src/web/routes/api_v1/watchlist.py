"""Watchlist API endpoint with AI attitude enrichment.

Per PRD v36.0: Watchlist items show AI's current attitude toward each stock.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends

from src.web.dependencies import (
    get_message_store,
    get_watchlist_service,
)
from src.web.services.message_store import MessageStore
from src.web.services.watchlist_service import WatchlistService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["watchlist"])


@router.get("/")
async def list_watchlist(
    watchlist_svc: WatchlistService = Depends(get_watchlist_service),
    msg_store: MessageStore = Depends(get_message_store),
) -> list[dict[str, Any]]:
    """List watchlist stocks with AI attitude and latest message summary."""
    items = await asyncio.to_thread(watchlist_svc.list_all)

    # Build latest message lookup
    all_msgs, _ = await asyncio.to_thread(msg_store.list_messages, page=1, per_page=200)
    msg_map: dict[str, dict] = {}
    for msg in all_msgs:
        symbol = msg.get("symbol")
        if symbol and symbol not in msg_map:
            msg_map[symbol] = msg

    result = []
    for item in items:
        symbol = item.get("symbol", "")
        entry: dict[str, Any] = {
            "symbol": symbol,
            "name": item.get("name", ""),
            "ai_attitude": "中性",
        }

        # Latest message summary
        msg = msg_map.get(symbol)
        if msg:
            entry["latest_message_summary"] = msg.get("summary", "")[:100]
        else:
            entry["latest_message_summary"] = ""

        result.append(entry)

    return result

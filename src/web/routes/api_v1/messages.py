"""Assistant inbox message API endpoints.

Per PRD v36.0: Message-driven investment assistant — REST API.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.web.dependencies import get_message_store
from src.web.services.message_store import MessageStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["messages"])


@router.get("/")
async def list_messages(
    type: str | None = Query(None, description="Message type filter"),
    filter: str | None = Query(None, description="Comma-separated type filter alias"),
    symbol: str | None = Query(None, description="Stock symbol filter"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    unread_only: bool = Query(False, description="Only show unread messages"),
    store: MessageStore = Depends(get_message_store),
) -> dict:
    """List messages with pagination and optional filters.

    Supports comma-separated type filter (e.g. type=buy_signal,sell_signal).
    The `filter` param is an alias for `type` used by the frontend.
    """
    msg_type = filter or type
    items, total = await asyncio.to_thread(
        store.list_messages,
        msg_type=msg_type,
        symbol=symbol,
        unread_only=unread_only,
        page=page,
        per_page=per_page,
    )
    unread = await asyncio.to_thread(store.count_unread)
    return {
        "items": items,
        "total": total,
        "count": total,
        "page": page,
        "per_page": per_page,
        "has_more": page * per_page < total,
        "unread_count": unread,
    }


@router.get("/unread-count")
async def unread_count(
    store: MessageStore = Depends(get_message_store),
) -> dict:
    """Count unread messages (for badge display)."""
    count = await asyncio.to_thread(store.count_unread)
    return {"count": count}


@router.get("/{message_id}")
async def get_message(
    message_id: int,
    store: MessageStore = Depends(get_message_store),
) -> dict:
    """Get a single message with full detail."""
    msg = await asyncio.to_thread(store.get_message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


@router.post("/{message_id}/read")
async def mark_read(
    message_id: int,
    store: MessageStore = Depends(get_message_store),
) -> dict:
    """Mark a message as read."""
    ok = await asyncio.to_thread(store.mark_read, message_id)
    if not ok:
        # Either not found or already read — still return success
        pass
    return {"success": True}


# ---------------------------------------------------------------------------
# Push endpoint — used by InvestorAgent MCP tool to push messages to Discord
# ---------------------------------------------------------------------------


class PushMessageRequest(BaseModel):
    msg_type: str = "market_insight"
    title: str
    summary: str
    symbol: str | None = None
    action_advice: str | None = None
    risk_note: str | None = None
    priority: str = "high"
    confidence: float | None = None


@router.post("/push")
async def push_message(
    body: PushMessageRequest,
    store: MessageStore = Depends(get_message_store),
) -> dict:
    """Create a message and publish to Redis for Discord push.

    Used by InvestorAgent's push_message_to_user MCP tool.
    """
    now = datetime.now(UTC)
    msg_id = await asyncio.to_thread(
        store.create_message,
        symbol=body.symbol,
        msg_type=body.msg_type,
        title=body.title,
        summary=body.summary,
        content=body.summary,
        priority=body.priority,
        action_advice=body.action_advice,
        risk_note=body.risk_note,
        raw_data_ref={"source": "investor_agent_mcp", "confidence": body.confidence},
        data_freshness="realtime",
        data_collected_at=now.isoformat(),
    )

    # Publish to Redis for Discord
    try:
        import redis

        r = redis.Redis(host="redis", port=6379, db=0, decode_responses=True)
        payload = {
            "type": body.msg_type,
            "symbol": body.symbol or "",
            "title": body.title,
            "summary": body.summary,
            "priority": body.priority,
            "action_advice": body.action_advice or "",
            "risk_note": body.risk_note or "",
            "confidence": body.confidence,
            "message_id": msg_id,
        }
        r.publish("assistant:messages", json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        logger.warning("Redis publish failed: %s", exc)

    return {"success": True, "message_id": msg_id}

"""Notification API endpoints — recent alerts, read status, unread count.

Per PRD v2.4 FR-NP003: Notification API + Redis channel.
"""

import dataclasses
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends

from src.web.dependencies import get_redis, get_system_alert_engine
from src.web.routes.api_v1.schemas import NotificationItem, UnreadCountResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notifications"])

NOTIFICATIONS_KEY = "notifications:alerts"
READ_SET_KEY = "notifications:read_ids"


def _collect_notification_ids(r, limit: int = 200) -> list[str]:
    """Extract all notification IDs currently in the Redis list."""
    raw_items = r.lrange(NOTIFICATIONS_KEY, 0, limit - 1)
    ids: list[str] = []
    for raw in raw_items:
        try:
            item = json.loads(raw)
            nid = item.get("id", "")
            if nid:
                ids.append(nid)
        except (json.JSONDecodeError, TypeError):
            continue
    return ids


@router.get("/recent", response_model=list[NotificationItem])
async def get_recent_notifications(
    limit: int = 50,
    r=Depends(get_redis),
) -> list[dict]:
    """Get the most recent notifications from Redis.

    Returns up to *limit* notifications, newest first.
    """
    if r is None:
        return []

    try:
        raw_items = r.lrange(NOTIFICATIONS_KEY, 0, limit - 1)
        read_ids = r.smembers(READ_SET_KEY) or set()

        result = []
        for raw in raw_items:
            try:
                item = json.loads(raw)
                item["read"] = item.get("id", "") in read_ids
                result.append(item)
            except json.JSONDecodeError:
                continue
        return result
    except Exception as exc:
        logger.warning("Failed to fetch notifications: %s", exc)
        return []


@router.post("/read")
async def mark_notifications_read(
    ids: list[str] = Body(..., description="Notification IDs to mark as read"),
    r=Depends(get_redis),
) -> dict:
    """Mark notifications as read by their IDs."""
    if r is None:
        return {"status": "error", "message": "Redis unavailable"}

    try:
        if ids:
            r.sadd(READ_SET_KEY, *ids)
        return {"status": "ok", "marked": len(ids)}
    except Exception as exc:
        logger.warning("Failed to mark notifications read: %s", exc)
        return {"status": "error", "message": str(exc)}


@router.post("/read-all")
async def mark_all_notifications_read(
    r=Depends(get_redis),
) -> dict:
    """Mark ALL current notifications as read and prune stale IDs.

    This replaces the read set with only the IDs that currently exist
    in the notification list, preventing the set from growing unboundedly.
    """
    if r is None:
        return {"status": "error", "message": "Redis unavailable"}

    try:
        current_ids = _collect_notification_ids(r)
        if not current_ids:
            # No notifications at all — clear the read set too
            r.delete(READ_SET_KEY)
            return {"status": "ok", "marked": 0}

        # Replace the read set atomically: delete old + add current IDs
        pipe = r.pipeline()
        pipe.delete(READ_SET_KEY)
        pipe.sadd(READ_SET_KEY, *current_ids)
        pipe.execute()

        return {"status": "ok", "marked": len(current_ids)}
    except Exception as exc:
        logger.warning("Failed to mark all notifications read: %s", exc)
        return {"status": "error", "message": str(exc)}


@router.post("/trigger-test")
async def trigger_test_notification(
    r=Depends(get_redis),
) -> dict:
    """Push a test notification to Redis for debugging the notification pipeline.

    Useful outside of trading hours when Celery tasks won't produce real alerts.
    """
    if r is None:
        return {"status": "error", "message": "Redis unavailable"}

    try:
        notification = {
            "id": str(uuid.uuid4()),
            "type": "system",
            "title": "测试通知",
            "summary": "通知系统工作正常。这是一条测试消息。",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "",
        }
        r.lpush(NOTIFICATIONS_KEY, json.dumps(notification, ensure_ascii=False))
        r.publish("notifications:push", json.dumps(notification, ensure_ascii=False))
        return {"status": "ok", "notification": notification}
    except Exception as exc:
        logger.warning("Failed to push test notification: %s", exc)
        return {"status": "error", "message": str(exc)}


@router.post("/purge-read")
async def purge_read_notifications(
    r=Depends(get_redis),
) -> dict:
    """Remove all read notifications from the Redis list.

    Reads the full notification list, identifies which ones are in the
    read-IDs set, removes them from the list, and cleans the read set.
    """
    if r is None:
        return {"status": "error", "message": "Redis unavailable"}

    try:
        read_ids = r.smembers(READ_SET_KEY) or set()
        if not read_ids:
            return {"status": "ok", "purged": 0}

        raw_items = r.lrange(NOTIFICATIONS_KEY, 0, -1)
        purged = 0
        pipe = r.pipeline()
        for raw in raw_items:
            try:
                item = json.loads(raw)
                if item.get("id", "") in read_ids:
                    pipe.lrem(NOTIFICATIONS_KEY, 1, raw)
                    purged += 1
            except (json.JSONDecodeError, TypeError):
                continue

        # Clear the read set since those notifications are gone
        pipe.delete(READ_SET_KEY)
        pipe.execute()

        return {"status": "ok", "purged": purged}
    except Exception as exc:
        logger.warning("Failed to purge read notifications: %s", exc)
        return {"status": "error", "message": str(exc)}


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    r=Depends(get_redis),
) -> dict:
    """Get the count of unread notifications.

    Iterates through actual notification IDs and checks against the
    read set, instead of using ``total - read_count`` which drifts
    when old notifications are trimmed from the list.
    """
    if r is None:
        return {"count": 0}

    try:
        current_ids = _collect_notification_ids(r)
        if not current_ids:
            return {"count": 0}

        read_ids = r.smembers(READ_SET_KEY) or set()
        unread = sum(1 for nid in current_ids if nid not in read_ids)
        return {"count": unread}
    except Exception as exc:
        logger.warning("Failed to get unread count: %s", exc)
        return {"count": 0}


@router.get("/alerts/system")
async def get_system_alerts(
    symbol: str | None = None,
    severity: str | None = None,
    engine=Depends(get_system_alert_engine),
) -> list[dict]:
    """Get active system-level alerts with optional filtering.

    Query parameters:
        symbol: Filter alerts to a specific stock symbol.
        severity: Filter alerts by severity level (e.g. "critical", "warning", "info").

    Returns a list of alert dicts with fields: alert_id, rule_name, severity,
    title, description, symbol, data, timestamp.
    """
    alerts = engine.get_active_alerts(symbol=symbol, severity=severity)
    return [dataclasses.asdict(a) for a in alerts]


@router.get("/alerts/system/rules")
async def list_system_alert_rules(
    engine=Depends(get_system_alert_engine),
) -> list[dict]:
    """List all registered system alert rules.

    Returns the engine's registered rule definitions.
    """
    return engine.list_rules()

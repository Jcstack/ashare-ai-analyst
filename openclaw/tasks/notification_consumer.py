"""Event bus consumer: Notification — creates MessageStore entries from event streams.

Subscribes to ``events:signal`` + ``events:risk`` + ``events:regime`` via
consumer group ``notification``.

- Signal events  -> type="trading_signal",  priority by confidence
- Risk alerts    -> type="risk_alert",      priority="high"
- Regime changes -> type="regime_change",   priority="medium"

Dedup via Redis SET with 4h TTL key pattern:
``dedup:notify:{event_type}:{symbol}:{hour_bucket}``

Designed to run as a periodic Celery task (e.g. every 60s) that drains the
streams in bounded batches rather than a long-running blocking consumer.
"""

from __future__ import annotations

import json
import time
from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.notification_consumer")

_CONSUMER_GROUP = "notification"
_CONSUMER_NAME = "notification-consumer-worker"
_STREAMS = ["events:signal", "events:risk", "events:regime"]
_MAX_EVENTS_PER_RUN = 50
_DEDUP_TTL_SECONDS = 4 * 3600  # 4 hours
_DEDUP_PREFIX = "dedup:notify"


def _hour_bucket() -> int:
    """Return current time truncated to hour for dedup bucketing."""
    return int(time.time()) // 3600


@app.task(
    name="openclaw.tasks.notification_consumer.task_consume_notifications",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def task_consume_notifications(self) -> dict[str, Any]:
    """Drain signal/risk/regime streams and create MessageStore entries.

    Returns:
        Summary dict with events_read, messages_created, and deduped counts.
    """
    events_read = 0
    messages_created = 0
    deduped = 0

    try:
        from src.event_bus.bus import EventBus

        bus = EventBus()
    except Exception as exc:
        logger.warning("EventBus unavailable, skipping notification consumer: %s", exc)
        return {
            "status": "bus_unavailable",
            "events_read": 0,
            "messages_created": 0,
            "deduped": 0,
        }

    # Redis client for dedup — optional, proceed without if unavailable
    redis_client = None
    try:
        from src.web.dependencies import get_redis

        redis_client = get_redis()
    except Exception:
        logger.debug("Redis unavailable for dedup — notifications may duplicate")

    # Lazy import MessageStore
    try:
        from src.web.services.message_store import MessageStore

        store = MessageStore()
    except Exception as exc:
        logger.warning("MessageStore unavailable: %s", exc)
        return {
            "status": "store_unavailable",
            "events_read": 0,
            "messages_created": 0,
            "deduped": 0,
        }

    pending_messages: list[dict[str, Any]] = []

    def _handle_event(stream: str, entry_id: str, parsed: dict[str, Any]) -> None:
        nonlocal events_read
        events_read += 1

        event_type = parsed.get("type", "unknown")
        data = parsed.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                data = {}

        symbol = data.get("symbol", "")

        # Build message spec based on stream
        msg: dict[str, Any] | None = None

        if stream == "events:signal":
            confidence = float(data.get("confidence", 0))
            direction = data.get("direction", "neutral")
            source = data.get("source", "unknown")
            reason = data.get("reason", "")

            # Only push high-confidence signals as trading_signal to user.
            # Raw pattern detections (confidence 0.5-0.7) are NOT actionable
            # without LLM analysis — they go through HeartbeatAgent instead.
            if confidence < 0.8:
                logger.debug(
                    "Signal %s %s skipped (confidence=%.2f < 0.8, source=%s)",
                    symbol,
                    direction,
                    confidence,
                    source,
                )
                return  # Skip — let HeartbeatAgent pick this up via tools

            priority = "high" if confidence >= 0.9 else "medium"
            msg = {
                "symbol": symbol or None,
                "msg_type": "trading_signal",
                "title": f"交易信号: {symbol} {direction}" if symbol else "交易信号",
                "summary": reason[:200]
                if reason
                else f"{source} {direction} (置信度{confidence:.0%})",
                "priority": priority,
                "action_advice": reason[:200] if reason else "",
            }

        elif stream == "events:risk":
            alert_msg = data.get("message", "")
            severity = float(data.get("severity", 0))
            msg = {
                "symbol": symbol or None,
                "msg_type": "risk_alert",
                "title": f"风险警报: {symbol}" if symbol else "风险警报",
                "summary": alert_msg[:200] if alert_msg else f"风险等级 {severity:.0%}",
                "priority": "high",
            }

        elif stream == "events:regime":
            phase = data.get("phase", "unknown")
            phase_cn = data.get("phase_cn", phase)
            prev_phase = data.get("prev_phase", "")
            confidence = float(data.get("confidence", 0))
            msg = {
                "symbol": None,
                "msg_type": "regime_change",
                "title": f"市场情绪: {phase_cn}",
                "summary": f"情绪周期从 {prev_phase} 转变为 {phase_cn} (置信度{confidence:.0%})",
                "priority": "medium",
            }

        if msg is not None:
            msg["event_type"] = event_type
            msg["dedup_symbol"] = symbol
            pending_messages.append(msg)

    # Read events in a bounded batch
    try:
        bus.subscribe(
            streams=_STREAMS,
            consumer_group=_CONSUMER_GROUP,
            consumer_name=_CONSUMER_NAME,
            callback=_handle_event,
            batch_size=_MAX_EVENTS_PER_RUN,
            block_ms=1000,
            max_iterations=1,
        )
    except Exception as exc:
        logger.warning("EventBus subscribe failed: %s", exc)

    # Create MessageStore entries with dedup
    bucket = _hour_bucket()
    for msg in pending_messages:
        event_type = msg.pop("event_type", "unknown")
        dedup_symbol = msg.pop("dedup_symbol", "")
        dedup_key = f"{_DEDUP_PREFIX}:{event_type}:{dedup_symbol}:{bucket}"

        # Dedup check
        if redis_client is not None:
            try:
                if not redis_client.set(dedup_key, "1", nx=True, ex=_DEDUP_TTL_SECONDS):
                    deduped += 1
                    continue
            except Exception:
                pass  # Proceed without dedup if Redis fails

        try:
            store.create_message(**msg)
            messages_created += 1
        except Exception as exc:
            logger.debug("Failed to create message: %s", exc)

        # Publish to assistant:messages for Discord push
        if redis_client is not None and msg.get("priority") in ("high", "critical"):
            try:
                discord_payload = {
                    "type": msg.get("msg_type", "market_watch"),
                    "title": msg.get("title", ""),
                    "summary": msg.get("summary", ""),
                    "symbol": msg.get("symbol", ""),
                    "priority": msg.get("priority", "medium"),
                    "confidence": 0.7,  # EventBus signals pass convergence gate
                }
                redis_client.publish(
                    "assistant:messages",
                    json.dumps(discord_payload, ensure_ascii=False),
                )
            except Exception as exc:
                logger.debug("Failed to publish to assistant:messages: %s", exc)

    logger.info(
        "Notification consumer: %d events, %d messages created, %d deduped",
        events_read,
        messages_created,
        deduped,
    )
    return {
        "status": "ok",
        "events_read": events_read,
        "messages_created": messages_created,
        "deduped": deduped,
    }

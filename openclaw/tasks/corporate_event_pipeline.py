"""Corporate event scanning pipeline.

Scans for high-impact corporate events (announcements, lock-up expiry,
block trades, insider activity) and publishes to the event bus for
notification and InvestmentDirector consumption.

Celery tasks:
- task_corporate_event_scan: every 15min, 8:00-18:00 weekdays
- task_lockup_calendar_refresh: daily 16:30
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.corporate_event_pipeline")


def _get_app():
    from openclaw.celery_app import app

    return app


def _publish_event(event_type: str, data: dict[str, Any]) -> None:
    """Publish corporate event to event bus and message store."""
    try:
        from src.event_bus.bus import get_event_bus

        bus = get_event_bus()
        bus.publish(
            "events:news",
            event_type,
            json.dumps(data, ensure_ascii=False, default=str),
        )
    except Exception as exc:
        logger.warning("Event bus publish failed: %s", exc)


def _create_message(
    msg_type: str,
    title: str,
    summary: str,
    symbol: str | None = None,
    priority: str = "medium",
    action_advice: str | None = None,
    risk_note: str | None = None,
) -> None:
    """Create a message in the MessageStore for user notification."""
    try:
        from src.web.services.message_store import MessageStore

        store = MessageStore()
        store.create_message(
            msg_type=msg_type,
            title=title,
            summary=summary,
            symbol=symbol,
            priority=priority,
            action_advice=action_advice,
            risk_note=risk_note,
        )
    except Exception as exc:
        logger.warning("MessageStore creation failed: %s", exc)


def _dedup_key(prefix: str, symbol: str) -> str:
    """Build Redis dedup key for corporate events."""
    hour_bucket = int(time.time() // 14400)  # 4-hour windows
    return f"dedup:corp:{prefix}:{symbol}:{hour_bucket}"


def _is_dedup(key: str) -> bool:
    """Check and set dedup flag in Redis."""
    try:
        import redis

        r = redis.from_url("redis://localhost:6379/0")
        if r.exists(key):
            return True
        r.setex(key, 14400, "1")
        return False
    except Exception:
        return False


def task_corporate_event_scan() -> dict[str, Any]:
    """Scan for high-impact corporate announcements.

    Runs every 15 minutes during 8:00-18:00 on weekdays.
    """
    logger.info("Starting corporate event scan")
    stats = {"announcements_found": 0, "high_impact": 0, "published": 0}

    try:
        from src.data.cninfo_announcement import CninfoAnnouncementFetcher

        fetcher = CninfoAnnouncementFetcher()
        announcements = fetcher.fetch_recent_sync(days=1)
        stats["announcements_found"] = len(announcements)

        high_impact = [a for a in announcements if a.is_high_impact]
        stats["high_impact"] = len(high_impact)

        for ann in high_impact:
            dedup = _dedup_key(f"ann_{ann.announcement_type}", ann.symbol)
            if _is_dedup(dedup):
                continue

            priority = (
                "high"
                if ann.announcement_type in ("restructuring", "risk_warning")
                else "medium"
            )

            _create_message(
                msg_type="corporate_announcement",
                title=f"{ann.name}({ann.symbol}): {ann.title}",
                summary=f"公告类型: {ann.announcement_type}, 关键词: {', '.join(ann.impact_keywords)}",
                symbol=ann.symbol,
                priority=priority,
                action_advice=f"查看公告详情: {ann.url}" if ann.url else None,
            )

            _publish_event(
                "corporate_announcement",
                {
                    "symbol": ann.symbol,
                    "name": ann.name,
                    "title": ann.title,
                    "type": ann.announcement_type,
                    "severity": 0.8 if priority == "high" else 0.5,
                },
            )
            stats["published"] += 1

    except Exception as exc:
        logger.error("Corporate event scan failed: %s", exc)

    logger.info("Corporate event scan complete: %s", stats)
    return stats


def task_lockup_calendar_refresh() -> dict[str, Any]:
    """Refresh lock-up expiry calendar and alert on major unlocks.

    Runs daily at 16:30.
    """
    logger.info("Starting lockup calendar refresh")
    stats = {"upcoming_events": 0, "major_events": 0, "alerts_sent": 0}

    try:
        from src.data.lockup_expiry import LockupExpiryFetcher

        fetcher = LockupExpiryFetcher()
        upcoming = fetcher.fetch_upcoming_sync(days=7)
        stats["upcoming_events"] = len(upcoming)

        for expiry in upcoming:
            if not fetcher.is_major_unlock(expiry):
                continue

            stats["major_events"] += 1
            dedup = _dedup_key("lockup", expiry.symbol)
            if _is_dedup(dedup):
                continue

            value_str = (
                f"{expiry.shares_market_value_wan / 10000:.1f}亿"
                if expiry.shares_market_value_wan >= 10000
                else f"{expiry.shares_market_value_wan:.0f}万"
            )

            _create_message(
                msg_type="lockup_warning",
                title=f"解禁预警: {expiry.name}({expiry.symbol}) {expiry.days_until_unlock}天后",
                summary=f"解禁{expiry.shares_pct_of_total:.1f}%股份(约{value_str}), 持有人: {expiry.holder_name}",
                symbol=expiry.symbol,
                priority="high",
                risk_note=f"大额解禁可能带来卖压, 解禁类型: {expiry.holder_type}",
            )
            stats["alerts_sent"] += 1

    except Exception as exc:
        logger.error("Lockup calendar refresh failed: %s", exc)

    logger.info("Lockup calendar refresh complete: %s", stats)
    return stats

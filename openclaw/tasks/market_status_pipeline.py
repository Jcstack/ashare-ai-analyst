"""Market status notification tasks — opening/closing reminders, holiday previews,
daily calendar refresh, and emergency event detection.

Provides Celery tasks for:
1. Market opening reminder (09:10 on trading days)
2. Market closing reminder (14:50 on trading days)
3. Holiday summary (18:00 on last trading day before holiday)
4. Daily calendar refresh (08:30 Mon-Fri) — re-fetch adata + YAML emergency_closures
5. Emergency event scan (every 15min 08:00-09:30) — keyword scan of intelligence hub

Per Plan: Market Closure Awareness Phase 3A + enhancements.
"""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from openclaw.celery_app import app
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.market_status_pipeline")

NOTIFICATIONS_KEY = "notifications:alerts"
MAX_NOTIFICATIONS = 200

# Keywords that indicate potential emergency market closure
_EMERGENCY_KEYWORDS = [
    "临时停牌",
    "暂停交易",
    "熔断",
    "紧急休市",
    "台风红色预警",
    "暂停开市",
    "延迟开市",
    "全天停牌",
    "交易所临时休市",
    "全市场停牌",
]

# Redis key for emergency scan dedup (prevents firing multiple times per day)
_EMERGENCY_DEDUP_KEY = "emergency_scan:fired:{date}"
_EMERGENCY_DEDUP_TTL = 86400  # 24 hours


def _get_redis():
    """Get a Redis client for notification storage."""
    import redis

    config = load_config("openclaw")
    broker = config.get("celery", {}).get("broker_url", "redis://redis:6379/0")
    return redis.from_url(broker, decode_responses=True)


def _push_notification(r, key: str, notification: dict[str, Any]) -> None:
    """Push a notification to Redis list, capping at MAX_NOTIFICATIONS."""
    notification.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    notification.setdefault("read", False)
    notification.setdefault(
        "id", f"{notification.get('type', 'alert')}_{int(time.time() * 1000)}"
    )
    r.lpush(key, json.dumps(notification, ensure_ascii=False))
    r.ltrim(key, 0, MAX_NOTIFICATIONS - 1)


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


@app.task(
    name="openclaw.tasks.market_status_pipeline.task_market_opening_reminder",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def task_market_opening_reminder(self) -> dict[str, Any]:
    """Push '即将开盘' notification at 09:10 on trading days."""
    if not _should_execute("task_market_opening_reminder"):
        logger.info("task_market_opening_reminder: skipped (timeline guard)")
        return {"status": "skipped"}

    from src.data.trading_calendar import TradingCalendar

    cal = TradingCalendar()

    if not cal.is_trading_day(date.today()):
        logger.info("task_market_opening_reminder: not a trading day, skipping")
        return {"status": "skipped", "reason": "not_trading_day"}

    try:
        r = _get_redis()
        _push_notification(
            r,
            NOTIFICATIONS_KEY,
            {
                "type": "market_status",
                "title": "A股即将开盘",
                "summary": "A股将于09:30开盘，请关注集合竞价动向。",
            },
        )
        logger.info("Market opening reminder pushed")
        return {"status": "success"}
    except Exception as exc:
        logger.warning("Failed to push opening reminder: %s", exc)
        return {"status": "error", "error": str(exc)}


@app.task(
    name="openclaw.tasks.market_status_pipeline.task_market_closing_reminder",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def task_market_closing_reminder(self) -> dict[str, Any]:
    """Push '即将收盘' notification at 14:50 on trading days."""
    if not _should_execute("task_market_closing_reminder"):
        logger.info("task_market_closing_reminder: skipped (timeline guard)")
        return {"status": "skipped"}

    from src.data.trading_calendar import TradingCalendar

    cal = TradingCalendar()

    if not cal.is_trading_day(date.today()):
        logger.info("task_market_closing_reminder: not a trading day, skipping")
        return {"status": "skipped", "reason": "not_trading_day"}

    try:
        r = _get_redis()
        _push_notification(
            r,
            NOTIFICATIONS_KEY,
            {
                "type": "market_status",
                "title": "A股即将收盘",
                "summary": "A股将于15:00收盘，注意尾盘集合竞价(14:57-15:00)。",
            },
        )
        logger.info("Market closing reminder pushed")
        return {"status": "success"}
    except Exception as exc:
        logger.warning("Failed to push closing reminder: %s", exc)
        return {"status": "error", "error": str(exc)}


@app.task(
    name="openclaw.tasks.market_status_pipeline.task_holiday_summary",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def task_holiday_summary(self) -> dict[str, Any]:
    """Push holiday preview notification at 18:00 on last trading day before holiday.

    Checks if tomorrow is a non-trading day that starts a holiday period.
    """
    if not _should_execute("task_holiday_summary"):
        logger.info("task_holiday_summary: skipped (timeline guard)")
        return {"status": "skipped"}

    from src.data.trading_calendar import TradingCalendar

    cal = TradingCalendar()
    today = date.today()

    # Only run if today IS a trading day
    if not cal.is_trading_day(today):
        return {"status": "skipped", "reason": "not_trading_day"}

    # Check if tomorrow starts a non-trading period
    tomorrow = today + timedelta(days=1)
    if cal.is_trading_day(tomorrow):
        return {"status": "skipped", "reason": "tomorrow_is_trading"}

    # Check if the non-trading period is a known holiday
    holiday_info = cal.get_holiday_period_info(tomorrow)
    if not holiday_info:
        # Just a normal weekend, no special notification needed
        # Unless it's a long weekend (3+ days)
        if not cal.is_holiday_period(tomorrow):
            return {"status": "skipped", "reason": "normal_weekend"}

    try:
        r = _get_redis()
        if holiday_info:
            name = holiday_info["name"]
            end_date = holiday_info["end_date"]
            next_td = holiday_info["next_trading_day"]
            summary = (
                f"明日起A股休市（{name}假期），"
                f"休市至{end_date}。"
                f"下一交易日: {next_td}。"
                "港股/美股仍可能正常交易，请关注全球市场动态。"
            )
        else:
            ntd = cal.next_trading_day(today)
            summary = f"明日起A股休市，下一交易日: {ntd.isoformat()}。"

        _push_notification(
            r,
            NOTIFICATIONS_KEY,
            {
                "type": "holiday_preview",
                "title": f"休市提醒 — {holiday_info['name'] if holiday_info else '连续休市'}",
                "summary": summary,
            },
        )
        logger.info("Holiday summary notification pushed")
        return {"status": "success"}
    except Exception as exc:
        logger.warning("Failed to push holiday summary: %s", exc)
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Daily calendar refresh (08:30 Mon-Fri)
# ---------------------------------------------------------------------------


@app.task(
    name="openclaw.tasks.market_status_pipeline.task_calendar_refresh",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def task_calendar_refresh(self) -> dict[str, Any]:
    """Re-fetch adata trading dates and re-read YAML emergency_closures.

    Runs at 08:30 Mon-Fri to pick up:
    - Updated adata calendar (e.g. newly announced holidays for next year)
    - Manually added emergency_closures in config/calendar.yaml
    """
    if not _should_execute("task_calendar_refresh"):
        logger.info("task_calendar_refresh: skipped (timeline guard)")
        return {"status": "skipped"}

    from src.web.dependencies import get_trading_calendar

    try:
        cal = get_trading_calendar()
        result = cal.refresh()
        logger.info("Calendar refresh completed: %s", result)
        return {"status": "success", **result}
    except Exception as exc:
        logger.error("Calendar refresh failed: %s", exc)
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Emergency event scan (every 15min, 08:00-09:30)
# ---------------------------------------------------------------------------


@app.task(
    name="openclaw.tasks.market_status_pipeline.task_emergency_scan",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def task_emergency_scan(self) -> dict[str, Any]:
    """Scan intelligence hub for emergency closure signals.

    Runs every 15 minutes between 08:00 and 09:30 on weekdays.
    Scans recent (last 2h) intelligence items for keywords indicating
    potential market closures (熔断, 临时停牌, 台风红色预警, etc.).

    On match:
    1. Injects emergency_closure into the TradingCalendar singleton
    2. Pushes a high-priority notification to the user
    3. Sets a Redis dedup key to prevent re-firing the same day
    """
    if not _should_execute("task_emergency_scan"):
        logger.info("task_emergency_scan: skipped (timeline guard)")
        return {"status": "skipped"}

    today = date.today()

    # Skip weekends — no need to scan
    if today.weekday() >= 5:
        return {"status": "skipped", "reason": "weekend"}

    # Skip holiday weekdays — no trading, no need for emergency scan
    try:
        from src.data.trading_calendar import TradingCalendar

        _cal = TradingCalendar()
        if not _cal.is_trading_day(today):
            return {"status": "skipped", "reason": "holiday"}
    except Exception:
        pass  # If TradingCalendar unavailable, proceed with scan

    # Dedup check — only fire once per day per emergency
    try:
        r = _get_redis()
        dedup_key = _EMERGENCY_DEDUP_KEY.format(date=today.isoformat())
        if r.exists(dedup_key):
            logger.debug("task_emergency_scan: already fired today, skipping")
            return {"status": "skipped", "reason": "already_fired_today"}
    except Exception:
        r = None

    # Scan intelligence hub for emergency keywords
    matched_items = _scan_for_emergency_keywords()

    if not matched_items:
        logger.debug("task_emergency_scan: no emergency signals found")
        return {"status": "ok", "matches": 0}

    # Found emergency signals — inject closure and notify
    from src.web.dependencies import get_trading_calendar

    cal = get_trading_calendar()

    # Build reason from matched items
    titles = [m["title"] for m in matched_items[:3]]
    keywords_found = [m["keyword"] for m in matched_items[:3]]
    reason = f"情报检测: {', '.join(titles[:2])}"

    # Only inject if not already an emergency
    if cal.is_emergency_closure(today):
        logger.info("task_emergency_scan: emergency already registered for today")
        return {"status": "ok", "matches": len(matched_items), "action": "already_set"}

    cal.add_emergency_closure(today, reason)
    logger.warning(
        "Emergency closure auto-detected: %d items matched, keywords=%s",
        len(matched_items),
        keywords_found,
    )

    # Push notification
    if r is not None:
        _push_notification(
            r,
            NOTIFICATIONS_KEY,
            {
                "type": "market_status",
                "title": "紧急休市预警",
                "summary": (
                    f"检测到可能影响今日交易的重大事件: {titles[0]}。"
                    "系统已自动标记今日为紧急休市，请关注交易所最新公告确认。"
                ),
            },
        )
        # Set dedup key
        r.set(dedup_key, "1", ex=_EMERGENCY_DEDUP_TTL)

    return {
        "status": "emergency_detected",
        "matches": len(matched_items),
        "reason": reason,
        "keywords": keywords_found,
    }


def _scan_for_emergency_keywords() -> list[dict[str, str]]:
    """Query intelligence hub for recent items matching emergency keywords.

    Returns list of dicts with 'title', 'keyword', 'item_id' for each match.
    """
    try:
        from src.intelligence_hub.info_store import InfoStore

        store = InfoStore()
    except Exception:
        logger.warning("InfoStore unavailable for emergency scan")
        return []

    # Fetch recent items (last 2 hours worth, across all categories)
    # We use days=1 since get_feed doesn't support hours, then filter by time
    try:
        items = store.get_feed(limit=200, days=1, sort_by="time")
    except Exception:
        logger.warning("Failed to query InfoStore for emergency scan")
        return []

    # Filter to last 2 hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    matches: list[dict[str, str]] = []

    for item in items:
        # Check publish time
        pub = item.get("published_at", "")
        if pub:
            try:
                pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
            except (ValueError, TypeError):
                continue

        text = f"{item.get('title', '')} {item.get('summary', '')}"
        for kw in _EMERGENCY_KEYWORDS:
            if kw in text:
                matches.append(
                    {
                        "title": item.get("title", "")[:80],
                        "keyword": kw,
                        "item_id": item.get("item_id", ""),
                    }
                )
                break  # One match per item is enough

    return matches

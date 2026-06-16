"""Qlib binary data update Celery task.

Scheduled at 16:15 CST Mon-Fri (after ``task_fetch_all`` at 16:00).
Reads cached parquet files from ``data/raw/`` and writes Qlib binary data
to ``~/.qlib/qlib_data/cn_data/``.

Follows the same patterns as ``research_pipeline.py``:
timeline guard, Redis notification, graceful error handling.
"""

import json
import time
from datetime import datetime, timezone
from typing import Any

from openclaw.celery_app import app
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.qlib_update_pipeline")


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


QLIB_KEY = "notifications:qlib"
MAX_NOTIFICATIONS = 200


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
        "id", f"{notification.get('type', 'qlib')}_{int(time.time() * 1000)}"
    )
    r.lpush(key, json.dumps(notification, ensure_ascii=False))
    r.ltrim(key, 0, MAX_NOTIFICATIONS - 1)


@app.task(
    name="openclaw.tasks.qlib_update_pipeline.task_qlib_data_update",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    soft_time_limit=300,
    time_limit=360,
)
def task_qlib_data_update(self) -> dict[str, Any]:
    """Update Qlib binary data from cached parquet files.

    Scheduled at 16:15 CST Mon-Fri, 15 minutes after ``task_fetch_all``
    writes fresh OHLCV parquet to ``data/raw/``.

    The task reads parquet caches and appends new trading days to
    ``~/.qlib/qlib_data/cn_data/`` (shared via Docker volume mount).
    """
    if not _should_execute("task_qlib_data_update"):
        logger.info("task_qlib_data_update: skipped (timeline guard)")
        return {"status": "skipped"}

    logger.info("Starting Qlib data update from parquet cache")

    try:
        from scripts.qlib_data_updater import update_from_cache

        result = update_from_cache()

        if "error" in result:
            logger.error("Qlib data update failed: %s", result["error"])
            raise RuntimeError(result["error"])

        updated = result.get("updated_symbols", 0)
        total_days = result.get("total_days", 0)
        calendar_end = result.get("calendar_end", "unknown")

        # Push notification
        try:
            r = _get_redis()
            _push_notification(
                r,
                QLIB_KEY,
                {
                    "type": "qlib_data_update",
                    "title": "Qlib数据更新完成",
                    "summary": (
                        f"更新 {updated} 只标的, "
                        f"+{total_days} 交易日, "
                        f"日历截止 {calendar_end}"
                    ),
                    "symbol": None,
                    "action": "/admin/qlib-status",
                },
            )
        except Exception as exc:
            logger.warning("Redis notification failed: %s", exc)

        logger.info(
            "Qlib data update complete: %d symbols updated, %d new days, "
            "calendar end %s",
            updated,
            total_days,
            calendar_end,
        )
        return {
            "status": "ok",
            "updated_symbols": updated,
            "total_days": total_days,
            "calendar_end": calendar_end,
        }

    except Exception as exc:
        logger.error("Qlib data update task failed: %s", exc)
        raise self.retry(exc=exc)

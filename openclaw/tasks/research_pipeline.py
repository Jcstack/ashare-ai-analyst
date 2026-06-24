"""Research workstation Celery tasks — sentinel capture and data aggregation.

Provides scheduled tasks for the three-model research pipeline:
- ``task_sentinel_capture``: Gemini-powered news/sentiment scanning (intraday)
- ``task_research_aggregate``: Multi-source Bayesian fusion (post-close)

Follows the same patterns as ``sentiment_pipeline.py``:
timeline guard, Redis notification, graceful error handling.
"""

import json
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from openclaw.celery_app import app
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.research_pipeline")

_CST = ZoneInfo("Asia/Shanghai")


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


RESEARCH_KEY = "notifications:research"
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
        "id", f"{notification.get('type', 'research')}_{int(time.time() * 1000)}"
    )
    r.lpush(key, json.dumps(notification, ensure_ascii=False))
    r.ltrim(key, 0, MAX_NOTIFICATIONS - 1)


@app.task(
    name="openclaw.tasks.research_pipeline.task_sentinel_capture",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def task_sentinel_capture(self) -> dict[str, Any]:
    """Run sentinel capture: news/anomaly/sentiment scanning via Gemini.

    Runs every 30 minutes during trading hours (9:30-15:00 CST).
    Captures current market sentiment for default symbols.

    Results are written to ``data/raw/gemini_sense.json`` and
    summary pushed to Redis ``notifications:research``.
    """
    if not _should_execute("task_sentinel_capture"):
        logger.info("task_sentinel_capture: skipped (timeline guard)")
        return {"status": "skipped"}

    logger.info("Starting sentinel capture task")

    try:
        from src.data.sentinel_capture import SentinelCapture

        capture = SentinelCapture()
        result = capture.capture()

        symbols_count = len(result.get("symbols", []))
        fallback = result.get("fallback_used", True)

        # Push notification
        try:
            r = _get_redis()
            _push_notification(
                r,
                RESEARCH_KEY,
                {
                    "type": "sentinel_capture",
                    "title": "哨兵扫描完成",
                    "summary": f"扫描 {symbols_count} 只标的, "
                    f"{'降级模式' if fallback else 'Gemini合成'}",
                    "symbol": None,
                    "action": "/research",
                },
            )
        except Exception as exc:
            logger.warning("Redis notification failed: %s", exc)

        logger.info(
            "Sentinel capture complete: %d symbols, fallback=%s",
            symbols_count,
            fallback,
        )
        return {
            "status": "ok",
            "symbols": symbols_count,
            "fallback_used": fallback,
        }

    except Exception as exc:
        logger.error("Sentinel capture task failed: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="openclaw.tasks.research_pipeline.task_research_aggregate",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def task_research_aggregate(self) -> dict[str, Any]:
    """Run data aggregation: Bayesian fusion of all research sources.

    Runs daily after market close (e.g. 15:30 CST).
    Produces fused research signals for all default symbols.

    Output: ``scripts/output/reports/research_signal_{date}.json``
    """
    if not _should_execute("task_research_aggregate"):
        logger.info("task_research_aggregate: skipped (timeline guard)")
        return {"status": "skipped"}

    logger.info("Starting research aggregation task")

    try:
        from scripts.data_aggregator import DataAggregator

        aggregator = DataAggregator()

        # Load default symbols from config
        config = load_config("research")
        symbols = config.get("orchestration", {}).get("default_symbols", [])
        if not symbols:
            logger.warning("No default symbols configured")
            return {"status": "ok", "signals": 0}

        date_str = datetime.now(_CST).strftime("%Y-%m-%d")
        results = aggregator.aggregate(symbols, date_str)

        # Push notification with summary
        try:
            r = _get_redis()
            signals_summary = ", ".join(
                f"{r_['symbol']}({r_.get('fusion', {}).get('signal', '?')})"
                for r_ in results[:5]
            )
            _push_notification(
                r,
                RESEARCH_KEY,
                {
                    "type": "research_aggregate",
                    "title": "研究信号聚合完成",
                    "summary": f"{len(results)} 只标的: {signals_summary}",
                    "symbol": None,
                    "action": "/research",
                },
            )
        except Exception as exc:
            logger.warning("Redis notification failed: %s", exc)

        logger.info("Research aggregation complete: %d signals", len(results))
        return {"status": "ok", "signals": len(results)}

    except Exception as exc:
        logger.error("Research aggregation task failed: %s", exc)
        raise self.retry(exc=exc)

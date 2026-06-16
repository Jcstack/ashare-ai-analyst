"""Sentiment scanning and market overview tasks for real-time notifications.

Provides Celery tasks that run during trading hours to detect sentiment
shifts, hot stock entries, and generate market overviews.

Per PRD v2.4 FR-NP001: Intraday sentiment scanning.
Per PRD v2.4 FR-NP002: Market global analysis task.
"""

import json
import time
from datetime import datetime, timezone
from typing import Any

from openclaw.celery_app import app
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.sentiment_pipeline")


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


NOTIFICATIONS_KEY = "notifications:alerts"
MARKET_KEY = "notifications:market"
MAX_NOTIFICATIONS = 200


def _get_redis():
    """Get a Redis client for notification storage."""
    import redis

    config = load_config("openclaw")
    broker = config.get("celery", {}).get("broker_url", "redis://redis:6379/0")
    return redis.from_url(broker, decode_responses=True)


def _strip_exchange_prefix(symbol: str) -> str:
    """Strip exchange prefix from symbol.

    ``'SZ002131'`` → ``'002131'``, ``'600519'`` → ``'600519'``.
    """
    if len(symbol) > 6 and symbol[:2] in ("SZ", "SH", "BJ"):
        return symbol[2:]
    return symbol


def _push_notification(r, key: str, notification: dict[str, Any]) -> None:
    """Push a notification to Redis list, capping at MAX_NOTIFICATIONS."""
    notification.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    notification.setdefault("read", False)
    notification.setdefault(
        "id", f"{notification.get('type', 'alert')}_{int(time.time() * 1000)}"
    )
    r.lpush(key, json.dumps(notification, ensure_ascii=False))
    r.ltrim(key, 0, MAX_NOTIFICATIONS - 1)


@app.task(
    name="openclaw.tasks.sentiment_pipeline.task_sentiment_scan",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def task_sentiment_scan(self) -> dict[str, Any]:
    """Scan hot stocks for sentiment shifts and anomalies.

    Runs every 30 minutes during trading hours (9:30-15:00 CST).
    Checks top 50 hot stocks for:
    - Sentiment score changes
    - New entries in hot rankings
    - Unusual trading anomalies

    Results are pushed to Redis ``notifications:alerts``.
    """
    if not _should_execute("task_sentiment_scan"):
        logger.info("task_sentiment_scan: skipped (timeline guard)")
        return {"status": "skipped", "alerts": 0}

    logger.info("Starting sentiment scan task")
    alerts_generated = 0

    try:
        from src.data.news_fetcher import NewsFetcher

        fetcher = NewsFetcher()
        r = _get_redis()

        # Fetch current hot stocks
        hot_df = fetcher.fetch_hot_rank()
        if hot_df.empty:
            logger.info("No hot rank data available")
            return {"status": "ok", "alerts": 0}

        hot_records = hot_df.head(50).to_dict(orient="records")

        # Batch fetch ALL market anomalies (not per-stock).
        # ak.stock_changes_em(symbol=...) expects a *category* name,
        # not a stock code.  fetch_market_anomalies() handles this.
        all_anomalies = fetcher.fetch_market_anomalies()
        logger.info(
            "Market anomalies fetched: %d records across all categories",
            len(all_anomalies),
        )

        # Cross-match: hot stocks that also appear in anomaly data
        for stock in hot_records[:20]:
            raw_symbol = stock.get("symbol", "")
            name = stock.get("name", "")
            if not raw_symbol:
                continue

            symbol = _strip_exchange_prefix(raw_symbol)

            if all_anomalies.empty:
                continue

            stock_anomalies = all_anomalies[
                all_anomalies["symbol"].astype(str) == symbol
            ]
            for _, row in stock_anomalies.iterrows():
                change_type = str(row.get("change_type", ""))
                desc = str(row.get("description", ""))
                summary = f"[{change_type}] {desc}" if desc else change_type
                _push_notification(
                    r,
                    NOTIFICATIONS_KEY,
                    {
                        "type": "anomaly",
                        "title": f"{name} 异动",
                        "summary": summary,
                        "symbol": symbol,
                        "action": f"/stock/{symbol}",
                    },
                )
                alerts_generated += 1

        # If no market overview exists yet, trigger one so the
        # notification centre is never completely empty.
        if r.llen(MARKET_KEY) == 0:
            logger.info(
                "No market overview data found, triggering task_market_overview",
            )
            task_market_overview.delay()

        logger.info("Sentiment scan complete: %d alerts generated", alerts_generated)
        return {"status": "ok", "alerts": alerts_generated}

    except Exception as exc:
        logger.error("Sentiment scan failed: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="openclaw.tasks.sentiment_pipeline.task_market_overview",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def task_market_overview(self) -> dict[str, Any]:
    """Generate a market-level AI overview.

    Runs at 11:30 (midday) and 15:30 (market close) CST.
    Produces a brief market summary using LLM analysis.

    Results are pushed to Redis ``notifications:market``.
    """
    if not _should_execute("task_market_overview"):
        logger.info("task_market_overview: skipped (timeline guard)")
        return {"status": "skipped"}

    logger.info("Starting market overview task")

    try:
        from src.prediction.realtime_analyzer import RealtimeAnalyzer

        analyzer = RealtimeAnalyzer()
        r = _get_redis()

        overview = analyzer.get_market_overview()
        if overview.get("status") == "error":
            logger.warning("Market overview LLM call failed")
            return {"status": "error", "message": overview.get("summary", "")}

        _push_notification(
            r,
            MARKET_KEY,
            {
                "type": "market_overview",
                "title": "市场概览",
                "summary": overview.get("summary", ""),
                "symbol": None,
                "action": "/intelligence",
            },
        )

        # Also push to alerts for unified notification stream
        _push_notification(
            r,
            NOTIFICATIONS_KEY,
            {
                "type": "market_overview",
                "title": "市场概览",
                "summary": overview.get("summary", ""),
                "symbol": None,
                "action": "/intelligence",
            },
        )

        logger.info("Market overview generated successfully")
        return {"status": "ok", "trend": overview.get("market_trend", "neutral")}

    except Exception as exc:
        logger.error("Market overview failed: %s", exc)
        raise self.retry(exc=exc)

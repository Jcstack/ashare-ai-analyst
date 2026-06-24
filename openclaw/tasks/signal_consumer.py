"""Event bus consumer: Signal Engine — routes market/news events to InvestmentDirector.

Subscribes to ``events:market`` + ``events:news`` via consumer group ``signal_engine``.
Market events (price_spike, volume_anomaly) are filtered by z_score > 2.0;
news events by severity > 0.5.  Qualifying events trigger
``InvestmentDirector.handle_event()``.

Designed to run as a periodic Celery task (e.g. every 60s) that drains the
streams in bounded batches rather than a long-running blocking consumer.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.signal_consumer")

_CONSUMER_GROUP = "signal_engine"
_CONSUMER_NAME = "signal-consumer-worker"
_STREAMS = ["events:market", "events:news"]
_MAX_EVENTS_PER_RUN = 50
_MARKET_Z_SCORE_THRESHOLD = 2.0
_NEWS_SEVERITY_THRESHOLD = 0.5


def _run_async(coro):
    """Run an async coroutine from sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _get_director():
    """Lazy-import the InvestmentDirector singleton."""
    from src.web.dependencies import get_investment_director

    return get_investment_director()


@app.task(
    name="openclaw.tasks.signal_consumer.task_consume_signals",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def task_consume_signals(self) -> dict[str, Any]:
    """Drain events:market + events:news and route qualifying events to InvestmentDirector.

    Returns:
        Summary dict with events_read and events_acted counts.
    """
    events_read = 0
    events_acted = 0

    try:
        from src.event_bus.bus import EventBus

        bus = EventBus()
    except Exception as exc:
        logger.warning("EventBus unavailable, skipping signal consumer: %s", exc)
        return {"status": "bus_unavailable", "events_read": 0, "events_acted": 0}

    try:
        director = _get_director()
    except Exception as exc:
        logger.warning("InvestmentDirector unavailable: %s", exc)
        return {"status": "director_unavailable", "events_read": 0, "events_acted": 0}

    qualifying_events: list[dict[str, Any]] = []

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

        # Filter: market events by z_score, news events by severity
        if stream == "events:market":
            z_score = float(data.get("z_score", 0))
            if z_score < _MARKET_Z_SCORE_THRESHOLD:
                return
        elif stream == "events:news":
            severity = float(data.get("severity", 0))
            if severity < _NEWS_SEVERITY_THRESHOLD:
                return
        else:
            return

        event_dict = {
            "type": event_type,
            "stream": stream,
            "entry_id": entry_id,
            "symbol": data.get("symbol", ""),
            "severity": data.get("severity", data.get("z_score", 0.0)),
            **data,
        }
        qualifying_events.append(event_dict)

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

    # Route qualifying events to InvestmentDirector
    for event_dict in qualifying_events:
        try:
            result = _run_async(director.handle_event(event_dict))
            if result is not None:
                events_acted += 1
        except Exception as exc:
            logger.debug(
                "Director handle_event failed for %s: %s",
                event_dict.get("symbol", "?"),
                exc,
            )

    logger.info(
        "Signal consumer: %d events read, %d acted on",
        events_read,
        events_acted,
    )
    return {
        "status": "ok",
        "events_read": events_read,
        "events_acted": events_acted,
    }

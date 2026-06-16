"""Celery tasks for the Autonomous Trading Loop.

4 beat-scheduled tasks that drive the agent's daily routine:
  - cycle:      every 15 min during trading hours (09:15-15:05)
  - premarket:  08:00 Mon-Fri
  - postmarket: 15:30 Mon-Fri
  - overnight:  20:00 Mon-Fri
"""

from __future__ import annotations

import asyncio
import logging

from openclaw.app import app

logger = logging.getLogger(__name__)


def _get_loop():
    """Lazy-import the trading loop singleton."""
    from src.web.dependencies import get_trading_loop

    return get_trading_loop()


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


@app.task(
    name="openclaw.tasks.trading_loop.task_trading_loop_cycle",
    soft_time_limit=120,
    time_limit=180,
)
def task_trading_loop_cycle():
    """Run one OODA cycle (every 15 min during trading)."""
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        logger.debug("Not a trading day — skipping cycle")
        return {"skipped": True, "reason": "not_trading_day"}

    trading_loop = _get_loop()
    result = _run_async(trading_loop.run_cycle())
    return result.to_dict()


@app.task(
    name="openclaw.tasks.trading_loop.task_trading_loop_premarket",
    soft_time_limit=120,
    time_limit=180,
)
def task_trading_loop_premarket():
    """Morning briefing (08:00 Mon-Fri)."""
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    trading_loop = _get_loop()
    result = _run_async(trading_loop.run_premarket())
    return {"briefing": result}


@app.task(
    name="openclaw.tasks.trading_loop.task_trading_loop_postmarket",
    soft_time_limit=120,
    time_limit=180,
)
def task_trading_loop_postmarket():
    """Evening review (15:30 Mon-Fri)."""
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    trading_loop = _get_loop()
    result = _run_async(trading_loop.run_postmarket())
    return {"review": result}


@app.task(
    name="openclaw.tasks.trading_loop.task_trading_loop_overnight",
    soft_time_limit=300,
    time_limit=360,
)
def task_trading_loop_overnight():
    """Overnight research (20:00 Mon-Fri)."""
    trading_loop = _get_loop()
    result = _run_async(trading_loop.run_overnight())
    return {"result": result}

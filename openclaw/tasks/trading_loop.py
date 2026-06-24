"""Celery tasks for the Autonomous Trading Loop and InvestmentDirector.

Beat-scheduled tasks that drive the agent's daily routine:
  - premarket:        08:00 Mon-Fri  (InvestmentDirector)
  - auction_monitor:  09:15 Mon-Fri  (InvestmentDirector)
  - morning_session:  09:30 Mon-Fri  (InvestmentDirector)
  - cycle:            every 15 min during trading hours (09:30-15:05)
  - late_session:     14:30 Mon-Fri  (InvestmentDirector)
  - close_briefing:   15:05 Mon-Fri  (InvestmentDirector)
  - postmarket:       15:30 Mon-Fri  (InvestmentDirector)
  - overnight:        20:00 Mon-Fri
"""

from __future__ import annotations

import asyncio
import logging

from openclaw.celery_app import app

logger = logging.getLogger(__name__)


def _get_loop():
    """Lazy-import the trading loop singleton."""
    from src.web.dependencies import get_trading_loop

    return get_trading_loop()


def _get_director():
    """Lazy-import the InvestmentDirector singleton."""
    from src.web.dependencies import get_investment_director

    return get_investment_director()


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


def _is_trading_day() -> bool:
    """Check if today is a trading day."""
    from openclaw.timeline_scheduler import TimelineScheduler

    return TimelineScheduler().is_trading_day()


# ------------------------------------------------------------------
# OODA cycle (existing, runs during trading hours)
# ------------------------------------------------------------------


def _try_event_driven(trading_loop):
    """Attempt event-driven cycle if event bus is available.

    Returns CycleResult if event-driven mode ran, None to fall back
    to scheduled mode.
    """
    try:
        from src.event_bus.bus import EventBus

        bus = EventBus()
        # Quick health check — try a simple ping
        bus._redis.ping()
        logger.info("Event bus healthy — running event-driven cycle")
        return _run_async(trading_loop.run_event_driven(bus, timeout=300))
    except Exception as exc:
        logger.debug("Event-driven mode unavailable: %s", exc)
        return None


def _try_director_cycle(trading_loop, director):
    """Attempt Director-coordinated cycle (7-team pipeline).

    Returns CycleResult dict if successful, None to fall back to legacy.
    """
    try:
        result = _run_async(trading_loop.run_cycle_via_director(director))
        logger.info(
            "Director cycle completed — %d proposals, %d errors",
            len(result.proposals_generated),
            len(result.errors),
        )
        return result.to_dict()
    except Exception as exc:
        logger.warning("Director cycle failed, falling back to legacy: %s", exc)
        return None


@app.task(
    name="openclaw.tasks.trading_loop.task_trading_loop_cycle",
    soft_time_limit=120,
    time_limit=180,
)
def task_trading_loop_cycle():
    """Run one OODA cycle (every 15 min during trading).

    Pipeline priority:
      1. Event-driven mode (Redis event bus)
      2. InvestmentDirector coordinate_cycle (7-team pipeline)
      3. Legacy AutonomousTradingLoop.run_cycle() (safety fallback)
    """
    if not _is_trading_day():
        logger.debug("Not a trading day — skipping cycle")
        return {"skipped": True, "reason": "not_trading_day"}

    trading_loop = _get_loop()

    # 1. Try event-driven mode first
    result = _try_event_driven(trading_loop)
    if result is not None:
        return result.to_dict()

    # 2. Try Director coordinate_cycle (7-team pipeline)
    director = _get_director()
    director_result = _try_director_cycle(trading_loop, director)
    if director_result is not None:
        return director_result

    # 3. Fall back to legacy scheduled mode
    logger.info("Using legacy run_cycle() as final fallback")
    result = _run_async(trading_loop.run_cycle())
    return result.to_dict()


# ------------------------------------------------------------------
# InvestmentDirector lifecycle tasks
# ------------------------------------------------------------------


@app.task(
    name="openclaw.tasks.trading_loop.task_trading_loop_premarket",
    soft_time_limit=180,
    time_limit=240,
)
def task_trading_loop_premarket():
    """08:00 — Pre-market brief via InvestmentDirector."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    director = _get_director()
    result = _run_async(director.pre_market_brief())
    return {"briefing": result}


@app.task(
    name="openclaw.tasks.trading_loop.task_auction_monitor",
    soft_time_limit=60,
    time_limit=90,
)
def task_auction_monitor():
    """09:15 — Call auction monitor via InvestmentDirector."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    director = _get_director()
    result = _run_async(director.call_auction_monitor())
    return {"auction": result}


@app.task(
    name="openclaw.tasks.trading_loop.task_morning_session",
    soft_time_limit=60,
    time_limit=90,
)
def task_morning_session():
    """09:30 — Morning session check via InvestmentDirector."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    director = _get_director()
    result = _run_async(director.morning_session())
    return {"morning": result}


@app.task(
    name="openclaw.tasks.trading_loop.task_late_session",
    soft_time_limit=180,
    time_limit=240,
)
def task_late_session():
    """14:30 — Late session decision window via InvestmentDirector."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    director = _get_director()
    result = _run_async(director.late_session())
    return {"late_session": result}


@app.task(
    name="openclaw.tasks.trading_loop.task_close_briefing",
    soft_time_limit=60,
    time_limit=90,
)
def task_close_briefing():
    """15:05 — Close briefing via InvestmentDirector."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    director = _get_director()
    result = _run_async(director.close_briefing())
    return {"close": result}


@app.task(
    name="openclaw.tasks.trading_loop.task_trading_loop_postmarket",
    soft_time_limit=180,
    time_limit=240,
)
def task_trading_loop_postmarket():
    """15:30 — Post-market review via InvestmentDirector."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    director = _get_director()
    result = _run_async(director.post_market_review())
    return {"review": result}


@app.task(
    name="openclaw.tasks.trading_loop.task_fast_scan",
    soft_time_limit=30,
    time_limit=45,
)
def task_fast_scan():
    """5-minute fast scan: stop-loss, leaders, sentiment (no LLM)."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    trading_loop = _get_loop()
    return _run_async(trading_loop.run_fast_scan())


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


# ------------------------------------------------------------------
# Broker health check (Phase 0 — safety net)
# ------------------------------------------------------------------


@app.task(
    name="openclaw.tasks.trading_loop.task_broker_health_check",
    soft_time_limit=30,
    time_limit=45,
)
def task_broker_health_check():
    """Check broker connectivity (every 5 min during trading hours).

    Auto-activates the kill switch after 3 consecutive failures.
    """
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    from src.utils.config import load_config

    try:
        cfg = load_config("broker")
    except Exception:
        cfg = {}

    if cfg.get("mode", "simulation") == "simulation":
        return {"skipped": True, "reason": "simulation_mode"}

    from src.web.dependencies import get_kill_switch, get_redis
    from src.web.services.broker_interface import create_broker
    from src.trading.broker_health import BrokerHealthMonitor

    broker = create_broker()
    kill_switch = get_kill_switch()
    redis_client = get_redis()
    monitor = BrokerHealthMonitor(
        broker=broker,
        kill_switch=kill_switch,
        redis_client=redis_client,
    )
    return monitor.check()


# ------------------------------------------------------------------
# Order lifecycle polling (Phase 2 — fill/rejection tracking)
# ------------------------------------------------------------------


@app.task(
    name="openclaw.tasks.trading_loop.task_order_lifecycle_poll",
    soft_time_limit=30,
    time_limit=45,
)
def task_order_lifecycle_poll():
    """Poll pending broker orders for fill/rejection (every 1 min during trading).

    Detects filled orders and records them in trade_service + action_queue.
    """
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    from src.utils.config import load_config

    try:
        cfg = load_config("broker")
    except Exception:
        cfg = {}

    if cfg.get("mode", "simulation") == "simulation":
        return {"skipped": True, "reason": "simulation_mode"}

    from src.trading.order_lifecycle import OrderLifecycleManager
    from src.web.dependencies import (
        get_action_queue_service,
        get_confirmation_gate,
        get_trade_service,
    )
    from src.web.services.broker_interface import create_broker

    manager = OrderLifecycleManager(
        broker=create_broker(),
        gate=get_confirmation_gate(),
        trade_service=get_trade_service(),
        action_queue=get_action_queue_service(),
    )
    results = manager.poll_pending_orders()
    return {"polled": len(results), "results": results}

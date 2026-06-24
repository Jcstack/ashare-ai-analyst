"""Celery task for the HeartbeatAgent — autonomous investor loop.

One task replaces 8 fixed InvestorAgent sessions. Runs every 5 minutes
during market hours. The LLM decides what to do — the code provides
tools, context, and guardrails.

Schedule:
    Every 5 min, 08:00-15:30, Mon-Fri (trading days only)
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from openclaw.celery_app import app

logger = logging.getLogger(__name__)

_agent_singleton = None
_agent_lock = threading.Lock()


def _get_heartbeat_agent():
    """Lazy-import and build HeartbeatAgent with LLMGateway + ToolRegistry.

    Same dependency injection pattern as InvestorAgent, reuses the same
    ToolRegistry (59 tools).
    """
    global _agent_singleton
    if _agent_singleton is not None:
        return _agent_singleton

    with _agent_lock:
        # Double-check after acquiring lock
        if _agent_singleton is not None:
            return _agent_singleton

        from src.agent_loop.heartbeat_agent import HeartbeatAgent
        from src.llm.gateway import LLMGateway
        from src.llm.router import LLMRouter
        from src.web.dependencies import (
            get_capital_service,
            get_global_market_fetcher,
            get_portfolio_store,
            get_realtime_quote_manager,
        )
        from src.web.services.message_store import MessageStore
        from src.web.services.tool_registry import ToolRegistry

        gateway = LLMGateway(LLMRouter())

        registry = ToolRegistry()
        deps: dict = {
            "realtime_quote_manager": get_realtime_quote_manager(),
            "global_market_fetcher": get_global_market_fetcher(),
            "capital_service": get_capital_service(),
        }
        # Optional deps — degrade gracefully
        for name, getter in [
            ("stock_service", "get_stock_service"),
            ("stock_registry", "get_stock_registry"),
            ("trading_calendar", "get_trading_calendar"),
            ("trend_news_aggregator", "get_trend_news_aggregator"),
        ]:
            try:
                from src.web import dependencies

                deps[name] = getattr(dependencies, getter)()
            except Exception:
                logger.warning("Optional dep '%s' failed to load", name)
        registry.register_all(deps)

        _agent_singleton = HeartbeatAgent(
            gateway=gateway,
            tool_registry=registry,
            portfolio_store=get_portfolio_store(),
            capital_service=get_capital_service(),
            message_store=MessageStore(),
            quote_manager=get_realtime_quote_manager(),
            global_market_fetcher=get_global_market_fetcher(),
        )
        return _agent_singleton


def _run_async(coro: Any) -> Any:
    """Run async coroutine from sync Celery task."""
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

    try:
        scheduler = TimelineScheduler()
        return scheduler.is_trading_day()
    except Exception:
        # Default to True on weekdays
        from datetime import datetime

        return datetime.now().weekday() < 5


@app.task(
    name="openclaw.tasks.heartbeat.task_agent_heartbeat",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    soft_time_limit=480,
    time_limit=540,
)
def task_agent_heartbeat(self: Any) -> dict[str, Any]:
    """5-minute heartbeat — agent decides what to do.

    Replaces 8 fixed InvestorAgent sessions with one self-directing loop.
    The LLM receives market pulse + state and chooses its own workflow.
    """
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    try:
        agent = _get_heartbeat_agent()
        return _run_async(agent.run_heartbeat())
    except Exception as exc:
        logger.error("Heartbeat task failed: %s", exc, exc_info=True)
        return {"error": str(exc)}


@app.task(
    name="openclaw.tasks.heartbeat.task_agent_event_response",
    bind=True,
    max_retries=0,
    soft_time_limit=180,
    time_limit=210,
)
def task_agent_event_response(self: Any, event_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rapid event response — 3-turn mini session ($0.02 budget).

    Triggered by event_agent_consumer when a significant market event
    occurs (price spike, volume anomaly, news break).
    """
    if not event_data:
        return {"skipped": True, "reason": "no_event_data"}

    try:
        agent = _get_heartbeat_agent()
        return _run_async(agent.run_event_response(event_data))
    except Exception as exc:
        logger.error("Event response failed: %s", exc, exc_info=True)
        return {"error": str(exc)}

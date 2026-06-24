"""Celery tasks for the InvestorAgent — Claude Code agent loop.

Replaces the rigid pipeline with LLM-driven sessions at key market times.
The model IS the agent; these tasks are just the scheduled triggers.

Schedule:
    08:00  pre_market     — overnight review, today's strategy
    09:15  call_auction   — gap analysis, holdings expectations
    09:30  market_open    — first observation, immediate risks
    10:30  morning_check  — morning performance, signals
    11:35  midday         — morning summary, afternoon outlook
    13:30  afternoon      — afternoon scan, late session prep
    14:30  late_session   — CRITICAL: final buy/sell decisions
    15:05  close          — day review, P&L, tomorrow plan
"""

from __future__ import annotations

import asyncio
import logging

from openclaw.celery_app import app

logger = logging.getLogger(__name__)


def _get_agent():
    """Lazy-import and build InvestorAgent with LLMGateway + ToolRegistry.

    The ToolRegistry gives the agent 60+ tools to call autonomously.
    The LLM decides which tools to use — the code just executes them.
    """
    from src.agent_loop.investor_agent import InvestorAgent
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

    # Build ToolRegistry with available dependencies.
    # register_all() uses deps.get() — missing services degrade gracefully.
    registry = ToolRegistry()
    deps: dict = {
        "realtime_quote_manager": get_realtime_quote_manager(),
        "global_market_fetcher": get_global_market_fetcher(),
        "capital_service": get_capital_service(),
    }
    # Optional deps — import what's available without crashing
    try:
        from src.web.dependencies import get_stock_service

        deps["stock_service"] = get_stock_service()
    except Exception:
        pass
    try:
        from src.web.dependencies import get_stock_registry

        deps["stock_registry"] = get_stock_registry()
    except Exception:
        pass
    try:
        from src.web.dependencies import get_trading_calendar

        deps["trading_calendar"] = get_trading_calendar()
    except Exception:
        pass
    try:
        from src.web.dependencies import get_trend_news_aggregator

        deps["trend_news_aggregator"] = get_trend_news_aggregator()
    except Exception:
        pass
    registry.register_all(deps)

    return InvestorAgent(
        gateway=gateway,
        tool_registry=registry,
        portfolio_store=get_portfolio_store(),
        capital_service=get_capital_service(),
        message_store=MessageStore(),
        quote_manager=get_realtime_quote_manager(),
        global_market_fetcher=get_global_market_fetcher(),
    )


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


# ---------------------------------------------------------------------------
# Agent session tasks — one per market time slot
# ---------------------------------------------------------------------------


@app.task(
    name="openclaw.tasks.investor_agent.task_pre_market",
    soft_time_limit=300,
    time_limit=360,
)
def task_pre_market():
    """08:00 — Pre-market strategy via InvestorAgent."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    agent = _get_agent()
    return _run_async(agent.run_session("pre_market"))


@app.task(
    name="openclaw.tasks.investor_agent.task_call_auction",
    soft_time_limit=300,
    time_limit=360,
)
def task_call_auction():
    """09:15 — Call auction monitoring via InvestorAgent."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    agent = _get_agent()
    return _run_async(agent.run_session("call_auction"))


@app.task(
    name="openclaw.tasks.investor_agent.task_market_open",
    soft_time_limit=300,
    time_limit=360,
)
def task_market_open():
    """09:30 — Market open observation via InvestorAgent."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    agent = _get_agent()
    return _run_async(agent.run_session("market_open"))


@app.task(
    name="openclaw.tasks.investor_agent.task_morning_check",
    soft_time_limit=300,
    time_limit=360,
)
def task_morning_check():
    """10:30 — Morning check-in via InvestorAgent."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    agent = _get_agent()
    return _run_async(agent.run_session("morning_check"))


@app.task(
    name="openclaw.tasks.investor_agent.task_midday",
    soft_time_limit=300,
    time_limit=360,
)
def task_midday():
    """11:35 — Midday summary via InvestorAgent."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    agent = _get_agent()
    return _run_async(agent.run_session("midday"))


@app.task(
    name="openclaw.tasks.investor_agent.task_afternoon",
    soft_time_limit=300,
    time_limit=360,
)
def task_afternoon():
    """13:30 — Afternoon scan via InvestorAgent."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    agent = _get_agent()
    return _run_async(agent.run_session("afternoon"))


@app.task(
    name="openclaw.tasks.investor_agent.task_late_session",
    soft_time_limit=420,
    time_limit=480,
)
def task_late_session():
    """14:30 — CRITICAL: Late session buy/sell decisions via InvestorAgent."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    agent = _get_agent()
    # Use opus for the most important decision of the day
    # agent._model removed — uses gateway caller routing
    agent._timeout = 240
    return _run_async(agent.run_session("late_session"))


@app.task(
    name="openclaw.tasks.investor_agent.task_close",
    soft_time_limit=300,
    time_limit=360,
)
def task_close():
    """15:05 — Close review via InvestorAgent."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    agent = _get_agent()
    return _run_async(agent.run_session("close"))


# v57.0: Market scan sessions
@app.task(
    name="openclaw.tasks.investor_agent.task_market_scan",
    soft_time_limit=180,
    time_limit=240,
)
def task_market_scan():
    """10:00 + 13:00 — Full market opportunity scan via InvestorAgent."""
    if not _is_trading_day():
        return {"skipped": True, "reason": "not_trading_day"}

    agent = _get_agent()
    return _run_async(agent.run_session("market_scan"))

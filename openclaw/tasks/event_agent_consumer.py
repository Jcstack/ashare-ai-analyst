"""Event-driven agent consumer — triggers mini agent sessions from market events.

Drains ``events:market`` (price spikes, volume anomalies) AND
``events:signal`` (scanner 70+ candidates, intraday signals) and
triggers a constrained mini agent session for qualifying events.

Qualifying:
- events:market — held stock z_score > 2.0, watchlist z_score > 2.5
- events:signal — scanner score > 70 (auto-qualifies, no z-score filter)

Rate-limited: max 15 sessions/hour via Redis counter.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)

_CONSUMER_GROUP = "event_agent"
_CONSUMER_NAME = "event-agent-worker"
_STREAMS = ["events:market", "events:signal"]
_MAX_EVENTS_PER_RUN = 20
_HELD_Z_THRESHOLD = 2.0
_WATCHLIST_Z_THRESHOLD = 2.5
_MAX_SESSIONS_PER_HOUR = 15
_RATE_LIMIT_KEY = "event_agent:hourly_count"


def _is_trading_hours() -> bool:
    """Check if we're in A-share trading hours."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    hour, minute = now.hour, now.minute
    if now.weekday() >= 5:
        return False
    # 09:30-11:30, 13:00-15:00
    if (hour == 9 and minute >= 30) or (10 <= hour <= 10):
        return True
    if hour == 11 and minute <= 30:
        return True
    if 13 <= hour <= 14:
        return True
    return False


def _get_held_symbols() -> set[str]:
    """Get currently held stock symbols."""
    try:
        from src.web.dependencies import get_portfolio_store

        ps = get_portfolio_store()
        if ps:
            positions = ps.list_positions()
            return {p.get("symbol", "") for p in positions if p.get("symbol")}
    except Exception:
        pass
    try:
        from src.web.dependencies import get_trade_service

        svc = get_trade_service()
        if svc and hasattr(svc, "broker"):
            positions = svc.broker.get_positions()
            return {p.symbol for p in positions}
    except Exception:
        pass
    return set()


def _check_rate_limit() -> bool:
    """Check if we're under the hourly session limit. Returns True if OK."""
    try:
        import redis

        r = redis.Redis(host="redis", port=6379, db=0)
        count = r.incr(_RATE_LIMIT_KEY)
        if count == 1:
            r.expire(_RATE_LIMIT_KEY, 3600)
        return count <= _MAX_SESSIONS_PER_HOUR
    except Exception:
        return True  # Allow if Redis unavailable


def _run_mini_session(symbol: str, event_data: dict[str, Any]) -> dict[str, Any]:
    """Trigger a mini HeartbeatAgent event response via Celery task.

    Dispatches asynchronously to avoid blocking the consumer.
    Falls back to synchronous InvestorAgent if heartbeat task unavailable.
    """
    try:
        from openclaw.tasks.heartbeat import task_agent_event_response

        # Async dispatch — returns immediately
        task_agent_event_response.delay(event_data)
        return {"status": "dispatched", "symbol": symbol}
    except Exception:
        logger.warning("Heartbeat dispatch failed, falling back to InvestorAgent")
        import asyncio

        from src.agent_loop.investor_agent import InvestorAgent
        from src.web.dependencies import (
            get_capital_service,
            get_llm_gateway,
            get_realtime_quote_manager,
            get_tool_registry,
        )
        from src.web.services.message_store import MessageStore

        gateway = get_llm_gateway()
        registry = get_tool_registry()

        agent = InvestorAgent(
            gateway=gateway,
            tool_registry=registry,
            message_store=MessageStore(),
            quote_manager=get_realtime_quote_manager(),
            capital_service=get_capital_service(),
        )

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                agent.run_session(
                    "event_triggered",
                    symbol=symbol,
                    event_data=event_data,
                )
            )
        finally:
            loop.close()


@shared_task(
    name="openclaw.tasks.event_agent_consumer.task_event_driven_agent_consumer",
    bind=True,
    max_retries=0,
    soft_time_limit=55,
    time_limit=60,
)
def task_event_driven_agent_consumer(self: Any) -> dict[str, Any]:
    """Drain events:market and trigger mini agent sessions for qualifying events.

    Runs every minute during trading hours. Each invocation:
    1. Drains up to 20 events from events:market
    2. Filters by z-score threshold (held stocks lower, watchlist higher)
    3. Triggers mini InvestorAgent sessions (max 10/hour)
    """
    if not _is_trading_hours():
        return {"status": "outside_trading_hours"}

    result: dict[str, Any] = {
        "events_read": 0,
        "events_qualifying": 0,
        "sessions_triggered": 0,
        "errors": [],
    }

    try:
        from src.event_bus.bus import EventBus

        bus = EventBus()
    except Exception as exc:
        return {"status": "event_bus_unavailable", "error": str(exc)}

    held_symbols = _get_held_symbols()
    qualifying: list[dict[str, Any]] = []

    def _handle(stream: str, entry_id: str, parsed: dict[str, Any]) -> None:
        result["events_read"] += 1
        data = parsed.get("data", parsed)
        symbol = data.get("symbol", "")

        if not symbol:
            return

        # Scanner signals (events:signal) — type-specific thresholds.
        # Scanner candidates (LeaderDetector 70+) keep high bar.
        # Call auction signals have lower natural confidence (0.3-0.5)
        # and use a separate threshold to avoid being filtered out.
        source = data.get("source", "")
        event_type_raw = data.get("type", "")
        if stream == "events:signal" or source == "market_scanner":
            confidence = float(data.get("confidence", 0))
            # Call auction / intraday signals use lower threshold
            if event_type_raw in ("call_auction", "intraday_signal"):
                threshold = 0.35
            else:
                threshold = 0.7  # Scanner score 70+
            if confidence >= threshold:
                qualifying.append(
                    {
                        "symbol": symbol,
                        "z_score": 0,
                        "confidence": confidence,
                        "event_type": event_type_raw or "scanner_candidate",
                        **data,
                    }
                )
            return

        # Market events (price spikes, volume anomalies) — z-score filter
        z_score = float(data.get("z_score", 0))
        if symbol in held_symbols:
            threshold = _HELD_Z_THRESHOLD
        else:
            threshold = _WATCHLIST_Z_THRESHOLD

        if z_score >= threshold:
            qualifying.append(
                {
                    "symbol": symbol,
                    "z_score": z_score,
                    "event_type": parsed.get("type", "unknown"),
                    **data,
                }
            )

    try:
        bus.subscribe(
            streams=_STREAMS,
            consumer_group=_CONSUMER_GROUP,
            consumer_name=_CONSUMER_NAME,
            callback=_handle,
            batch_size=_MAX_EVENTS_PER_RUN,
            block_ms=1000,
            max_iterations=1,
        )
    except Exception as exc:
        logger.warning("Event bus subscribe failed: %s", exc)
        result["errors"].append(str(exc))

    result["events_qualifying"] = len(qualifying)

    # Trigger mini sessions for qualifying events
    for event in qualifying:
        if not _check_rate_limit():
            logger.info("Event agent hourly rate limit reached")
            break

        symbol = event["symbol"]
        try:
            session_result = _run_mini_session(symbol, event)
            result["sessions_triggered"] += 1
            logger.info(
                "Event-triggered session for %s: %s",
                symbol,
                session_result,
            )
        except Exception as exc:
            logger.warning("Mini session failed for %s: %s", symbol, exc)
            result["errors"].append(f"{symbol}: {exc}")

    if result["sessions_triggered"]:
        logger.info(
            "Event agent: %d events → %d qualifying → %d sessions",
            result["events_read"],
            result["events_qualifying"],
            result["sessions_triggered"],
        )

    return result

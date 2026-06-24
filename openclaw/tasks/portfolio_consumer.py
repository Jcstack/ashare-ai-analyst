"""Event bus consumer: Portfolio Engine — updates DailyPlan and position limits.

Subscribes to ``events:signal`` + ``events:portfolio`` + ``events:regime`` via
consumer group ``portfolio_engine``.

- Converged signals: update DailyPlan buy/sell candidates in SharedBeliefState.
- Regime changes: recalculate position limits via ``belief_state.get_position_limits()``.
- Portfolio changes: publish summary to ``events:portfolio`` for other consumers.

Designed to run as a periodic Celery task (e.g. every 60s) that drains the
streams in bounded batches rather than a long-running blocking consumer.
"""

from __future__ import annotations

import json
from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.portfolio_consumer")

_CONSUMER_GROUP = "portfolio_engine"
_CONSUMER_NAME = "portfolio-consumer-worker"
_STREAMS = ["events:signal", "events:portfolio", "events:regime"]
_MAX_EVENTS_PER_RUN = 50
_SIGNAL_CONFIDENCE_THRESHOLD = 0.5


@app.task(
    name="openclaw.tasks.portfolio_consumer.task_consume_portfolio_events",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def task_consume_portfolio_events(self) -> dict[str, Any]:
    """Drain signal/portfolio/regime streams and update DailyPlan + position limits.

    Returns:
        Summary dict with events_read, plan_updates, regime_recalcs, and
        portfolio_publishes counts.
    """
    events_read = 0
    plan_updates = 0
    regime_recalcs = 0
    portfolio_publishes = 0

    try:
        from src.event_bus.bus import EventBus

        bus = EventBus()
    except Exception as exc:
        logger.warning("EventBus unavailable, skipping portfolio consumer: %s", exc)
        return {
            "status": "bus_unavailable",
            "events_read": 0,
            "plan_updates": 0,
            "regime_recalcs": 0,
            "portfolio_publishes": 0,
        }

    try:
        from src.web.dependencies import get_shared_belief_state

        belief_state = get_shared_belief_state()
    except Exception as exc:
        logger.warning("SharedBeliefState unavailable: %s", exc)
        return {
            "status": "belief_state_unavailable",
            "events_read": 0,
            "plan_updates": 0,
            "regime_recalcs": 0,
            "portfolio_publishes": 0,
        }

    def _handle_event(stream: str, entry_id: str, parsed: dict[str, Any]) -> None:
        nonlocal events_read, plan_updates, regime_recalcs, portfolio_publishes
        events_read += 1

        data = parsed.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                data = {}

        # --- Converged signals: update DailyPlan buy/sell candidates ---
        if stream == "events:signal":
            symbol = data.get("symbol", "")
            direction = data.get("direction", "neutral")
            confidence = float(data.get("confidence", 0))
            reason = data.get("reason", "")

            if confidence < _SIGNAL_CONFIDENCE_THRESHOLD or not symbol:
                return

            plan = belief_state.daily_plan
            candidate = {
                "symbol": symbol,
                "direction": direction,
                "confidence": confidence,
                "reason": reason[:100] if reason else "",
                "source": data.get("source", "event_bus"),
            }

            if direction in ("buy", "long"):
                # Avoid duplicates in buy candidates
                existing_symbols = {c.get("symbol") for c in plan.buy_candidates}
                if symbol not in existing_symbols:
                    plan.buy_candidates.append(candidate)
                    belief_state.set_daily_plan(plan)
                    plan_updates += 1
                    logger.info(
                        "Added %s to DailyPlan buy candidates (conf=%.2f)",
                        symbol,
                        confidence,
                    )
            elif direction in ("sell", "short"):
                existing_symbols = {c.get("symbol") for c in plan.sell_plan}
                if symbol not in existing_symbols:
                    plan.sell_plan.append(candidate)
                    belief_state.set_daily_plan(plan)
                    plan_updates += 1
                    logger.info(
                        "Added %s to DailyPlan sell plan (conf=%.2f)",
                        symbol,
                        confidence,
                    )

        # --- Regime changes: recalculate position limits ---
        elif stream == "events:regime":
            try:
                limits = belief_state.get_position_limits()
                belief_state.update_cash_strategy()
                regime_recalcs += 1
                logger.info(
                    "Position limits recalculated: max_pos=%.0f%%, max_eq=%.0f%%, buys=%s",
                    limits.get("max_position_pct", 0) * 100,
                    limits.get("max_equity_pct", 0) * 100,
                    limits.get("buys_allowed", True),
                )
            except Exception as exc:
                logger.debug("Failed to recalculate position limits: %s", exc)

        # --- Portfolio changes: publish summary for other consumers ---
        elif stream == "events:portfolio":
            try:
                from src.web.dependencies import get_portfolio_store

                portfolio_store = get_portfolio_store()
                positions = portfolio_store.list_positions()
                summary = {
                    "position_count": len(positions),
                    "symbols": [p.get("symbol", "") for p in positions[:20]],
                    "source": "portfolio_consumer",
                }
                bus.publish("events:portfolio", "portfolio_summary", summary)
                portfolio_publishes += 1
            except Exception as exc:
                logger.debug("Failed to publish portfolio summary: %s", exc)

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

    logger.info(
        "Portfolio consumer: %d events, %d plan updates, %d regime recalcs, %d publishes",
        events_read,
        plan_updates,
        regime_recalcs,
        portfolio_publishes,
    )
    return {
        "status": "ok",
        "events_read": events_read,
        "plan_updates": plan_updates,
        "regime_recalcs": regime_recalcs,
        "portfolio_publishes": portfolio_publishes,
    }

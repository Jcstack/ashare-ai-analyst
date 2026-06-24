"""Event bus consumer: Risk Engine — monitors portfolio/market/regime events for risk.

Subscribes to ``events:portfolio`` + ``events:market`` + ``events:regime`` via
consumer group ``risk_engine``.

- Regime events: update SharedBeliefState regime fields.
- Market events for held positions: check price against stop-loss thresholds.
- Risk budget exhaustion: publish risk_alert via ``publish_risk_alert()``.

Designed to run as a periodic Celery task (e.g. every 60s) that drains the
streams in bounded batches rather than a long-running blocking consumer.
"""

from __future__ import annotations

import json
from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.risk_consumer")

_CONSUMER_GROUP = "risk_engine"
_CONSUMER_NAME = "risk-consumer-worker"
_STREAMS = ["events:portfolio", "events:market", "events:regime"]
_MAX_EVENTS_PER_RUN = 50


@app.task(
    name="openclaw.tasks.risk_consumer.task_consume_risk_events",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def task_consume_risk_events(self) -> dict[str, Any]:
    """Drain risk-relevant streams and update SharedBeliefState / publish alerts.

    Returns:
        Summary dict with events_read, regime_updates, stop_loss_alerts, and
        risk_alerts counts.
    """
    events_read = 0
    regime_updates = 0
    stop_loss_alerts = 0
    risk_alerts = 0

    try:
        from src.event_bus.bus import EventBus

        bus = EventBus()
    except Exception as exc:
        logger.warning("EventBus unavailable, skipping risk consumer: %s", exc)
        return {
            "status": "bus_unavailable",
            "events_read": 0,
            "regime_updates": 0,
            "stop_loss_alerts": 0,
            "risk_alerts": 0,
        }

    try:
        from src.web.dependencies import get_shared_belief_state

        belief_state = get_shared_belief_state()
    except Exception as exc:
        logger.warning("SharedBeliefState unavailable: %s", exc)
        return {
            "status": "belief_state_unavailable",
            "events_read": 0,
            "regime_updates": 0,
            "stop_loss_alerts": 0,
            "risk_alerts": 0,
        }

    try:
        from src.web.dependencies import get_portfolio_store

        portfolio_store = get_portfolio_store()
        positions = portfolio_store.list_positions()
    except Exception as exc:
        logger.warning("PortfolioStore unavailable: %s", exc)
        positions = []

    # Index held positions by symbol for O(1) lookup
    positions_by_symbol: dict[str, dict[str, Any]] = {}
    for pos in positions:
        sym = pos.get("symbol", "")
        if sym:
            positions_by_symbol[sym] = pos

    def _handle_event(stream: str, entry_id: str, parsed: dict[str, Any]) -> None:
        nonlocal events_read, regime_updates, stop_loss_alerts, risk_alerts
        events_read += 1

        data = parsed.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                data = {}

        # --- Regime events: update SharedBeliefState ---
        if stream == "events:regime":
            try:
                update_kwargs: dict[str, Any] = {}
                if data.get("phase"):
                    update_kwargs["sentiment_phase"] = data["phase"]
                if data.get("phase_cn"):
                    update_kwargs["sentiment_phase_cn"] = data["phase_cn"]
                if data.get("hmm_state"):
                    update_kwargs["hmm_state"] = data["hmm_state"]
                if data.get("reflexivity_state"):
                    update_kwargs["reflexivity_state"] = data["reflexivity_state"]
                if update_kwargs:
                    belief_state.update_regime(**update_kwargs)
                    regime_updates += 1
            except Exception as exc:
                logger.debug("Failed to update regime from event %s: %s", entry_id, exc)

        # --- Market events for held positions: check stop-loss ---
        elif stream == "events:market":
            symbol = data.get("symbol", "")
            if symbol in positions_by_symbol:
                pos = positions_by_symbol[symbol]
                event_price = float(data.get("price", 0))
                stop_loss = float(pos.get("stop_loss", 0))

                if event_price > 0 and stop_loss > 0 and event_price <= stop_loss:
                    stop_loss_alerts += 1
                    logger.warning(
                        "STOP-LOSS breach: %s price=%.2f <= stop=%.2f",
                        symbol,
                        event_price,
                        stop_loss,
                    )
                    try:
                        from src.event_bus.producers import publish_risk_alert

                        publish_risk_alert(
                            alert_type="stop_loss_breach",
                            symbol=symbol,
                            severity=0.9,
                            message=(
                                f"{symbol} 触发止损: 当前价 {event_price:.2f} "
                                f"<= 止损价 {stop_loss:.2f}"
                            ),
                        )
                    except Exception as exc:
                        logger.debug("Failed to publish stop-loss alert: %s", exc)

        # --- Portfolio events: check risk budget ---
        elif stream == "events:portfolio":
            if belief_state.risk_budget.is_halted:
                risk_alerts += 1
                logger.warning("Risk budget exhausted — publishing halt alert")
                try:
                    from src.event_bus.producers import publish_risk_alert

                    publish_risk_alert(
                        alert_type="risk_budget_exhausted",
                        symbol="PORTFOLIO",
                        severity=1.0,
                        message="每日风险预算已耗尽，交易暂停",
                    )
                except Exception as exc:
                    logger.debug("Failed to publish risk budget alert: %s", exc)

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
        "Risk consumer: %d events, %d regime updates, %d stop-loss, %d risk alerts",
        events_read,
        regime_updates,
        stop_loss_alerts,
        risk_alerts,
    )
    return {
        "status": "ok",
        "events_read": events_read,
        "regime_updates": regime_updates,
        "stop_loss_alerts": stop_loss_alerts,
        "risk_alerts": risk_alerts,
    }

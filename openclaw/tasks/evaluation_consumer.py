"""Event bus consumer: Evaluation Team — tracks thesis lifecycle and validates positions.

Subscribes to ``events:portfolio`` + ``events:thesis`` via consumer group
``evaluation_team``.

- Thesis changes: log state transitions, update ThesisTracker.
- Portfolio changes: check thesis invalidation conditions against current prices.
- Publishes to ``events:thesis`` if thesis confidence changes.

Designed to run as a periodic Celery task (e.g. every 60s) that drains the
streams in bounded batches rather than a long-running blocking consumer.
"""

from __future__ import annotations

import json
from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.evaluation_consumer")

_CONSUMER_GROUP = "evaluation_team"
_CONSUMER_NAME = "evaluation-consumer-worker"
_STREAMS = ["events:portfolio", "events:thesis"]
_MAX_EVENTS_PER_RUN = 50


@app.task(
    name="openclaw.tasks.evaluation_consumer.task_consume_evaluation_events",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def task_consume_evaluation_events(self) -> dict[str, Any]:
    """Drain portfolio/thesis streams and manage thesis lifecycle.

    Returns:
        Summary dict with events_read, thesis_updates, invalidations_checked,
        and thesis_publishes counts.
    """
    events_read = 0
    thesis_updates = 0
    invalidations_checked = 0
    thesis_publishes = 0

    try:
        from src.event_bus.bus import EventBus

        bus = EventBus()
    except Exception as exc:
        logger.warning("EventBus unavailable, skipping evaluation consumer: %s", exc)
        return {
            "status": "bus_unavailable",
            "events_read": 0,
            "thesis_updates": 0,
            "invalidations_checked": 0,
            "thesis_publishes": 0,
        }

    try:
        from src.web.dependencies import get_thesis_tracker

        tracker = get_thesis_tracker()
    except Exception as exc:
        logger.warning("ThesisTracker unavailable: %s", exc)
        return {
            "status": "tracker_unavailable",
            "events_read": 0,
            "thesis_updates": 0,
            "invalidations_checked": 0,
            "thesis_publishes": 0,
        }

    def _handle_event(stream: str, entry_id: str, parsed: dict[str, Any]) -> None:
        nonlocal events_read, thesis_updates, invalidations_checked, thesis_publishes
        events_read += 1

        data = parsed.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                data = {}

        # --- Thesis events: log state transitions, update tracker ---
        if stream == "events:thesis":
            thesis_id = data.get("thesis_id", "")
            symbol = data.get("symbol", "")
            status = data.get("status", "")
            confidence = float(data.get("confidence", 0))

            if not thesis_id:
                return

            logger.info(
                "Thesis state change: %s (%s) -> %s (conf=%.2f)",
                thesis_id[:8],
                symbol,
                status,
                confidence,
            )

            # If the thesis is weakening, add evidence about the confidence drop
            thesis = tracker.get_thesis(thesis_id)
            if thesis and thesis.status != status:
                # The thesis_tracker itself already persists status via add_evidence
                # or direct status changes. Here we log and track the transition.
                thesis_updates += 1

                # If confidence dropped significantly, publish an updated event
                if (
                    thesis.current_confidence > 0
                    and abs(thesis.current_confidence - confidence) > 0.05
                ):
                    try:
                        from src.event_bus.producers import publish_thesis_change

                        publish_thesis_change(
                            thesis_id=thesis_id,
                            symbol=symbol,
                            status=status,
                            confidence=confidence,
                        )
                        thesis_publishes += 1
                    except Exception as exc:
                        logger.debug("Failed to publish thesis change: %s", exc)

        # --- Portfolio events: check thesis invalidation conditions ---
        elif stream == "events:portfolio":
            # Get current active theses and check invalidation conditions
            try:
                active_theses = tracker.get_active_theses()
                for thesis in active_theses:
                    symbol = thesis.symbol

                    # Try to get a current price from the event data
                    # Portfolio events may include price/market data
                    price = float(data.get("price", 0))
                    event_symbol = data.get("symbol", "")

                    # Only check if the event is for this thesis's symbol
                    if event_symbol and event_symbol != symbol:
                        continue

                    if price > 0:
                        was_invalidated = tracker.check_invalidation(
                            thesis.id,
                            current_price=price,
                            market_data=data,
                        )
                        invalidations_checked += 1

                        if was_invalidated:
                            logger.warning(
                                "Thesis %s (%s) INVALIDATED by portfolio event (price=%.2f)",
                                thesis.id[:8],
                                symbol,
                                price,
                            )
                            # Publish invalidation event
                            try:
                                from src.event_bus.producers import (
                                    publish_thesis_change,
                                )

                                publish_thesis_change(
                                    thesis_id=thesis.id,
                                    symbol=symbol,
                                    status="invalidated",
                                    confidence=thesis.current_confidence,
                                )
                                thesis_publishes += 1
                            except Exception as exc:
                                logger.debug(
                                    "Failed to publish thesis invalidation: %s", exc
                                )
            except Exception as exc:
                logger.debug("Failed to check thesis invalidation: %s", exc)

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
        "Evaluation consumer: %d events, %d thesis updates, %d invalidation checks, %d publishes",
        events_read,
        thesis_updates,
        invalidations_checked,
        thesis_publishes,
    )
    return {
        "status": "ok",
        "events_read": events_read,
        "thesis_updates": thesis_updates,
        "invalidations_checked": invalidations_checked,
        "thesis_publishes": thesis_publishes,
    }

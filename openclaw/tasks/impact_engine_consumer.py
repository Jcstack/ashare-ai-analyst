"""Event bus consumer: Impact Engine — processes news events into trading signals.

Subscribes to ``events:news`` via Redis Streams consumer group and runs each
event through the EventImpactEngine causal chain pipeline. Resulting signals
are published to ``events:signal`` and significant chains are stored as
MessageStore entries.

Designed to run as a periodic Celery task (e.g. every 60s) that drains the
stream in bounded batches rather than a long-running blocking consumer.

Part of v50.0 Gap 4: Wire Impact Engine into intelligence pipeline via event bus.
"""

from __future__ import annotations

from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.impact_engine_consumer")

# Consumer group / consumer name for this task
_CONSUMER_GROUP = "signal_engine"
_CONSUMER_NAME = "impact-engine-worker"
_STREAM = "events:news"
_MAX_EVENTS_PER_RUN = 50
_MIN_SIGNAL_CONFIDENCE = 0.3
_MESSAGE_CONFIDENCE_THRESHOLD = 0.5


@app.task(
    name="openclaw.tasks.impact_engine_consumer.task_consume_news_for_impact",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def task_consume_news_for_impact(self) -> dict[str, Any]:
    """Drain events:news and process each through the Impact Engine.

    Reads up to _MAX_EVENTS_PER_RUN events from the ``events:news`` stream
    using a consumer group, constructs causal chains, and publishes resulting
    signals to ``events:signal``.

    Returns:
        Summary dict with events_read, signals_produced, and messages_created counts.
    """
    events_read = 0
    signals_produced = 0
    messages_created = 0

    try:
        from src.event_bus.bus import EventBus

        bus = EventBus()
    except Exception as exc:
        logger.warning("EventBus unavailable, skipping impact consumer: %s", exc)
        return {
            "status": "bus_unavailable",
            "events_read": 0,
            "signals_produced": 0,
            "messages_created": 0,
        }

    try:
        from src.web.dependencies import get_impact_engine

        engine = get_impact_engine()
    except Exception as exc:
        logger.warning("ImpactEngine unavailable: %s", exc)
        return {
            "status": "engine_unavailable",
            "events_read": 0,
            "signals_produced": 0,
            "messages_created": 0,
        }

    collected_signals: list[dict[str, Any]] = []

    def _handle_event(stream: str, entry_id: str, parsed: dict[str, Any]) -> None:
        nonlocal events_read
        events_read += 1

        data = parsed.get("data", {})
        event_type = parsed.get("type", "unknown")

        # Build event dict compatible with ImpactEngine.process_event()
        event = {
            "title": data.get("title", ""),
            "summary": data.get("summary", ""),
            "description": data.get("description", ""),
            "confidence": data.get("severity", 0.6),
            "sectors": data.get("sectors", []),
            "event_id": entry_id,
            "event_type": event_type,
        }

        try:
            signals = engine.process_event(event)
            if not signals:
                # Template match failed — try async LLM fallback for novel events
                import asyncio

                try:
                    llm_signals = asyncio.run(engine.process_event_async(event))
                    if llm_signals:
                        signals = llm_signals
                        logger.info(
                            "LLM fallback produced %d signals for event %s",
                            len(llm_signals),
                            entry_id,
                        )
                except Exception as llm_exc:
                    logger.debug(
                        "LLM fallback failed for event %s: %s", entry_id, llm_exc
                    )
            collected_signals.extend(signals)
        except Exception as exc:
            logger.debug("ImpactEngine failed for event %s: %s", entry_id, exc)

        # Populate knowledge graph with event and affected stocks (v50.0 SS 6.4)
        try:
            from src.web.dependencies import get_knowledge_graph

            kg = get_knowledge_graph()
            kg.add_event(
                event_id=entry_id,
                title=event.get("title", ""),
                event_type=event_type,
                severity=event.get("confidence", 0.5),
            )
            for sig in signals:
                sym = sig.get("symbol", "")
                if sym:
                    kg.add_stock(sym)
                    kg.add_edge(
                        source=sym,
                        target=entry_id,
                        relation="affected_by",
                        confidence=sig.get("confidence", 0.5),
                        decay_rate=0.05,
                    )
                    # Add sector edges from signal metadata
                    for sect in event.get("sectors", []):
                        if isinstance(sect, str) and sect:
                            kg.add_sector(sect, name=sect)
                            kg.add_edge(
                                source=sym,
                                target=sect,
                                relation="belongs_to",
                                confidence=1.0,
                            )
        except Exception as exc:
            logger.debug("KG population failed for event %s: %s", entry_id, exc)

    # Read events in a bounded batch (1 iteration of the subscribe loop)
    try:
        bus.subscribe(
            streams=[_STREAM],
            consumer_group=_CONSUMER_GROUP,
            consumer_name=_CONSUMER_NAME,
            callback=_handle_event,
            batch_size=_MAX_EVENTS_PER_RUN,
            block_ms=1000,  # Short block — this is a periodic task, not a daemon
            max_iterations=1,
        )
    except Exception as exc:
        logger.warning("EventBus subscribe failed: %s", exc)

    if not collected_signals:
        return {
            "status": "ok",
            "events_read": events_read,
            "signals_produced": 0,
            "messages_created": 0,
        }

    # Publish tradeable signals to events:signal
    try:
        from src.event_bus.producers import publish_signal_detected

        for sig in collected_signals:
            if sig.get("confidence", 0) < _MIN_SIGNAL_CONFIDENCE:
                continue
            publish_signal_detected(
                symbol=sig.get("symbol", ""),
                direction=sig.get("direction", "neutral"),
                source=sig.get("source", "impact_chain"),
                confidence=sig.get("confidence", 0.5),
                reason=sig.get("metadata", {}).get("impact", ""),
            )
            signals_produced += 1
    except Exception as exc:
        logger.warning("Failed to publish impact signals: %s", exc)

    # Create MessageStore entries for significant impact chains
    # Group signals by symbol for consolidated messages
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for sig in collected_signals:
        sym = sig.get("symbol", "")
        if sym and sig.get("confidence", 0) > _MESSAGE_CONFIDENCE_THRESHOLD:
            by_symbol.setdefault(sym, []).append(sig)

    if by_symbol:
        try:
            from src.web.services.message_store import MessageStore

            store = MessageStore()
            for sym, sigs in by_symbol.items():
                max_conf = max(s.get("confidence", 0) for s in sigs)
                chain_summary = "; ".join(
                    f"{s['metadata'].get('impact', '')}({s.get('direction', '')})"
                    for s in sigs[:5]
                    if s.get("metadata")
                )
                store.create_message(
                    symbol=sym,
                    msg_type="impact_chain",
                    title=f"事件影响链：{sym}",
                    summary=chain_summary[:200] if chain_summary else "多维度事件影响",
                    priority="high" if max_conf > 0.7 else "medium",
                )
                messages_created += 1
        except Exception as exc:
            logger.warning("Failed to create impact chain messages: %s", exc)

    logger.info(
        "Impact engine consumer: %d events → %d signals, %d messages",
        events_read,
        signals_produced,
        messages_created,
    )
    return {
        "status": "ok",
        "events_read": events_read,
        "signals_produced": signals_produced,
        "messages_created": messages_created,
    }

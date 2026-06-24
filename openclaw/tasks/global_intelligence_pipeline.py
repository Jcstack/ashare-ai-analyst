"""Global Intelligence Pipeline — Celery tasks for the 4-team agent system.

Sentinel → Analyst → Strategist → Messenger pipeline.
"""

import asyncio
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run async coroutine in sync Celery task context.

    Uses asyncio.run() which creates a fresh event loop each time.
    Falls back to thread-pool executor if a loop is already running.
    """
    # Guard: if caller accidentally passes a non-coroutine, return it directly
    if not asyncio.iscoroutine(coro) and not asyncio.isfuture(coro):
        return coro

    try:
        return asyncio.run(coro)
    except RuntimeError:
        # Event loop already running (e.g., inside Jupyter or nested context)
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()


@shared_task(
    name="openclaw.tasks.global_intelligence.task_sentinel_crawl",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def task_sentinel_crawl(self):
    """Sentinel team: crawl all RSS feeds and publish to event bus (every 5 min)."""
    try:
        from src.intelligence.agents.rss_crawler_agent import get_rss_crawler_agent

        from dataclasses import asdict

        agent = get_rss_crawler_agent()
        result = agent.crawl()
        logger.info("Sentinel crawl: %s", result)
        return asdict(result)
    except Exception as exc:
        logger.error("Sentinel crawl failed: %s", exc)
        raise self.retry(exc=exc)


@shared_task(
    name="openclaw.tasks.global_intelligence.task_cn_news_crawl",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def task_cn_news_crawl(self):
    """Sentinel team: fetch Chinese A-share news directly (every 10 min).

    Bypasses broken rsshub.app RSS feeds. Calls CLS, WSCN, Jin10, Sina 7x24
    APIs directly and stores to InfoStore.
    """
    try:
        from src.data.cn_news_direct import CnNewsDirectFetcher
        from src.web.dependencies import get_info_store

        fetcher = CnNewsDirectFetcher()
        items = fetcher.fetch_all_sync(limit=50)

        if not items:
            return {"status": "ok", "items": 0}

        info_store = get_info_store()
        from src.intelligence_hub.models import InfoItem

        info_items = []
        for item in items:
            info_items.append(
                InfoItem(
                    source_id=f"cn_direct:{item.source}",
                    source_name=item.source,
                    title=item.title,
                    summary=item.content[:500],
                    url=item.url,
                    category="market",
                    priority="high" if item.is_important else "normal",
                    published_at=item.publish_time.strftime("%Y-%m-%d %H:%M:%S"),
                )
            )

        stored, errors = info_store.store_batch(info_items)
        if errors:
            logger.debug("CN news dedup: %d duplicates skipped", len(errors))

        logger.info("CN news crawl: %d fetched, %d stored", len(items), stored)
        return {"status": "ok", "fetched": len(items), "stored": stored}
    except Exception as exc:
        logger.error("CN news crawl failed: %s", exc)
        return {"error": str(exc)}


@shared_task(
    name="openclaw.tasks.global_intelligence.task_macro_pulse",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def task_macro_pulse(self):
    """Sentinel team: check macro data releases (every 1 min during windows)."""
    try:
        from src.intelligence.agents.macro_pulse_agent import get_macro_pulse_agent

        agent = get_macro_pulse_agent()
        result = agent.check_releases()
        if result and result.surprises:
            logger.info("Macro surprise detected: %s", result.surprises)
        return {
            "data_releases": len(result.data_releases),
            "surprises": [s.to_dict() for s in result.surprises],
            "alerts": result.alerts,
        }
    except Exception as exc:
        logger.error("Macro pulse failed: %s", exc)
        return {"error": str(exc)}


@shared_task(
    name="openclaw.tasks.global_intelligence.task_wire_digest",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def task_wire_digest(self):
    """Sentinel team: generate global market wire digest (every 30 min)."""
    try:
        from src.intelligence.agents.wire_digest_agent import get_wire_digest_agent

        agent = get_wire_digest_agent()
        pulse = agent.generate_and_store()
        logger.info("Wire digest generated")
        # MarketPulse dataclass → dict for Celery JSON serialization
        from dataclasses import asdict

        return (
            asdict(pulse)
            if hasattr(pulse, "__dataclass_fields__")
            else {"status": "ok"}
        )
    except Exception as exc:
        logger.error("Wire digest failed: %s", exc)
        return {"error": str(exc)}


@shared_task(
    name="openclaw.tasks.global_intelligence.task_analyst_pipeline",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def task_analyst_pipeline(self):
    """Analyst team: understand events, build causal chains, track state, find analogies.

    Triggered after sentinel crawl, or on schedule (every 10 min).
    """
    try:
        from src.intelligence.agents.event_understanding_agent import (
            get_event_understanding_agent,
        )
        from src.intelligence.agents.causal_chain_agent import get_causal_chain_agent
        from src.intelligence.agents.event_state_tracker import get_event_state_tracker
        from src.intelligence.agents.historical_analogy_agent import (
            get_historical_analogy_agent,
        )
        from src.intelligence.event_bus import get_event_bus

        event_bus = get_event_bus()
        understanding_agent = get_event_understanding_agent()
        causal_agent = get_causal_chain_agent()
        state_tracker = get_event_state_tracker()
        analogy_agent = get_historical_analogy_agent()

        # 1. Read recent raw intel from event bus
        recent_bus_events = _run_async(
            event_bus.read_history("sentinel:raw_intel", count=50)
        )
        if not recent_bus_events:
            return {"status": "no_new_intel"}

        # Extract data dicts from BusEvent objects
        recent_items = [e.data for e in recent_bus_events]

        # 2. Event Understanding
        understandings = _run_async(understanding_agent.analyze_batch(recent_items))

        # 3. For each understood event with A-share relevance
        results = {"understood": len(understandings), "chains": 0, "analogies": 0}
        for event in understandings:
            if event.get("a_share_relevance", 0) < 0.3:
                continue

            # Causal chain
            chains = _run_async(causal_agent.build_chains(event))
            results["chains"] += len(chains)

            # State tracking
            state_tracker.register_event(
                title=event.get("one_line_summary", ""),
                event_type=event.get("event_type", ""),
                region=event.get("region", "未知"),
                sectors=event.get("affected_sectors"),
                symbols=event.get("affected_symbols"),
                ai_summary=event.get("ai_summary", ""),
            )

            # Historical analogy
            analogies = _run_async(analogy_agent.find_analogies(event))
            results["analogies"] += len(analogies)

        logger.info("Analyst pipeline: %s", results)
        return results
    except Exception as exc:
        logger.error("Analyst pipeline failed: %s", exc)
        raise self.retry(exc=exc)


@shared_task(
    name="openclaw.tasks.global_intelligence.task_strategist_pipeline",
    bind=True,
    max_retries=1,
    default_retry_delay=120,
)
def task_strategist_pipeline(self):
    """Strategist team: scenario planning + risk assessment + opportunity scanning.

    Triggered after analyst pipeline, or on schedule (every 15 min).
    """
    try:
        from src.intelligence.agents.scenario_planner_agent import (
            get_scenario_planner_agent,
        )
        from src.intelligence.agents.cross_event_risk_agent import (
            get_cross_event_risk_agent,
        )
        from src.intelligence.agents.opportunity_scanner_agent import (
            get_opportunity_scanner_agent,
        )
        from src.intelligence.event_bus import get_event_bus

        event_bus = get_event_bus()
        scenario_agent = get_scenario_planner_agent()
        risk_agent = get_cross_event_risk_agent()
        opportunity_agent = get_opportunity_scanner_agent()

        # Read recent analyst outputs (extract .data from BusEvent objects)
        understood = [
            e.data
            for e in _run_async(
                event_bus.read_history("analyst:event_understood", count=20)
            )
        ]
        chains = [
            e.data
            for e in _run_async(
                event_bus.read_history("analyst:causal_chain", count=20)
            )
        ]
        analogies = [
            e.data
            for e in _run_async(
                event_bus.read_history("analyst:causal_chain", count=10)
            )
        ]

        if not understood:
            return {"status": "no_understood_events"}

        results = {"scenarios": 0, "signals": 0, "risk_alerts": 0}

        # Cross-event risk assessment (consider all events together)
        risk = _run_async(risk_agent.assess_risk(understood[-1], understood))
        if risk.risk_level in ("medium", "high", "critical"):
            results["risk_alerts"] += 1

        # Per-event processing
        for event in understood:
            # Find relevant chains for this event
            event_chains = [
                c
                for c in chains
                if c.get("event", {}).get("one_line_summary")
                == event.get("one_line_summary")
            ]
            event_analogies = [
                a
                for a in analogies
                if a.get("current_event") == event.get("one_line_summary")
            ]

            # Scenario planning
            scenario_set = _run_async(
                scenario_agent.plan_scenarios(event, event_chains, event_analogies)
            )
            if scenario_set:
                results["scenarios"] += 1

            # Opportunity scanning
            signals = _run_async(
                opportunity_agent.scan_opportunities(
                    event,
                    event_chains,
                    scenarios={
                        "scenarios": [
                            {"name": s.name, "probability": s.probability}
                            for s in scenario_set.scenarios
                        ]
                    }
                    if scenario_set
                    else None,
                    risk={
                        "risk_level": risk.risk_level,
                        "risk_score": risk.risk_score,
                        "alert_message": risk.alert_message,
                    },
                )
            )
            results["signals"] += len(signals)

        logger.info("Strategist pipeline: %s", results)
        return results
    except Exception as exc:
        logger.error("Strategist pipeline failed: %s", exc)
        return {"error": str(exc)}


@shared_task(
    name="openclaw.tasks.global_intelligence.task_messenger_digest",
    bind=True,
    max_retries=1,
)
def task_messenger_digest(self, digest_type: str = "morning"):
    """Messenger team: generate and route intelligence digest."""
    try:
        from src.intelligence.agents.event_digest_agent import get_event_digest_agent
        from src.intelligence.agents.alert_priority_router import (
            get_alert_priority_router,
        )
        from src.intelligence.event_bus import get_event_bus

        digest_agent = get_event_digest_agent()
        router = get_alert_priority_router()
        event_bus = get_event_bus()

        # Gather recent events (extract .data from BusEvent objects)
        events = [
            e.data
            for e in _run_async(
                event_bus.read_history("analyst:event_understood", count=30)
            )
        ]
        signals_raw = [
            e.data
            for e in _run_async(event_bus.read_history("strategist:signal", count=20))
        ]

        result = _run_async(
            digest_agent.generate_digest(digest_type, events, signals_raw)
        )

        if result.get("generated"):
            # Route through priority router for Discord push
            _run_async(
                router.route_alert(
                    {
                        "type": "intelligence_digest",
                        "title": f"{'📋' if digest_type == 'morning' else '📊' if digest_type == 'midday' else '🌙'} "
                        f"{'早盘' if digest_type == 'morning' else '午间' if digest_type == 'midday' else '收盘'}情报简报",
                        "content": result.get("content", ""),
                        "priority": "high" if digest_type == "morning" else "normal",
                    }
                )
            )

        return result
    except Exception as exc:
        logger.error("Messenger digest failed: %s", exc)
        return {"error": str(exc)}


@shared_task(name="openclaw.tasks.global_intelligence.task_messenger_alert")
def task_messenger_alert(event_data: dict):
    """Messenger team: write and route a single high-priority alert.

    Called by strategist when a significant signal is detected.
    """
    try:
        from src.intelligence.agents.plain_language_writer import (
            get_plain_language_writer,
        )
        from src.intelligence.agents.alert_priority_router import (
            get_alert_priority_router,
        )

        writer = get_plain_language_writer()
        router = get_alert_priority_router()

        message = _run_async(
            writer.write_message(
                event=event_data.get("event", {}),
                scenarios=event_data.get("scenarios"),
                signals=event_data.get("signals"),
                risk=event_data.get("risk"),
                analogies=event_data.get("analogies"),
            )
        )

        result = _run_async(router.route_alert(message))
        return result
    except Exception as exc:
        logger.error("Messenger alert failed: %s", exc)
        return {"error": str(exc)}

"""Full intelligence processing pipeline — orchestrates the complete flow.

Replaces fragmented Celery beat schedules with a single coordinated pipeline:
  1. Read raw intel from event bus
  2. LLM understanding (EventUnderstandingAgent) with source weighting (C4)
  3. Knowledge graph auto-population (C1+C8)
  4. Event state tracking with semantic dedup (C3)
  5. Fermentation sync (C5)
  6. Impact chain construction → signal production (feeds C2 in next trading loop)

Runs every 10 minutes during extended hours (7:00-23:00).
"""

from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.intel_processing_pipeline")


def task_intelligence_pipeline_full() -> dict[str, Any]:
    """Full intelligence pipeline: Crawl → Understand → KG → Track → Chain.

    Returns dict with counts for each stage.
    """
    results: dict[str, Any] = {
        "raw_items": 0,
        "understood": 0,
        "kg_populated": 0,
        "events_tracked": 0,
        "fermentation_synced": 0,
        "chains_built": 0,
        "signals_produced": 0,
    }

    # ── Stage 1: Read recent raw intel ──
    raw_items: list[dict[str, Any]] = []
    try:
        from src.data.cn_news_direct import CnNewsDirectFetcher

        cn_fetcher = CnNewsDirectFetcher()
        all_news = cn_fetcher.fetch_all_sync(limit=30)
        for item in all_news:
            raw_items.append(
                {
                    "title": item.title,
                    "summary": item.content[:300],
                    "layer": "L4" if item.source in ("jin10", "sina") else "L3",
                    "url": item.url,
                }
            )
    except Exception as exc:
        logger.warning("Stage 1 (CN news) failed: %s", exc)

    # Also pull from Weibo trending (market-relevant only)
    try:
        from src.data.weibo_trending import WeiboTrendingFetcher

        weibo = WeiboTrendingFetcher()
        market_trends = weibo.fetch_market_relevant_sync()
        for trend in market_trends[:5]:
            raw_items.append(
                {
                    "title": trend.topic,
                    "summary": f"微博热搜#{trend.rank} 热度{trend.heat:,}",
                    "layer": "L5",
                    "url": "",
                }
            )
    except Exception as exc:
        logger.debug("Stage 1 (Weibo) failed: %s", exc)

    results["raw_items"] = len(raw_items)
    if not raw_items:
        logger.info("Intel pipeline: no raw items to process")
        return results

    # ── Stage 2: LLM understanding with source weights (C4) + KG population (C1+C8) ──
    understandings = []
    try:
        from src.intelligence.agents.event_understanding_agent import (
            get_event_understanding_agent,
        )

        agent = get_event_understanding_agent()
        agent.reset_budget()
        understandings = agent.analyze_batch(raw_items)
        results["understood"] = len(understandings)
        # KG population happens automatically inside analyze_item (C1+C8)
        results["kg_populated"] = len(understandings)
    except Exception as exc:
        logger.warning("Stage 2 (LLM understanding) failed: %s", exc)

    # ── Stage 3: Event state tracking with semantic dedup (C3) ──
    try:
        from src.intelligence.agents.event_state_tracker import (
            get_event_state_tracker,
        )

        tracker = get_event_state_tracker()
        for u in understandings:
            if u.a_share_relevance < 0.3:
                continue
            try:
                tracker.register_event(
                    title=u.one_line_summary or u.source_title[:50],
                    event_type=u.event_type,
                    sectors=u.key_sectors,
                )
                results["events_tracked"] += 1
            except Exception:
                pass

        # Evaluate state transitions (DETECTED → DEVELOPING → ESCALATING)
        try:
            tracker.evaluate_transitions()
        except Exception:
            pass
    except Exception as exc:
        logger.warning("Stage 3 (event tracking) failed: %s", exc)

    # ── Stage 4: Fermentation sync (C5) ──
    try:
        from src.intelligence.fermentation_engine import FermentationEngine
        from src.intelligence.agents.event_state_tracker import (
            get_event_state_tracker,
        )

        ferm = FermentationEngine()
        tracker = get_event_state_tracker()
        synced = ferm.sync_to_state_tracker(tracker)
        results["fermentation_synced"] = synced
    except Exception as exc:
        logger.debug("Stage 4 (fermentation sync) failed: %s", exc)

    # ── Stage 5: Impact chain construction for active events ──
    try:
        from src.intelligence.impact_engine import EventImpactEngine
        from src.intelligence.agents.event_state_tracker import (
            get_event_state_tracker,
        )

        tracker = get_event_state_tracker()
        active_events = tracker.get_active_events()
        engine = EventImpactEngine()

        for event in active_events:
            state_val = (
                event.state.value if hasattr(event.state, "value") else str(event.state)
            )
            if state_val not in ("detected", "developing", "escalating", "relapsed"):
                continue
            try:
                event_dict = {
                    "title": event.title,
                    "summary": getattr(event, "ai_summary", ""),
                    "confidence": getattr(event, "probability_holds", 0.5),
                    "sectors": getattr(event, "affected_sectors", []),
                    "event_id": event.event_id,
                    "event_type": getattr(event, "event_type", "unknown"),
                }
                signals = engine.process_event(event_dict)
                if signals:
                    results["chains_built"] += 1
                    results["signals_produced"] += len(signals)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Stage 5 (impact chains) failed: %s", exc)

    # ── Flush KG to disk ──
    try:
        from src.web.dependencies import get_knowledge_graph

        get_knowledge_graph().flush()
    except Exception:
        pass

    logger.info(
        "Intel pipeline complete: raw=%d understood=%d tracked=%d "
        "ferment=%d chains=%d signals=%d",
        results["raw_items"],
        results["understood"],
        results["events_tracked"],
        results["fermentation_synced"],
        results["chains_built"],
        results["signals_produced"],
    )
    return results

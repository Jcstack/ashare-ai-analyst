"""Automatic intelligence hub refresh task.

Periodically refreshes intelligence hub sources and pushes notifications
when new items are found.

Per I-008: Intelligence hub requires manual refresh — this task automates it.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from openclaw.celery_app import app
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.intel_refresh_pipeline")

NOTIFICATIONS_KEY = "notifications:alerts"
MAX_NOTIFICATIONS = 200


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


def _get_redis():
    """Get a Redis client for notification storage."""
    import redis

    config = load_config("openclaw")
    broker = config.get("celery", {}).get("broker_url", "redis://redis:6379/0")
    return redis.from_url(broker, decode_responses=True)


def _match_portfolio(
    store: "InfoStore",  # noqa: F821
    new_item_ids: list[str],
) -> dict[str, list[str]]:
    """Match new intel items against portfolio + watchlist symbols.

    Returns:
        Mapping of symbol -> list of matching item_ids.
    """
    import json as _json

    # Collect tracked symbols from SQLite sources
    tracked_symbols: set[str] = set()

    # From portfolio (SQLite)
    try:
        from src.web.services.portfolio_store import PortfolioStore

        for pos in PortfolioStore(capital_service=None).list_positions():
            sym = pos.get("symbol", "")
            if sym:
                tracked_symbols.add(sym)
    except Exception:
        pass

    # From watchlist (SQLite)
    try:
        from src.web.services.watchlist_service import WatchlistService

        for item in WatchlistService().list_all():
            sym = item.get("symbol", "")
            if sym:
                tracked_symbols.add(sym)
    except Exception:
        pass

    if not tracked_symbols:
        return {}

    # Check intel_analysis config
    try:
        ia_config = load_config("intel_analysis")
        if not ia_config.get("intel_analysis", {}).get("enabled", True):
            return {}
    except Exception:
        pass

    # Load new items and match related_symbols
    items = store.get_items_by_ids(new_item_ids)
    matched: dict[str, list[str]] = {}
    for item in items:
        related = item.get("related_symbols", "[]")
        if isinstance(related, str):
            try:
                related = _json.loads(related)
            except (ValueError, TypeError):
                related = []
        for sym in related:
            if sym in tracked_symbols:
                matched.setdefault(sym, []).append(item["item_id"])

    return matched


def _backfill_symbols(
    store: "InfoStore",  # noqa: F821
    extractor: "SymbolExtractor",  # noqa: F821
    batch_size: int = 500,
) -> int:
    """Re-extract related_symbols for items that currently have none.

    Processes up to *batch_size* items per call.  Designed to be called
    at the end of each ``task_intel_refresh`` cycle so the backlog is
    gradually cleared (~500 items every 30 min).

    Returns the number of items updated.
    """
    items = store.get_items_missing_symbols(limit=batch_size, days=30)
    if not items:
        return 0

    updated = 0
    for item in items:
        symbols = extractor.extract(item["title"], item.get("summary") or "")
        if symbols:
            if store.update_related_symbols(item["item_id"], symbols):
                updated += 1

    if updated:
        logger.info(
            "Backfill: updated related_symbols for %d/%d items", updated, len(items)
        )
    return updated


@app.task(
    name="openclaw.tasks.intel_refresh_pipeline.task_intel_refresh",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def task_intel_refresh(self) -> dict[str, Any]:
    """Refresh intelligence hub sources and push notifications for new items.

    Runs every 30 minutes (7:00-23:00 CST, all days of week).
    Non-trading days are handled by the timeline guard which may skip execution.

    Results are pushed to Redis ``notifications:alerts`` when new items arrive.
    """
    if not _should_execute("task_intel_refresh"):
        logger.info("task_intel_refresh: skipped (timeline guard)")
        return {"status": "skipped", "new_items": 0}

    logger.info("Starting intel refresh task")

    try:
        from src.intelligence_hub.aggregator import InfoAggregator
        from src.intelligence_hub.dedup import DedupChecker
        from src.intelligence_hub.event_cluster import EventClusterer
        from src.intelligence_hub.info_store import InfoStore
        from src.intelligence_hub.scorer import ContentScorer
        from src.intelligence_hub.simhash import FuzzyDedupChecker
        from src.intelligence_hub.social_guardrails import SocialGuardrails
        from src.intelligence_hub.source_registry import SourceRegistry
        from src.intelligence_hub.symbol_extractor import SymbolExtractor

        config = {}
        try:
            config = load_config("intelligence_hub")
        except Exception:
            pass

        store = InfoStore()
        sources_cfg = config.get("sources", {})
        sources_list = [
            {"source_id": sid, **scfg}
            for sid, scfg in sources_cfg.items()
            if scfg.get("enabled", True)
        ]
        health_cfg = config.get("health", {})
        registry = SourceRegistry(
            sources_list,
            warn_after=health_cfg.get("warn_after_failures", 3),
            down_after=health_cfg.get("down_after_failures", 8),
        )
        scorer = ContentScorer(config.get("scoring"))
        dedup = DedupChecker(fuzzy_checker=FuzzyDedupChecker())
        guardrails = SocialGuardrails(registry=registry)
        clusterer = EventClusterer()

        # Build symbol extractor with extra names from watchlist (SQLite)
        extra_names: dict[str, str] = {}
        try:
            from src.web.services.watchlist_service import WatchlistService

            for item in WatchlistService().list_all():
                code = item.get("symbol", "")
                name = item.get("name", "")
                if code and name:
                    extra_names[code] = name
        except Exception:
            pass
        extractor = SymbolExtractor(extra_names=extra_names)

        aggregator = InfoAggregator(
            store=store,
            config=config,
            source_registry=registry,
            scorer=scorer,
            dedup_checker=dedup,
            social_guardrails=guardrails,
            event_clusterer=clusterer,
            symbol_extractor=extractor,
        )

        new_items, new_item_ids = aggregator.refresh(force=True)

        # Push notification when new items are found
        if new_items > 0:
            try:
                r = _get_redis()
                notification = {
                    "id": str(uuid.uuid4()),
                    "type": "hot_entry",
                    "title": f"情报更新: {new_items} 条新情报",
                    "summary": "情报中心已获取最新情报，点击查看详情。",
                    "symbol": None,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "read": False,
                    "action": "/info-hub",
                    "new_item_ids": new_item_ids[:50],
                }
                r.lpush(
                    NOTIFICATIONS_KEY,
                    json.dumps(notification, ensure_ascii=False),
                )
                r.ltrim(NOTIFICATIONS_KEY, 0, MAX_NOTIFICATIONS - 1)
            except Exception as exc:
                logger.warning("Failed to push intel refresh notification: %s", exc)

        # Portfolio matching: find new items related to tracked symbols
        if new_items > 0 and new_item_ids:
            try:
                matched = _match_portfolio(store, new_item_ids)
                if matched:
                    from openclaw.tasks.intel_analysis_pipeline import (
                        task_intel_portfolio_analysis,
                    )

                    cycle = datetime.now(UTC).strftime("%Y%m%d_%H%M")
                    task_intel_portfolio_analysis.delay(matched, cycle)
                    logger.info(
                        "Dispatched intel analysis for %d symbols: %s",
                        len(matched),
                        list(matched.keys()),
                    )
            except Exception as exc:
                logger.warning("Portfolio matching failed: %s", exc)

        # Backfill: re-extract symbols for old items missing related_symbols
        backfilled = 0
        try:
            backfilled = _backfill_symbols(store, extractor)
        except Exception as exc:
            logger.warning("Symbol backfill failed: %s", exc)

        logger.info(
            "Intel refresh complete: %d new items, %d backfilled", new_items, backfilled
        )
        return {"status": "ok", "new_items": new_items, "backfilled": backfilled}

    except Exception as exc:
        logger.error("Intel refresh failed: %s", exc)
        raise self.retry(exc=exc)

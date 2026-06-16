"""API service layer for Intelligence Hub.

Part of v21.0 Intelligence Hub. Follows sentiment_service.py pattern —
lazy-loaded dependencies via _get_*() methods.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from src.intelligence_hub.aggregator import InfoAggregator
from src.intelligence_hub.delivery_tracker import DeliveryTracker
from src.intelligence_hub.diversity import DiversityReranker
from src.intelligence_hub.event_cluster import EventClusterer
from src.intelligence_hub.info_store import InfoStore
from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.source_registry import SourceRegistry
from src.intelligence_hub.symbol_extractor import SymbolExtractor

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


class IntelligenceHubService:
    """Orchestrates Intelligence Hub operations for API endpoints."""

    def __init__(
        self,
        store: InfoStore,
        aggregator: InfoAggregator,
        source_registry: SourceRegistry | None = None,
        diversity_reranker: DiversityReranker | None = None,
        delivery_tracker: DeliveryTracker | None = None,
        event_clusterer: EventClusterer | None = None,
        symbol_extractor: SymbolExtractor | None = None,
    ) -> None:
        self._store = store
        self._aggregator = aggregator
        self._registry = source_registry
        self._reranker = diversity_reranker
        self._delivery_tracker = delivery_tracker
        self._clusterer = event_clusterer
        self._symbol_extractor = symbol_extractor
        self._last_manual_refresh: str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    def _ensure_data(self) -> None:
        """One-time initial load if the store is empty (cold start).

        Celery ``task_intel_refresh`` handles periodic refreshes;
        the manual refresh endpoint handles on-demand refreshes.
        Running ``aggregator.refresh(force=False)`` on every read was
        adding seconds of latency when the cooldown expired and could
        mask cross-process WAL visibility issues (I-033).
        """
        if not self._store.is_empty():
            return
        try:
            self._aggregator.refresh(force=True)
        except Exception as exc:
            logger.warning("Cold-start auto-refresh failed: %s", exc)

    def get_feed(
        self,
        *,
        category: str | None = None,
        priority: str | None = None,
        search: str | None = None,
        bookmarked: bool | None = None,
        symbol: str | None = None,
        limit: int = 50,
        offset: int = 0,
        days: int = 30,
        sort_by: str = "time",
        user_domains: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get paginated feed with optional filters and diversity reranking."""
        self._ensure_data()
        rows = self._store.get_feed(
            category=category,
            priority=priority,
            search=search,
            bookmarked=bookmarked,
            symbol=symbol,
            limit=limit,
            offset=offset,
            days=days,
            sort_by=sort_by,
        )
        items = [self._enrich_response(self._row_to_response(r)) for r in rows]

        # Apply diversity reranking if enabled
        if self._reranker and user_domains:
            info_items = [self._row_to_info_item(r) for r in rows]
            reranked = self._reranker.rerank(info_items, user_domains=user_domains)
            # Rebuild response list in reranked order
            item_map = {
                r.get("item_id", ""): self._enrich_response(self._row_to_response(r))
                for r in rows
            }
            items = [item_map[it.item_id] for it in reranked if it.item_id in item_map]

        return {"items": items, "total": len(items)}

    def get_overview(self, days: int = 30) -> dict[str, Any]:
        """Get category summaries, totals, and source count."""
        self._ensure_data()
        return self._store.get_overview(days=days)

    def get_categories(self, days: int = 30) -> list[dict[str, Any]]:
        """Get category list with counts and unread."""
        self._ensure_data()
        counts = self._store.get_category_counts(days=days)
        return [{"category": cat, **vals} for cat, vals in counts.items()]

    def get_items_by_ids(self, item_ids: list[str]) -> list[dict[str, Any]]:
        """Batch fetch items by IDs, with clean response format."""
        rows = self._store.get_items_by_ids(item_ids)
        return [self._enrich_response(self._row_to_response(r)) for r in rows]

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        """Get a single item by ID."""
        row = self._store.get_item(item_id)
        if row is None:
            return None
        return self._enrich_response(self._row_to_response(row))

    def toggle_bookmark(self, item_id: str) -> dict[str, Any] | None:
        """Toggle bookmark status for an item."""
        result = self._store.toggle_bookmark(item_id)
        if result is None:
            return None
        return {"item_id": item_id, "is_bookmarked": result}

    def mark_read(self, item_id: str) -> dict[str, Any] | None:
        """Mark an item as read."""
        success = self._store.mark_read(item_id)
        if not success:
            return None
        return {"item_id": item_id, "is_read": True}

    def refresh(self) -> dict[str, Any]:
        """Trigger a manual refresh from all sources."""
        since = self._last_manual_refresh
        new_items, new_item_ids = self._aggregator.refresh(force=True)

        # If aggregator reports 0 (e.g. Celery already stored the items),
        # fall back to counting items and fetching IDs since last manual refresh.
        if new_items == 0:
            new_items = self._store.count_since(since)
        if not new_item_ids and new_items > 0:
            new_item_ids = self._store.get_recent_ids(since, limit=50)

        self._last_manual_refresh = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "new_items": new_items,
            "new_item_ids": new_item_ids[:50],
            "status": "ok",
        }

    def get_sources_health(self) -> list[dict[str, Any]]:
        """Return per-source health status from the registry."""
        if self._registry is None:
            return []
        return self._registry.get_all_health()

    # ------------------------------------------------------------------
    # Delivery tracking (v23.0 Phase 3)
    # ------------------------------------------------------------------

    def track_delivery(self, item_id: str, event_type: str) -> dict[str, Any]:
        """Record a single delivery event."""
        if self._delivery_tracker is None:
            return {"status": "tracking_disabled"}
        self._delivery_tracker.track(item_id, event_type)
        return {"item_id": item_id, "event_type": event_type, "status": "ok"}

    def track_batch_delivery(
        self, item_ids: list[str], event_type: str
    ) -> dict[str, Any]:
        """Record batch delivery events."""
        if self._delivery_tracker is None:
            return {"count": 0, "status": "tracking_disabled"}
        count = self._delivery_tracker.track_batch(item_ids, event_type)
        return {"count": count, "event_type": event_type, "status": "ok"}

    def get_delivery_stats(self, days: int = 7) -> dict[str, Any]:
        """Return aggregate delivery statistics."""
        if self._delivery_tracker is None:
            return {
                "total_displayed": 0,
                "total_clicked": 0,
                "total_analyzed": 0,
                "click_through_rate": 0.0,
                "unique_items_displayed": 0,
            }
        return self._delivery_tracker.get_stats(days=days)

    def get_popular_items(self, limit: int = 20, days: int = 7) -> list[dict[str, Any]]:
        """Return most-clicked items."""
        if self._delivery_tracker is None:
            return []
        return self._delivery_tracker.get_popular_items(limit=limit, days=days)

    # ------------------------------------------------------------------
    # Event clustering (v23.0 Phase 3)
    # ------------------------------------------------------------------

    def get_event_clusters(self, days: int = 7, min_sources: int = 1) -> dict[str, Any]:
        """Return event clusters with cross-verification data."""
        self._ensure_data()
        rows = self._store.get_feed(days=days, limit=500, sort_by="time")
        info_items = [self._row_to_info_item(r) for r in rows]

        if self._clusterer is None:
            return {"clusters": []}

        clusters = self._clusterer.cluster(info_items)

        result = []
        for cluster in clusters:
            if cluster.unique_sources < min_sources:
                continue
            items_data = [
                self._row_to_response(r)
                for r in rows
                if r.get("item_id") in {it.item_id for it in cluster.items}
            ]
            timestamps = [
                it.published_at or it.fetched_at
                for it in cluster.items
                if it.published_at or it.fetched_at
            ]
            result.append(
                {
                    "cluster_id": cluster.cluster_id,
                    "representative_title": cluster.representative_title,
                    "unique_sources": cluster.unique_sources,
                    "cross_verification_score": cluster.cross_verification_score,
                    "items": items_data,
                    "earliest": min(timestamps) if timestamps else "",
                    "latest": max(timestamps) if timestamps else "",
                }
            )

        # Sort by most recent first
        result.sort(key=lambda c: c["latest"], reverse=True)
        return {"clusters": result}

    @staticmethod
    def _row_to_info_item(row: dict[str, Any]) -> InfoItem:
        """Convert a database row dict to an InfoItem for reranking."""
        tags = row.get("tags", [])
        if isinstance(tags, str):
            tags = json.loads(tags)
        symbols = row.get("related_symbols", [])
        if isinstance(symbols, str):
            symbols = json.loads(symbols)
        extra = row.get("extra", {})
        if isinstance(extra, str):
            extra = json.loads(extra)
        return InfoItem(
            item_id=row.get("item_id", ""),
            source_id=row.get("source_id", ""),
            source_name=row.get("source_name", ""),
            title=row.get("title", ""),
            summary=row.get("summary") or "",
            url=row.get("url") or "",
            category=row.get("category", "market"),
            priority=row.get("priority", "normal"),
            tags=tags,
            related_symbols=symbols,
            published_at=row.get("published_at") or "",
            fetched_at=row.get("fetched_at") or "",
            is_bookmarked=bool(row.get("is_bookmarked", 0)),
            is_read=bool(row.get("is_read", 0)),
            extra=extra,
            content_score=row.get("content_score"),
        )

    @staticmethod
    def _clean_html(text: str) -> str:
        """Strip HTML tags and collapse whitespace."""
        if not text:
            return text
        cleaned = _HTML_TAG_RE.sub("", text)
        return " ".join(cleaned.split())

    def _enrich_response(self, resp: dict[str, Any]) -> dict[str, Any]:
        """Add symbol name mapping if a symbol extractor is available."""
        symbols = resp.get("related_symbols", [])
        if symbols and self._symbol_extractor:
            names: dict[str, str] = {}
            for code in symbols:
                name = self._symbol_extractor.get_stock_name(code)
                if name:
                    names[code] = name
            resp["related_symbol_names"] = names
        else:
            resp["related_symbol_names"] = {}
        return resp

    @classmethod
    def _row_to_response(cls, row: dict[str, Any]) -> dict[str, Any]:
        """Convert a database row dict to a clean API response dict."""
        return {
            "item_id": row.get("item_id", ""),
            "source_id": row.get("source_id", ""),
            "source_name": row.get("source_name", ""),
            "title": cls._clean_html(row.get("title", "")),
            "summary": cls._clean_html(row.get("summary") or ""),
            "url": row.get("url") or "",
            "category": row.get("category", "market"),
            "priority": row.get("priority", "normal"),
            "tags": json.loads(row["tags"])
            if isinstance(row.get("tags"), str)
            else row.get("tags", []),
            "related_symbols": json.loads(row["related_symbols"])
            if isinstance(row.get("related_symbols"), str)
            else row.get("related_symbols", []),
            "published_at": row.get("published_at") or "",
            "fetched_at": row.get("fetched_at") or "",
            "is_bookmarked": bool(row.get("is_bookmarked", 0)),
            "is_read": bool(row.get("is_read", 0)),
            "extra": json.loads(row["extra"])
            if isinstance(row.get("extra"), str)
            else row.get("extra", {}),
            "content_score": row.get("content_score"),
            "score_explain": json.loads(row["score_explain"])
            if isinstance(row.get("score_explain"), str)
            else row.get("score_explain", {}),
        }

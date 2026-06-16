"""REST endpoints for Intelligence Hub under /intelligence-hub.

Part of v21.0 Intelligence Hub.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.web.dependencies import get_intelligence_hub_service, get_redis
from src.web.services.intelligence_hub_service import IntelligenceHubService

logger = logging.getLogger(__name__)

_NOTIFICATIONS_KEY = "notifications:alerts"

router = APIRouter(tags=["intelligence-hub"])


@router.get("/feed")
async def get_feed(
    category: str | None = Query(None, description="Filter by category"),
    priority: str | None = Query(None, description="Filter by priority"),
    search: str | None = Query(None, description="Search in title/summary"),
    bookmarked: bool | None = Query(None, description="Filter bookmarked only"),
    symbol: str | None = Query(None, description="Filter by related symbol"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    days: int = Query(30, ge=1, le=365, description="Lookback days"),
    sort_by: str = Query("time", description="Sort order: time | score"),
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> dict:
    """Paginated feed of information items with optional filters."""
    return await asyncio.to_thread(
        service.get_feed,
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


@router.get("/overview")
async def get_overview(
    days: int = Query(30, ge=1, le=365),
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> dict:
    """Category summaries, totals, and source count."""
    return await asyncio.to_thread(service.get_overview, days=days)


@router.get("/categories")
async def get_categories(
    days: int = Query(30, ge=1, le=365),
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> list[dict]:
    """Category list with counts and unread."""
    return await asyncio.to_thread(service.get_categories, days=days)


@router.get("/item/{item_id}")
async def get_item(
    item_id: str,
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> dict:
    """Single item detail."""
    result = service.get_item(item_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return result


@router.post("/item/{item_id}/bookmark")
async def toggle_bookmark(
    item_id: str,
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> dict:
    """Toggle bookmark status for an item."""
    result = service.toggle_bookmark(item_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return result


@router.post("/item/{item_id}/read")
async def mark_read(
    item_id: str,
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> dict:
    """Mark an item as read."""
    result = service.mark_read(item_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return result


@router.get("/events/clusters")
async def get_event_clusters(
    days: int = Query(7, ge=1, le=30, description="Lookback days"),
    min_sources: int = Query(1, ge=1, le=10, description="Minimum unique sources"),
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> dict:
    """Event clusters with cross-verification data."""
    return await asyncio.to_thread(
        service.get_event_clusters, days=days, min_sources=min_sources
    )


@router.get("/sources/health")
async def get_sources_health(
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> list[dict]:
    """Per-source health status."""
    return service.get_sources_health()


@router.post("/refresh")
async def refresh(
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
    r=Depends(get_redis),
) -> dict:
    """Manual source refresh."""
    result = await asyncio.to_thread(service.refresh)

    # Push notification to Redis when new items are found
    new_items = result.get("new_items", 0)
    if new_items > 0 and r is not None:
        try:
            new_item_ids = result.get("new_item_ids", [])
            notification = {
                "id": str(uuid.uuid4()),
                "type": "hot_entry",
                "title": f"情报更新: {new_items} 条新情报",
                "summary": "情报中心已获取最新情报，点击查看详情。",
                "symbol": None,
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "/info-hub",
                "new_item_ids": new_item_ids[:50],
            }
            r.lpush(_NOTIFICATIONS_KEY, json.dumps(notification, ensure_ascii=False))
        except Exception as exc:
            logger.warning("Failed to push intel refresh notification: %s", exc)

    return result


# ------------------------------------------------------------------
# Delivery tracking (v23.0 Phase 3)
# ------------------------------------------------------------------


@router.post("/item/{item_id}/track")
async def track_delivery(
    item_id: str,
    event_type: str = Query(
        ..., description="Event type: displayed, clicked, analyzed"
    ),
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> dict:
    """Track a delivery event (displayed, clicked, analyzed)."""
    return service.track_delivery(item_id, event_type)


@router.post("/track/batch")
async def track_batch_delivery(
    item_ids: list[str] = Body(..., description="List of item IDs"),
    event_type: str = Query(
        ..., description="Event type: displayed, clicked, analyzed"
    ),
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> dict:
    """Track batch delivery events."""
    return service.track_batch_delivery(item_ids, event_type)


@router.get("/delivery/stats")
async def get_delivery_stats(
    days: int = Query(7, ge=1, le=365, description="Lookback window in days"),
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> dict:
    """Aggregate delivery statistics."""
    return service.get_delivery_stats(days=days)


@router.get("/delivery/popular")
async def get_popular_items(
    limit: int = Query(20, ge=1, le=100, description="Max items to return"),
    days: int = Query(7, ge=1, le=365, description="Lookback window in days"),
    service: IntelligenceHubService = Depends(get_intelligence_hub_service),
) -> list[dict]:
    """Most-clicked items."""
    return service.get_popular_items(limit=limit, days=days)

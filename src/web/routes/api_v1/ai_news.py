"""API routes for global AI news aggregation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.web.dependencies import get_ai_news_service
from src.web.services.ai_news_service import AiNewsService

router = APIRouter(tags=["ai-news"])


@router.get("/")
async def list_ai_news(
    category: str | None = Query(
        None, description="Filter: official|research|community|github"
    ),
    source: str | None = Query(
        None, description="Filter by source_id (comma-separated)"
    ),
    search: str | None = Query(None, description="Search title/summary"),
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    svc: AiNewsService = Depends(get_ai_news_service),
) -> dict:
    """List AI news with filtering and pagination."""
    return svc.list_news(
        category=category,
        source_id=source,
        search=search,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )


@router.get("/sources")
async def get_sources(
    svc: AiNewsService = Depends(get_ai_news_service),
) -> list[dict]:
    """Get all sources with article counts and circuit status."""
    return svc.get_source_stats()


@router.get("/unread-count")
async def get_unread_count(
    svc: AiNewsService = Depends(get_ai_news_service),
) -> dict:
    """Get unread AI news count."""
    return {"count": svc.get_unread_count()}


@router.get("/{news_id}")
async def get_news_item(
    news_id: int,
    svc: AiNewsService = Depends(get_ai_news_service),
) -> dict:
    """Get a single news item."""
    item = svc.get_news(news_id)
    if not item:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="News item not found")
    return item


@router.post("/{news_id}/read")
async def mark_read(
    news_id: int,
    svc: AiNewsService = Depends(get_ai_news_service),
) -> dict:
    """Mark a news item as read."""
    svc.mark_read(news_id)
    return {"success": True}


@router.post("/refresh")
async def refresh_news(
    source: str | None = Query(None, description="Refresh specific source_id"),
    svc: AiNewsService = Depends(get_ai_news_service),
) -> dict:
    """Trigger a manual refresh of AI news sources."""
    results = svc.refresh(source_id=source)
    total = sum(results.values())
    return {"new_items": total, "by_source": results}

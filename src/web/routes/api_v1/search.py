"""Stock search JSON API endpoint.

Provides real-time fuzzy search across all A-share stocks (FR-W002).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.data.registry import StockRegistry
from src.web.dependencies import get_stock_registry
from src.web.routes.api_v1.schemas import StockSearchItem

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[StockSearchItem])
async def search_stocks(
    q: str = Query("", description="Search query (code or name)"),
    limit: int = Query(20, ge=1, le=50, description="Max results"),
    registry: StockRegistry = Depends(get_stock_registry),
) -> list[dict]:
    """Search all A-share stocks by code prefix or name substring.

    Args:
        q: Search query string.
        limit: Maximum number of results.

    Returns:
        List of matching stocks with symbol, name, and board.
    """
    return registry.search(q, limit=limit)

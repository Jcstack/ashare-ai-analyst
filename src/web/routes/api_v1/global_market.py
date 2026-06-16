"""Global market API endpoints — indices, commodities, currencies.

Per PRD v3.2 FR-GM002: Global market API endpoints.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends

from src.data.global_market import GlobalMarketFetcher
from src.web.dependencies import get_global_market_fetcher
from src.web.schemas.market import (
    GlobalCommodityItem,
    GlobalCurrencyItem,
    GlobalIndexItem,
    GlobalMarketSnapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["global-market"])


@router.get("/snapshot", response_model=GlobalMarketSnapshot)
async def get_global_snapshot(
    fetcher: GlobalMarketFetcher = Depends(get_global_market_fetcher),
) -> dict:
    """Get a complete global market snapshot (indices + commodities + currencies)."""
    try:
        return await asyncio.to_thread(fetcher.fetch_global_snapshot)
    except Exception:
        logger.warning("Global market snapshot fetch failed")
        return {"indices": [], "commodities": [], "currencies": []}


@router.get("/indices", response_model=list[GlobalIndexItem])
async def get_global_indices(
    fetcher: GlobalMarketFetcher = Depends(get_global_market_fetcher),
) -> list[dict]:
    """Get global stock market indices."""
    try:
        return await asyncio.to_thread(fetcher.fetch_global_indices)
    except Exception:
        logger.warning("Global indices fetch failed")
        return []


@router.get("/commodities", response_model=list[GlobalCommodityItem])
async def get_global_commodities(
    fetcher: GlobalMarketFetcher = Depends(get_global_market_fetcher),
) -> list[dict]:
    """Get commodity prices (gold, oil, etc.)."""
    try:
        return await asyncio.to_thread(fetcher.fetch_commodities)
    except Exception:
        logger.warning("Global commodities fetch failed")
        return []


@router.get("/currencies", response_model=list[GlobalCurrencyItem])
async def get_global_currencies(
    fetcher: GlobalMarketFetcher = Depends(get_global_market_fetcher),
) -> list[dict]:
    """Get currency exchange rates."""
    try:
        return await asyncio.to_thread(fetcher.fetch_currencies)
    except Exception:
        logger.warning("Global currencies fetch failed")
        return []

"""Settings JSON API endpoints.

Provides config reading, watchlist update, individual stock
add/remove for the watchlist, and user preferences persistence as JSON.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from src.utils.config import load_config
from src.web.dependencies import get_stock_service, get_watchlist_service
from src.web.services.watchlist_service import WatchlistService
from src.web.routes.api_v1.schemas import (
    ApiResponse,
    WatchlistAddRequest,
    WatchlistUpdateRequest,
)

logger = logging.getLogger(__name__)

_USER_PREFS_PATH = Path("data/processed/user-preferences.json")

router = APIRouter(tags=["settings"])


def _prefetch_stock_data(symbol: str) -> None:
    """Background: warm OHLCV cache for newly added stock."""
    try:
        svc = get_stock_service()
        svc.get_stock_data(symbol)
        logger.info("Prefetched OHLCV for %s", symbol)
    except Exception as exc:
        logger.warning("Prefetch failed for %s: %s", symbol, exc)


@router.get("/config/{section}")
async def get_config(section: str) -> dict:
    """Read a configuration section.

    Args:
        section: Config section name (e.g. 'stocks', 'analysis', 'web').

    Returns:
        The full configuration dict for the requested section.
    """
    config = load_config(section)
    return {"section": section, "config": config}


@router.post("/watchlist", response_model=ApiResponse)
async def update_watchlist(
    req: WatchlistUpdateRequest,
    wl_svc: WatchlistService = Depends(get_watchlist_service),
) -> dict:
    """Update the stocks watchlist (full replacement).

    Args:
        req: New watchlist entries.

    Returns:
        Success or error response.
    """
    wl_svc.bulk_replace(req.watchlist)
    return {"status": "success", "message": "自选股列表已更新"}


@router.post("/watchlist/add", response_model=ApiResponse)
async def add_to_watchlist(
    req: WatchlistAddRequest,
    background_tasks: BackgroundTasks,
    wl_svc: WatchlistService = Depends(get_watchlist_service),
) -> dict:
    """Add a single stock to the watchlist.

    Args:
        req: Stock to add (symbol, name, board).

    Returns:
        Success or error response.
    """
    if wl_svc.contains(req.symbol):
        return {"status": "error", "message": f"{req.symbol} already in watchlist"}

    wl_svc.add(req.symbol, req.name, req.board)
    background_tasks.add_task(_prefetch_stock_data, req.symbol)
    return {
        "status": "success",
        "message": f"Added {req.name} ({req.symbol}) to watchlist",
    }


@router.delete("/watchlist/{symbol}", response_model=ApiResponse)
async def remove_from_watchlist(
    symbol: str,
    wl_svc: WatchlistService = Depends(get_watchlist_service),
) -> dict:
    """Remove a stock from the watchlist.

    Args:
        symbol: 6-digit stock code to remove.

    Returns:
        Success or error response.
    """
    if not wl_svc.remove(symbol):
        raise HTTPException(status_code=404, detail=f"{symbol} not in watchlist")

    return {"status": "success", "message": f"Removed {symbol} from watchlist"}


# ---------------------------------------------------------------------------
# User preferences (eject state persistence)
# ---------------------------------------------------------------------------


@router.get("/user-preferences")
async def get_user_preferences() -> JSONResponse:
    """Read persisted user preferences (eject state).

    Returns the full JSON blob or 404 if not yet saved.
    """
    if not _USER_PREFS_PATH.exists():
        return JSONResponse(status_code=404, content={"detail": "No preferences saved"})

    try:
        data = json.loads(_USER_PREFS_PATH.read_text(encoding="utf-8"))
        return JSONResponse(content=data)
    except Exception:
        logger.exception("Failed to read user preferences")
        return JSONResponse(status_code=404, content={"detail": "No preferences saved"})


@router.put("/user-preferences")
async def put_user_preferences(request: Request) -> dict:
    """Persist user preferences (eject state) to disk.

    Accepts arbitrary JSON — the frontend owns the schema.
    """
    body = await request.json()

    try:
        _USER_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _USER_PREFS_PATH.write_text(
            json.dumps(body, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("Failed to write user preferences")
        raise HTTPException(status_code=500, detail="Failed to save preferences")

    return {"status": "success"}

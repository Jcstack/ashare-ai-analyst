"""Settings Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel


class UpdateConfigRequest(BaseModel):
    """Request to update a config section."""

    params: dict


class WatchlistAddRequest(BaseModel):
    """Request to add a stock to the watchlist."""

    symbol: str
    name: str
    board: str = "main"


class WatchlistRemoveRequest(BaseModel):
    """Request to remove a stock from the watchlist."""

    symbol: str


class WatchlistUpdateRequest(BaseModel):
    """Request to update the watchlist."""

    watchlist: list[dict[str, str]]

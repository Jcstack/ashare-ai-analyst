"""Notification Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel


class NotificationItem(BaseModel):
    """A single notification/alert item."""

    id: str = ""
    type: str = ""
    title: str = ""
    summary: str = ""
    symbol: str | None = None
    timestamp: str = ""
    read: bool = False
    action: str = ""
    new_item_ids: list[str] = []


class UnreadCountResponse(BaseModel):
    """Unread notification count."""

    count: int = 0

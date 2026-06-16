"""User configuration API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.web.dependencies import get_user_config_service
from src.web.schemas.user_config import NotificationPrefs, UserFollows
from src.web.services.user_config_service import ALLOWED_KEYS, UserConfigService

router = APIRouter(tags=["user-config"])


class UserConfigResponse(BaseModel):
    config: dict[str, str]


class UserConfigUpdateRequest(BaseModel):
    config: dict[str, str]


# ------------------------------------------------------------------
# Legacy generic config
# ------------------------------------------------------------------


@router.get("/config", response_model=UserConfigResponse)
async def get_user_config(
    svc: UserConfigService = Depends(get_user_config_service),
):
    """Return all user configuration key-value pairs."""
    return UserConfigResponse(config=svc.get_all())


@router.put("/config", response_model=UserConfigResponse)
async def update_user_config(
    body: UserConfigUpdateRequest,
    svc: UserConfigService = Depends(get_user_config_service),
):
    """Batch update user configuration values."""
    invalid_keys = set(body.config.keys()) - ALLOWED_KEYS
    if invalid_keys:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid config keys: {invalid_keys}. Allowed: {ALLOWED_KEYS}",
        )
    for key, value in body.config.items():
        svc.set(key, value)
    return UserConfigResponse(config=svc.get_all())


# ------------------------------------------------------------------
# v20.0 Phase 4 — User follows
# ------------------------------------------------------------------


@router.get("/follows", response_model=UserFollows)
async def get_user_follows(
    svc: UserConfigService = Depends(get_user_config_service),
):
    """Return user follow preferences across 8 dimensions."""
    return UserFollows(**svc.get_follows())


@router.put("/follows", response_model=UserFollows)
async def update_user_follows(
    body: UserFollows,
    svc: UserConfigService = Depends(get_user_config_service),
):
    """Update user follow preferences. Merges with existing config."""
    updated = svc.update_follows(body.model_dump(exclude_unset=True))
    return UserFollows(**updated)


# ------------------------------------------------------------------
# v20.0 Phase 4 — Notification preferences
# ------------------------------------------------------------------


@router.get("/notification-prefs", response_model=NotificationPrefs)
async def get_notification_prefs(
    svc: UserConfigService = Depends(get_user_config_service),
):
    """Return user notification preferences."""
    return NotificationPrefs(**svc.get_notification_prefs())


@router.put("/notification-prefs", response_model=NotificationPrefs)
async def update_notification_prefs(
    body: NotificationPrefs,
    svc: UserConfigService = Depends(get_user_config_service),
):
    """Update user notification preferences. Merges with existing config."""
    updated = svc.update_notification_prefs(body.model_dump(exclude_unset=True))
    return NotificationPrefs(**updated)

"""Admin JSON API endpoints.

Provides key management, usage stats, balance checks,
routing configuration, and Qlib diagnostics as JSON.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.web.dependencies import (
    get_admin_service,
    get_audit_log,
    get_data_health_tracker,
    get_qmt_adapter,
    get_timeline_scheduler,
)
from src.audit.immutable_log import SIGNAL_EVENT_TYPES, ImmutableAuditLog
from src.web.services.admin_service import AdminService
from src.web.routes.api_v1.schemas import (
    AddKeyRequest,
    ApiKeyInfo,
    ApiResponse,
    RoutingConfig,
    UpdateConfigRequest,
    UpdateRoutingRequest,
    UsageDashboard,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

_GENERIC_ERROR_MESSAGE = "Internal server error"


@router.get("/keys", response_model=list[ApiKeyInfo])
async def list_keys(svc: AdminService = Depends(get_admin_service)) -> list[dict]:
    """List all API keys with masked values."""
    return svc.list_keys()


@router.post("/keys", response_model=ApiResponse)
async def add_key(
    req: AddKeyRequest,
    svc: AdminService = Depends(get_admin_service),
) -> dict:
    """Add a new API key.

    Args:
        req: Key details including provider, key, label, and optional expiry.

    Returns:
        Success or error response.
    """
    result = svc.add_key(req.provider, req.key, req.label, req.expires_at)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.delete("/keys/{provider}/{label}", response_model=ApiResponse)
async def remove_key(
    provider: str,
    label: str,
    svc: AdminService = Depends(get_admin_service),
) -> dict:
    """Remove an API key.

    Args:
        provider: Provider name.
        label: Key label.

    Returns:
        Success or error response.
    """
    result = svc.remove_key(provider, label)
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.get("/usage", response_model=UsageDashboard)
async def get_usage(svc: AdminService = Depends(get_admin_service)) -> dict:
    """Return usage dashboard data for the last 7 days."""
    return svc.get_usage_dashboard()


@router.get("/balance")
async def check_balance(svc: AdminService = Depends(get_admin_service)) -> list[dict]:
    """Check balances for all available providers."""
    return svc.check_balances()


@router.get("/routing", response_model=RoutingConfig)
async def get_routing(svc: AdminService = Depends(get_admin_service)) -> dict:
    """Return current routing configuration."""
    return svc.get_routing_config()


@router.post("/routing", response_model=ApiResponse)
async def update_routing(
    req: UpdateRoutingRequest,
    svc: AdminService = Depends(get_admin_service),
) -> dict:
    """Update the routing strategy.

    Args:
        req: New routing strategy.

    Returns:
        Success or error response.
    """
    result = svc.update_routing_strategy(req.strategy)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/config/{section}", response_model=ApiResponse)
async def update_config(
    section: str,
    req: UpdateConfigRequest,
    svc: AdminService = Depends(get_admin_service),
) -> dict:
    """Update a configuration section.

    Args:
        section: Config section name (e.g. 'stocks', 'analysis', 'llm').
        req: Key-value pairs to update.

    Returns:
        Success or error response.
    """
    result = svc.update_analysis_params(section, req.params)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/schedule-status")
async def get_schedule_status(
    scheduler=Depends(get_timeline_scheduler),
) -> dict:
    """Return current timeline scheduler status.

    Per PRD v3.2 FR-SS001.
    """
    return scheduler.get_status()


@router.post("/schedule-override", response_model=ApiResponse)
async def set_schedule_override(
    profile: str | None = Body(None, embed=True),
    scheduler=Depends(get_timeline_scheduler),
) -> dict:
    """Manually override the schedule profile.

    Pass ``null`` to clear the override.

    Per PRD v3.2 FR-SS001.
    """
    from openclaw.timeline_scheduler import ScheduleProfile

    if profile is None:
        scheduler.set_override(None)
        return {"status": "success", "message": "Schedule override cleared"}

    try:
        p = ScheduleProfile(profile)
    except ValueError:
        valid = [v.value for v in ScheduleProfile]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid profile '{profile}'. Valid: {valid}",
        )

    scheduler.set_override(p)
    return {"status": "success", "message": f"Schedule override set to {p.value}"}


@router.get("/data-health")
async def get_data_health(
    tracker=Depends(get_data_health_tracker),
) -> dict:
    """Return health status for all tracked data sources.

    Includes per-source success rate, latency, and overall status.
    """
    return tracker.get_all_health()


@router.get("/data-sources")
async def get_data_sources(
    tracker=Depends(get_data_health_tracker),
    qmt=Depends(get_qmt_adapter),
) -> dict:
    """Return health status for all data sources including QMT.

    Provides a unified view of all data source backends with their
    current health, latency, and availability status.
    """
    from src.data.source_router import DataSourceRouter

    router_instance = DataSourceRouter()
    router_status = router_instance.get_status()
    tracker_health = tracker.get_all_health()

    return {
        "qmt": qmt.get_health_info(),
        "source_router": router_status,
        "data_health": tracker_health,
    }


@router.get("/qlib-status")
async def get_qlib_status_endpoint() -> dict:
    """Qlib data and adapter health status."""
    from scripts.qlib_data_updater import get_qlib_status
    from src.prediction.qlib_adapter import QlibAdapter

    result: dict = {}

    # Data status (runs synchronously — reads files)
    try:
        result["data"] = await asyncio.to_thread(get_qlib_status)
    except Exception:
        logger.exception("Failed to fetch Qlib data status")
        result["data"] = {"error": _GENERIC_ERROR_MESSAGE}

    # Adapter status
    try:
        adapter = QlibAdapter()
        result["adapter"] = adapter.get_health_info()
    except Exception:
        logger.exception("Failed to fetch Qlib adapter status")
        result["adapter"] = {"error": _GENERIC_ERROR_MESSAGE}

    return result


@router.get("/audit/signals")
async def get_signal_audit(
    event_type: str | None = Query(
        None,
        description=(
            "Filter by event type. Must be one of: "
            "signal_published, signal_confirmed, signal_blocked, "
            "notification_dispatched, notification_suppressed, phase_transition"
        ),
    ),
    limit: int = Query(50, ge=1, le=500, description="Max entries to return"),
    audit_log: ImmutableAuditLog = Depends(get_audit_log),
) -> list[dict]:
    """Return signal-related audit log entries.

    Filters the immutable audit log to only signal/notification/phase
    event types. Optionally narrows to a single event_type.

    Per PRD v20.0 Phase 7: Observability.
    """
    if event_type is not None:
        if event_type not in SIGNAL_EVENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid event_type '{event_type}'. "
                    f"Valid: {sorted(SIGNAL_EVENT_TYPES)}"
                ),
            )
        entries = audit_log.get_entries(event_type=event_type, limit=limit)
    else:
        # Fetch from all signal event types, merge and sort
        all_entries = []
        for et in SIGNAL_EVENT_TYPES:
            all_entries.extend(audit_log.get_entries(event_type=et, limit=limit))
        # Sort by timestamp descending, take top N
        all_entries.sort(key=lambda e: e.timestamp, reverse=True)
        entries = all_entries[:limit]

    return [
        {
            "entry_id": e.entry_id,
            "timestamp": e.timestamp,
            "event_type": e.event_type,
            "actor": e.actor,
            "payload": e.payload,
        }
        for e in entries
    ]

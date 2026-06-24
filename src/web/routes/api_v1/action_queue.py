"""Action queue API endpoints.

Exposes the action queue for pending trade actions that await user
confirmation before execution.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.web.dependencies import get_action_queue_service, get_trade_service
from src.web.services.action_queue_service import ActionQueueService
from src.web.services.trade_service import TradeService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["actions"])


class FillRequest(BaseModel):
    """Request body for recording an execution fill."""

    price: float
    shares: int


@router.get("/")
async def list_actions(
    status: str | None = Query(None, description="Filter by status"),
    svc: ActionQueueService = Depends(get_action_queue_service),
) -> dict:
    """List actions, optionally filtered by status.

    Without a status filter, returns all actions ordered by creation date.
    With ``status=pending``, returns actions sorted by urgency x confidence.
    """
    if status == "pending":
        items = svc.list_pending()
    else:
        items = svc.list_actions(status=status)
    return {"actions": [item.to_dict() for item in items]}


@router.get("/stats")
async def action_stats(
    svc: ActionQueueService = Depends(get_action_queue_service),
) -> dict:
    """Return action counts by status."""
    return svc.get_stats()


@router.get("/{action_id}")
async def get_action(
    action_id: str,
    svc: ActionQueueService = Depends(get_action_queue_service),
) -> dict:
    """Get a single action by ID."""
    item = svc.get_action(action_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")
    return item.to_dict()


@router.post("/{action_id}/confirm")
async def confirm_action(
    action_id: str,
    svc: ActionQueueService = Depends(get_action_queue_service),
) -> dict:
    """User confirms they will execute this action."""
    item = svc.confirm_action(action_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")
    return item.to_dict()


@router.post("/{action_id}/reject")
async def reject_action(
    action_id: str,
    svc: ActionQueueService = Depends(get_action_queue_service),
) -> dict:
    """User rejects this action."""
    item = svc.reject_action(action_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")
    return item.to_dict()


@router.post("/{action_id}/fill")
async def record_fill(
    action_id: str,
    req: FillRequest,
    svc: ActionQueueService = Depends(get_action_queue_service),
    trade_svc: TradeService = Depends(get_trade_service),
) -> dict:
    """Record the execution fill and sync to portfolio.

    After recording fill_price/fill_shares in the action queue, automatically
    calls TradeService to update PortfolioStore and CapitalService.
    """
    item = svc.record_fill(action_id, fill_price=req.price, fill_shares=req.shares)
    if not item:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")

    # Sync to portfolio: action queue fill → TradeService → PortfolioStore
    try:
        plan = item.execution_plan or {}
        trade_svc.execute_trade(
            symbol=item.symbol,
            stock_name=plan.get("stock_name", item.symbol),
            action=item.action,
            shares=req.shares,
            price=req.price,
            reasoning=f"Action queue fill: {plan.get('reason', '')}",
            gate_request_id=item.id,
        )
        logger.info(
            "Action %s synced to portfolio: %s %d shares @ %.2f",
            action_id,
            item.action,
            req.shares,
            req.price,
        )
    except Exception as exc:
        logger.error("Failed to sync action %s to portfolio: %s", action_id, exc)

    return item.to_dict()

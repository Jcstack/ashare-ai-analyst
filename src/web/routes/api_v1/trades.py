"""Trade API endpoints — execute, record, and query trades.

Endpoints:
    POST   /api/v1/trades/execute          — Execute an agent-recommended trade
    POST   /api/v1/trades/manual           — Record a manually-entered trade
    GET    /api/v1/trades                  — List trade history
    GET    /api/v1/trades/profile          — Get trading behavior profile
    POST   /api/v1/trades/recommendations/:id/decision — Accept/reject a recommendation
    GET    /api/v1/trades/recommendations  — List recommendations
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.web.dependencies import (
    get_confirmation_gate,
    get_execution_bridge,
    get_kill_switch,
    get_trade_service,
)
from src.web.schemas.chat import AgentRecommendation, Trade, TradingProfile
from src.web.services.trade_service import TradeService
from src.trading.kill_switch import KillSwitch
from src.workflow.confirmation_gate import ConfirmationGate


def _is_simulation_mode() -> bool:
    """Check if broker is in simulation mode (trading hours not enforced)."""
    try:
        from src.utils.config import load_config

        broker_cfg = load_config("broker")
        return broker_cfg.get("mode", "simulation") == "simulation"
    except Exception:
        return True  # default to simulation


def require_market_open() -> None:
    """FastAPI dependency that blocks trade execution when A-share market is closed.

    Skipped in simulation mode — allows trading at any time.
    Raises HTTPException 409 with MARKET_CLOSED code, Chinese message,
    and next_trading_day when trading is not in session (live/qmt mode only).
    """
    if _is_simulation_mode():
        return

    from src.utils.market_hours import get_market_status_for_ui

    status = get_market_status_for_ui()
    if not status["is_trading"]:
        detail: dict[str, Any] = {
            "code": "MARKET_CLOSED",
            "message": f"当前{status['label']}，无法执行交易",
            "status": status["status"],
        }
        if status["next_event"]:
            detail["next_trading_time"] = status["next_event"]["time"]
        if status.get("holiday_info"):
            detail["holiday_info"] = status["holiday_info"]
        raise HTTPException(status_code=409, detail=detail)


router = APIRouter(tags=["trades"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ExecuteTradeRequest(BaseModel):
    """Request to execute an agent-recommended trade."""

    symbol: str
    stock_name: str
    action: Literal["buy", "sell", "add", "reduce"]
    shares: int = Field(gt=0)
    price: float = Field(gt=0)
    reasoning: str = ""
    thread_id: str | None = None
    recommendation_id: str | None = None
    decision_feedback: str | None = None


class ManualTradeRequest(BaseModel):
    """Request to record a manual trade."""

    symbol: str
    stock_name: str
    action: Literal["buy", "sell", "add", "reduce"]
    shares: int = Field(gt=0)
    price: float = Field(gt=0)
    reasoning: str = ""
    recommendation_id: str | None = None


class CreateGateRequest(BaseModel):
    """Request to create a confirmation gate for a trade."""

    trade_type: Literal["buy", "sell", "add", "reduce"]
    symbol: str
    quantity: int = Field(gt=0)
    price: float | None = None
    thread_id: str = ""
    auto_risk_check: bool = True


class ConfirmGateRequest(BaseModel):
    """Request to confirm a gate (user approval step)."""

    feedback: str = ""


class GateResponse(BaseModel):
    """Response for gate operations."""

    request_id: str
    symbol: str
    trade_type: str
    quantity: int
    price: float | None = None
    current_stage: str
    created_at: str
    updated_at: str


class RecommendationDecisionRequest(BaseModel):
    """Request to accept or reject a recommendation."""

    decision: Literal["accepted", "rejected", "modified"]
    feedback: str | None = None


class KillSwitchRequest(BaseModel):
    """Request to toggle the kill switch."""

    active: bool
    reason: str = ""


class TradeListResponse(BaseModel):
    """Response for listing trades."""

    trades: list[Trade] = Field(default_factory=list)
    total: int = 0


class RecommendationListResponse(BaseModel):
    """Response for listing recommendations."""

    recommendations: list[AgentRecommendation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/trades/execute", response_model=Trade, dependencies=[Depends(require_market_open)]
)
def execute_trade(
    req: ExecuteTradeRequest,
    trade_service: TradeService = Depends(get_trade_service),
) -> Any:
    """Execute a simulated trade (typically from agent recommendation)."""
    return trade_service.execute_trade(
        symbol=req.symbol,
        stock_name=req.stock_name,
        action=req.action,
        shares=req.shares,
        price=req.price,
        reasoning=req.reasoning,
        thread_id=req.thread_id,
        recommendation_id=req.recommendation_id,
        decision_feedback=req.decision_feedback,
    )


@router.post(
    "/trades/manual", response_model=Trade, dependencies=[Depends(require_market_open)]
)
def record_manual_trade(
    req: ManualTradeRequest,
    trade_service: TradeService = Depends(get_trade_service),
) -> Any:
    """Record a manually-entered trade for portfolio sync."""
    return trade_service.record_manual_trade(
        symbol=req.symbol,
        stock_name=req.stock_name,
        action=req.action,
        shares=req.shares,
        price=req.price,
        reasoning=req.reasoning,
        recommendation_id=req.recommendation_id,
    )


@router.get("/trades", response_model=TradeListResponse)
def list_trades(
    symbol: str | None = None,
    limit: int = 50,
    offset: int = 0,
    trade_service: TradeService = Depends(get_trade_service),
) -> Any:
    """List trade history, optionally filtered by symbol."""
    trades = trade_service.get_trade_history(symbol=symbol, limit=limit, offset=offset)
    total = trade_service.get_trade_count(symbol=symbol)
    return TradeListResponse(trades=trades, total=total)


@router.get("/trades/profile", response_model=TradingProfile)
def get_trading_profile(
    trade_service: TradeService = Depends(get_trade_service),
) -> Any:
    """Compute and return the user's trading behavior profile."""
    return trade_service.compute_trading_profile()


@router.post(
    "/trades/recommendations/{recommendation_id}/decision",
    response_model=dict,
)
def update_recommendation_decision(
    recommendation_id: str,
    req: RecommendationDecisionRequest,
    trade_service: TradeService = Depends(get_trade_service),
) -> Any:
    """Accept or reject an agent recommendation."""
    updated = trade_service.update_recommendation_decision(
        recommendation_id=recommendation_id,
        decision=req.decision,
        feedback=req.feedback,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return {"success": True, "recommendation_id": recommendation_id}


@router.get("/trades/recommendations", response_model=RecommendationListResponse)
def list_recommendations(
    thread_id: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
    trade_service: TradeService = Depends(get_trade_service),
) -> Any:
    """List agent recommendations, optionally filtered by thread or symbol."""
    recs = trade_service.get_recommendations(
        thread_id=thread_id, symbol=symbol, limit=limit
    )
    return RecommendationListResponse(recommendations=recs)


# ---------------------------------------------------------------------------
# Gate endpoints (Simulation-First Execution Flow)
# ---------------------------------------------------------------------------


@router.post(
    "/trades/gate",
    response_model=GateResponse,
    dependencies=[Depends(require_market_open)],
)
def create_gate(
    req: CreateGateRequest,
    gate: ConfirmationGate = Depends(get_confirmation_gate),
) -> Any:
    """Create a confirmation gate request for a trade.

    Optionally runs auto risk check (PENDING → RISK_APPROVED).
    """
    gate_req = gate.create_request(
        trade_type=req.trade_type,
        symbol=req.symbol,
        quantity=req.quantity,
        price=req.price,
        thread_id=req.thread_id,
    )

    # Auto risk check if requested
    if req.auto_risk_check and gate_req.current_stage == "PENDING":
        gate.auto_risk_check(gate_req.request_id)
        # Refresh to get updated stage
        gate_req = gate.get_request(gate_req.request_id) or gate_req

    return GateResponse(
        request_id=gate_req.request_id,
        symbol=gate_req.symbol,
        trade_type=gate_req.trade_type,
        quantity=gate_req.quantity,
        price=gate_req.price,
        current_stage=gate_req.current_stage,
        created_at=gate_req.created_at,
        updated_at=gate_req.updated_at,
    )


@router.post("/trades/gate/{request_id}/confirm")
def confirm_gate(
    request_id: str,
    req: ConfirmGateRequest,
    gate: ConfirmationGate = Depends(get_confirmation_gate),
) -> dict[str, Any]:
    """User confirms a gate request (RISK_APPROVED → USER_CONFIRMED).

    In broker mode, this also triggers order submission via ExecutionBridge.
    """
    gate_req = gate.get_request(request_id)
    if not gate_req:
        raise HTTPException(status_code=404, detail="Gate request not found")

    if gate_req.current_stage != "RISK_APPROVED":
        raise HTTPException(
            status_code=400,
            detail=f"Gate not in RISK_APPROVED stage (is {gate_req.current_stage})",
        )

    success = gate.confirm_user(request_id, actor="user", notes=req.feedback)
    if not success:
        raise HTTPException(status_code=400, detail="Gate confirmation failed")

    # If execution bridge is available, submit to broker
    execution_bridge = get_execution_bridge()
    broker_result = None
    if execution_bridge and execution_bridge.is_live_mode():
        exec_result = execution_bridge.execute_confirmed(request_id)
        broker_result = {
            "status": exec_result.status,
            "broker_order_id": exec_result.broker_order_id,
            "reason": exec_result.reason,
        }

    gate_req = gate.get_request(request_id) or gate_req
    response: dict[str, Any] = {
        "request_id": gate_req.request_id,
        "symbol": gate_req.symbol,
        "trade_type": gate_req.trade_type,
        "quantity": gate_req.quantity,
        "price": gate_req.price,
        "current_stage": gate_req.current_stage,
        "created_at": gate_req.created_at,
        "updated_at": gate_req.updated_at,
    }
    if broker_result:
        response["broker"] = broker_result
    return response


@router.get("/trades/gate/{request_id}", response_model=GateResponse)
def get_gate(
    request_id: str,
    gate: ConfirmationGate = Depends(get_confirmation_gate),
) -> Any:
    """Get the current state of a gate request."""
    gate_req = gate.get_request(request_id)
    if not gate_req:
        raise HTTPException(status_code=404, detail="Gate request not found")

    return GateResponse(
        request_id=gate_req.request_id,
        symbol=gate_req.symbol,
        trade_type=gate_req.trade_type,
        quantity=gate_req.quantity,
        price=gate_req.price,
        current_stage=gate_req.current_stage,
        created_at=gate_req.created_at,
        updated_at=gate_req.updated_at,
    )


# ---------------------------------------------------------------------------
# Kill Switch endpoints
# ---------------------------------------------------------------------------


@router.post("/trades/kill-switch")
def toggle_kill_switch(
    req: KillSwitchRequest,
    kill_switch: KillSwitch = Depends(get_kill_switch),
) -> dict[str, Any]:
    """Activate or deactivate the trading kill switch."""
    if req.active:
        kill_switch.activate(reason=req.reason, activated_by="api")
    else:
        kill_switch.deactivate()
    return kill_switch.status().__dict__


@router.get("/trades/kill-switch")
def get_kill_switch_status(
    kill_switch: KillSwitch = Depends(get_kill_switch),
) -> dict[str, Any]:
    """Get current kill switch state."""
    return kill_switch.status().__dict__

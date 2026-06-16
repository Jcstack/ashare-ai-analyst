"""Capital management API endpoints.

Endpoints:
    POST  /api/v1/capital/deposit   — Deposit funds
    POST  /api/v1/capital/withdraw  — Withdraw funds
    GET   /api/v1/capital/balance   — Get capital breakdown
    GET   /api/v1/capital/history   — List capital transactions
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.web.dependencies import get_capital_service
from src.web.schemas.capital import (
    CapitalBreakdown,
    CapitalHistoryResponse,
    CapitalTransaction,
    DepositRequest,
    WithdrawRequest,
)
from src.web.services.capital_service import CapitalService

router = APIRouter(tags=["capital"])


@router.post("/deposit", response_model=CapitalTransaction)
def deposit(
    req: DepositRequest,
    capital_service: CapitalService = Depends(get_capital_service),
) -> Any:
    """Deposit funds into the capital account."""
    return capital_service.deposit(amount=req.amount, description=req.description)


@router.post("/withdraw", response_model=CapitalTransaction)
def withdraw(
    req: WithdrawRequest,
    capital_service: CapitalService = Depends(get_capital_service),
) -> Any:
    """Withdraw funds from the capital account."""
    try:
        return capital_service.withdraw(amount=req.amount, description=req.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/balance", response_model=CapitalBreakdown)
def get_balance(
    capital_service: CapitalService = Depends(get_capital_service),
) -> Any:
    """Get full capital breakdown (cash + position values)."""
    return capital_service.get_breakdown()


@router.get("/history", response_model=CapitalHistoryResponse)
def get_history(
    limit: int = 50,
    offset: int = 0,
    tx_type: str | None = None,
    capital_service: CapitalService = Depends(get_capital_service),
) -> Any:
    """List capital transaction history."""
    transactions = capital_service.get_history(
        limit=limit, offset=offset, tx_type=tx_type
    )
    total = capital_service.get_transaction_count(tx_type=tx_type)
    return CapitalHistoryResponse(transactions=transactions, total=total)

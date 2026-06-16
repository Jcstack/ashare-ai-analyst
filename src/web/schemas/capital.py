"""Pydantic models for the capital management system.

Covers transaction records, balance queries, and breakdown views.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CapitalTransaction(BaseModel):
    """A single capital transaction (deposit, withdrawal, or trade settlement)."""

    id: str
    type: str  # initial_deposit | deposit | withdrawal | trade_buy | trade_sell | position_liquidation
    amount: float  # signed: + inflow, - outflow
    balance_after: float
    trade_id: str | None = None
    symbol: str | None = None
    description: str = ""
    created_at: str


class CapitalBalance(BaseModel):
    """Current capital balance snapshot."""

    available_cash: float = 0.0
    total_transactions: int = 0
    has_initial_deposit: bool = False


class PositionCapital(BaseModel):
    """Capital tied up in a single position."""

    symbol: str
    stock_name: str
    shares: int
    cost_price: float
    market_value: float
    cost_basis: float  # shares * cost_price


class CapitalBreakdown(BaseModel):
    """Full capital breakdown: cash + positions."""

    available_cash: float = 0.0
    position_value: float = 0.0
    total_assets: float = 0.0
    utilization_rate: float = 0.0  # position_value / total_assets
    positions: list[PositionCapital] = Field(default_factory=list)
    has_initial_deposit: bool = False


class DepositRequest(BaseModel):
    """Request to deposit funds."""

    amount: float = Field(gt=0)
    description: str = ""


class WithdrawRequest(BaseModel):
    """Request to withdraw funds."""

    amount: float = Field(gt=0)
    description: str = ""


class PositionLiquidationRequest(BaseModel):
    """Request to liquidate (clear) a position and recover capital."""

    symbol: str
    stock_name: str
    shares: int = Field(gt=0)
    price: float = Field(gt=0)
    position_id: str


class CapitalHistoryResponse(BaseModel):
    """Paginated capital transaction history."""

    transactions: list[CapitalTransaction] = Field(default_factory=list)
    total: int = 0

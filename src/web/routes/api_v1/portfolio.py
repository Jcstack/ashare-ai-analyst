"""Portfolio API endpoints.

Provides portfolio persistence (save/load), position CRUD with capital
validation, position liquidation, and AI-powered diagnosis.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from src.web.dependencies import (
    get_capital_service,
    get_portfolio_service,
    get_portfolio_store,
)
from src.web.schemas.capital import CapitalTransaction, PositionLiquidationRequest
from src.web.services.capital_service import CapitalService
from src.web.services.portfolio_service import PortfolioService
from src.web.services.portfolio_store import PortfolioStore
from src.web.routes.api_v1.schemas import (
    ApiResponse,
    PortfolioData,
    PortfolioDiagnosisRequest,
    PortfolioDiagnosisResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["portfolio"])


@router.get("/portfolio", response_model=PortfolioData)
async def load_portfolio(
    store: PortfolioStore = Depends(get_portfolio_store),
) -> dict:
    """Load persisted portfolio data from SQLite."""
    return store.get_portfolio_data()


@router.get("/portfolio/enriched")
async def load_portfolio_enriched(
    store: PortfolioStore = Depends(get_portfolio_store),
) -> dict:
    """Load portfolio enriched with realtime prices and P&L.

    Returns positions with current_price, market_value, pnl, pnl_percent,
    plus portfolio-level totals (total_cost, total_value, total_pnl).
    Used by MCP tools so research threads can see actual P&L.
    """
    base = store.get_portfolio_data()
    positions = base.get("positions", [])
    if not positions:
        return {
            **base,
            "total_cost": 0,
            "total_market_value": 0,
            "total_pnl": 0,
            "total_pnl_percent": 0,
        }

    # Fetch realtime quotes for all held symbols
    symbols = [p["symbol"] for p in positions]
    price_map: dict[str, dict] = {}
    try:
        from src.data.realtime import RealtimeQuoteManager

        rtm = RealtimeQuoteManager()
        quotes_df = await asyncio.to_thread(rtm.get_quotes, symbols)
        if not quotes_df.empty:
            for _, row in quotes_df.iterrows():
                price_map[row["symbol"]] = {
                    "price": row.get("price"),
                    "pct_change": row.get("pct_change"),
                    "prev_close": row.get("prev_close"),
                }
    except Exception as exc:
        logger.warning("Failed to fetch realtime quotes for portfolio: %s", exc)

    # Enrich each position with P&L
    total_cost = 0.0
    total_value = 0.0
    enriched = []
    for p in positions:
        cost_price = p.get("costPrice", 0)
        shares = p.get("shares", 0)
        position_cost = cost_price * shares
        total_cost += position_cost

        quote = price_map.get(p["symbol"], {})
        current_price = quote.get("price")

        if current_price and current_price > 0:
            market_value = current_price * shares
            pnl = market_value - position_cost
            pnl_percent = (pnl / position_cost * 100) if position_cost > 0 else 0
            total_value += market_value
        else:
            market_value = None
            pnl = None
            pnl_percent = None
            total_value += position_cost  # fallback: use cost

        enriched.append(
            {
                **p,
                "currentPrice": current_price,
                "todayChange": quote.get("pct_change"),
                "marketValue": round(market_value, 2) if market_value else None,
                "pnl": round(pnl, 2) if pnl is not None else None,
                "pnlPercent": round(pnl_percent, 2)
                if pnl_percent is not None
                else None,
            }
        )

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    return {
        "version": base.get("version", 1),
        "updatedAt": base.get("updatedAt", ""),
        "positions": enriched,
        "total_cost": round(total_cost, 2),
        "total_market_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_percent": round(total_pnl_pct, 2),
    }


@router.put("/portfolio", response_model=ApiResponse)
async def save_portfolio(
    req: PortfolioData,
    store: PortfolioStore = Depends(get_portfolio_store),
) -> dict:
    """Persist portfolio data (full replacement)."""
    try:
        store.save_portfolio_data(req.model_dump())
        logger.info(
            "Portfolio saved: %d positions, updated %s",
            len(req.positions),
            req.updatedAt,
        )
        return {"status": "success", "message": "Portfolio saved"}
    except Exception as exc:
        logger.error("Failed to save portfolio: %s", exc)
        raise HTTPException(status_code=500, detail=f"Save failed: {exc}")


# ---------------------------------------------------------------------------
# Position CRUD
# ---------------------------------------------------------------------------


@router.post("/portfolio/positions")
async def add_position(
    request: Request,
    store: PortfolioStore = Depends(get_portfolio_store),
) -> dict:
    """Add a new position with optional capital validation.

    Returns the new position or 400 if capital is insufficient.
    """
    body = await request.json()
    try:
        pos = store.add_position(
            symbol=body["symbol"],
            name=body["name"],
            board=body.get("board", "main"),
            cost_price=float(body["costPrice"]),
            shares=int(body["shares"]),
            buy_date=body.get("buyDate", ""),
            note=body.get("note", ""),
            validate_capital=body.get("validateCapital", True),
        )
        return pos
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/portfolio/positions/{position_id}")
async def update_position(
    position_id: str,
    request: Request,
    store: PortfolioStore = Depends(get_portfolio_store),
) -> dict:
    """Update an existing position."""
    body = await request.json()
    # Map camelCase from frontend to snake_case for store
    updates: dict = {}
    field_map = {
        "costPrice": "cost_price",
        "shares": "shares",
        "buyDate": "buy_date",
        "note": "note",
        "name": "name",
        "board": "board",
        "symbol": "symbol",
    }
    for camel, snake in field_map.items():
        if camel in body:
            updates[snake] = body[camel]
    # Also accept snake_case directly
    for key in ("cost_price", "shares", "buy_date", "note", "name", "board", "symbol"):
        if key in body and key not in updates:
            updates[key] = body[key]

    result = store.update_position(position_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found")
    return result


@router.delete("/portfolio/positions/{position_id}")
async def delete_position(
    position_id: str,
    store: PortfolioStore = Depends(get_portfolio_store),
) -> dict:
    """Delete a position without capital recovery."""
    if not store.remove_position(position_id):
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found")
    return {"status": "success", "message": f"Position {position_id} removed"}


# ---------------------------------------------------------------------------
# Liquidation (clear position + recover capital)
# ---------------------------------------------------------------------------


@router.post("/portfolio/positions/liquidate", response_model=CapitalTransaction)
async def liquidate_position(
    req: PositionLiquidationRequest,
    store: PortfolioStore = Depends(get_portfolio_store),
    capital_svc: CapitalService = Depends(get_capital_service),
) -> dict:
    """Clear a position and recover capital at current market price.

    Records a ``position_liquidation`` transaction in the capital ledger
    and removes the position from the database.
    """
    # Find the position by position_id or by symbol
    pos = store.get_position(req.position_id)
    if pos:
        tx_data = store.liquidate_position(req.position_id, req.price)
        return tx_data
    else:
        # Fallback: record capital recovery even if position not found in store
        tx = capital_svc.record_position_liquidation(
            symbol=req.symbol,
            stock_name=req.stock_name,
            shares=req.shares,
            price=req.price,
        )
        return tx.model_dump()


# ---------------------------------------------------------------------------
# AI Diagnosis
# ---------------------------------------------------------------------------


@router.post("/portfolio/diagnose", response_model=PortfolioDiagnosisResult)
async def diagnose_portfolio(
    req: PortfolioDiagnosisRequest,
    svc: PortfolioService = Depends(get_portfolio_service),
) -> dict:
    """Run AI diagnosis on the user's portfolio."""
    positions = [p.model_dump() for p in req.positions]
    result = await asyncio.to_thread(svc.diagnose_portfolio, positions)
    return result

"""Backtest JSON API endpoints.

Provides strategy listing and backtest execution as JSON.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.web.dependencies import get_backtest_service
from src.web.routes.api_v1.schemas import (
    BacktestRequest,
    BacktestRequestV2,
    BacktestResponse,
    BacktestResponseV2,
    StrategyInfo,
    StrategyMetadataResponse,
)

router = APIRouter(tags=["backtest"])


@router.get("/strategies", response_model=list[StrategyInfo])
async def list_strategies(svc=Depends(get_backtest_service)) -> list[dict]:
    """Return available backtest strategies."""
    return svc.get_available_strategies()


@router.post("/backtest", response_model=BacktestResponse)
async def run_backtest(
    req: BacktestRequest,
    svc=Depends(get_backtest_service),
) -> dict:
    """Run a strategy backtest and return results as JSON.

    Args:
        req: Backtest request with symbol, strategy, and board.

    Returns:
        Backtest result with metrics, equity curve, and report.
    """
    result = svc.run_backtest(req.symbol, req.strategy, board=req.board)
    return result


@router.post("/backtest/v2", response_model=BacktestResponseV2)
async def run_backtest_v2(
    req: BacktestRequestV2,
    svc=Depends(get_backtest_service),
) -> dict:
    """Run an enhanced backtest with parameter overrides.

    Returns enriched results including signals, round-trips, dates,
    attribution, and strategy metadata.
    """
    result = svc.run_backtest(
        req.symbol,
        req.strategy,
        board=req.board,
        param_overrides=req.param_overrides,
    )
    return result


@router.get("/strategies/{key}/metadata", response_model=StrategyMetadataResponse)
async def get_strategy_metadata(
    key: str,
    svc=Depends(get_backtest_service),
) -> dict:
    """Return flow chart and parameter metadata for a strategy."""
    return svc.get_strategy_metadata(key)

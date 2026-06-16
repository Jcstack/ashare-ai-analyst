"""Strategy Lab API endpoints.

Provides NL strategy creation, AI optimization, attribution analysis,
and signal checking for paper trading.

Implements FR-AI001~AI003, FR-SG001, FR-PT002 from PRD v3.0.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.web.dependencies import (
    get_strategy_lab_service,
    get_paper_trade_signal_service,
)
from src.web.routes.api_v1.schemas import (
    AIAttributionRequest,
    AIAttributionResult,
    AIOptimizationRequest,
    AIOptimizationResult,
    CheckSignalsRequest,
    LatestSignalItem,
    NLStrategyRequest,
    NLStrategyResult,
)

router = APIRouter(tags=["strategy-lab"])


@router.post("/nl-create", response_model=NLStrategyResult)
async def nl_create_strategy(
    req: NLStrategyRequest,
    svc=Depends(get_strategy_lab_service),
) -> dict:
    """Create a strategy from natural language description."""
    return svc.create_from_nl(req.description, symbol=req.symbol)


@router.post("/ai-optimize", response_model=AIOptimizationResult)
async def ai_optimize_params(
    req: AIOptimizationRequest,
    svc=Depends(get_strategy_lab_service),
) -> dict:
    """AI-driven parameter optimization suggestions."""
    return svc.optimize_params(
        symbol=req.symbol,
        strategy_key=req.strategy_key,
        current_params=req.current_params,
        current_metrics=req.current_metrics,
    )


@router.post("/ai-attribution", response_model=AIAttributionResult)
async def ai_attribution_analysis(
    req: AIAttributionRequest,
    svc=Depends(get_strategy_lab_service),
) -> dict:
    """AI-driven backtest attribution analysis."""
    return svc.analyze_attribution(
        symbol=req.symbol,
        strategy_name=req.strategy_name,
        round_trips=req.round_trips,
        metrics=req.metrics,
    )


@router.get("/latest-signals/{symbol}", response_model=list[LatestSignalItem])
async def get_latest_signals(
    symbol: str,
    svc=Depends(get_paper_trade_signal_service),
) -> list[dict]:
    """Get latest signals from all strategies for a symbol."""
    return svc.get_latest_signals(symbol)


@router.post("/check-signals", response_model=list[LatestSignalItem])
async def check_paper_trade_signals(
    req: CheckSignalsRequest,
    svc=Depends(get_paper_trade_signal_service),
) -> list[dict]:
    """Check signals for paper trade positions."""
    return svc.check_signals(req.positions)

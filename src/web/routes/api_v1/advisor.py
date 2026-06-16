"""AI Trading Advisor API endpoints.

Per PRD v3.2 FR-TA001~004, FR-HS003~004.

Provides:
- GET /advisor/stock/{symbol} — individual stock operation advice
- GET /advisor/watchlist — watchlist strategy report
- POST /advisor/portfolio — portfolio add/reduce advice
- GET /advisor/holiday-impact/{symbol} — holiday impact assessment
- GET /advisor/reopen-briefing — pre-open briefing report
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Query

from src.web.dependencies import get_advisor_service
from src.web.schemas.advisor import (
    HolidayImpactResult,
    PortfolioAdviceRequest,
    PortfolioAdviceResult,
    ReopenBriefingResult,
    StockAdviceResult,
    WatchlistStrategyResult,
)
from src.web.services.advisor_service import AdvisorService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["advisor"])


@router.get("/stock/{symbol}", response_model=StockAdviceResult)
async def get_stock_advice(
    symbol: str,
    svc: AdvisorService = Depends(get_advisor_service),
) -> dict:
    """Get AI-generated operation advice for a single stock."""
    try:
        return await asyncio.to_thread(svc.get_stock_advice, symbol)
    except Exception:
        logger.exception("Stock advice failed for %s", symbol)
        return {
            "status": "error",
            "symbol": symbol,
            "action": "watch",
            "action_label": "观望",
            "confidence": 0.0,
            "risk_level": "high",
            "quant_signals": {},
            "ai_reasoning": [],
            "risk_warnings": ["服务暂时不可用"],
            "disclaimer": "AI 分析仅供参考，不构成投资建议。",
        }


@router.get("/watchlist", response_model=WatchlistStrategyResult)
async def get_watchlist_strategy(
    symbols: str = Query("", description="Comma-separated stock codes"),
    svc: AdvisorService = Depends(get_advisor_service),
) -> dict:
    """Get strategy report for watchlist stocks."""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {"status": "error", "items": [], "total": 0, "disclaimer": ""}

    try:
        return await asyncio.to_thread(svc.get_watchlist_strategy, symbol_list)
    except Exception:
        logger.exception("Watchlist strategy failed")
        return {"status": "error", "items": [], "total": 0, "disclaimer": ""}


@router.post("/portfolio", response_model=PortfolioAdviceResult)
async def get_portfolio_advice(
    request: PortfolioAdviceRequest,
    svc: AdvisorService = Depends(get_advisor_service),
) -> dict:
    """Get add/reduce/stop-loss advice for held positions."""
    if not request.positions:
        return {"status": "error", "positions": [], "total": 0, "disclaimer": ""}

    try:
        return await asyncio.to_thread(svc.get_portfolio_advice, request.positions)
    except Exception:
        logger.exception("Portfolio advice failed")
        return {"status": "error", "positions": [], "total": 0, "disclaimer": ""}


@router.get("/holiday-impact/{symbol}", response_model=HolidayImpactResult)
async def get_holiday_impact(
    symbol: str,
    svc: AdvisorService = Depends(get_advisor_service),
) -> dict:
    """Assess holiday impact on a held stock."""
    try:
        return await asyncio.to_thread(svc.get_holiday_impact, symbol)
    except Exception:
        logger.exception("Holiday impact failed for %s", symbol)
        return {
            "status": "error",
            "symbol": symbol,
            "impact_score": 0.5,
            "impact_direction": "neutral",
            "factors": [],
            "ai_assessment": "评估暂时不可用",
            "suggested_action": "watch",
            "confidence": 0.0,
            "disclaimer": "AI 分析仅供参考，不构成投资建议。",
        }


@router.get("/reopen-briefing", response_model=ReopenBriefingResult)
async def get_reopen_briefing(
    svc: AdvisorService = Depends(get_advisor_service),
) -> dict:
    """Get pre-open comprehensive briefing report."""
    try:
        return await asyncio.to_thread(svc.get_reopen_briefing)
    except Exception:
        logger.exception("Reopen briefing failed")
        return {
            "status": "error",
            "market_outlook": "neutral",
            "confidence": 0.0,
            "summary": "研判报告暂时不可用",
            "key_events": [],
            "position_impacts": [],
            "recommendations": [],
            "risk_warnings": [],
            "disclaimer": "AI 分析仅供参考，不构成投资建议。",
        }

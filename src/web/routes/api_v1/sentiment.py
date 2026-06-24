"""Sentiment analysis and cross-market API endpoints.

Per PRD v3.2 FR-TN003 (resonance), FR-TN004 (sentiment report),
FR-TN005 (market pulse), FR-GM004 (cross-market).
"""

import asyncio

from fastapi import APIRouter, Depends, Query

from src.web.dependencies import get_sentiment_service
from src.web.services.sentiment_service import SentimentService
from src.utils.logger import get_logger

logger = get_logger("routes.sentiment")

router = APIRouter(tags=["sentiment"])

_GENERIC_ERROR_MESSAGE = "舆情分析服务暂时不可用，请稍后再试"


@router.get("/resonance")
async def get_resonance_events(
    symbols: str = Query("", description="Comma-separated watchlist symbols"),
    svc: SentimentService = Depends(get_sentiment_service),
):
    """Get cross-platform resonance events (FR-TN003).

    Detects trending topics appearing on multiple platforms simultaneously.
    """
    watchlist = [s.strip() for s in symbols.split(",") if s.strip()] or None

    try:
        result = await asyncio.to_thread(svc.get_resonance_events, watchlist)
        return result
    except Exception:
        logger.exception("Resonance detection failed")
        return {
            "status": "error",
            "events": [],
            "total": 0,
            "message": _GENERIC_ERROR_MESSAGE,
        }


@router.get("/report")
async def get_sentiment_report(
    symbols: str = Query("", description="Comma-separated watchlist symbols"),
    svc: SentimentService = Depends(get_sentiment_service),
):
    """Get structured AI sentiment analysis report (FR-TN004).

    Returns 6-part analysis: core trends, policy signals, global linkage,
    risk alerts, sector outlook, and overall outlook.
    """
    watchlist = [s.strip() for s in symbols.split(",") if s.strip()] or None

    try:
        result = await asyncio.to_thread(
            svc.get_sentiment_report,
            watchlist=watchlist,
        )
        return result
    except Exception:
        logger.exception("Sentiment report failed")
        return {
            "status": "error",
            "core_trends": [],
            "policy_signals": [],
            "global_linkage": {},
            "risk_alerts": [],
            "sector_outlook": {},
            "overall_outlook": "舆情分析暂时不可用",
            "message": _GENERIC_ERROR_MESSAGE,
        }


@router.get("/market-pulse")
async def get_market_pulse(
    symbols: str = Query("", description="Comma-separated watchlist symbols"),
    svc: SentimentService = Depends(get_sentiment_service),
):
    """Get combined market pulse data for dashboard (FR-TN005).

    Returns hot events, holdings-related news, and global market summary.
    """
    watchlist = [s.strip() for s in symbols.split(",") if s.strip()] or None

    try:
        result = await asyncio.to_thread(
            svc.get_market_pulse,
            watchlist=watchlist,
        )
        return result
    except Exception:
        logger.exception("Market pulse failed")
        return {
            "status": "error",
            "hot_events": [],
            "holdings_news": {},
            "message": _GENERIC_ERROR_MESSAGE,
        }


@router.get("/cross-market/{symbol}")
async def get_cross_market_analysis(
    symbol: str,
    svc: SentimentService = Depends(get_sentiment_service),
):
    """Get cross-market correlation analysis for a stock (FR-GM004).

    Returns peer performance, impact scores, and correlation data.
    """
    try:
        result = await asyncio.to_thread(svc.get_cross_market_analysis, symbol)
        return result
    except Exception:
        logger.exception("Cross-market analysis failed for %s", symbol)
        return {
            "symbol": symbol,
            "combined_impact_score": 0.0,
            "impact_direction": "neutral",
            "message": _GENERIC_ERROR_MESSAGE,
        }

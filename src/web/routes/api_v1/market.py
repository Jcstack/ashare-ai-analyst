"""Market data API endpoints — real-time quotes, indices, dragon-tiger, limit-up, SSE stream.

Per PRD FR-D004/D005/D006: real-time and market event data.
Per PRD v2.0 FR-RT001: SSE streaming for real-time quote updates.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Query, Request
from sse_starlette.sse import EventSourceResponse

from src.data.trading_calendar import TradingCalendar
from src.web.dependencies import (
    get_market_service,
    get_realtime_quote_manager,
    get_stock_service,
    get_trading_calendar,
)
from src.web.services.market_service import MarketService
from src.web.services.stock_service import StockService
from src.web.utils import sanitize_records
from src.web.routes.api_v1.schemas import (
    DragonTigerItem,
    DragonTigerSeatItem,
    DragonTigerStockStats,
    LimitUpItem,
    MarketIndex,
    RealtimeQuote,
    TradingCalendarInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["market"])


@router.get("/indices", response_model=list[MarketIndex])
async def get_market_indices(
    market_svc: MarketService = Depends(get_market_service),
) -> list[dict]:
    """Get major A-share market indices with multi-source fallback.

    Source chain: Sina → EastMoney → Xueqiu → cached → seed values.
    Ensures indices are never empty on cold start (FR-DR002).
    """
    return await asyncio.to_thread(market_svc.get_market_indices)


@router.get("/realtime", response_model=list[RealtimeQuote])
async def get_realtime_quotes(
    symbols: str = Query(
        "", description="Comma-separated stock codes, empty for watchlist"
    ),
    svc: StockService = Depends(get_stock_service),
    quote_mgr=Depends(get_realtime_quote_manager),
) -> list[dict]:
    """Get real-time quotes for stocks.

    If symbols is empty, returns quotes for the configured watchlist.
    """
    symbol_list = (
        [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    )

    if symbol_list is None:
        # Default to watchlist
        watchlist = svc.get_watchlist()
        symbol_list = [s["symbol"] for s in watchlist]

    # Try RealtimeQuoteManager singleton, fall back to legacy fetcher
    try:
        df = await asyncio.to_thread(quote_mgr.get_quotes, symbol_list)
    except Exception:
        logger.debug("RealtimeQuoteManager unavailable, falling back to legacy fetcher")
        try:
            df = await asyncio.to_thread(
                svc.fetcher.fetch_realtime_quotes, symbols=symbol_list
            )
        except Exception:
            logger.warning("Real-time quotes unavailable (all sources failed)")
            return []

    records = df.to_dict(orient="records")
    return sanitize_records(records)


@router.get("/dragon-tiger", response_model=list[DragonTigerItem])
async def get_dragon_tiger(
    start_date: str = Query("", description="Start date YYYYMMDD"),
    end_date: str = Query("", description="End date YYYYMMDD"),
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    """Get dragon-tiger list data.

    Data is typically available after market close (~16:00 CST).
    Returns empty list if data is not yet available.
    """
    try:
        df = await asyncio.to_thread(
            svc.fetcher.fetch_dragon_tiger,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception:
        logger.warning("Dragon-tiger data not available (may be during trading hours)")
        return []
    records = df.to_dict(orient="records")
    return sanitize_records(records)


@router.get("/limit-up", response_model=list[LimitUpItem])
async def get_limit_up(
    date: str = Query("", description="Date YYYYMMDD, default today"),
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    """Get limit-up pool data."""
    df = await asyncio.to_thread(svc.fetcher.fetch_limit_up_pool, date=date)
    records = df.to_dict(orient="records")
    return sanitize_records(records)


@router.get("/dragon-tiger/{symbol}", response_model=list[DragonTigerItem])
async def get_stock_dragon_tiger(
    symbol: str,
    days: int = Query(30, description="Look-back window in calendar days"),
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    """Get dragon-tiger records for a specific stock over the last *days* days."""
    end = datetime.now()
    start = end - timedelta(days=days)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    try:
        df = await asyncio.to_thread(
            svc.fetcher.fetch_dragon_tiger,
            start_date=start_str,
            end_date=end_str,
        )
    except Exception:
        logger.warning(
            "Dragon-tiger data not available for %s (may be during trading hours)",
            symbol,
        )
        return []

    # Normalize symbol column for comparison (strip leading zeros / suffixes)
    symbol_clean = symbol.strip()
    if "代码" in df.columns:
        col = "代码"
    elif "symbol" in df.columns:
        col = "symbol"
    else:
        col = None

    if col is not None:
        df = df[df[col].astype(str).str.strip() == symbol_clean]

    records = df.to_dict(orient="records")
    return sanitize_records(records)


@router.get("/dragon-tiger/{symbol}/seats", response_model=list[DragonTigerSeatItem])
async def get_dragon_tiger_seats(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    """Get dragon-tiger seat details for a specific stock.

    Per PRD v2.3 FR-DT001.
    """
    try:
        df = await asyncio.to_thread(svc.fetcher.fetch_dragon_tiger_seats, symbol)
    except Exception:
        logger.warning("Dragon-tiger seats not available for %s", symbol)
        return []

    records = df.to_dict(orient="records")
    return sanitize_records(records)


@router.get("/dragon-tiger/{symbol}/stats", response_model=DragonTigerStockStats)
async def get_dragon_tiger_stats(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> dict:
    """Get dragon-tiger historical statistics for a stock.

    Per PRD v2.3 FR-DT001.
    """
    try:
        df = await asyncio.to_thread(svc.fetcher.fetch_dragon_tiger_stock_stats, symbol)
    except Exception:
        logger.warning("Dragon-tiger stats not available for %s", symbol)
        return {
            "appearances_3m": 0,
            "institution_net_buy": 0,
            "avg_return_5d": 0,
            "win_rate_5d": 0,
        }

    if df.empty:
        return {
            "appearances_3m": 0,
            "institution_net_buy": 0,
            "avg_return_5d": 0,
            "win_rate_5d": 0,
        }

    row = df.iloc[0]

    def safe_float(val: object, default: float = 0.0) -> float:
        if val is None:
            return default
        if isinstance(val, float) and val != val:  # NaN
            return default
        return float(val)

    return {
        "appearances_3m": int(safe_float(row.get("appearances", 0))),
        "institution_net_buy": safe_float(row.get("inst_net_amount", 0)),
        "avg_return_5d": 0.0,
        "win_rate_5d": 0.0,
    }


@router.get("/calendar", response_model=TradingCalendarInfo)
async def get_trading_calendar_info(
    cal: TradingCalendar = Depends(get_trading_calendar),
) -> dict:
    """Get trading calendar information for today.

    Per PRD v3.2 FR-HS001.
    """
    return cal.get_calendar_info()


@router.get("/status")
async def get_market_status() -> dict:
    """Get comprehensive market status for frontend display.

    Returns status, label, is_trading, next_event with countdown,
    holiday_info, and emergency closure details.
    Designed for frontend polling (recommended: every 30s).
    """
    from src.utils.market_hours import get_market_status_for_ui

    return await asyncio.to_thread(get_market_status_for_ui)


@router.get("/stream")
async def stream_quotes(
    request: Request,
    symbols: str = Query(
        "", description="Comma-separated stock codes, empty for watchlist"
    ),
    svc: StockService = Depends(get_stock_service),
    quote_mgr=Depends(get_realtime_quote_manager),
) -> EventSourceResponse:
    """SSE endpoint streaming real-time quote updates.

    Sends quote snapshots every 10 seconds until client disconnects.
    Falls back gracefully if the realtime data source is unavailable.

    Args:
        request: FastAPI request (used for disconnect detection).
        symbols: Comma-separated 6-digit stock codes.

    Returns:
        EventSourceResponse with periodic quote events.
    """

    async def event_generator() -> AsyncGenerator[dict, None]:
        symbol_list = (
            [s.strip() for s in symbols.split(",") if s.strip()]
            if symbols
            else [s["symbol"] for s in svc.get_watchlist()]
        )

        manager = quote_mgr

        while True:
            if await request.is_disconnected():
                break

            try:
                if manager is not None:
                    df = await asyncio.to_thread(manager.get_quotes, symbol_list)
                else:
                    df = await asyncio.to_thread(
                        svc.fetcher.fetch_realtime_quotes, symbols=symbol_list
                    )

                records = df.to_dict(orient="records")
                sanitize_records(records)

                yield {
                    "event": "quote",
                    "data": json.dumps(records, ensure_ascii=False),
                }
            except Exception as exc:
                logger.warning("SSE stream error: %s", exc)
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"error": "Quote fetch failed"},
                        ensure_ascii=False,
                    ),
                }

            await asyncio.sleep(10)

    return EventSourceResponse(event_generator())

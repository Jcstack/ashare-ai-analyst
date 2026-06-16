"""Stock-related JSON API endpoints.

Provides watchlist, stock detail, OHLCV, indicators, patterns,
and support/resistance data as JSON.
"""

from __future__ import annotations

import asyncio
import logging
import re

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from src.data.realtime import RealtimeQuoteManager
from src.web.dependencies import (
    get_realtime_analyzer,
    get_realtime_quote_manager,
    get_stock_registry,
    get_stock_service,
    get_strategy_context_service,
    get_watchlist_service,
)
from src.web.services.stock_service import StockService
from src.web.services.watchlist_service import WatchlistService
from src.web.utils import sanitize_records
from src.web.routes.api_v1.schemas import (
    BayesianAnalysisResult,
    FundFlowDetail,
    FundFlowItem,
    IndicatorsFullRecord,
    IndicatorsSummary,
    IntradayTradesStats,
    OHLCVRecord,
    PatternDetection,
    RealtimeSnapshot,
    SRAnalysisResult,
    StockDetail,
    SupportResistanceLevel,
    WatchlistItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stocks"])

_PREFIXED_RE = re.compile(r"^(?:sh|sz|bj)(\d{6})$", re.IGNORECASE)


def _normalize_symbol(symbol: str) -> str:
    """Strip sh/sz exchange prefix if present, returning bare 6-digit code."""
    m = _PREFIXED_RE.match(symbol)
    return m.group(1) if m else symbol


@router.get("/indicators/explanations")
async def get_indicator_explanations(
    indicator: str = Query(
        "",
        description="Specific indicator key (MA, MACD, RSI, KDJ, BOLL, VOL). Empty for all.",
    ),
) -> dict:
    """Get beginner-friendly explanations for technical indicators."""
    from src.analysis.explanations import (
        get_all_explanations,
        get_indicator_explanation,
    )

    if indicator:
        result = get_indicator_explanation(indicator)
        if result is None:
            return {"error": f"Unknown indicator: {indicator}"}
        return {indicator.upper(): result}
    return get_all_explanations()


@router.get("/watchlist", response_model=list[WatchlistItem])
async def get_watchlist(
    svc: StockService = Depends(get_stock_service),
    wl_svc: WatchlistService = Depends(get_watchlist_service),
) -> list[dict]:
    """Return the watchlist with latest price info for each stock."""
    watchlist = wl_svc.list_all()
    if not watchlist:
        return []

    symbols = [e["symbol"] for e in watchlist]

    # Batch fetch realtime quotes (1 call instead of N)
    quotes_map: dict[str, dict] = {}
    try:
        manager = RealtimeQuoteManager()
        df = await asyncio.to_thread(manager.get_quotes, symbols)
        for rec in df.to_dict(orient="records"):
            sym = rec.get("symbol", "")
            quotes_map[sym] = rec
    except Exception:
        logger.debug("Batch quote fetch failed, falling back to per-stock")

    result = []
    for entry in watchlist:
        symbol = entry["symbol"]
        quote = quotes_map.get(symbol, {})
        if quote:
            info = {
                "close": quote.get("price"),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "change": quote.get("change"),
                "pct_change": quote.get("pct_change"),
                "volume": int(quote["volume"])
                if quote.get("volume") is not None
                else None,
            }
        else:
            info = await asyncio.to_thread(svc.get_latest_price_info, symbol) or {}
        result.append(
            {
                "symbol": symbol,
                "name": entry.get("name", symbol),
                "board": entry.get("board", "main"),
                **info,
            }
        )
    return result


@router.get("/stock/{symbol}", response_model=StockDetail)
async def get_stock_detail(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> dict:
    """Return stock detail with latest price, name, and board type.

    Works for ANY A-share stock, not just those in the watchlist.
    """
    symbol = _normalize_symbol(symbol)
    info = svc.get_latest_price_info(symbol)
    if info is None:
        # Fallback: fetch realtime quote (Sina/Xueqiu/adata) for stocks without OHLCV cache
        try:
            quote_mgr = get_realtime_quote_manager()
            quote = await asyncio.to_thread(quote_mgr.get_single_quote, symbol)
            if quote.get("price") is not None:
                info = {
                    "close": float(quote["price"]),
                    "open": float(quote["open"])
                    if quote.get("open")
                    else float(quote["price"]),
                    "high": float(quote["high"])
                    if quote.get("high")
                    else float(quote["price"]),
                    "low": float(quote["low"])
                    if quote.get("low")
                    else float(quote["price"]),
                    "change": float(quote.get("change", 0)),
                    "pct_change": float(quote.get("pct_change", 0)),
                    "volume": int(quote["volume"]) if quote.get("volume") else 0,
                    "date": "",
                }
        except Exception:
            logger.debug("Realtime quote fallback failed for %s", symbol)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

    # Look up name and board from watchlist first
    name = symbol
    board = "main"
    for entry in svc.get_watchlist():
        if entry["symbol"] == symbol:
            name = entry.get("name", symbol)
            board = entry.get("board", "main")
            break
    else:
        # Fallback to StockRegistry for stocks not in watchlist
        registry = get_stock_registry()
        reg_info = registry.get_stock_info(symbol)
        if reg_info:
            name = reg_info["name"]
            board = reg_info["board"]

    return {"symbol": symbol, "name": name, "board": board, **info}


@router.get("/stock/{symbol}/ohlcv", response_model=list[OHLCVRecord])
async def get_ohlcv(
    symbol: str,
    period: str = Query(
        "daily", description="daily|weekly|monthly|1|5|15|30|60|timeline"
    ),
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    """Return OHLCV data as JSON records for client-side charting."""
    symbol = _normalize_symbol(symbol)
    df = await asyncio.to_thread(svc.get_stock_data_by_period, symbol, period)
    if df is None or df.empty:
        raise HTTPException(
            status_code=404, detail=f"No data for {symbol} (period={period})"
        )

    base_cols = ["date", "open", "high", "low", "close", "volume"]
    available = [c for c in base_cols if c in df.columns]
    out = df[available].copy()
    out["date"] = out["date"].astype(str)
    for col in ["open", "high", "low", "close"]:
        if col in out.columns:
            out[col] = out[col].astype(float)
    if "volume" in out.columns:
        out["volume"] = (
            pd.to_numeric(out["volume"], errors="coerce").fillna(0).astype(int)
        )
    return out.to_dict(orient="records")


@router.get("/stock/{symbol}/intraday-trades", response_model=IntradayTradesStats)
async def get_intraday_trades(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> dict:
    """Return aggregated buy/sell volume statistics from intraday tick data."""
    symbol = _normalize_symbol(symbol)
    result = await asyncio.to_thread(svc.get_intraday_trades, symbol)
    if result is None:
        return {
            "buy_volume": 0,
            "sell_volume": 0,
            "neutral_volume": 0,
            "total_volume": 0,
            "buy_ratio": 0,
            "sell_ratio": 0,
            "is_historical": False,
        }
    return result


@router.get("/stock/{symbol}/realtime-snapshot", response_model=RealtimeSnapshot)
async def get_realtime_snapshot(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
    quote_mgr: RealtimeQuoteManager = Depends(get_realtime_quote_manager),
) -> dict:
    """Return a composite realtime snapshot (quote + trades + fund flow).

    Combines 4 independent data fetches into a single response so the
    frontend can replace 4-5 polling requests with one 30-second poll.
    Each sub-query is independently fault-tolerant — if one fails, the
    others still return data.
    """
    symbol = _normalize_symbol(symbol)
    from datetime import datetime

    from src.utils.market_hours import is_a_share_trading_open

    market_open = is_a_share_trading_open()

    async def _get_quote() -> dict | None:
        try:
            df = await asyncio.to_thread(quote_mgr.get_quotes, [symbol])
            if not df.empty:
                rec = df.iloc[0].to_dict()
                sanitize_records([rec])
                return {
                    "price": rec.get("price"),
                    "change": rec.get("change"),
                    "pct_change": rec.get("pct_change"),
                    "volume": rec.get("volume"),
                    "open": rec.get("open"),
                    "high": rec.get("high"),
                    "low": rec.get("low"),
                    "prev_close": rec.get("prev_close"),
                    "amount": rec.get("amount"),
                }
        except Exception as exc:
            logger.debug("Snapshot quote failed for %s: %s", symbol, exc)
        return None

    async def _get_trades() -> dict | None:
        try:
            result = await asyncio.to_thread(
                svc.get_intraday_trades_with_ticks, symbol, 50
            )
            return result
        except Exception as exc:
            logger.debug("Snapshot trades failed for %s: %s", symbol, exc)
        return None

    async def _get_fund_flow() -> dict | None:
        try:
            df = await asyncio.to_thread(svc.fetcher.fetch_intraday_fund_flow, symbol)
            if not df.empty:
                rec = df.iloc[0].to_dict()
                sanitize_records([rec])
                return {
                    "date": str(rec.get("date", "")),
                    "main_net": rec.get("main_net"),
                    "super_large_net": rec.get("super_large_net"),
                    "large_net": rec.get("large_net"),
                    "medium_net": rec.get("medium_net"),
                    "small_net": rec.get("small_net"),
                }
        except Exception as exc:
            logger.debug("Snapshot fund flow failed for %s: %s", symbol, exc)
        return None

    async def _get_fund_flow_detail() -> dict | None:
        try:
            df = await asyncio.to_thread(svc.fetcher.fetch_fund_flow_detail, symbol)
            if not df.empty:
                rec = df.iloc[0].to_dict()
                sanitize_records([rec])
                for key in ("inflow", "outflow", "net"):
                    val = rec.get(key)
                    if isinstance(val, str):
                        rec[key] = _parse_cn_number(val)
                return {
                    "inflow": rec.get("inflow"),
                    "outflow": rec.get("outflow"),
                    "net": rec.get("net"),
                }
        except Exception as exc:
            logger.debug("Snapshot fund flow detail failed for %s: %s", symbol, exc)
        return None

    # Each sub-query gets a 15s ceiling — fast enough for realtime data.
    _SNAPSHOT_TIMEOUT = 15

    async def _with_timeout(coro, label: str):
        try:
            return await asyncio.wait_for(coro, timeout=_SNAPSHOT_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(
                "Snapshot %s timed out for %s (%ds)", label, symbol, _SNAPSHOT_TIMEOUT
            )
            return None

    # After market close, trades/fund_flow data is static — skip slow API calls
    if market_open:
        quote, trades, fund_flow, fund_flow_detail = await asyncio.gather(
            _with_timeout(_get_quote(), "quote"),
            _with_timeout(_get_trades(), "trades"),
            _with_timeout(_get_fund_flow(), "fund_flow"),
            _with_timeout(_get_fund_flow_detail(), "fund_flow_detail"),
        )
    else:
        quote = await _with_timeout(_get_quote(), "quote")
        trades, fund_flow, fund_flow_detail = None, None, None

    return {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "quote": quote,
        "trades": trades,
        "fund_flow": fund_flow,
        "fund_flow_detail": fund_flow_detail,
    }


@router.get("/stock/{symbol}/indicators", response_model=IndicatorsSummary)
async def get_indicators(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> dict:
    """Return the latest indicator values for a stock."""
    symbol = _normalize_symbol(symbol)
    summary = svc.get_indicators_summary(symbol)
    if not summary:
        raise HTTPException(status_code=404, detail=f"No indicators for {symbol}")
    return {"values": summary}


@router.get(
    "/stock/{symbol}/indicators/full",
    response_model=list[IndicatorsFullRecord],
)
async def get_indicators_full(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    """Return full DataFrame with OHLCV + indicators for chart overlays."""
    symbol = _normalize_symbol(symbol)
    df = svc.get_stock_with_indicators(symbol)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"No indicator data for {symbol}")

    # Identify indicator columns (non-OHLCV)
    base_cols = {"date", "open", "high", "low", "close", "volume"}
    indicator_cols = [c for c in df.columns if c not in base_cols]

    records = []
    for _, row in df.iterrows():
        indicators = {}
        for col in indicator_cols:
            val = row.get(col)
            indicators[col] = round(float(val), 4) if pd.notna(val) else None
        records.append(
            {
                "date": str(row.get("date", "")),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "indicators": indicators,
            }
        )
    return records


@router.get(
    "/stock/{symbol}/indicators/bayesian",
    response_model=BayesianAnalysisResult,
)
async def get_bayesian_indicators(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> dict:
    """Return Bayesian conditional probability analysis for indicators.

    Per PRD v2.3 FR-BI003. Computes P(up|indicator in bin) for RSI, MACD,
    KDJ, Bollinger Band position, and volume ratio.
    """
    symbol = _normalize_symbol(symbol)
    from datetime import datetime

    from src.analysis.bayesian_indicators import BayesianIndicatorAnalyzer

    df = svc.get_stock_with_indicators(symbol)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")

    analyzer = BayesianIndicatorAnalyzer()
    result = analyzer.analyze(df)

    # Look up name
    name = symbol
    for entry in svc.get_watchlist():
        if entry["symbol"] == symbol:
            name = entry.get("name", symbol)
            break
    else:
        registry = get_stock_registry()
        reg_info = registry.get_stock_info(symbol)
        if reg_info:
            name = reg_info["name"]

    return {
        "symbol": symbol,
        "name": name,
        "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        "lookback_days": analyzer.lookback_days,
        "forward_days": analyzer.forward_days,
        **result,
    }


@router.get("/stock/{symbol}/patterns", response_model=list[PatternDetection])
async def get_patterns(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    """Return detected candlestick patterns for a stock."""
    symbol = _normalize_symbol(symbol)
    df = svc.get_stock_with_patterns(symbol)
    if df is None or df.empty:
        return []

    pattern_cols = [c for c in df.columns if c.startswith("pattern_")]
    last_row = df.iloc[-1]
    patterns = []
    for col in pattern_cols:
        if last_row[col] != 0:
            patterns.append(
                {
                    "name": col.replace("pattern_", ""),
                    "value": int(last_row[col]),
                }
            )
    return patterns


@router.get(
    "/stock/{symbol}/support-resistance",
    response_model=list[SupportResistanceLevel],
)
async def get_support_resistance(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    """Return support and resistance levels for a stock."""
    symbol = _normalize_symbol(symbol)
    levels = svc.get_support_resistance(symbol)
    return levels


@router.get("/stock/{symbol}/fund-flow", response_model=list[FundFlowItem])
async def get_fund_flow(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    """Get individual stock fund flow data (main/retail net inflow).

    Per PRD v2.4 FR-SR005.
    """
    symbol = _normalize_symbol(symbol)
    try:
        df = await asyncio.to_thread(svc.fetcher.fetch_fund_flow, symbol)
    except Exception:
        logger.warning("Fund flow unavailable for %s", symbol)
        return []

    if df.empty:
        return []

    records = df.to_dict(orient="records")
    return sanitize_records(records)


@router.get("/stock/{symbol}/fund-flow/intraday", response_model=list[FundFlowItem])
async def get_intraday_fund_flow(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    """Get today's intraday fund-flow data for a stock."""
    symbol = _normalize_symbol(symbol)
    try:
        df = await asyncio.to_thread(svc.fetcher.fetch_intraday_fund_flow, symbol)
    except Exception:
        logger.warning("Intraday fund flow unavailable for %s", symbol)
        return []

    if df.empty:
        return []

    records = df.to_dict(orient="records")
    return sanitize_records(records)


@router.get("/stock/{symbol}/fund-flow/detail", response_model=FundFlowDetail)
async def get_fund_flow_detail(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
) -> dict:
    """Get per-stock inflow/outflow detail from real-time data."""
    symbol = _normalize_symbol(symbol)
    try:
        df = await asyncio.to_thread(svc.fetcher.fetch_fund_flow_detail, symbol)
    except Exception:
        logger.warning("Fund flow detail unavailable for %s", symbol)
        return {"symbol": symbol}

    if df.empty:
        return {"symbol": symbol}

    rec = df.iloc[0].to_dict()
    sanitize_records([rec])
    # AKShare may return Chinese-formatted strings (e.g. "20.84亿", "0.91%")
    # that need to be converted to numeric values for the schema.
    for key in ("price", "pct_change", "inflow", "outflow", "net", "amount"):
        val = rec.get(key)
        if isinstance(val, str):
            rec[key] = _parse_cn_number(val)
    return rec


def _parse_cn_number(s: str) -> float | None:
    """Parse a Chinese-formatted number string to float.

    Handles suffixes like 亿 (1e8) and 万 (1e4), and strips % signs.
    Returns None if parsing fails.
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip().replace(",", "").replace("，", "")
    try:
        if s.endswith("%"):
            return float(s[:-1])
        if s.endswith("亿"):
            return float(s[:-1]) * 1e8
        if s.endswith("万"):
            return float(s[:-1]) * 1e4
        return float(s)
    except (ValueError, TypeError):
        return None


@router.get("/stock/{symbol}/comprehensive-analysis")
async def get_comprehensive_analysis(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
    analyzer=Depends(get_realtime_analyzer),
) -> dict:
    """Get comprehensive realtime analysis combining fund-flow, dragon-tiger,
    quotes, and indicators.

    Per PRD v2.4 — provides a holistic AI summary during trading hours.
    """
    symbol = _normalize_symbol(symbol)

    # Gather all inputs in parallel
    async def _get_quote() -> dict | None:
        try:
            manager = RealtimeQuoteManager()
            df = await asyncio.to_thread(manager.get_quotes, [symbol])
            if not df.empty:
                rec = df.iloc[0].to_dict()
                sanitize_records([rec])
                return rec
        except Exception:
            pass
        return None

    async def _get_fund_flow() -> list[dict]:
        try:
            df = await asyncio.to_thread(svc.fetcher.fetch_intraday_fund_flow, symbol)
            if not df.empty:
                return df.to_dict(orient="records")
        except Exception:
            pass
        return []

    async def _get_dragon_tiger() -> list[dict]:
        try:
            from datetime import datetime, timedelta

            end = datetime.now()
            start = end - timedelta(days=7)
            df = await asyncio.to_thread(
                svc.fetcher.fetch_dragon_tiger,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            if not df.empty:
                sym_col = (
                    "代码"
                    if "代码" in df.columns
                    else "symbol"
                    if "symbol" in df.columns
                    else None
                )
                if sym_col:
                    df = df[df[sym_col].astype(str).str.strip() == symbol.strip()]
                return df.to_dict(orient="records")
        except Exception:
            pass
        return []

    async def _get_indicators() -> dict:
        try:
            return svc.get_indicators_summary(symbol) or {}
        except Exception:
            return {}

    async def _get_valuation() -> dict:
        try:
            return await asyncio.to_thread(
                svc.fetcher.fetch_valuation_indicator, symbol
            )
        except Exception:
            return {}

    async def _get_strategy_signals() -> dict:
        try:
            strategy_ctx_svc = get_strategy_context_service()
            return await asyncio.to_thread(
                strategy_ctx_svc.get_strategy_context, symbol
            )
        except Exception:
            return {}

    async def _get_bayesian() -> dict:
        try:
            strategy_ctx_svc = get_strategy_context_service()
            return await asyncio.to_thread(
                strategy_ctx_svc.get_bayesian_context, symbol
            )
        except Exception:
            return {}

    async def _get_fund_flow_detail() -> dict:
        try:
            df = await asyncio.to_thread(svc.fetcher.fetch_fund_flow_detail, symbol)
            if not df.empty:
                rec = df.iloc[0].to_dict()
                sanitize_records([rec])
                return rec
        except Exception:
            return {}
        return {}

    (
        quote,
        fund_flow,
        dragon_tiger,
        indicators,
        valuation,
        strategy_signals,
        bayesian,
        fund_flow_detail,
    ) = await asyncio.gather(
        _get_quote(),
        _get_fund_flow(),
        _get_dragon_tiger(),
        _get_indicators(),
        _get_valuation(),
        _get_strategy_signals(),
        _get_bayesian(),
        _get_fund_flow_detail(),
    )

    # Derive board type and price limit for the symbol
    from src.data.registry import StockRegistry

    board = StockRegistry.get_board(symbol)
    _BOARD_LABEL = {"star": "科创板", "chinext": "创业板", "main": "主板"}
    _PRICE_LIMIT = {"star": "±20%", "chinext": "±20%", "main": "±10%"}
    board_type = _BOARD_LABEL.get(board, "主板")
    price_limit = _PRICE_LIMIT.get(board, "±10%")

    try:
        result = await asyncio.to_thread(
            analyzer.analyze_comprehensive_realtime,
            symbol,
            quote,
            fund_flow,
            dragon_tiger,
            indicators,
            strategy_signals=strategy_signals,
            bayesian_analysis=bayesian,
            board_type=board_type,
            price_limit=price_limit,
            valuation=valuation,
            fund_flow_detail=fund_flow_detail,
        )
        return result
    except Exception as exc:
        logger.warning("Comprehensive analysis failed for %s: %s", symbol, exc)
        return {
            "symbol": symbol,
            "signal": "neutral",
            "summary": "分析暂不可用",
            "points": [],
            "risks": [],
        }


@router.get("/stock/{symbol}/sr-analysis", response_model=SRAnalysisResult)
async def get_sr_analysis(
    symbol: str,
    svc: StockService = Depends(get_stock_service),
    analyzer=Depends(get_realtime_analyzer),
) -> dict:
    """Get AI-enhanced support/resistance analysis with fund flow context.

    Per PRD v2.4 FR-SR005.
    """
    symbol = _normalize_symbol(symbol)
    # Gather inputs
    levels = svc.get_support_resistance(symbol)
    price_info = svc.get_latest_price_info(symbol)
    current_price = price_info.get("close", 0) if price_info else 0

    fund_flow_records: list[dict] = []
    try:
        df = await asyncio.to_thread(svc.fetcher.fetch_fund_flow, symbol)
        if not df.empty:
            fund_flow_records = df.to_dict(orient="records")
    except Exception:
        pass

    result = await asyncio.to_thread(
        analyzer.analyze_support_resistance,
        symbol,
        levels,
        current_price,
        fund_flow_records,
    )
    return result

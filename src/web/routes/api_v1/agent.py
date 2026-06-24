"""AI Agent API endpoints.

Per PRD v2.0 FR-AI001/AI002/AI003.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends

from src.utils.market_hours import get_market_session
from src.web.utils import sanitize_records
from src.web.dependencies import (
    get_alert_engine,
    get_analysis_data_validator,
    get_capital_flow_service,
    get_market_service,
    get_move_analyzer,
    get_news_fetcher,
    get_policy_news_fetcher,
    get_realtime_analyzer,
    get_realtime_quote_manager,
    get_stock_service,
    get_strategy_context_service,
)
from src.web.routes.api_v1.schemas import (
    AIAnalysisResult,
    Alert,
    ChartEventsResult,
    DragonTigerAIResult,
    MarketAIOverview,
    MoveAnalysisRequest,
    MoveAnalysisResult,
    QuickInsight,
    UnifiedAnalysisResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])

_GENERIC_ERROR_MESSAGE = "AI分析服务暂时不可用，请稍后再试"

_DATA_FETCH_SEMAPHORE = asyncio.Semaphore(8)
_DATA_FETCH_TIMEOUT = 30  # seconds per individual data fetch
_MIN_QUALITY_FOR_ANALYSIS = 30


async def _throttled_thread(fn, *args):
    """Run a blocking function in a thread with concurrency + timeout limiting."""
    async with _DATA_FETCH_SEMAPHORE:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args), timeout=_DATA_FETCH_TIMEOUT
        )


async def _gather_analysis_data(
    symbol: str,
    position: dict[str, Any] | None = None,
) -> Any:
    """Unified data gathering, validation, and strategy aggregation.

    Collects quote, news, anomalies, indicators, indices, sector info,
    fund flow, strategy signals, and Bayesian analysis in parallel,
    then validates and enriches the data.

    Args:
        symbol: 6-digit stock code.
        position: Optional portfolio position context.

    Returns:
        Validated AnalysisContext ready for AI consumption.
    """
    svc = get_stock_service()
    quote_mgr = get_realtime_quote_manager()
    news_fetcher_inst = get_news_fetcher()
    strategy_ctx_svc = get_strategy_context_service()
    validator = get_analysis_data_validator()
    capital_flow_svc = get_capital_flow_service()
    policy_fetcher = get_policy_news_fetcher()

    # Use daily fund_flow (with accurate dates) outside trading hours;
    # intraday minute-level data is only reliable during trading sessions.
    session = get_market_session()
    if session.get("is_trading"):
        fund_flow_fn = svc.fetcher.fetch_intraday_fund_flow
    else:
        fund_flow_fn = svc.fetcher.fetch_fund_flow

    # Gather all data in parallel (throttled to limit concurrency)
    results = await asyncio.gather(
        _throttled_thread(quote_mgr.get_single_quote, symbol),
        _throttled_thread(news_fetcher_inst.fetch_stock_news, symbol),
        _throttled_thread(news_fetcher_inst.fetch_stock_anomalies, symbol),
        _throttled_thread(svc.get_indicators_summary, symbol),
        _safe_get_market_indices(),
        _throttled_thread(svc.get_stock_sector_info, symbol),
        _throttled_thread(fund_flow_fn, symbol),
        _throttled_thread(strategy_ctx_svc.get_strategy_context, symbol),
        _throttled_thread(strategy_ctx_svc.get_bayesian_context, symbol),
        _throttled_thread(svc.get_intraday_trades_with_ticks, symbol),
        _throttled_thread(capital_flow_svc.get_macro_overview),
        _throttled_thread(svc.get_support_resistance, symbol),
        _throttled_thread(svc.fetcher.fetch_dragon_tiger_stock_stats, symbol),
        _throttled_thread(svc.fetcher.fetch_fund_flow_detail, symbol),
        _throttled_thread(svc.fetcher.fetch_intraday_fund_flow_series, symbol),
        _throttled_thread(policy_fetcher.format_for_prompt, None, 8),
        _throttled_thread(svc.fetcher.fetch_valuation_indicator, symbol),
        return_exceptions=True,
    )

    if isinstance(results[0], Exception):
        logger.warning("Quote fetch failed for %s: %s", symbol, results[0])
    quote = results[0] if not isinstance(results[0], Exception) else {}
    news_raw = results[1] if not isinstance(results[1], Exception) else None
    anomalies_raw = results[2] if not isinstance(results[2], Exception) else None
    indicators = results[3] if not isinstance(results[3], Exception) else None
    indices = results[4] if not isinstance(results[4], Exception) else []
    sector_info = results[5] if not isinstance(results[5], Exception) else None
    fund_flow_raw = results[6] if not isinstance(results[6], Exception) else None
    strategy_ctx = results[7] if not isinstance(results[7], Exception) else {}
    bayesian_ctx = results[8] if not isinstance(results[8], Exception) else {}
    intraday_trades = results[9] if not isinstance(results[9], Exception) else None
    capital_flow_raw = results[10] if not isinstance(results[10], Exception) else {}
    support_resistance = results[11] if not isinstance(results[11], Exception) else []
    dragon_tiger_raw = results[12] if not isinstance(results[12], Exception) else None
    fund_flow_detail_raw = (
        results[13] if not isinstance(results[13], Exception) else None
    )
    fund_flow_timeline = results[14] if not isinstance(results[14], Exception) else []
    policy_context = results[15] if not isinstance(results[15], Exception) else ""
    valuation_raw = results[16] if not isinstance(results[16], Exception) else {}

    return validator.validate_and_enrich(
        symbol=symbol,
        quote=quote,
        indicators=indicators,
        fund_flow=fund_flow_raw,
        sector_info=sector_info,
        news=news_raw,
        anomalies=anomalies_raw,
        indices=indices,
        strategy_signals=strategy_ctx,
        bayesian=bayesian_ctx,
        position=position,
        intraday_trades=intraday_trades,
        capital_flow_context=capital_flow_raw,
        support_resistance=support_resistance,
        dragon_tiger=dragon_tiger_raw,
        fund_flow_detail=fund_flow_detail_raw,
        fund_flow_timeline=fund_flow_timeline
        if isinstance(fund_flow_timeline, list)
        else [],
        policy_context=policy_context if isinstance(policy_context, str) else "",
        valuation=valuation_raw if isinstance(valuation_raw, dict) else {},
    )


async def _safe_get_market_indices() -> list[dict]:
    """Safely fetch market indices, returning empty list on failure."""
    try:
        market_svc = get_market_service()
        return await asyncio.to_thread(market_svc.get_market_indices)
    except Exception:
        return []


@router.get("/stock/{symbol}/ai-analysis", response_model=AIAnalysisResult)
async def get_ai_analysis(
    symbol: str,
    analyzer=Depends(get_realtime_analyzer),
) -> dict:
    """Get cached comprehensive AI analysis for a stock."""

    try:
        ctx = await _gather_analysis_data(symbol)
        if ctx.data_quality_score < _MIN_QUALITY_FOR_ANALYSIS:
            return {
                "status": "data_insufficient",
                "symbol": symbol,
                "message": "该股票数据正在收集中，请稍后再试",
            }
        result = await asyncio.to_thread(
            analyzer.analyze_stock_realtime,
            symbol=symbol,
            quote=ctx.quote,
            news_items=ctx.news_items,
            anomalies=ctx.anomalies,
            indicators=ctx.indicators,
            strategy_signals=ctx.strategy_signals,
            bayesian_analysis=ctx.bayesian_analysis,
            board_type=ctx.board_type,
            price_limit=ctx.price_limit,
            data_quality_score=ctx.data_quality_score,
            data_warnings=ctx.data_warnings,
            intraday_trades=ctx.intraday_trades,
            sector_info=ctx.sector_info,
        )
        return result
    except Exception as exc:
        logger.exception("AI analysis failed for %s", symbol)
        return {
            "status": "error",
            "symbol": symbol,
            "message": _GENERIC_ERROR_MESSAGE,
            "error_type": type(exc).__name__,
        }


@router.get(
    "/stock/{symbol}/unified-analysis",
    response_model=UnifiedAnalysisResult,
)
async def get_unified_analysis(
    symbol: str,
    analyzer=Depends(get_realtime_analyzer),
) -> dict:
    """Unified seven-dimension AI analysis (v8.0).

    Merges comprehensive analysis + trading advice into a single LLM call
    with the v7.0 seven-dimension framework. Returns action, confidence,
    risk level, 7 dimension scores, risk warnings, and data references.
    """
    try:
        ctx = await _gather_analysis_data(symbol)
        if ctx.data_quality_score < _MIN_QUALITY_FOR_ANALYSIS:
            return {
                "status": "data_insufficient",
                "symbol": symbol,
                "action": "watch",
                "action_label": "数据不足",
                "confidence": {"score": 0.0, "label": "无法评估", "basis": []},
                "risk_level": "unknown",
                "summary": "该股票数据正在收集中，暂时无法进行AI分析，请稍后再试。",
                "dimensions": [],
                "risk_warnings": [
                    {"type": "data", "level": "high", "message": w}
                    for w in ctx.data_warnings
                ],
                "data_references": [],
                "disclaimer": "",
            }

        # Gather advisor-specific context (news + global market)
        news_context: list[dict] = []
        global_context: dict = {}
        try:
            from src.web.dependencies import get_advisor_service

            advisor_svc = get_advisor_service()
            if hasattr(advisor_svc, "_fetch_news_context"):
                news_context = await asyncio.to_thread(
                    advisor_svc._fetch_news_context, symbol
                )
            if hasattr(advisor_svc, "_fetch_global_context"):
                global_context = await asyncio.to_thread(
                    advisor_svc._fetch_global_context
                )
        except Exception:
            logger.debug("Optional advisor context unavailable for %s", symbol)

        result = await asyncio.to_thread(
            analyzer.analyze_stock_unified,
            symbol=symbol,
            quote=ctx.quote,
            indicators=ctx.indicators,
            news_items=ctx.news_items,
            anomalies=ctx.anomalies,
            fund_flow=ctx.fund_flow,
            strategy_signals=ctx.strategy_signals,
            bayesian_analysis=ctx.bayesian_analysis,
            board_type=ctx.board_type,
            price_limit=ctx.price_limit,
            data_quality_score=ctx.data_quality_score,
            data_warnings=ctx.data_warnings,
            sector_info=ctx.sector_info,
            news_context=news_context,
            global_context=global_context,
            intraday_trades=ctx.intraday_trades,
            capital_flow_context=ctx.capital_flow_context,
            policy_context=ctx.policy_context,
            support_resistance=ctx.support_resistance,
            dragon_tiger=ctx.dragon_tiger,
            fund_flow_detail=ctx.fund_flow_detail,
            divergence_signals=ctx.divergence_signals,
            valuation=ctx.valuation,
        )

        # Run independent evaluator (rule-based, ~5ms)
        try:
            from src.agents.evaluator_agent import EvaluatorAgent

            evaluator = EvaluatorAgent()
            eval_report = evaluator.evaluate(
                result,
                data_quality_score=ctx.data_quality_score,
            )
            result["evaluation"] = eval_report.to_dict()
        except Exception:
            logger.debug("Evaluator skipped for %s", symbol)

        return result
    except Exception:
        logger.exception("Unified analysis failed for %s", symbol)
        return {
            "status": "error",
            "symbol": symbol,
            "message": _GENERIC_ERROR_MESSAGE,
            "action": "watch",
            "action_label": "建议观望",
            "confidence": {"score": 0.0, "label": "", "basis": []},
            "risk_level": "high",
            "summary": "分析暂时不可用",
            "dimensions": [],
            "risk_warnings": [],
            "data_references": [],
            "disclaimer": "",
        }


@router.get("/stock/{symbol}/quick-insight", response_model=QuickInsight)
async def get_quick_insight(
    symbol: str,
    analyzer=Depends(get_realtime_analyzer),
    quote_mgr=Depends(get_realtime_quote_manager),
    svc=Depends(get_stock_service),
) -> dict:
    """Get quick AI one-liner insight (cheap model, 5min cache)."""

    # Quick insight uses lighter data gathering (no full context needed)
    quote = await asyncio.to_thread(quote_mgr.get_single_quote, symbol)
    indicators = None
    try:
        indicators = await asyncio.to_thread(svc.get_indicators_summary, symbol)
    except Exception:
        logger.warning("Failed to fetch indicators for %s", symbol)

    # Get strategy signals and board type for quick insight
    strategy_signals: dict = {}
    try:
        strategy_ctx_svc = get_strategy_context_service()
        strategy_signals = await asyncio.to_thread(
            strategy_ctx_svc.get_strategy_context, symbol
        )
    except Exception:
        pass

    # Fetch concept sector info for quick insight
    sector_info = None
    try:
        sector_info = await asyncio.to_thread(svc.get_stock_sector_info, symbol)
    except Exception:
        pass

    validator = get_analysis_data_validator()
    board_type, price_limit = validator._detect_board(symbol)

    try:
        result = await asyncio.to_thread(
            analyzer.get_quick_insight,
            symbol=symbol,
            quote=quote,
            indicators=indicators,
            strategy_signals=strategy_signals,
            board_type=board_type,
            price_limit=price_limit,
            sector_info=sector_info,
        )
        return result
    except Exception:
        logger.exception("Quick insight failed for %s", symbol)
        return {
            "symbol": symbol,
            "signal": "neutral",
            "confidence": 0.0,
            "summary": "分析暂不可用，请稍后再试",
            "risk_badge": "medium",
        }


@router.post("/stock/{symbol}/analyze", response_model=AIAnalysisResult)
async def trigger_fresh_analysis(
    symbol: str,
    analyzer=Depends(get_realtime_analyzer),
) -> dict:
    """Force a fresh comprehensive AI analysis (bypasses cache)."""

    try:
        ctx = await _gather_analysis_data(symbol)
        result = await asyncio.to_thread(
            analyzer.analyze_stock_realtime,
            symbol=symbol,
            quote=ctx.quote,
            news_items=ctx.news_items,
            anomalies=ctx.anomalies,
            indicators=ctx.indicators,
            force_refresh=True,
            strategy_signals=ctx.strategy_signals,
            bayesian_analysis=ctx.bayesian_analysis,
            board_type=ctx.board_type,
            price_limit=ctx.price_limit,
            data_quality_score=ctx.data_quality_score,
            data_warnings=ctx.data_warnings,
            intraday_trades=ctx.intraday_trades,
            sector_info=ctx.sector_info,
        )
        return result
    except Exception as exc:
        logger.exception("Fresh analysis failed for %s", symbol)
        return {
            "status": "error",
            "symbol": symbol,
            "message": _GENERIC_ERROR_MESSAGE,
            "error_type": type(exc).__name__,
        }


@router.get("/stock/{symbol}/alerts", response_model=list[Alert])
async def get_stock_alerts(
    symbol: str,
    alert_engine=Depends(get_alert_engine),
    quote_mgr=Depends(get_realtime_quote_manager),
    svc=Depends(get_stock_service),
) -> list[dict]:
    """Get rule-based alerts for a stock."""

    quote = await asyncio.to_thread(quote_mgr.get_single_quote, symbol)
    name = quote.get("name", symbol)
    board = "main"

    # Look up board info from watchlist or registry
    for entry in svc.get_watchlist():
        if entry["symbol"] == symbol:
            board = entry.get("board", "main")
            name = entry.get("name", name)
            break
    else:
        try:
            from src.web.dependencies import get_stock_registry

            registry = get_stock_registry()
            reg_info = registry.get_stock_info(symbol)
            if reg_info:
                board = reg_info.get("board", "main")
                name = reg_info.get("name", name)
        except Exception:
            pass

    indicators = None
    try:
        indicators = await asyncio.to_thread(svc.get_indicators_summary, symbol)
    except Exception:
        logger.warning("Optional data fetch failed for %s", symbol)

    ohlcv_df = None
    try:
        ohlcv_df = await asyncio.to_thread(svc.get_stock_data, symbol)
    except Exception:
        logger.warning("Optional data fetch failed for %s", symbol)

    alerts = await asyncio.to_thread(
        alert_engine.check_alerts,
        symbol=symbol,
        name=name,
        quote=quote,
        indicators=indicators,
        ohlcv_df=ohlcv_df,
        board=board,
    )
    return alerts


@router.get("/market/ai-overview", response_model=MarketAIOverview)
async def get_market_ai_overview(
    analyzer=Depends(get_realtime_analyzer),
    news_fetcher=Depends(get_news_fetcher),
) -> dict:
    """Get AI-powered market overview/morning briefing."""

    hot_df = await asyncio.to_thread(news_fetcher.fetch_hot_rank)
    hot_stocks = hot_df.to_dict(orient="records") if not hot_df.empty else []

    try:
        result = await asyncio.to_thread(
            analyzer.get_market_overview, hot_stocks=hot_stocks
        )
        return result
    except Exception as exc:
        logger.exception("Market AI overview failed")
        return {
            "status": "error",
            "message": _GENERIC_ERROR_MESSAGE,
            "error_type": type(exc).__name__,
        }


@router.post("/stock/{symbol}/move-analysis", response_model=MoveAnalysisResult)
async def analyze_stock_move(
    symbol: str,
    body: MoveAnalysisRequest | None = None,
    move_analyzer=Depends(get_move_analyzer),
) -> dict:
    """Analyze why a stock moved (up/down) today.

    Combines market indices, sector, news, technical indicators, strategy signals,
    Bayesian analysis, and optional portfolio position context to produce a
    factor-weighted attribution.

    Per PRD v2.2 FR-PI001/PI002.
    """

    # Build optional position context
    position = None
    if body and body.cost_price is not None:
        position = {
            "cost_price": body.cost_price,
            "shares": body.shares,
            "holding_days": body.holding_days,
        }

    try:
        ctx = await _gather_analysis_data(symbol, position=position)
        result = await asyncio.to_thread(
            move_analyzer.analyze_move,
            symbol=symbol,
            name=ctx.name,
            quote=ctx.quote,
            indices=ctx.indices,
            news_items=ctx.news_items,
            anomalies=ctx.anomalies,
            indicators=ctx.indicators,
            position=ctx.position,
            sector_info=ctx.sector_info,
            fund_flow=ctx.fund_flow,
            strategy_signals=ctx.strategy_signals,
            bayesian_analysis=ctx.bayesian_analysis,
            board_type=ctx.board_type,
            price_limit=ctx.price_limit,
            data_quality_score=ctx.data_quality_score,
            data_warnings=ctx.data_warnings,
        )
        return result
    except Exception as exc:
        logger.exception("Move analysis failed for %s", symbol)
        return {
            "status": "error",
            "symbol": symbol,
            "name": symbol,
            "message": _GENERIC_ERROR_MESSAGE,
            "error_type": type(exc).__name__,
        }


@router.get(
    "/stock/{symbol}/dragon-tiger/ai-analysis",
    response_model=DragonTigerAIResult,
)
async def get_dragon_tiger_ai(
    symbol: str,
    analyzer=Depends(get_realtime_analyzer),
    svc=Depends(get_stock_service),
    quote_mgr=Depends(get_realtime_quote_manager),
) -> dict:
    """AI analysis of dragon-tiger data for a specific stock.

    Combines seat details, historical statistics, and current technicals
    to produce a structured AI interpretation.

    Per PRD v2.3 FR-DT002.
    """

    # Gather data
    quote = await asyncio.to_thread(quote_mgr.get_single_quote, symbol)
    name = quote.get("name", symbol)

    indicators = None
    try:
        indicators = await asyncio.to_thread(svc.get_indicators_summary, symbol)
    except Exception:
        logger.warning("Optional data fetch failed for %s", symbol)

    # Fetch dragon tiger data
    seats_df = await asyncio.to_thread(svc.fetcher.fetch_dragon_tiger_seats, symbol)
    stats_df = await asyncio.to_thread(
        svc.fetcher.fetch_dragon_tiger_stock_stats, symbol
    )

    seats = seats_df.to_dict(orient="records") if not seats_df.empty else []
    stats = stats_df.to_dict(orient="records") if not stats_df.empty else []

    # Clean NaN values
    sanitize_records(seats)
    sanitize_records(stats)

    try:
        result = await asyncio.to_thread(
            analyzer.analyze_dragon_tiger,
            symbol=symbol,
            name=name,
            quote=quote,
            seats=seats,
            stats=stats,
            indicators=indicators,
        )
        return result
    except Exception as exc:
        logger.exception("Dragon tiger AI failed for %s", symbol)
        return {
            "status": "error",
            "symbol": symbol,
            "message": _GENERIC_ERROR_MESSAGE,
            "error_type": type(exc).__name__,
        }


def _format_anomaly_details(change_type: str, raw_desc: Any, time_str: str) -> str:
    """Format raw anomaly description into human-readable text.

    AKShare ``stock_changes_em`` returns "相关信息" as raw numeric values
    (e.g. ``"0.087382,35.59000,0.087382"``).  This function converts them
    to readable descriptions based on the anomaly category.
    """
    desc = str(raw_desc) if raw_desc is not None else ""
    time_part = time_str[-8:] if len(time_str) >= 8 else time_str

    # Try to parse comma-separated numeric values
    parts = [p.strip() for p in desc.split(",") if p.strip()]
    nums: list[float] = []
    for p in parts:
        try:
            nums.append(float(p))
        except ValueError:
            # Non-numeric — return original description as-is
            return desc if desc else f"{time_part} {change_type}"

    if not nums:
        return f"{time_part} {change_type}"

    # Format based on anomaly type.
    # AKShare stock_changes_em "相关信息" field layout varies by category:
    #   火箭发射/高台跳水: deviation_pct, price, change_pct
    #   大笔买入/大笔卖出: volume(shares), price, change_pct
    #   封涨停板/封跌停板: seal_amount, price, change_pct
    if change_type in ("大笔买入", "大笔卖出"):
        if len(nums) >= 2:
            vol = nums[0]
            price = nums[1]
            vol_str = f"{vol / 1e4:.0f}万股" if vol >= 1e4 else f"{vol:.0f}股"
            label = "买入" if change_type == "大笔买入" else "卖出"
            return f"{time_part} {label} {vol_str} 价格 {price:.2f}"
        return f"{time_part} {change_type}"
    elif change_type in ("封涨停板", "封跌停板"):
        if len(nums) >= 2:
            price = nums[1]
            label = "封涨停" if change_type == "封涨停板" else "封跌停"
            return f"{time_part} {label} 价格 {price:.2f}"
        return f"{time_part} {change_type}"
    else:
        # 火箭发射 / 高台跳水 / other: deviation%, price, change%
        if len(nums) >= 2:
            pct = nums[0] * 100 if abs(nums[0]) < 1 else nums[0]
            price = nums[1]
            return f"{time_part} 价格 {price:.2f} 涨幅 {pct:+.2f}%"
        return f"{time_part} {change_type}"


_BULLISH_ANOMALIES = {"火箭发射", "大笔买入", "封涨停板"}
_BEARISH_ANOMALIES = {"高台跳水", "大笔卖出", "封跌停板"}


def _anomaly_impact(change_type: str) -> str:
    """Determine impact sentiment from anomaly category."""
    if change_type in _BULLISH_ANOMALIES:
        return "positive"
    if change_type in _BEARISH_ANOMALIES:
        return "negative"
    return "neutral"


@router.get("/stock/{symbol}/chart-events", response_model=ChartEventsResult)
async def get_chart_events(
    symbol: str,
    days: int = 120,
    news_fetcher=Depends(get_news_fetcher),
    svc=Depends(get_stock_service),
) -> dict:
    """Aggregate chart annotation events for a stock.

    Combines news dates, dragon-tiger dates, anomaly dates, and
    candlestick pattern signals into a unified event list for
    K-line chart markers.

    Per PRD v2.3 FR-CA001.
    """
    from datetime import datetime, timedelta

    events: list[dict] = []

    # News events — sorted by datetime descending to prioritise recent news
    try:
        news_df = await asyncio.to_thread(news_fetcher.fetch_stock_news, symbol)
        if not news_df.empty:
            if "datetime" in news_df.columns:
                news_df = news_df.sort_values("datetime", ascending=False)
            for _, row in news_df.head(20).iterrows():
                dt_str = str(row.get("datetime", ""))
                date_str = dt_str[:10] if len(dt_str) >= 10 else dt_str
                url = str(row.get("url", "")) if row.get("url") else None
                events.append(
                    {
                        "date": date_str,
                        "type": "news",
                        "title": str(row.get("title", ""))[:50],
                        "impact": "neutral",
                        "details": str(row.get("content", ""))[:100],
                        **({"url": url} if url else {}),
                    }
                )
    except Exception:
        logger.warning("Optional data fetch failed for %s", symbol)

    # Dragon tiger events
    try:
        end = datetime.now()
        start = end - timedelta(days=days)
        dt_df = await asyncio.to_thread(
            svc.fetcher.fetch_dragon_tiger,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if not dt_df.empty:
            col = "symbol" if "symbol" in dt_df.columns else None
            if col:
                dt_df = dt_df[dt_df[col].astype(str).str.strip() == symbol.strip()]
            else:
                # Cannot filter without symbol column — skip to avoid leaking all stocks
                dt_df = dt_df.iloc[0:0]
            for _, row in dt_df.iterrows():
                date_val = row.get("date", "")
                date_str = (
                    date_val.strftime("%Y-%m-%d")
                    if hasattr(date_val, "strftime")
                    else str(date_val)[:10]
                )
                net_buy = row.get("net_buy", 0) or 0
                impact = (
                    "positive"
                    if net_buy > 0
                    else "negative"
                    if net_buy < 0
                    else "neutral"
                )
                events.append(
                    {
                        "date": date_str,
                        "type": "dragon_tiger",
                        "title": f"龙虎榜：净买入 {net_buy / 1e8:.1f} 亿"
                        if net_buy
                        else "龙虎榜上榜",
                        "impact": impact,
                        "details": str(
                            row.get("reason", "") or row.get("list_reason", "")
                        ),
                    }
                )
    except Exception:
        logger.warning("Optional data fetch failed for %s", symbol)

    # Anomaly events — datetime may be time-only (e.g. "09:37:09"), prepend today
    today_str = datetime.now().strftime("%Y-%m-%d")
    try:
        anomaly_df = await asyncio.to_thread(news_fetcher.fetch_stock_anomalies, symbol)
        if not anomaly_df.empty:
            for _, row in anomaly_df.head(10).iterrows():
                dt_str = str(row.get("datetime", ""))
                if len(dt_str) >= 10:
                    date_str = dt_str[:10]
                else:
                    # Time-only value like "09:37:09" — use today's date
                    date_str = today_str
                change_type = str(row.get("change_type", ""))
                details = _format_anomaly_details(
                    change_type, row.get("description", ""), dt_str
                )
                impact = _anomaly_impact(change_type)
                events.append(
                    {
                        "date": date_str,
                        "type": "anomaly",
                        "title": f"异动：{change_type}",
                        "impact": impact,
                        "details": details,
                    }
                )
    except Exception:
        logger.warning("Optional data fetch failed for %s", symbol)

    # Pattern events (from OHLCV data) — limited to recent 30 days to reduce noise
    try:
        df = await asyncio.to_thread(svc.get_stock_with_patterns, symbol)
        if df is not None and not df.empty:
            pattern_cols = [c for c in df.columns if c.startswith("pattern_")]
            for _, row in df.tail(30).iterrows():
                for col in pattern_cols:
                    if row[col] != 0:
                        pattern_name = col.replace("pattern_", "")
                        date_str = str(row.get("date", ""))[:10]
                        is_bullish = row[col] > 0
                        events.append(
                            {
                                "date": date_str,
                                "type": "pattern",
                                "title": f"K线形态：{pattern_name}",
                                "impact": "positive" if is_bullish else "negative",
                                "details": "看涨信号" if is_bullish else "看跌信号",
                            }
                        )
    except Exception:
        logger.warning("Optional data fetch failed for %s", symbol)

    return {"symbol": symbol, "events": events}

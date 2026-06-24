"""Unified AI conversation endpoints.

v11.0: Single conversation entry for initial analysis + multi-turn follow-up.
Reuses ``_gather_analysis_data`` from agent.py for data collection.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends

from src.web.dependencies import (
    get_conversation_service,
    get_realtime_analyzer,
)
from src.web.routes.api_v1.agent import _MIN_QUALITY_FOR_ANALYSIS, _gather_analysis_data
from src.web.schemas.conversation import (
    ConversationRequest,
    ConversationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["conversation"])


@router.post(
    "/stock/{symbol}/conversation",
    response_model=ConversationResponse,
)
async def conversation(
    symbol: str,
    body: ConversationRequest | None = None,
    analyzer=Depends(get_realtime_analyzer),
    conv_svc=Depends(get_conversation_service),
) -> dict[str, Any]:
    """Start or continue an AI conversation about a stock.

    - **No body / no session_id**: Start a new conversation with full analysis.
    - **message + session_id**: Continue with a follow-up question.
    """
    body = body or ConversationRequest()
    session_id = body.session_id
    message = body.message
    position = body.position.model_dump() if body.position else None

    # --- Continue existing conversation ---
    if session_id and message:
        try:
            result = await asyncio.to_thread(
                conv_svc.continue_conversation,
                symbol=symbol,
                session_id=session_id,
                message=message,
                position=position,
            )
            return result
        except Exception as exc:
            logger.error("Conversation followup failed for %s: %s", symbol, exc)
            return {
                "status": "error",
                "session_id": session_id or "",
                "symbol": symbol,
                "message": str(exc),
                "messages": [],
                "suggested_questions": [],
                "disclaimer": "",
            }

    # --- Start new conversation ---
    intel_ctx = body.intel_context
    try:
        # Gather data (reuses agent.py logic)
        ctx = await _gather_analysis_data(symbol, position=position)
        if ctx.data_quality_score < _MIN_QUALITY_FOR_ANALYSIS:
            return {
                "status": "data_insufficient",
                "session_id": "",
                "symbol": symbol,
                "message": "该股票数据正在收集中，暂时无法进行AI分析，请稍后再试。",
                "messages": [],
                "suggested_questions": [],
                "disclaimer": "",
            }

        # Gather advisor + intel context in parallel (I-055 optimization)
        async def _fetch_news_ctx() -> list[dict]:
            try:
                from src.web.dependencies import get_advisor_service

                adv = get_advisor_service()
                if hasattr(adv, "_fetch_news_context"):
                    return await asyncio.to_thread(adv._fetch_news_context, symbol)
            except Exception:
                pass
            return []

        async def _fetch_global_ctx() -> dict:
            try:
                from src.web.dependencies import get_advisor_service

                adv = get_advisor_service()
                if hasattr(adv, "_fetch_global_context"):
                    return await asyncio.to_thread(adv._fetch_global_context)
            except Exception:
                pass
            return {}

        async def _build_intel() -> str:
            if intel_ctx and intel_ctx.item_ids:
                return await asyncio.to_thread(
                    conv_svc.build_intel_prompt,
                    item_ids=intel_ctx.item_ids,
                    symbol=symbol,
                    analysis_angle=intel_ctx.analysis_angle,
                    sector=intel_ctx.sector,
                )
            elif not intel_ctx:
                return await asyncio.to_thread(
                    conv_svc.build_intel_prompt,
                    symbol=symbol,
                    auto_limit=5,
                )
            return ""

        news_context, global_context, intel_prompt = await asyncio.gather(
            _fetch_news_ctx(),
            _fetch_global_ctx(),
            _build_intel(),
        )

        # Run unified analysis (with 120s timeout — LLM can stall for minutes)
        _LLM_TIMEOUT = 480  # seconds — generous for Claude Code bridge
        try:
            analysis_result = await asyncio.wait_for(
                asyncio.to_thread(
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
                    intel_context=intel_prompt if intel_prompt else None,
                    policy_context=ctx.policy_context,
                    capital_flow_context=ctx.capital_flow_context,
                    support_resistance=ctx.support_resistance,
                    dragon_tiger=ctx.dragon_tiger,
                    fund_flow_detail=ctx.fund_flow_detail,
                    fund_flow_timeline=ctx.fund_flow_timeline,
                    divergence_signals=ctx.divergence_signals,
                ),
                timeout=_LLM_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Unified analysis timed out after %ds for %s", _LLM_TIMEOUT, symbol
            )
            analysis_result = {
                "status": "timeout",
                "symbol": symbol,
                "action": "watch",
                "action_label": "建议观望",
                "confidence": {"score": 0.0, "label": "极低(分析超时)", "basis": []},
                "risk_level": "unknown",
                "summary": f"AI分析超时（>{_LLM_TIMEOUT}秒），请稍后重试。",
                "dimensions": [],
                "risk_warnings": ["分析服务响应超时"],
                "data_references": [],
                "disclaimer": "",
            }

        # Start conversation session — use ctx.quote (already fetched in _gather)
        result = conv_svc.start_conversation(
            symbol=symbol,
            analysis_result=analysis_result,
            position=position,
            quote=ctx.quote,
        )
        return result

    except Exception as exc:
        logger.error("Conversation start failed for %s: %s", symbol, exc)
        return {
            "status": "error",
            "session_id": "",
            "symbol": symbol,
            "message": str(exc),
            "messages": [],
            "suggested_questions": [],
            "disclaimer": "",
        }


@router.delete(
    "/stock/{symbol}/conversation/{session_id}",
)
async def clear_conversation(
    symbol: str,
    session_id: str,
    conv_svc=Depends(get_conversation_service),
) -> dict[str, Any]:
    """Clear a conversation session."""
    return conv_svc.clear_conversation(symbol, session_id)

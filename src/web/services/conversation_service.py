"""Unified AI Conversation Service.

v11.0: Single conversation entry point that merges initial analysis with
multi-turn follow-up Q&A, position context, and holiday/market awareness.

Reuses:
- ``agent.py:_gather_analysis_data()`` for data collection
- ``RealtimeAnalyzer.analyze_stock_unified()`` for structured analysis
- ``HolidayResearchService.ask_followup()`` pattern for multi-turn dialogue
- ``analysis_frameworks.py`` for system prompt construction
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("web.conversation_service")

_DISCLAIMER = "AI 分析仅供参考，不构成投资建议。股市有风险，投资需谨慎。"

CONVERSATION_MAX_TURNS = 20

_FOLLOWUP_SYSTEM_PROMPT = """\
你是A股投研分析专家。基于以下已完成的结构化分析与实时行情数据，与用户进行多轮对话。

## 要求
1. 用中文回答，简洁精准
2. 引用分析中的具体数据和维度，不要凭空编造数字
3. 如果用户问的信息不在已有分析中，诚实说明
4. 所有价格必须基于提供的实时行情，严禁猜测
5. 保持对话上下文连贯性
"""


class ConversationService:
    """Orchestrates unified AI conversation for individual stocks.

    Lifecycle:
    1. Start: full data gathering → unified analysis → cache → return
    2. Followup: load cached analysis → refresh quote → LLM Q&A → return
    3. Clear: delete session from Redis
    """

    REDIS_PREFIX = "agent_conversation"
    SESSION_TTL = 24 * 3600  # 24 hours

    def __init__(
        self,
        stock_service: Any = None,
        realtime_analyzer: Any = None,
        quote_manager: Any = None,
        trading_calendar: Any = None,
        global_market_fetcher: Any = None,
        info_store: Any = None,
    ) -> None:
        self._stock_service = stock_service
        self._realtime_analyzer = realtime_analyzer
        self._quote_manager = quote_manager
        self._trading_calendar = trading_calendar
        self._global_market_fetcher = global_market_fetcher
        self._info_store = info_store
        self._router = None
        self._redis = None
        self._redis_checked = False

    # --- Lazy component getters ---

    def _get_router(self):
        if self._router is None:
            from src.web.dependencies import get_llm_gateway

            self._router = get_llm_gateway()
        return self._router

    def _get_redis(self):
        if not self._redis_checked:
            self._redis_checked = True
            try:
                import redis as redis_lib

                from src.utils.config import load_config

                config = load_config("openclaw")
                broker = config.get("celery", {}).get(
                    "broker_url", "redis://redis:6379/0"
                )
                self._redis = redis_lib.from_url(broker, decode_responses=True)
                self._redis.ping()
            except Exception:
                self._redis = None
        return self._redis

    def _session_key(self, symbol: str, session_id: str) -> str:
        return f"{self.REDIS_PREFIX}:{symbol}:{session_id}"

    # --- Public API ---

    def start_conversation(
        self,
        symbol: str,
        analysis_result: dict[str, Any],
        position: dict[str, Any] | None = None,
        quote: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Start a new conversation with a pre-computed analysis result.

        The analysis is already computed by the route handler using
        ``_gather_analysis_data`` + ``analyze_stock_unified``.

        Args:
            symbol: Stock code.
            analysis_result: Pre-computed UnifiedAnalysisResult dict.
            position: Optional position context.
            quote: Real-time quote dict.

        Returns:
            ConversationResponse dict.
        """
        session_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        # Build initial assistant message from analysis summary
        summary = analysis_result.get("summary", "分析完成")
        action_label = analysis_result.get("action_label", "")
        if action_label:
            summary = f"**{action_label}** — {summary}"

        messages = [{"role": "assistant", "content": summary, "timestamp": now}]

        # Generate context-aware suggested questions
        suggested = self._generate_suggestions(symbol, analysis_result, position, quote)

        # Cache session data in Redis
        session_data = {
            "symbol": symbol,
            "analysis": analysis_result,
            "position": position,
            "messages": messages,
            "created_at": now,
            "quote_snapshot": quote,
        }
        self._save_session(symbol, session_id, session_data)

        return {
            "status": "ok",
            "session_id": session_id,
            "symbol": symbol,
            "analysis": analysis_result,
            "messages": messages,
            "suggested_questions": suggested,
            "generated_at": now,
            "model_used": analysis_result.get("model_used", ""),
            "disclaimer": _DISCLAIMER,
        }

    def continue_conversation(
        self,
        symbol: str,
        session_id: str,
        message: str,
        position: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Continue an existing conversation with a follow-up question.

        Loads cached analysis, refreshes quote only, sends to LLM.

        Args:
            symbol: Stock code.
            session_id: Session ID from start_conversation.
            message: User's follow-up question.
            position: Optional updated position context.

        Returns:
            ConversationResponse dict.
        """
        from src.llm.base import LLMMessage
        from src.llm.router import RoutingStrategy

        now = datetime.now(timezone.utc).isoformat()

        # Load session
        session_data = self._load_session(symbol, session_id)
        if not session_data:
            return {
                "status": "error",
                "session_id": session_id,
                "symbol": symbol,
                "message": "会话不存在或已过期，请重新开始分析。",
                "messages": [],
                "suggested_questions": [],
                "generated_at": now,
                "disclaimer": _DISCLAIMER,
            }

        analysis = session_data.get("analysis", {})
        messages = session_data.get("messages", [])
        cached_position = session_data.get("position")
        effective_position = position or cached_position

        # Append user message
        messages.append({"role": "user", "content": message, "timestamp": now})

        # Refresh real-time quote — fallback to initial snapshot if refresh fails
        fresh_quote = self._refresh_quote(symbol)
        if not fresh_quote or fresh_quote.get("price") is None:
            cached_quote = session_data.get("quote_snapshot", {})
            if cached_quote and cached_quote.get("price") is not None:
                logger.info("Using cached quote snapshot for %s followup", symbol)
                fresh_quote = cached_quote

        # Build context summary for LLM
        context_summary = self._build_context_summary(
            symbol, analysis, fresh_quote, effective_position
        )

        # Build LLM messages
        llm_messages = [
            LLMMessage(role="system", content=_FOLLOWUP_SYSTEM_PROMPT),
            LLMMessage(role="user", content=f"## 分析上下文\n{context_summary}"),
            LLMMessage(
                role="assistant",
                content="好的，我已了解分析上下文。请提问。",
            ),
        ]

        # Add conversation history (limited)
        history = messages[-(CONVERSATION_MAX_TURNS * 2) :]
        for msg in history:
            llm_messages.append(LLMMessage(role=msg["role"], content=msg["content"]))

        router = self._get_router()

        try:
            response = router.complete(
                messages=llm_messages,
                caller="conversation_service.followup",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=16384,
                temperature=0.4,
                symbol=symbol,
                analysis_type="conversation_followup",
            )
            answer = response.text.strip()
            model_used = getattr(response, "model", "")

            messages.append({"role": "assistant", "content": answer, "timestamp": now})
        except Exception as exc:
            logger.exception("Conversation followup failed for %s: %s", symbol, exc)
            # Remove failed user message
            if messages and messages[-1]["role"] == "user":
                messages.pop()
            return {
                "status": "error",
                "session_id": session_id,
                "symbol": symbol,
                "analysis": analysis,
                "messages": messages,
                "suggested_questions": [],
                "generated_at": now,
                "model_used": "",
                "disclaimer": _DISCLAIMER,
                "message": "追问服务暂时不可用，请稍后重试。",
            }

        # Update position if provided
        if position:
            session_data["position"] = position
        session_data["messages"] = messages
        self._save_session(symbol, session_id, session_data)

        return {
            "status": "ok",
            "session_id": session_id,
            "symbol": symbol,
            "analysis": analysis,
            "messages": messages,
            "suggested_questions": [],
            "generated_at": now,
            "model_used": model_used,
            "disclaimer": _DISCLAIMER,
        }

    def clear_conversation(self, symbol: str, session_id: str) -> dict[str, Any]:
        """Delete a conversation session."""
        r = self._get_redis()
        if r:
            try:
                r.delete(self._session_key(symbol, session_id))
            except Exception as exc:
                logger.debug("Redis delete failed: %s", exc)
        return {"status": "ok", "session_id": session_id}

    # --- Internal helpers ---

    def _refresh_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch fresh real-time quote."""
        if not self._quote_manager:
            return {}
        try:
            return self._quote_manager.get_single_quote(symbol) or {}
        except Exception as exc:
            logger.debug("Quote refresh failed for %s: %s", symbol, exc)
            return {}

    def _build_context_summary(
        self,
        symbol: str,
        analysis: dict[str, Any],
        quote: dict[str, Any] | None,
        position: dict[str, Any] | None,
    ) -> str:
        """Build concise context from cached analysis + fresh quote."""
        parts = [f"## 标的: {symbol}"]

        # Fresh quote
        if quote and quote.get("price") is not None:
            parts.append(
                f"实时行情: 最新价 {quote['price']}, "
                f"涨跌幅 {quote.get('pct_change', 'N/A')}%"
            )

        # Analysis summary
        action_label = analysis.get("action_label", "")
        summary = analysis.get("summary", "")
        confidence = analysis.get("confidence", {})
        conf_score = confidence.get("score", 0) if isinstance(confidence, dict) else 0
        parts.append(f"AI 结论: {action_label} (置信度 {conf_score:.0%})")
        parts.append(f"摘要: {summary}")

        # Dimensions
        dims = analysis.get("dimensions", [])
        if dims:
            dim_lines = []
            for d in dims:
                label = d.get("label", d.get("key", ""))
                signal = d.get("signal", "neutral")
                score = d.get("score", 0.5)
                dim_lines.append(f"  {label}: {signal} ({score:.0%})")
            parts.append("维度分析:\n" + "\n".join(dim_lines))

        # Risk warnings
        warnings = analysis.get("risk_warnings", [])
        if warnings:
            w_lines = [w.get("description", "") for w in warnings[:5]]
            parts.append("风险提示: " + "; ".join(w_lines))

        # Contrarian check
        contrarian = analysis.get("contrarian_check", "")
        if contrarian:
            parts.append(f"反转提醒: {contrarian}")

        # Position context
        if position:
            cost = position.get("cost_price")
            shares = position.get("shares", 0)
            days = position.get("holding_days")
            if cost:
                parts.append(f"持仓: 成本价 {cost}, 数量 {shares}")
                if quote and quote.get("price") is not None:
                    pnl = (quote["price"] - cost) * shares
                    pnl_pct = (quote["price"] / cost - 1) * 100 if cost else 0
                    parts.append(f"浮盈/亏: {pnl:+.2f} ({pnl_pct:+.2f}%)")
                if days:
                    parts.append(f"持仓天数: {days}")

        # Holiday/market context
        if self._trading_calendar:
            try:
                cal = self._trading_calendar
                if cal.is_holiday_period():
                    parts.append("市场状态: 当前为假期休市期间")
                    next_day = cal.next_trading_day()
                    if next_day:
                        parts.append(f"下一交易日: {next_day}")
            except Exception:
                pass

        return "\n".join(parts)

    def _generate_suggestions(
        self,
        symbol: str,
        analysis: dict[str, Any],
        position: dict[str, Any] | None,
        quote: dict[str, Any] | None,
    ) -> list[str]:
        """Generate context-aware suggested follow-up questions."""
        suggestions: list[str] = []

        action = analysis.get("action", "watch")
        risk_level = analysis.get("risk_level", "medium")

        # Position-aware questions
        if position:
            suggestions.append("我的持仓该怎么操作？")
            if action in ("reduce", "sell"):
                suggestions.append("如果要减仓，建议分几次卖出？")
            elif action in ("add", "buy"):
                suggestions.append("建议加仓多少比例？")
        else:
            if action in ("buy", "add"):
                suggestions.append("现在可以建仓吗？买多少合适？")
            else:
                suggestions.append("什么时候可以考虑买入？")

        # Risk-aware
        if risk_level == "high":
            suggestions.append("主要风险是什么？怎么规避？")

        # Market-aware
        if self._trading_calendar:
            try:
                if self._trading_calendar.is_holiday_period():
                    suggestions.append("假期期间需要关注什么？")
            except Exception:
                pass

        # Quote-aware
        if quote and quote.get("pct_change") is not None:
            pct = quote["pct_change"]
            if isinstance(pct, (int, float)):
                if pct > 5:
                    suggestions.append("今天大涨的原因是什么？")
                elif pct < -5:
                    suggestions.append("今天大跌是什么原因？")

        # General
        if len(suggestions) < 3:
            suggestions.append("帮我总结一下关键的买卖信号")

        return suggestions[:4]

    def _save_session(self, symbol: str, session_id: str, data: dict[str, Any]) -> None:
        """Persist session to Redis (or silently skip if unavailable)."""
        r = self._get_redis()
        if r:
            try:
                key = self._session_key(symbol, session_id)
                r.set(key, json.dumps(data, ensure_ascii=False, default=str))
                r.expire(key, self.SESSION_TTL)
            except Exception as exc:
                logger.debug("Redis save failed: %s", exc)

    def _load_session(self, symbol: str, session_id: str) -> dict[str, Any] | None:
        """Load session from Redis."""
        r = self._get_redis()
        if not r:
            return None
        try:
            key = self._session_key(symbol, session_id)
            raw = r.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Redis load failed: %s", exc)
        return None

    # --- Intelligence Hub integration ---

    def build_intel_prompt(
        self,
        item_ids: list[str] | None = None,
        symbol: str | None = None,
        analysis_angle: str | None = None,
        sector: str | None = None,
        auto_limit: int = 5,
    ) -> str:
        """Build a prompt section from Intelligence Hub items.

        Supports two modes:
        - **Explicit**: item_ids provided (Push/Pull mode from frontend).
        - **Auto**: No item_ids, queries InfoStore for recent items related
          to the symbol/sector.

        Returns:
            Formatted prompt string, or empty string if no items found.
        """
        if not self._info_store:
            return ""

        items = []

        if item_ids:
            # Explicit mode: fetch by IDs
            for item_id in item_ids[:10]:
                try:
                    item = self._info_store.get_item(item_id)
                    if item:
                        items.append(item)
                except Exception:
                    pass
        elif symbol:
            # Auto mode: query by symbol + sector
            try:
                feed = self._info_store.get_feed(
                    symbol=symbol, days=3, limit=auto_limit
                )
                items.extend(feed.get("items", []))
            except Exception:
                pass

            if sector:
                try:
                    sector_feed = self._info_store.get_feed(
                        search=sector, days=3, limit=3
                    )
                    seen = {i.item_id for i in items} if items else set()
                    for item in sector_feed.get("items", []):
                        if item.item_id not in seen:
                            items.append(item)
                except Exception:
                    pass

        if not items:
            return ""

        # Format items
        parts = ["## 相关情报信息\n"]
        for idx, item in enumerate(items[:10], 1):
            title = item.title if hasattr(item, "title") else item.get("title", "")
            source = (
                item.source_name
                if hasattr(item, "source_name")
                else item.get("source_name", "")
            )
            category = (
                item.category if hasattr(item, "category") else item.get("category", "")
            )
            summary = (
                item.summary if hasattr(item, "summary") else item.get("summary", "")
            )
            published = (
                item.published_at
                if hasattr(item, "published_at")
                else item.get("published_at", "")
            )

            parts.append(f"--- 情报 {idx} ---")
            parts.append(f"标题: {title}")
            parts.append(f"来源: {source} | 分类: {category} | 时间: {published}")
            if summary:
                parts.append(f"摘要: {summary}")
            parts.append("")

        if analysis_angle:
            angle_labels = {
                "impact_assessment": "影响评估",
                "investment_opportunity": "投资机会",
                "risk_warning": "风险预警",
                "comprehensive": "综合报告",
            }
            label = angle_labels.get(analysis_angle, analysis_angle)
            parts.append(f"请从「{label}」角度分析以上情报对标的的影响。")

        return "\n".join(parts)

"""Master Agent service — receives user messages, calls tools, returns replies.

Implements the agentic tool loop using Anthropic tool_use API:
1. Build system prompt with role/framework/portfolio context
2. Send messages + tool definitions to Claude
3. If Claude requests tool calls → execute → feed results back
4. Repeat until Claude produces a final text reply
5. Extract rich cards from reply, persist to SQLite
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.llm.base import LLMMessage, LLMToolResponse
from src.llm.router import LLMRouter
from src.utils.config import load_config
from src.utils.logger import get_logger
from src.web.schemas.chat import (
    ChatMessage,
    ChatThread,
    PersonaInfo,
    RichCard,
    ThreadContext,
    ThreadListItem,
    ToolCallRecord,
)
from src.web.services.tool_registry import ToolRegistry

logger = get_logger("web.agent_service")

_DB_PATH = Path("data/agent.db")
_MAX_TOOL_ROUNDS = 10
_MAX_LOOP_SECONDS = 900  # 15 min — Claude backend needs generous budget

# Type alias for optional agent registry
AgentRegistryType = Any

# Rich card extraction pattern: <!--RICH_CARDS:[...]-->
_RICH_CARDS_RE = re.compile(r"<!--\s*RICH_CARDS\s*:\s*(\[.*?\])\s*-->", re.DOTALL)


class AgentService:
    """Master Agent service that orchestrates the tool_use loop.

    Args:
        llm_router: LLMRouter for provider-agnostic completions.
        tool_registry: Registry of executable tools.
        db_path: Path to SQLite database for thread/message persistence.
        lineage_service: Optional LineageService for data provenance tracking.
    """

    def __init__(
        self,
        llm_router: LLMRouter,
        tool_registry: ToolRegistry,
        db_path: Path | None = None,
        user_config_service: Any | None = None,
        trade_service: Any | None = None,
        capital_service: Any | None = None,
        lineage_service: Any | None = None,
        agent_registry: AgentRegistryType | None = None,
        model_monitor: Any | None = None,
        reflection_agent: Any | None = None,
        memory_store: Any | None = None,
        audit_log: Any | None = None,
        schema_registry: Any | None = None,
        ensemble_validator: Any | None = None,
        intel_hub_service: Any | None = None,
        symbol_extractor: Any | None = None,
    ) -> None:
        self._llm = llm_router
        self._tools = tool_registry
        self._db_path = db_path or _DB_PATH
        self._user_config = user_config_service
        self._trade_service = trade_service
        self._capital_service = capital_service
        self._lineage = lineage_service
        self._agent_registry = agent_registry
        self._model_monitor = model_monitor
        self._reflection = reflection_agent
        self._memory_store = memory_store
        self._audit_log = audit_log
        self._schema_registry = schema_registry
        self._ensemble_validator = ensemble_validator
        self._intel_hub = intel_hub_service
        self._symbol_extractor = symbol_extractor
        self._ensure_db()
        # Deferred cleanup — non-blocking, errors are swallowed
        try:
            self.cleanup_old_threads(max_age_days=3)
        except Exception:
            logger.debug("Startup thread cleanup failed", exc_info=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_thread_only(
        self,
        title: str,
        context: ThreadContext | None = None,
        persona: str | None = None,
    ) -> str:
        """Create a thread record without processing any message.

        Returns:
            The new thread_id.
        """
        thread_id = str(uuid.uuid4())
        now = _now_iso()
        ctx_json = context.model_dump_json() if context else None
        persona_key = persona or "default"

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO threads (id, title, context, persona, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (thread_id, title, ctx_json, persona_key, now, now),
            )
        return thread_id

    async def create_thread(
        self,
        message: str,
        context: ThreadContext | None = None,
        use_multi_agent: bool = False,
        persona: str | None = None,
    ) -> tuple[str, ChatMessage]:
        """Create a new thread, process the first message, return reply.

        Returns:
            Tuple of (thread_id, agent_reply_message).
        """
        title = message[:50].strip()
        if len(message) > 50:
            title += "..."

        thread_id = self.create_thread_only(title, context, persona)

        # Process the message
        reply = await self.send_message(
            thread_id, message, use_multi_agent=use_multi_agent
        )
        return thread_id, reply

    async def send_message(
        self,
        thread_id: str,
        message: str,
        use_multi_agent: bool = False,
    ) -> ChatMessage:
        """Send a user message and get the agent reply.

        Implements the agentic tool loop:
        1. Load thread history
        2. Build system prompt
        3. Run tool loop until end_turn (Gemini) or bridge call (Claude Code)
        4. Extract rich cards
        5. Persist messages

        Returns:
            The agent's reply ChatMessage.
        """
        now = _now_iso()

        # Save user message
        user_msg_id = str(uuid.uuid4())
        user_msg = ChatMessage(
            id=user_msg_id,
            role="user",
            content=message,
            timestamp=now,
        )
        self._save_message(thread_id, user_msg)

        # Multi-agent path: delegate to MasterAgent orchestrator
        if use_multi_agent and self._agent_registry:
            return await self._send_multi_agent(thread_id, message)

        # ── Check persona backend ──────────────────────────────────
        persona_key = self._get_thread_persona(thread_id)
        persona_config = self._resolve_persona(persona_key)

        if persona_config.get("backend") == "claude_code":
            # Claude Code path — bypass Gemini tool loop entirely
            return await self._send_claude_code(thread_id, message, persona_config)

        # ── Auto-route to Claude Code for deep analysis requests ──
        should_route, auto_persona = self._should_auto_route_to_claude_code(message)
        if should_route and auto_persona:
            return await self._send_claude_code(thread_id, message, auto_persona)

        # ── Gemini tool loop (existing behavior, unchanged) ────────
        # Load conversation history for LLM
        history = self._load_history(thread_id)
        system_prompt = self._build_system_prompt(thread_id, user_message=message)

        llm_messages = [LLMMessage(role="system", content=system_prompt)]
        for msg in history:
            llm_messages.append(LLMMessage(role=msg.role, content=msg.content))

        # Tool loop
        tool_definitions = self._tools.get_tool_definitions()
        tool_records: list[ToolCallRecord] = []
        final_text: str | None = None
        loop_start = time.perf_counter()

        for _round in range(_MAX_TOOL_ROUNDS):
            # Check wall-clock budget before each LLM call
            elapsed_total = time.perf_counter() - loop_start
            if elapsed_total > _MAX_LOOP_SECONDS:
                logger.warning(
                    "Agent loop timeout (%.0fs) at round %d for thread %s",
                    elapsed_total,
                    _round,
                    thread_id,
                )
                final_text = await self._summarize_on_timeout(llm_messages)
                break

            # Run synchronous LLM call in a thread to avoid blocking
            # the uvicorn event loop (calls can take 10-60+ seconds)
            response: LLMToolResponse = await asyncio.to_thread(
                self._llm.complete_with_tools,
                messages=llm_messages,
                tools=tool_definitions,
                caller="agent_service.send_message",
                max_tokens=16384,
                temperature=0.3,
                analysis_type="agent_chat",
            )

            if response.stop_reason == "end_turn" or not response.tool_calls:
                final_text = response.text or ""
                if not final_text.strip():
                    logger.warning(
                        "LLM returned empty text at round %d, summarizing", _round
                    )
                    final_text = await self._summarize_on_timeout(llm_messages)
                break

            # Process tool calls
            # Use raw provider content if available (preserves thought_signature etc.)
            # Otherwise reconstruct from our ToolCall objects
            if response.raw_assistant_content is not None:
                assistant_content = response.raw_assistant_content
            else:
                assistant_blocks: list[dict[str, Any]] = []
                if response.text:
                    assistant_blocks.append({"type": "text", "text": response.text})
                for tc in response.tool_calls:
                    assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.input,
                        }
                    )
                assistant_content = assistant_blocks

            llm_messages.append(LLMMessage(role="assistant", content=assistant_content))

            # Execute tools and build tool_result message
            tool_results: list[dict[str, Any]] = []
            for tc in response.tool_calls:
                start = time.perf_counter()
                result_str = await self._tools.execute(tc.name, tc.input)
                elapsed = (time.perf_counter() - start) * 1000

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "tool_name": tc.name,
                        "content": result_str,
                    }
                )
                tool_records.append(
                    ToolCallRecord(
                        tool_name=tc.name,
                        input=tc.input,
                        output_summary=result_str[:200],
                        duration_ms=elapsed,
                    )
                )

                # Record lineage for this tool call
                self._record_tool_lineage(
                    tc.name,
                    tc.input,
                    result_str,
                    thread_id,
                    elapsed,
                )

            llm_messages.append(LLMMessage(role="user", content=tool_results))
        else:
            # Hit max rounds without end_turn
            final_text = response.text or ""
            if not final_text.strip():
                final_text = await self._summarize_on_timeout(llm_messages)
            logger.warning(
                "Agent loop hit max rounds (%d) for thread %s",
                _MAX_TOOL_ROUNDS,
                thread_id,
            )

        # Extract rich cards from reply
        rich_cards = self._extract_rich_cards(final_text)

        # Auto-save trade_decision cards as recommendations + predictions
        if self._trade_service and rich_cards:
            for card in rich_cards:
                if card.type == "trade_decision" and card.props.get("symbol"):
                    try:
                        rec = self._trade_service.save_recommendation(
                            thread_id=thread_id,
                            symbol=card.props["symbol"],
                            action=card.props.get("action", "buy"),
                            confidence=float(card.props.get("confidence", 0.5)),
                            reasoning=card.props.get("reasoning", ""),
                            risk_warnings=card.props.get("risks"),
                            stop_loss=(
                                float(card.props["stop_loss"])
                                if card.props.get("stop_loss") is not None
                                else None
                            ),
                        )
                        card.props["recommendation_id"] = rec.id

                        # Link to prediction tracking (v12.0 Phase 4)
                        self._record_recommendation_prediction(
                            rec.symbol,
                            rec.action,
                            rec.confidence,
                            rec.id,
                            thread_id,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to save recommendation for %s",
                            card.props.get("symbol"),
                            exc_info=True,
                        )

        clean_text = _RICH_CARDS_RE.sub("", final_text).strip()

        # Build and save agent reply
        reply = ChatMessage(
            id=str(uuid.uuid4()),
            role="assistant",
            content=clean_text,
            rich_cards=rich_cards or None,
            tool_calls=tool_records or None,
            timestamp=_now_iso(),
        )
        self._save_message(thread_id, reply)

        # Update thread timestamp
        with self._connect() as conn:
            conn.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?",
                (_now_iso(), thread_id),
            )

        return reply

    async def _send_multi_agent(
        self,
        thread_id: str,
        message: str,
    ) -> ChatMessage:
        """Process message using the orchestration pipeline.

        Delegates to OrchestratorAgent which plans a DAG of agent steps
        via PipelinePlanner, executes via PipelineExecutor, and returns
        the merged result.
        """
        from src.agents.master_agent import OrchestratorAgent
        from src.orchestration.executor import PipelineExecutor
        from src.orchestration.planner import PipelinePlanner

        executor = PipelineExecutor(
            agent_registry=self._agent_registry,
            schema_registry=self._schema_registry,
            lineage_service=self._lineage,
            audit_log=self._audit_log,
            ensemble_validator=self._ensemble_validator,
            reflection_agent=self._reflection,
            memory_store=self._memory_store,
        )
        planner = PipelinePlanner(
            llm_router=self._llm,
            available_agents=self._agent_registry.list_agents(),
        )
        orchestrator = OrchestratorAgent(
            executor=executor,
            planner=planner,
        )

        # Build thread context for agents
        context = self._get_thread_context(thread_id)
        thread_ctx: dict[str, Any] = {}
        if context:
            if context.symbol:
                thread_ctx["symbol"] = context.symbol
            thread_ctx["mode"] = context.mode

        # Inject capital hints
        capital_hints = self._build_capital_hints()
        if capital_hints:
            thread_ctx["capital_hints"] = capital_hints

        result = await orchestrator.process(
            user_message=message,
            thread_context=thread_ctx,
        )

        # Build and save agent reply with delegation metadata
        reply = ChatMessage(
            id=str(uuid.uuid4()),
            role="assistant",
            content=result.text,
            rich_cards=self._extract_rich_cards(result.text) or None,
            timestamp=_now_iso(),
            agent_name="orchestrator",
            delegation_chain=result.delegation_chain,
        )
        self._save_message(thread_id, reply)

        # Update thread timestamp
        with self._connect() as conn:
            conn.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?",
                (_now_iso(), thread_id),
            )

        logger.info(
            "Pipeline reply: agents=%s, tokens=%d, tool_calls=%d",
            result.agents_used,
            result.total_tokens,
            result.total_tool_calls,
        )

        return reply

    def list_threads(
        self, limit: int = 50, offset: int = 0
    ) -> tuple[list[ThreadListItem], int]:
        """List threads ordered by most recent update.

        Returns:
            Tuple of (thread list, total count) — single DB round-trip.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, context, created_at, updated_at, persona,"
                " (SELECT COUNT(*) FROM threads) AS total"
                " FROM threads ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()

        total = rows[0][6] if rows else 0
        items = []
        for row in rows:
            ctx = None
            if row[2]:
                try:
                    ctx = ThreadContext.model_validate_json(row[2])
                except Exception:
                    pass
            items.append(
                ThreadListItem(
                    id=row[0],
                    title=row[1],
                    context=ctx,
                    created_at=row[3],
                    updated_at=row[4],
                    persona=row[5],
                )
            )
        return items, total

    def get_thread(self, thread_id: str) -> ChatThread | None:
        """Load a thread with all its messages."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, title, context, created_at, updated_at, persona "
                "FROM threads WHERE id = ?",
                (thread_id,),
            ).fetchone()

        if not row:
            return None

        ctx = None
        if row[2]:
            try:
                ctx = ThreadContext.model_validate_json(row[2])
            except Exception:
                pass

        messages = self._load_history(thread_id)

        return ChatThread(
            id=row[0],
            title=row[1],
            messages=messages,
            context=ctx,
            persona=row[5],
            created_at=row[3],
            updated_at=row[4],
        )

    def delete_thread(self, thread_id: str) -> bool:
        """Delete a thread and its messages. Also closes Claude Code session."""
        # Close Claude Code session if present (fire-and-forget)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._close_claude_code_session(thread_id))
            else:
                loop.run_until_complete(self._close_claude_code_session(thread_id))
        except Exception:
            logger.debug("Failed to close CC session on delete", exc_info=True)

        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
            cursor = conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        return cursor.rowcount > 0

    def count_threads(self) -> int:
        """Count total threads."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM threads").fetchone()
        return row[0] if row else 0

    def cleanup_old_threads(self, max_age_days: int = 3) -> int:
        """Delete threads older than max_age_days and their messages.

        Returns:
            Number of deleted threads.
        """
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

        try:
            with self._connect() as conn:
                # Find old thread IDs
                old_ids = [
                    row[0]
                    for row in conn.execute(
                        "SELECT id FROM threads WHERE updated_at < ?", (cutoff,)
                    ).fetchall()
                ]
                if not old_ids:
                    return 0

                placeholders = ",".join("?" for _ in old_ids)
                conn.execute(
                    f"DELETE FROM messages WHERE thread_id IN ({placeholders})",
                    old_ids,
                )
                cursor = conn.execute(
                    f"DELETE FROM threads WHERE id IN ({placeholders})",
                    old_ids,
                )
                count = cursor.rowcount
                if count > 0:
                    logger.info(
                        "Cleaned up %d old threads (older than %d days)",
                        count,
                        max_age_days,
                    )
                return count
        except Exception:
            logger.debug("Thread cleanup failed", exc_info=True)
            return 0

    def submit_feedback(
        self,
        thread_id: str,
        message_id: str,
        satisfaction: str,
        feedback: str | None = None,
    ) -> bool:
        """Submit user feedback on an assistant message.

        Returns:
            True if the message was found and updated.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE messages SET satisfaction = ?, feedback = ? "
                "WHERE id = ? AND thread_id = ? AND role = 'assistant'",
                (satisfaction, feedback, message_id, thread_id),
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Lineage tracking
    # ------------------------------------------------------------------

    def _record_tool_lineage(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        result_str: str,
        thread_id: str,
        duration_ms: float,
    ) -> None:
        """Record a tool call in the lineage service (fire-and-forget)."""
        if not self._lineage:
            return
        try:
            # Snapshot the tool output
            snapshot = self._lineage.snapshot_data(
                source=tool_name,
                payload={"input": tool_input, "output_preview": result_str[:500]},
                source_type="computed",
                symbol=tool_input.get("symbol", ""),
            )
            # Record the operation node
            self._lineage.record_operation(
                operation=tool_name,
                operation_type="tool_call",
                output_snapshot_id=snapshot.id,
                agent_name="master",
                thread_id=thread_id,
                duration_ms=duration_ms,
                metadata={"tool_input_keys": list(tool_input.keys())},
            )
        except Exception:
            logger.debug("Failed to record lineage for %s", tool_name, exc_info=True)

    # ------------------------------------------------------------------
    # Prediction tracking
    # ------------------------------------------------------------------

    def _record_recommendation_prediction(
        self,
        symbol: str,
        action: str,
        confidence: float,
        recommendation_id: str,
        thread_id: str,
    ) -> None:
        """Record a prediction linked to a trade recommendation (fire-and-forget).

        Maps action to direction: buy/add → bullish, sell/reduce → bearish.
        """
        if not self._model_monitor:
            return
        try:
            direction_map = {
                "buy": "bullish",
                "add": "bullish",
                "sell": "bearish",
                "reduce": "bearish",
            }
            direction = direction_map.get(action, "neutral")
            self._model_monitor.record_prediction(
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                agent_name="master_agent",
                context={
                    "recommendation_id": recommendation_id,
                    "thread_id": thread_id,
                },
            )
        except Exception:
            logger.debug(
                "Failed to record prediction for recommendation %s",
                recommendation_id,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Timeout summarization
    # ------------------------------------------------------------------

    async def _summarize_on_timeout(self, llm_messages: list[LLMMessage]) -> str:
        """Generate a summary from already-collected tool data on timeout.

        Takes the system prompt, user message, and the last few messages
        (which contain tool results), then asks the LLM to produce a
        concise summary without any tool calls.

        Falls back to a static message if the summary call also fails.
        """
        fallback = "分析时间较长，已基于已有信息给出回复。请缩小问题范围后重试。"
        try:
            # Keep system prompt + user message + last 4 messages (tool results)
            summary_messages: list[LLMMessage] = []
            if llm_messages:
                summary_messages.append(llm_messages[0])  # system prompt
            if len(llm_messages) > 1:
                summary_messages.append(llm_messages[1])  # user message
            # Append last 4 messages (most recent tool results / assistant turns)
            tail = llm_messages[-4:] if len(llm_messages) > 5 else llm_messages[2:]
            summary_messages.extend(tail)

            summary_messages.append(
                LLMMessage(
                    role="user",
                    content=(
                        "由于时间限制，工具调用已停止。请根据上面已收集到的所有工具返回数据，"
                        "直接给出你的分析和建议。如果数据不足，请说明已获取的信息和局限性。"
                        "不要再调用任何工具。"
                    ),
                )
            )

            response: LLMToolResponse = await asyncio.to_thread(
                self._llm.complete_with_tools,
                messages=summary_messages,
                tools=[],  # No tools — force text-only reply
                caller="agent_service.summarize_timeout",
                max_tokens=1024,
                temperature=0.3,
                analysis_type="agent_chat",
            )
            if response.text:
                return response.text
        except Exception as exc:
            logger.warning("Timeout summarization failed: %s", exc)

        return fallback

    # ------------------------------------------------------------------
    # System prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self,
        thread_id: str,
        user_message: str = "",
        persona_config: dict | None = None,
    ) -> str:
        """Build the master agent system prompt with context injection."""
        # Base role description
        base_role = (
            "你是一个专业的 A 股投资分析 Agent。用户会向你提问关于股票投资的各种问题，"
            "你需要利用提供的工具获取实时数据并进行分析，给出专业、可操作的建议。"
        )

        # Inject persona overlay if present
        overlay = ""
        if persona_config:
            overlay = persona_config.get("system_prompt_overlay", "")

        parts = [base_role]
        if overlay:
            parts.append(overlay)
        parts.extend(
            [
                "",
                "## 数据准确性铁律（最高优先级）",
                "- **禁止编造任何数字**：价格、涨跌幅、成交量、资金流、目标价、止损价等所有数值"
                "必须来自工具返回的实时数据。绝不可凭记忆或推测给出具体数字。",
                "- **必须先调用工具获取数据，再引用数据**：没有调用 get_realtime_quote 之前，"
                "不得在回复中提及任何具体股价或涨跌幅。",
                "- **止损价必须低于当前价格**：如果做多建议止损价 ≥ 当前价，说明分析有误，必须修正。",
                "- **目标价必须合理**：目标价不得偏离当前价超过 ±30%（主板）或 ±40%（创业板/科创板）。",
                "- **涨跌幅描述必须与数据一致**：不得将正涨幅描述为下跌，或将小幅波动描述为涨停/跌停。",
                "- 如果某项数据不可用，明确告知用户'该数据暂不可用'，不得编造替代数据。",
                "",
                "## 回复规范",
                "- 使用中文回复",
                "- 结论先行，再给理由",
                "- 每个操作建议必须附带风险提示",
                "- 当给出买入建议时，必须同时给出建议止损位（用'如果跌到 XX 元建议卖出'表述）",
                "- 不使用专业量化术语（如 RSI/MACD/Sharpe），用通俗易懂的表达替代",
                "- 永远不说'一定涨'或'一定赚'",
                "",
                "## 工具使用",
                "- 你可以调用提供的工具来获取实时数据",
                "- 先获取数据，再基于数据分析，最后给出结论",
                "- 如果用户问的是具体个股，先获取实时行情和技术指标",
                "- 如果涉及概念板块，获取相关概念数据",
                "- 如果涉及全球市场影响，获取全球市场数据",
                "- **情报查询（必须执行）**: 分析个股时，**必须**先调用 "
                "`search_intel(symbol=...)` 获取该股票的本地情报。"
                "如果本地情报不足（返回空或少于 2 条），再调用 `web_search` "
                "联网搜索该股票最新新闻和消息，补充分析所需的消息面信息。",
                "- search_intel 返回空不要反复重试超过 2 次。"
                "web_search 用于联网搜索最新新闻、公告、研报等，补充本地情报不足。",
                "",
                "## Rich Card 输出",
                "当分析结果适合结构化展示时，在回复末尾附加 JSON 标记：",
                '<!--RICH_CARDS:[{"type": "stock_analysis", "props": {...}}]-->',
                "",
                "支持的 card 类型：",
                "- stock_analysis: 个股分析结果",
                "  props: title(可选,如'贵州茅台分析'), symbol, signal(bullish/bearish/neutral), "
                "confidence(0~1), summary(支持 Markdown，完整分析内容写在这里), "
                "dimensions(数组,每项含 key/label/signal/score/reasoning), risk_warnings(字符串数组)",
                "- trade_decision: 交易建议（含 action, shares, price, reasoning, risks, confidence, key_metrics, dimensions）",
                "- market_overview: 市场概览",
                "  props: title(如'市场简报'), signal(bullish/bearish/neutral), "
                "confidence(0~1), summary(支持 Markdown，将完整市场分析写在 summary 中，"
                "可以使用标题/列表/加粗等格式), dimensions(可选), risk_warnings(可选)",
                "- portfolio_summary: 持仓概览",
                "  props: title(如'持仓诊断'), signal, confidence, summary(支持 Markdown), "
                "dimensions(可选), risk_warnings(可选)",
                "",
                "**重要**: stock_analysis/market_overview/portfolio_summary 的 summary 字段支持完整 Markdown，"
                "请将详细分析内容全部写入 summary，不要截断。可以使用 ## 标题、- 列表、**加粗** 等格式。",
                "",
                "## 交易建议输出规范",
                "当你建议买入或卖出具体个股时，**必须**输出 trade_decision 类型的 Rich Card：",
                "- 必须先用 get_realtime_quote 获取最新价格，price 字段**必须使用工具返回的实时价格**，不得编造",
                "- shares 必须是 100 的整数倍",
                "- **买入时**: shares × price **不得超过**用户可用资金（见用户资金配置）。"
                "如果资金不足以买入 100 股，不要输出 trade_decision，在文字中说明资金不足",
                "- **卖出时**: 必须先调用 get_portfolio 确认用户持仓，"
                "shares **不得超过**用户实际持有股数。如未持有则不建议卖出",
                "- 必须包含 stop_loss（止损价，必须 < price，即低于当前价格）",
                "- 必须包含 risks（至少 1 条风险提示）",
                "- 必须包含 reasoning（交易理由）",
                "- 必须包含 confidence（置信度，0~1 之间的浮点数）",
                "- 建议包含 key_metrics（关键量化指标数组），每项含 label(指标名)、value(值)、signal(bullish/bearish/neutral)",
                "- 建议包含 dimensions（分析维度数组），每项含 label(维度名如'技术面')、signal(bullish/bearish/neutral)、score(0~1)",
                "",
                "示例：",
                '<!--RICH_CARDS:[{"type":"trade_decision","props":{"symbol":"600519",'
                '"stock_name":"贵州茅台","action":"buy","shares":100,"price":1680.5,'
                '"reasoning":"...","stop_loss":1600,"risks":["..."],'
                '"confidence":0.72,'
                '"key_metrics":[{"label":"5日涨幅","value":"+3.2%","signal":"bullish"},'
                '{"label":"主力资金","value":"净流入1.2亿","signal":"bullish"}],'
                '"dimensions":[{"label":"技术面","signal":"bullish","score":0.75},'
                '{"label":"资金面","signal":"bullish","score":0.68},'
                '{"label":"消息面","signal":"neutral","score":0.5}]}}]-->',
                "",
                "## 仓位管理规则",
                "- 单只股票建议仓位不超过总资金的 20%",
                "- risk_level=high: 仅观望或极小仓位(<=5%)",
                "- risk_level=medium: 谨慎建仓(<=10%)",
                "- risk_level=low: 正常建仓(<=15%)",
                "- 首次建仓建议分批（先 1/3，确认趋势再加仓）",
                "- 已盈利持仓的加仓不超过初始仓位的 50%",
                "",
                "## 免责声明",
                "⚠ 以上分析仅供研究学习参考，不构成任何投资建议。"
                "股市有风险，投资需谨慎。请根据自身风险承受能力做出独立判断。",
            ]
        )

        # Inject market session / holiday awareness
        market_hints = self._build_market_session_hints()
        if market_hints:
            parts.append("")
            parts.append("## 当前市场状态")
            parts.append(market_hints)

        # Inject user capital and risk preference
        capital_hints = self._build_capital_hints()
        if capital_hints:
            parts.append("")
            parts.append("## 用户资金配置")
            parts.append(capital_hints)

        # Inject context-specific hints from ThreadContext
        context = self._get_thread_context(thread_id)
        if context:
            context_hints = self._build_context_hints(context)
            if context_hints:
                parts.append("")
                parts.append("## 当前上下文")
                parts.append(context_hints)

        # Inject selected intel items
        intel_hints = self._build_intel_hints(thread_id)
        if intel_hints:
            parts.append("")
            parts.append("## 用户选择的情报")
            parts.append(intel_hints)

        # Auto-inject stock-related intel from intelligence hub
        stock_intel = self._build_stock_intel_context(
            user_message, thread_id, intel_hints
        )
        if stock_intel:
            parts.append("")
            parts.append("## 相关个股情报（自动检索）")
            parts.append(stock_intel)

        # Inject user trading behavior personality (v12.0 Phase 4)
        personality_hints = self._build_personality_hints()
        if personality_hints:
            parts.append("")
            parts.append("## 用户交易行为画像")
            parts.append(personality_hints)

        # Inject historical accuracy from model monitor (v18.0)
        accuracy_hints = self._build_accuracy_hints()
        if accuracy_hints:
            parts.append("")
            parts.append("## 历史预测准确率")
            parts.append(accuracy_hints)

        # Inject relevant memories (v18.0)
        memory_hints = self._build_memory_hints(thread_id)
        if memory_hints:
            parts.append("")
            parts.append("## 相关经验")
            parts.append(memory_hints)

        return "\n".join(parts)

    @staticmethod
    def _build_market_session_hints() -> str:
        """Build market session / holiday context for the system prompt."""
        try:
            from src.utils.market_hours import (
                format_session_for_prompt,
                get_market_session,
            )

            session = get_market_session()
            session_text = format_session_for_prompt(session)
            is_trading = session.get("is_trading", False)

            hints: list[str] = [session_text]

            if not is_trading:
                # Check if simulation mode — allow trade cards anytime
                is_sim = True
                try:
                    from src.utils.config import load_config

                    broker_cfg = load_config("broker")
                    is_sim = broker_cfg.get("mode", "simulation") == "simulation"
                except Exception:
                    pass

                label = session.get("label", "")
                if is_sim:
                    # Simulation mode: allow trade_decision cards anytime
                    hints.append("")
                    hints.append("**非交易时段提示**：")
                    hints.append(
                        f"- 当前为非交易时段（{label}），但模拟模式下可正常执行交易"
                    )
                    hints.append(
                        "- 可以输出 trade_decision 和 stock_analysis 类型的 Rich Card"
                    )
                    hints.append("- 模拟交易价格以最近行情为准")
                elif "假期" in label or "休市" in label:
                    hints.append("")
                    hints.append("**重要约束（休市期间必须遵守）**：")
                    hints.append("- 当前处于休市/假期期间，A 股市场未开盘")
                    hints.append(
                        "- 你可以正常进行专业分析，给出买入/卖出方向性建议（文字内容中）"
                    )
                    hints.append("- 可以输出 stock_analysis 类型的 Rich Card")
                    hints.append(
                        "- **禁止输出 trade_decision 类型的 Rich Card**，"
                        "因为休市期间交易无法执行"
                    )
                    hints.append("- 结论建议使用「节后关注」「开盘后择机操作」等表述")
                else:
                    hints.append("")
                    hints.append("**非交易时段提示**：")
                    hints.append(
                        "- 当前为非交易时段，可以正常进行分析和研究，给出方向性建议"
                    )
                    hints.append(
                        "- **不要输出 trade_decision 类型的 Rich Card**，"
                        "因为非交易时段交易无法执行"
                    )
                    hints.append("- 可以输出 stock_analysis 类型的 Rich Card")

            return "\n".join(hints)
        except Exception:
            return ""

    def _build_capital_hints(self) -> str:
        """Build capital/risk context from CapitalService + user config."""
        hints: list[str] = []

        # Read real-time capital from CapitalService
        capital: float | None = None
        if self._capital_service:
            try:
                breakdown = self._capital_service.get_breakdown()
                if breakdown.has_initial_deposit:
                    capital = breakdown.available_cash
                    hints.append(f"用户可用现金为 **{capital:.2f} 元**。")
                    if breakdown.position_value > 0:
                        hints.append(
                            f"持仓市值 **{breakdown.position_value:.2f} 元**，"
                            f"总资产 **{breakdown.total_assets:.2f} 元**，"
                            f"资金使用率 **{breakdown.utilization_rate:.1%}**。"
                        )
            except Exception:
                pass

        # Fallback: read from legacy user_config if no capital service data
        if capital is None and self._user_config:
            try:
                capital_str = self._user_config.get("available_capital")
                if capital_str:
                    capital = float(capital_str)
                    hints.append(f"用户可用资金为 **{capital:.0f} 元**。")
            except Exception:
                pass

        if capital is not None:
            hints.append("**买入建议硬性约束（必须遵守，否则建议无效）**：")
            hints.append(
                f"1. 建议买入总金额（shares × price）**不得超过** {capital:.2f} 元"
            )
            hints.append(
                "2. 单笔买入金额不得超过可用资金的 30%（保守型）/ 50%（稳健型）/ 70%（积极型）"
            )
            hints.append("3. shares 必须是 100 的整数倍")
            hints.append(
                "4. 计算公式：max_shares = floor(可用资金 × 仓位比例 / price / 100) × 100"
            )
            hints.append(
                "5. 如果计算出的 shares 为 0（即资金不足以买入 100 股），"
                "**不要输出 trade_decision 卡片**，改为在文字中说明资金不足"
            )

        # Risk preference from user_config
        risk: str | None = None
        if self._user_config:
            try:
                risk = self._user_config.get("risk_tolerance")
            except Exception:
                pass
        if risk:
            risk_labels = {
                "conservative": "保守型（优先安全，单笔上限 30%）",
                "moderate": "稳健型（风险均衡，单笔上限 50%）",
                "aggressive": "积极型（追求收益，单笔上限 70%）",
            }
            label = risk_labels.get(risk, risk)
            hints.append(f"用户风险偏好：{label}。")

        if not hints:
            return ""

        hints.append("")
        hints.append(
            "**卖出建议约束**：卖出股数不得超过用户实际持仓股数。"
            "请先用 get_portfolio 工具查询持仓，确认用户是否持有该股以及持有数量，"
            "再给出卖出建议。如果用户未持有该股，不要建议卖出。"
        )

        return "\n".join(hints)

    def _build_personality_hints(self) -> str:
        """Build user trading behavior profile for prompt injection."""
        if not self._trade_service:
            return ""
        try:
            profile = self._trade_service.compute_trading_profile()
        except Exception:
            return ""

        if profile.total_trades < 3:
            return ""

        lines: list[str] = []
        lines.append(f"用户共完成 {profile.total_trades} 笔交易。")
        lines.append(
            f"AI 建议采纳率 {profile.agent_adoption_rate:.0%}，"
            f"风险偏好 {profile.risk_tolerance}。"
        )

        if profile.win_rate > 0:
            lines.append(f"历史胜率 {profile.win_rate:.0%}。")
        if profile.avg_holding_days > 0:
            lines.append(f"平均持仓 {profile.avg_holding_days:.0f} 天。")
        if profile.preferred_sectors:
            lines.append(f"偏好板块：{'、'.join(profile.preferred_sectors)}。")
        if profile.common_biases:
            lines.append(f"行为偏差提醒：{'、'.join(profile.common_biases)}。")

        lines.append("")
        lines.append("根据用户风格调整建议的激进程度和仓位规模。")
        if "追涨倾向" in profile.common_biases:
            lines.append("注意：用户有追涨倾向，给出买入建议时需更审慎。")
        if "频繁交易" in profile.common_biases:
            lines.append("注意：用户交易频繁，适当提醒控制交易频率。")

        return "\n".join(lines)

    def _get_thread_context(self, thread_id: str) -> ThreadContext | None:
        """Read ThreadContext from the threads table."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT context FROM threads WHERE id = ?",
                    (thread_id,),
                ).fetchone()
            if row and row[0]:
                return ThreadContext.model_validate_json(row[0])
        except Exception:
            logger.debug("Failed to load thread context for %s", thread_id)
        return None

    def _build_accuracy_hints(self) -> str:
        """Build historical accuracy context from model monitor."""
        if not self._model_monitor:
            return ""
        try:
            summary = self._model_monitor.get_accuracy_summary(days=90)
            total = summary.get("total_predictions", 0)
            if total < 5:
                return ""
            acc_t5 = summary.get("accuracy_t5")
            if acc_t5 is None:
                return ""
            hints = [
                f"过去 90 天共 {total} 次预测，",
                f"T+5 准确率 {acc_t5:.0%}。",
            ]
            if acc_t5 < 0.50:
                hints.append("近期准确率低于基线，请更加保守地给出建议，降低置信度。")
            return " ".join(hints)
        except Exception:
            return ""

    def _build_memory_hints(self, thread_id: str) -> str:
        """Build relevant memory context for the current thread."""
        if not self._memory_store:
            return ""
        try:
            # Use thread context to build a query
            context = self._get_thread_context(thread_id)
            query_parts: list[str] = []
            if context and context.symbol:
                query_parts.append(context.symbol)
            if context and context.mode:
                query_parts.append(context.mode)
            if not query_parts:
                return ""

            query = " ".join(query_parts)
            symbol = context.symbol if context else None
            memories = self._memory_store.retrieve(query, symbol=symbol, limit=3)
            if not memories:
                return ""

            lines = []
            for mem in memories:
                lines.append(f"- [{mem.category}] {mem.content}")
            return "\n".join(lines)
        except Exception:
            return ""

    def _build_intel_hints(self, thread_id: str) -> str:
        """Build intel context from selected intelligence items."""
        if not self._intel_hub:
            return ""
        context = self._get_thread_context(thread_id)
        if not context or not context.intel_item_ids:
            return ""

        try:
            rows = self._intel_hub.get_items_by_ids(context.intel_item_ids)
        except Exception:
            logger.debug("Failed to load intel items for thread %s", thread_id)
            return ""

        if not rows:
            return ""

        lines: list[str] = []
        for idx, row in enumerate(rows, 1):
            title = row.get("title", "")
            source_name = row.get("source_name", "")
            category = row.get("category", "")
            summary = row.get("summary", "")
            tags = row.get("tags") or []
            symbols = row.get("related_symbols") or []
            symbol_names = row.get("related_symbol_names") or {}

            parts: list[str] = [f"[{idx}] **{title}**"]
            if source_name:
                parts.append(f"  来源: {source_name}")
            if category:
                parts.append(f"  分类: {category}")
            if summary:
                parts.append(f"  摘要: {summary}")
            if symbols:
                symbol_labels = [
                    f"{s}({symbol_names[s]})" if s in symbol_names else s
                    for s in symbols
                ]
                parts.append(f"  关联标的: {', '.join(symbol_labels)}")
            if tags:
                parts.append(f"  标签: {', '.join(tags)}")
            lines.append("\n".join(parts))

        # Matched portfolio symbols passed from frontend
        matched_portfolio = context.matched_portfolio_symbols or []

        # Tailor instruction based on whether a specific stock is selected
        lines.append("")
        symbol = context.symbol
        if symbol:
            lines.append(
                f"**分析要求**：用户已选定个股 {symbol}，请围绕 {symbol} 展开分析。"
                f"结合以上情报判断对 {symbol} 的具体影响（利好/利空/中性），"
                f"不要发散到全部持仓。如某条情报与 {symbol} 无直接关联，"
                f"说明间接影响路径（如板块联动、产业链传导）。"
            )
        elif matched_portfolio:
            portfolio_str = ", ".join(matched_portfolio)
            lines.append(
                f"**分析要求**：情报中提及的标的与用户持仓/自选有交集: {portfolio_str}。"
                f"请重点分析这些情报对 {portfolio_str} 的影响（利好/利空/中性），"
                "给出具体的操作建议。对于未命中持仓的情报，简要说明板块联动影响。"
            )
        else:
            lines.append(
                "**分析要求**：综合分析以上情报，判断对用户持仓的影响。"
                "如果关联标的与持仓有交集，重点分析这些个股；"
                "如果没有交集，分析相关行业板块的机会或风险。"
                "不要逐一分析全部持仓，聚焦在与情报有关的标的上。"
            )

        lines.append("")
        lines.append(
            "**引用规范**：分析中引用情报时，请标注来源编号，"
            "格式为 [编号]（如 [1]、[2]）。在回复末尾附「信息来源」小节，"
            "列出被引用的情报编号、标题和来源名称。"
        )
        return "\n".join(lines)

    def _build_stock_intel_context(
        self,
        user_message: str,
        thread_id: str,
        existing_intel_hints: str,
    ) -> str:
        """Auto-retrieve stock-related intel for symbols in the user message.

        Detects stock symbols from ThreadContext or user message text,
        queries the intel hub for recent items, deduplicates against
        user-selected intel, and formats a concise context block.

        Returns empty string if no symbols detected or no intel found.
        """
        if not self._intel_hub:
            return ""

        # Collect symbols: from thread context + user message extraction
        symbols: list[str] = []
        context = self._get_thread_context(thread_id)
        if context and context.symbol:
            symbols.append(context.symbol)

        if self._symbol_extractor and user_message:
            try:
                extracted = self._symbol_extractor.extract(user_message)
                for sym in extracted:
                    if sym not in symbols:
                        symbols.append(sym)
            except Exception:
                logger.debug("Symbol extraction failed", exc_info=True)

        if not symbols:
            return ""

        # Limit to 2 symbols to control token budget
        symbols = symbols[:2]

        # Collect IDs already in user-selected intel to avoid duplicates
        selected_ids: set[str] = set()
        if context and context.intel_item_ids:
            selected_ids = set(context.intel_item_ids)

        lines: list[str] = []
        idx = 0
        for sym in symbols:
            try:
                result = self._intel_hub.get_feed(symbol=sym, limit=5, days=7)
                items = result.get("items", [])
            except Exception:
                logger.debug("Auto-intel fetch failed for %s", sym)
                continue

            for item in items:
                item_id = item.get("id", "")
                if item_id and item_id in selected_ids:
                    continue
                idx += 1
                title = item.get("title", "")
                summary = item.get("summary", "")
                source_name = item.get("source_name", "")
                tags = item.get("tags") or []

                entry_parts: list[str] = [f"[{idx}] **{title}**"]
                if summary:
                    # Truncate long summaries
                    short = summary[:150] + ("..." if len(summary) > 150 else "")
                    entry_parts.append(f"  摘要: {short}")
                if source_name:
                    entry_parts.append(f"  来源: {source_name}")
                if tags:
                    entry_parts.append(f"  标签: {', '.join(tags[:5])}")
                lines.append("\n".join(entry_parts))

        if not lines:
            return ""

        sym_label = "、".join(symbols)
        header = f"以下是与 {sym_label} 相关的最近情报（自动检索，仅供参考）："
        lines.insert(0, header)
        lines.append("")
        lines.append(
            "如果以上情报不足以支撑消息面分析，请调用 web_search 联网搜索补充。"
        )
        return "\n".join(lines)

    @staticmethod
    def _build_context_hints(context: ThreadContext) -> str:
        """Build context-specific prompt hints based on ThreadContext."""
        mode = context.mode
        symbol = context.symbol

        if mode == "stock" and symbol:
            return (
                f"用户正在关注个股 {symbol}，优先使用 get_realtime_quote 和 "
                f"get_technical_indicators 工具分析该股票，"
                f"然后结合概念板块和资金面给出综合判断。"
                f"\n**必须**调用 search_intel(symbol='{symbol}') 获取相关情报，"
                f"如果情报不足再调用 web_search 联网搜索 {symbol} 最新消息。"
            )
        if mode == "portfolio":
            return (
                "用户希望诊断持仓组合，主动使用 get_portfolio 工具获取持仓数据，"
                "逐一分析各持仓个股，给出整体诊断和操作建议。"
            )
        if mode == "market":
            return (
                "用户关注市场整体概况，使用 get_global_markets 和 "
                "get_trending_news 工具获取市场数据和热点资讯，"
                "给出市场研判和板块观点。"
            )
        return ""

    # ------------------------------------------------------------------
    # Rich card extraction
    # ------------------------------------------------------------------

    def _extract_rich_cards(self, text: str) -> list[RichCard]:
        """Extract rich cards from the <!--RICH_CARDS:...--> marker."""
        match = _RICH_CARDS_RE.search(text)
        if not match:
            return []

        try:
            cards_data = json.loads(match.group(1))
            return [
                RichCard(type=c.get("type", "unknown"), props=c.get("props", {}))
                for c in cards_data
                if isinstance(c, dict)
            ]
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse rich cards from agent reply")
            return []

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a connection to the SQLite database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_db(self) -> None:
        """Create tables if they don't exist."""
        with self._connect() as conn:
            # Flush stale WAL from previous container (macOS Docker bind-mount).
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    context TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    rich_cards TEXT,
                    tool_calls TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (thread_id) REFERENCES threads(id)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_thread
                    ON messages(thread_id, timestamp);

                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    symbol TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    shares INTEGER NOT NULL,
                    price REAL NOT NULL,
                    amount REAL NOT NULL,
                    source TEXT NOT NULL,
                    reasoning TEXT,
                    agent_recommendation_id TEXT,
                    decision_feedback TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    executed_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recommendations (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reasoning TEXT NOT NULL,
                    risk_warnings TEXT,
                    stop_loss REAL,
                    user_decision TEXT DEFAULT 'pending',
                    user_feedback TEXT,
                    actual_outcome TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

            # Schema migration: add satisfaction/feedback columns to messages
            cursor = conn.execute("PRAGMA table_info(messages)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if "satisfaction" not in existing_cols:
                conn.execute("ALTER TABLE messages ADD COLUMN satisfaction TEXT")
                conn.execute("ALTER TABLE messages ADD COLUMN feedback TEXT")

            # Schema migration: add persona + cc_session columns to threads
            cursor = conn.execute("PRAGMA table_info(threads)")
            thread_cols = {row[1] for row in cursor.fetchall()}
            if "persona" not in thread_cols:
                conn.execute(
                    "ALTER TABLE threads ADD COLUMN persona TEXT DEFAULT 'default'"
                )
            if "cc_session_id" not in thread_cols:
                conn.execute("ALTER TABLE threads ADD COLUMN cc_session_id TEXT")

    def _save_message(self, thread_id: str, msg: ChatMessage) -> None:
        """Persist a message to SQLite."""
        rich_cards_json = (
            json.dumps([c.model_dump() for c in msg.rich_cards], ensure_ascii=False)
            if msg.rich_cards
            else None
        )
        tool_calls_json = (
            json.dumps([t.model_dump() for t in msg.tool_calls], ensure_ascii=False)
            if msg.tool_calls
            else None
        )

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages "
                "(id, thread_id, role, content, rich_cards, tool_calls, timestamp, "
                "satisfaction, feedback) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    msg.id,
                    thread_id,
                    msg.role,
                    msg.content,
                    rich_cards_json,
                    tool_calls_json,
                    msg.timestamp,
                    msg.satisfaction,
                    msg.feedback,
                ),
            )

    def _load_history(self, thread_id: str) -> list[ChatMessage]:
        """Load all messages for a thread, ordered by timestamp."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, role, content, rich_cards, tool_calls, timestamp, "
                "satisfaction, feedback "
                "FROM messages WHERE thread_id = ? ORDER BY timestamp",
                (thread_id,),
            ).fetchall()

        messages = []
        for row in rows:
            rich_cards = None
            if row[3]:
                try:
                    rich_cards = [RichCard(**c) for c in json.loads(row[3])]
                except (json.JSONDecodeError, TypeError):
                    pass

            tool_calls = None
            if row[4]:
                try:
                    tool_calls = [ToolCallRecord(**t) for t in json.loads(row[4])]
                except (json.JSONDecodeError, TypeError):
                    pass

            messages.append(
                ChatMessage(
                    id=row[0],
                    role=row[1],
                    content=row[2],
                    rich_cards=rich_cards,
                    tool_calls=tool_calls,
                    timestamp=row[5],
                    satisfaction=row[6],
                    feedback=row[7],
                )
            )
        return messages

    # ------------------------------------------------------------------
    # Persona helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_personas() -> dict[str, dict]:
        """Load persona definitions from config/llm.yaml."""
        try:
            cfg = load_config("llm")
            return cfg.get("personas", {})
        except Exception:
            logger.debug("Failed to load personas config", exc_info=True)
            return {}

    def list_personas(self) -> list[PersonaInfo]:
        """List available personas for the frontend selector."""
        personas = self._load_personas()
        return [
            PersonaInfo(
                key=key,
                display_name=cfg.get("display_name", key),
                description=cfg.get("description", ""),
                icon=cfg.get("icon", "default"),
                backend=cfg.get("backend", "gemini"),
            )
            for key, cfg in personas.items()
        ]

    def _resolve_persona(self, persona_key: str | None) -> dict:
        """Resolve persona key to its config dict."""
        personas = self._load_personas()
        key = persona_key or "default"
        if key in personas:
            cfg = dict(personas[key])
            cfg["key"] = key
            return cfg
        # Fallback to default
        default = personas.get("default", {})
        cfg = dict(default)
        cfg["key"] = "default"
        return cfg

    def _should_auto_route_to_claude_code(
        self, message: str
    ) -> tuple[bool, dict | None]:
        """Check if a message should be auto-routed to Claude Code.

        Uses keyword matching and message length to detect deep analysis
        requests without consuming an extra LLM call.

        Returns:
            (should_route, persona_config) — persona_config is a resolved
            persona dict ready for ``_send_claude_code()``, or None.
        """
        try:
            bridge_cfg = load_config("llm").get("claude_code_bridge", {})
            auto_cfg = bridge_cfg.get("auto_route", {})
        except Exception:
            return False, None

        if not auto_cfg.get("enabled", False):
            return False, None

        min_len = auto_cfg.get("min_message_length", 100)
        keywords: list[str] = auto_cfg.get("keywords", [])

        if not keywords:
            return False, None

        # Must contain at least one keyword
        matched_keyword = None
        for kw in keywords:
            if kw in message:
                matched_keyword = kw
                break

        if not matched_keyword:
            return False, None

        # Message length gate: short messages with a keyword still qualify
        # only if they look like an analysis request (contain a stock code,
        # a stock name, or explicit analysis intent).  For messages >= min_len
        # the keyword alone is sufficient.
        #
        # Strong keywords (深度分析, 全面分析, etc.) are unambiguous analysis
        # requests — they pass the gate unconditionally even for short messages.
        _STRONG_KEYWORDS = [
            "深度分析",
            "全面分析",
            "详细研究",
            "深入研究",
            "专家分析",
            "深度模式",
        ]
        if len(message) < min_len and matched_keyword not in _STRONG_KEYWORDS:
            has_stock_code = bool(re.search(r"\d{6}", message))
            # Chinese stock names: 2-4 CJK chars + suffix (股份/股票/集团/银行/证券 etc.)
            has_stock_name = bool(
                re.search(
                    r"[\u4e00-\u9fff]{2,4}(?:股份|股票|集团|银行|证券|保险|电子|科技|医药|能源|汽车)",
                    message,
                )
            )
            # Analysis-intent phrases that imply a concrete request
            _INTENT_PHRASES = [
                "持仓",
                "操作建议",
                "买入",
                "卖出",
                "加仓",
                "减仓",
                "止损",
                "止盈",
            ]
            has_intent = any(p in message for p in _INTENT_PHRASES)
            if not (has_stock_code or has_stock_name or has_intent):
                return False, None

        # Determine persona via keyword → category mapping
        mapping = auto_cfg.get("persona_mapping", {})
        persona_key = mapping.get("default", "analyst")

        # Simple keyword-to-category heuristic
        _CATEGORY_KEYWORDS = {
            "industry": ["产业链", "护城河", "商业模式"],
            "ai_tech": ["AI", "算力", "芯片", "人工智能"],
            "financial": ["估值", "财报", "基本面", "估值模型"],
            "quant": ["因子", "量化", "回测", "因子分析"],
            "portfolio": ["组合", "仓位", "风控"],
        }
        for category, cat_keywords in _CATEGORY_KEYWORDS.items():
            if any(ck in message for ck in cat_keywords):
                persona_key = mapping.get(category, persona_key)
                break

        # Resolve to full persona config
        personas = self._load_personas()
        if persona_key in personas:
            cfg = dict(personas[persona_key])
            cfg["key"] = persona_key
        else:
            # Fallback to analyst persona
            fallback_key = "analyst"
            cfg = dict(personas.get(fallback_key, {}))
            cfg["key"] = fallback_key

        # Ensure backend is claude_code
        cfg["backend"] = "claude_code"

        logger.info(
            "Auto-routing to Claude Code: keyword=%r persona=%s msg_len=%d",
            matched_keyword,
            cfg["key"],
            len(message),
        )

        return True, cfg

    def _get_thread_persona(self, thread_id: str) -> str:
        """Read the persona key from the threads table."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT persona FROM threads WHERE id = ?",
                    (thread_id,),
                ).fetchone()
            if row and row[0]:
                return row[0]
        except Exception:
            logger.debug("Failed to read thread persona for %s", thread_id)
        return "default"

    def _get_thread_cc_session(self, thread_id: str) -> str | None:
        """Read the Claude Code session ID for a thread."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT cc_session_id FROM threads WHERE id = ?",
                    (thread_id,),
                ).fetchone()
            if row and row[0]:
                return row[0]
        except Exception:
            logger.debug("Failed to read cc_session_id for %s", thread_id)
        return None

    def _save_thread_cc_session(self, thread_id: str, cc_session_id: str) -> None:
        """Persist the Claude Code session ID for a thread."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE threads SET cc_session_id = ? WHERE id = ?",
                    (cc_session_id, thread_id),
                )
        except Exception:
            logger.debug("Failed to save cc_session_id for %s", thread_id)

    # ------------------------------------------------------------------
    # Claude Code bridge call
    # ------------------------------------------------------------------

    async def _send_claude_code(
        self,
        thread_id: str,
        message: str,
        persona_config: dict,
    ) -> ChatMessage:
        """Send a message via the Claude Code bridge service.

        Bypasses the Gemini tool loop entirely. Claude Code uses its own
        MCP tools to fetch data from the Docker API.
        """
        import httpx

        bridge_cfg = {}
        try:
            bridge_cfg = load_config("llm").get("claude_code_bridge", {})
        except Exception:
            pass

        bridge_url = os.environ.get(
            "CLAUDE_CODE_BRIDGE_URL",
            bridge_cfg.get("url", "http://host.docker.internal:19821"),
        )
        timeout = bridge_cfg.get("timeout", 300)

        # Build conversation history
        history = self._load_history(thread_id)
        conversation = [{"role": m.role, "content": m.content} for m in history[:-1]]

        # Build system prompt with persona overlay
        system_prompt = self._build_system_prompt(
            thread_id, user_message=message, persona_config=persona_config
        )

        # Get or create Claude Code session ID
        session_id = self._get_thread_cc_session(thread_id)

        logger.info(
            "Claude Code call: thread=%s persona=%s session=%s",
            thread_id[:8],
            persona_config.get("key", "?"),
            (session_id or "new")[:8],
        )

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{bridge_url}/v1/chat",
                    json={
                        "session_id": session_id,
                        "message": message,
                        "system_prompt": system_prompt,
                        "conversation_history": conversation,
                        "model": bridge_cfg.get("model", "opus"),
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            logger.warning(
                "Claude Code bridge not reachable at %s — degrading to Gemini",
                bridge_url,
            )
            return await self._send_gemini_with_persona(
                thread_id, message, persona_config
            )
        except httpx.TimeoutException:
            logger.warning(
                "Claude Code bridge timed out after %ds — degrading to Gemini",
                timeout,
            )
            return await self._send_gemini_with_persona(
                thread_id, message, persona_config
            )
        except httpx.HTTPStatusError as exc:
            logger.error("Claude Code bridge error: %d", exc.response.status_code)
            error_detail = ""
            try:
                error_detail = exc.response.json().get("error", "")
            except Exception:
                pass
            data = {
                "text": f"Claude Code 调用失败: {error_detail or exc.response.status_code}",
                "session_id": session_id,
            }

        # Persist returned session ID for multi-turn
        new_session_id = data.get("session_id")
        if new_session_id and new_session_id != session_id:
            self._save_thread_cc_session(thread_id, new_session_id)

        final_text = data.get("text", "")

        # Extract rich cards (Claude Code may produce them too)
        rich_cards = self._extract_rich_cards(final_text)
        clean_text = _RICH_CARDS_RE.sub("", final_text).strip()

        reply = ChatMessage(
            id=str(uuid.uuid4()),
            role="assistant",
            content=clean_text,
            rich_cards=rich_cards or None,
            timestamp=_now_iso(),
            agent_name=f"claude_code:{persona_config.get('key', 'default')}",
        )
        self._save_message(thread_id, reply)

        # Update thread timestamp
        with self._connect() as conn:
            conn.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?",
                (_now_iso(), thread_id),
            )

        return reply

    async def _send_gemini_with_persona(
        self,
        thread_id: str,
        message: str,
        persona_config: dict,
    ) -> ChatMessage:
        """Degraded path: use Gemini tool loop with persona overlay.

        Called when the Claude Code bridge is unavailable. Reuses the
        standard Gemini tool loop but injects the persona's system_prompt_overlay.
        Prefixes the reply with a notice that deep analysis is temporarily unavailable.
        """
        logger.info(
            "Gemini persona fallback: thread=%s persona=%s",
            thread_id[:8],
            persona_config.get("key", "?"),
        )

        # Load conversation history
        history = self._load_history(thread_id)
        system_prompt = self._build_system_prompt(
            thread_id, user_message=message, persona_config=persona_config
        )

        llm_messages = [LLMMessage(role="system", content=system_prompt)]
        for msg in history:
            llm_messages.append(LLMMessage(role=msg.role, content=msg.content))

        # Run standard Gemini tool loop
        tool_definitions = self._tools.get_tool_definitions()
        tool_records: list[ToolCallRecord] = []
        final_text: str | None = None
        loop_start = time.perf_counter()

        for _round in range(_MAX_TOOL_ROUNDS):
            if time.perf_counter() - loop_start > _MAX_LOOP_SECONDS:
                final_text = await self._summarize_on_timeout(llm_messages)
                break

            llm_resp: LLMToolResponse = await asyncio.to_thread(
                self._llm.complete_with_tools,
                messages=llm_messages,
                tools=tool_definitions,
                caller=f"agent.persona_fallback.{persona_config.get('key', 'default')}",
                max_tokens=16384,
                temperature=0.3,
            )

            if not llm_resp.tool_calls:
                final_text = llm_resp.text
                break

            # Build assistant message from raw content or tool calls
            if llm_resp.raw_assistant_content is not None:
                assistant_content = llm_resp.raw_assistant_content
            else:
                assistant_blocks: list[dict[str, Any]] = []
                if llm_resp.text:
                    assistant_blocks.append({"type": "text", "text": llm_resp.text})
                for tc in llm_resp.tool_calls:
                    assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.input,
                        }
                    )
                assistant_content = assistant_blocks

            llm_messages.append(LLMMessage(role="assistant", content=assistant_content))

            # Execute tools and build tool_result message
            tool_results: list[dict[str, Any]] = []
            for tc in llm_resp.tool_calls:
                start = time.perf_counter()
                result_str = await self._tools.execute(tc.name, tc.input)
                elapsed = (time.perf_counter() - start) * 1000

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "tool_name": tc.name,
                        "content": result_str,
                    }
                )
                tool_records.append(
                    ToolCallRecord(
                        tool_name=tc.name,
                        input=tc.input,
                        output_summary=result_str[:200],
                        duration_ms=elapsed,
                    )
                )

            llm_messages.append(LLMMessage(role="user", content=tool_results))

        if final_text is None:
            final_text = "分析处理中，请稍后重试。"

        # Prefix with degradation notice
        notice = "（当前使用默认分析模式，深度分析服务暂时不可用）\n\n"
        final_text = notice + final_text

        rich_cards = self._extract_rich_cards(final_text)
        clean_text = _RICH_CARDS_RE.sub("", final_text).strip()

        reply = ChatMessage(
            id=str(uuid.uuid4()),
            role="assistant",
            content=clean_text,
            rich_cards=rich_cards or None,
            tool_calls=(
                [r.model_dump() for r in tool_records] if tool_records else None
            ),
            timestamp=_now_iso(),
            agent_name=f"gemini_fallback:{persona_config.get('key', 'default')}",
        )
        self._save_message(thread_id, reply)

        with self._connect() as conn:
            conn.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?",
                (_now_iso(), thread_id),
            )

        return reply

    async def _close_claude_code_session(self, thread_id: str) -> None:
        """Close the Claude Code session associated with a thread.

        Called when a thread is deleted to free bridge resources.
        """
        session_id = self._get_thread_cc_session(thread_id)
        if not session_id:
            return

        import httpx

        bridge_cfg = {}
        try:
            bridge_cfg = load_config("llm").get("claude_code_bridge", {})
        except Exception:
            pass

        bridge_url = os.environ.get(
            "CLAUDE_CODE_BRIDGE_URL",
            bridge_cfg.get("url", "http://host.docker.internal:19821"),
        )

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{bridge_url}/v1/sessions/{session_id}/close")
            logger.info(
                "Closed Claude Code session %s for thread %s",
                session_id[:8],
                thread_id[:8],
            )
        except Exception:
            logger.debug(
                "Failed to close Claude Code session %s", session_id[:8], exc_info=True
            )


def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()

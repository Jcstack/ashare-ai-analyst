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
_MAX_TOOL_ROUNDS = 5
_MAX_LOOP_SECONDS = (
    300  # 5 min — deep portfolio analysis needs multiple deep_analyze calls
)
_MAX_LLM_TOOLS_PER_REQUEST = 2  # Budget: max inner LLM calls per agent loop

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

    def create_thread_background(
        self,
        message: str,
        context: ThreadContext | None = None,
        persona: str | None = None,
    ) -> str:
        """Create a thread record in 'processing' state for background work.

        PRD v50 aligned: returns immediately, agent loop runs in background.
        Frontend polls GET /threads/:id for completion.

        Returns:
            The new thread_id.
        """
        title = message[:50].strip()
        if len(message) > 50:
            title += "..."
        thread_id = self.create_thread_only(title, context, persona)
        self._set_thread_status(thread_id, "processing")
        return thread_id

    async def process_thread_background(
        self,
        thread_id: str,
        message: str,
        use_multi_agent: bool = False,
    ) -> None:
        """Process a thread message in background. Updates status on completion."""
        try:
            await self.send_message(
                thread_id,
                message,
                use_multi_agent=use_multi_agent,
                _skip_user_save=True,  # User msg already saved by route
            )
            self._set_thread_status(thread_id, "ready")
        except Exception as exc:
            logger.exception("Background thread processing failed: %s", exc)
            self._set_thread_status(thread_id, "error")

    def _set_thread_status(self, thread_id: str, status: str) -> None:
        """Update the processing_status of a thread."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE threads SET processing_status = ?, updated_at = ? WHERE id = ?",
                (status, _now_iso(), thread_id),
            )

    def get_thread_status(self, thread_id: str) -> str | None:
        """Get the processing status of a thread."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT processing_status FROM threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
        return row[0] if row else None

    async def send_message(
        self,
        thread_id: str,
        message: str,
        use_multi_agent: bool = False,
        _skip_user_save: bool = False,
    ) -> ChatMessage:
        """Send a user message and get the agent reply.

        Implements the agentic tool loop:
        1. Load thread history
        2. Build system prompt
        3. Run tool loop until end_turn (Gemini) or bridge call (Claude Code)
        4. Extract rich cards
        5. Persist messages

        Args:
            _skip_user_save: If True, skip saving user message (already saved
                by background processing path).

        Returns:
            The agent's reply ChatMessage.
        """
        now = _now_iso()

        # Save user message (skipped in background path where it's pre-saved)
        if not _skip_user_save:
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

        # ── Tool loop (text-based tool_use via complete()) ──────────
        # Gemini Web does not support structured tool_use. We embed tool
        # definitions in the prompt and parse tool calls from text output.
        history = self._load_history(thread_id)
        system_prompt = self._build_system_prompt(thread_id, user_message=message)

        # Embed tool definitions in system prompt for text-based tool use
        tool_definitions = self._tools.get_tool_definitions()
        tool_instruction = self._build_tool_instruction(tool_definitions)
        system_with_tools = system_prompt + "\n\n" + tool_instruction

        llm_messages = [LLMMessage(role="system", content=system_with_tools)]
        for msg in history:
            llm_messages.append(LLMMessage(role=msg.role, content=msg.content))

        tool_records: list[ToolCallRecord] = []
        _tool_results_data: list[dict[str, Any]] = []
        _llm_tool_count = 0  # Track inner LLM tool calls for budget
        final_text: str | None = None
        loop_start = time.perf_counter()

        for _round in range(_MAX_TOOL_ROUNDS):
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

            response = await asyncio.to_thread(
                self._llm.complete,
                messages=llm_messages,
                caller="agent_service.send_message",
                max_tokens=16384,
                temperature=0.3,
                analysis_type="agent_chat",
            )

            # Parse tool calls from text response
            parsed_calls = self._parse_tool_calls_from_text(response.text)

            if not parsed_calls:
                # No tool calls — this is the final response
                final_text = self._strip_tool_call_blocks(response.text)
                if not final_text.strip():
                    logger.warning(
                        "LLM returned empty text at round %d, summarizing", _round
                    )
                    final_text = await self._summarize_on_timeout(llm_messages)
                break

            # Strip non-tool-call text from the assistant response before
            # appending to history.  Gemini sometimes generates hallucinated
            # analysis alongside tool_call tags; keeping that text pollutes
            # the context and the final answer may echo the wrong numbers.
            tool_call_only = "\n".join(
                m.group(0)
                for m in re.finditer(
                    r"<tool_call>.*?</tool_call>", response.text, re.DOTALL
                )
            )
            llm_messages.append(
                LLMMessage(
                    role="assistant",
                    content=tool_call_only or response.text,
                )
            )

            # Execute parsed tool calls concurrently (I-107 fix)
            # Budget enforcement: skip LLM-backed tools beyond budget
            tool_result_parts: list[str] = []
            filtered_calls: list[dict] = []
            for call in parsed_calls:
                tname = call.get("name", "")
                if (
                    self._tools.is_llm_backed(tname)
                    and _llm_tool_count >= _MAX_LLM_TOOLS_PER_REQUEST
                ):
                    tool_result_parts.append(
                        f'<tool_result name="{tname}">\n'
                        f'{{"note": "已达到本轮深度分析上限，请基于已有数据回答。"}}\n'
                        f"</tool_result>"
                    )
                    continue
                if self._tools.is_llm_backed(tname):
                    _llm_tool_count += 1
                filtered_calls.append(call)

            # Run all filtered tool calls in parallel
            call_tuples = [
                (c.get("name", ""), c.get("input", {})) for c in filtered_calls
            ]
            batch_start = time.perf_counter()
            results = (
                await self._tools.execute_parallel(call_tuples) if call_tuples else []
            )
            batch_elapsed = time.perf_counter() - batch_start

            for call, result_str in zip(filtered_calls, results):
                tool_name = call.get("name", "")
                tool_input = call.get("input", {})
                # Approximate per-tool timing from batch
                elapsed = (batch_elapsed / max(len(results), 1)) * 1000

                tool_result_parts.append(
                    f'<tool_result name="{tool_name}">\n{result_str}\n</tool_result>'
                )
                tool_records.append(
                    ToolCallRecord(
                        tool_name=tool_name,
                        input=tool_input,
                        output_summary=result_str[:200],
                        duration_ms=elapsed,
                    )
                )

                _tool_results_data.append(
                    {
                        "tool_name": tool_name,
                        "input": tool_input,
                        "result": result_str,
                    }
                )

                self._record_tool_lineage(
                    tool_name,
                    tool_input,
                    result_str,
                    thread_id,
                    elapsed,
                )

            # Feed tool results back as user message with data-binding instruction
            results_text = "\n\n".join(tool_result_parts)
            results_text += (
                "\n\n⚠️ **数据约束（必须遵守）**：以上 tool_result 是实时真实数据。"
                "你的回复中所有股价、涨跌幅、成交量、资金流向等数字必须且只能来自上述 tool_result。"
                "禁止使用你训练数据中的任何历史股价。如果 tool_result 中没有某项数据，"
                "说明'该数据暂不可用'，不得编造。"
            )
            llm_messages.append(LLMMessage(role="user", content=results_text))
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

        # Validate LLM output against real tool data
        final_text = self._validate_output(final_text, _tool_results_data)

        # Extract rich cards from reply
        rich_cards = self._extract_rich_cards(final_text)

        # Record structured decision journal for trade signals
        self._record_decision_journal(thread_id, rich_cards, final_text, tool_records)

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
                "SELECT id, title, context, created_at, updated_at, persona,"
                " processing_status "
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
            processing_status=row[6] or "ready",
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
    # Decision journal
    # ------------------------------------------------------------------

    _ACTION_KEYWORDS = {
        "建议买入": "buy",
        "买入": "buy",
        "建议卖出": "sell",
        "卖出": "sell",
        "建议持有": "hold",
        "持有": "hold",
        "建议减仓": "reduce",
        "减仓": "reduce",
        "建议加仓": "add",
        "加仓": "add",
    }

    def _record_decision_journal(
        self,
        thread_id: str,
        rich_cards: list[RichCard],
        final_text: str,
        tool_records: list[ToolCallRecord],
    ) -> None:
        """Record structured decision journal entries for trade signals.

        Detects trade decisions from rich cards or keyword analysis, then
        persists a causal-chain entry to the ``decision_journal`` table
        for future outcome tracking and calibration.
        """
        entries: list[dict[str, Any]] = []

        # 1. Extract from rich cards (primary path)
        for card in rich_cards:
            if card.type in ("trade_decision", "stock_analysis"):
                props = card.props
                symbol = props.get("symbol")
                if not symbol:
                    continue
                entries.append(
                    {
                        "symbol": symbol,
                        "action": props.get("action", "hold"),
                        "confidence": float(props.get("confidence", 0.5)),
                        "entry_price": (
                            float(props["entry_price"])
                            if props.get("entry_price") is not None
                            else (
                                float(props["price"])
                                if props.get("price") is not None
                                else None
                            )
                        ),
                        "stop_loss": (
                            float(props["stop_loss"])
                            if props.get("stop_loss") is not None
                            else None
                        ),
                        "target_price": (
                            float(props["target_price"])
                            if props.get("target_price") is not None
                            else (
                                float(props["price_target"])
                                if props.get("price_target") is not None
                                else None
                            )
                        ),
                        "trigger_event": props.get("trigger", "user_query"),
                        "key_evidence": {
                            "bull": props.get("bull_case", props.get("reasoning", "")),
                            "bear": props.get("bear_case", props.get("risks", "")),
                        },
                    }
                )

        # 2. Fallback: keyword detection when no rich cards matched
        if not entries:
            detected_action = None
            for keyword, action in self._ACTION_KEYWORDS.items():
                if keyword in final_text:
                    detected_action = action
                    break
            if not detected_action:
                return  # No trade signal detected

            # Try to extract symbol from text (6-digit patterns)
            symbol_match = re.search(r"\b(\d{6})\b", final_text)
            if not symbol_match:
                return
            # Extract reasoning context from surrounding text
            symbol_str = symbol_match.group(1)
            context_start = max(0, symbol_match.start() - 200)
            context_end = min(len(final_text), symbol_match.end() + 300)
            reasoning_snippet = final_text[context_start:context_end].strip()

            entries.append(
                {
                    "symbol": symbol_str,
                    "action": detected_action,
                    "confidence": 0.5,
                    "entry_price": None,
                    "stop_loss": None,
                    "target_price": None,
                    "trigger_event": "user_query",
                    "key_evidence": {
                        "bull": reasoning_snippet[:200]
                        if detected_action in ("buy", "add")
                        else "",
                        "bear": reasoning_snippet[:200]
                        if detected_action in ("sell", "reduce")
                        else "",
                    },
                }
            )

        # 3. Collect shared context
        data_sources = [r.tool_name for r in tool_records] if tool_records else []
        sentiment_phase = self._get_current_sentiment_phase()
        portfolio_ctx = self._get_portfolio_context_snapshot()

        # 4. Persist each entry
        now = _now_iso()
        try:
            with self._connect() as conn:
                for entry in entries:
                    journal_id = str(uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO decision_journal (
                            id, timestamp, thread_id, symbol, action,
                            confidence, trigger_event, data_sources,
                            key_evidence, sentiment_phase, portfolio_context,
                            entry_price, stop_loss, target_price
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            journal_id,
                            now,
                            thread_id,
                            entry["symbol"],
                            entry["action"],
                            entry["confidence"],
                            entry.get("trigger_event", "user_query"),
                            json.dumps(data_sources, ensure_ascii=False),
                            json.dumps(
                                entry.get("key_evidence", {}), ensure_ascii=False
                            ),
                            sentiment_phase,
                            json.dumps(portfolio_ctx, ensure_ascii=False)
                            if portfolio_ctx
                            else None,
                            entry.get("entry_price"),
                            entry.get("stop_loss"),
                            entry.get("target_price"),
                        ),
                    )
                    logger.info(
                        "Decision journal entry: %s %s %s (confidence=%.2f, id=%s)",
                        entry["action"],
                        entry["symbol"],
                        thread_id,
                        entry["confidence"],
                        journal_id,
                    )
        except Exception:
            logger.warning(
                "Failed to record decision journal for thread %s",
                thread_id,
                exc_info=True,
            )

    def _get_current_sentiment_phase(self) -> str:
        """Retrieve current market sentiment phase (best-effort)."""
        try:
            from src.agent_loop.sentiment_cycle import SentimentCycleDetector

            detector = SentimentCycleDetector()
            phase = detector.detect_phase()
            return phase.value if hasattr(phase, "value") else str(phase)
        except Exception:
            return "unknown"

    def _get_portfolio_context_snapshot(self) -> dict[str, Any] | None:
        """Build a lightweight portfolio snapshot for journal context."""
        if not self._capital_service:
            return None
        try:
            overview = self._capital_service.get_overview()
            return {
                "total_value": overview.get("total_value", 0),
                "cash": overview.get("cash", 0),
                "position_count": overview.get("position_count", 0),
                "sector_weights": overview.get("sector_weights", {}),
            }
        except Exception:
            return None

    def get_decision_stats(self, lookback_days: int = 30) -> dict[str, Any]:
        """Return aggregate statistics from the decision journal.

        Used for confidence calibration and optimization analysis.

        Args:
            lookback_days: How many days back to include.

        Returns:
            Dictionary with total_decisions, pending, wins, losses,
            win_rate, avg_confidence, avg_return_t1, by_sentiment_phase,
            and by_action breakdowns.
        """
        cutoff = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - lookback_days * 86400,
            tz=timezone.utc,
        ).isoformat()

        try:
            with self._connect() as conn:
                # Overall stats
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN outcome_status = 'pending' THEN 1 ELSE 0 END)
                            AS pending,
                        SUM(CASE WHEN outcome_status = 'win' THEN 1 ELSE 0 END)
                            AS wins,
                        SUM(CASE WHEN outcome_status = 'loss' THEN 1 ELSE 0 END)
                            AS losses,
                        AVG(confidence) AS avg_conf,
                        AVG(outcome_t1) AS avg_t1
                    FROM decision_journal
                    WHERE timestamp >= ?
                    """,
                    (cutoff,),
                ).fetchone()

                total = row[0] or 0
                pending = row[1] or 0
                wins = row[2] or 0
                losses = row[3] or 0
                avg_conf = round(row[4], 3) if row[4] is not None else None
                avg_t1 = round(row[5], 4) if row[5] is not None else None

                evaluated = wins + losses
                win_rate = round(wins / evaluated, 3) if evaluated > 0 else None

                # By sentiment phase
                phase_rows = conn.execute(
                    """
                    SELECT sentiment_phase, COUNT(*) AS cnt,
                        SUM(CASE WHEN outcome_status = 'win' THEN 1 ELSE 0 END)
                            AS wins
                    FROM decision_journal
                    WHERE timestamp >= ? AND sentiment_phase IS NOT NULL
                    GROUP BY sentiment_phase
                    """,
                    (cutoff,),
                ).fetchall()
                by_phase: dict[str, dict] = {}
                for pr in phase_rows:
                    phase_name = pr[0] or "unknown"
                    phase_cnt = pr[1] or 0
                    phase_wins = pr[2] or 0
                    by_phase[phase_name] = {
                        "count": phase_cnt,
                        "win_rate": round(phase_wins / phase_cnt, 3)
                        if phase_cnt > 0
                        else None,
                    }

                # By action
                action_rows = conn.execute(
                    """
                    SELECT action, COUNT(*) AS cnt,
                        SUM(CASE WHEN outcome_status = 'win' THEN 1 ELSE 0 END)
                            AS wins
                    FROM decision_journal
                    WHERE timestamp >= ? AND action IS NOT NULL
                    GROUP BY action
                    """,
                    (cutoff,),
                ).fetchall()
                by_action: dict[str, dict] = {}
                for ar in action_rows:
                    act_name = ar[0] or "unknown"
                    act_cnt = ar[1] or 0
                    act_wins = ar[2] or 0
                    by_action[act_name] = {
                        "count": act_cnt,
                        "win_rate": round(act_wins / act_cnt, 3)
                        if act_cnt > 0
                        else None,
                    }

                return {
                    "total_decisions": total,
                    "pending": pending,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": win_rate,
                    "avg_confidence": avg_conf,
                    "avg_return_t1": avg_t1,
                    "by_sentiment_phase": by_phase,
                    "by_action": by_action,
                }
        except Exception:
            logger.warning("Failed to compute decision stats", exc_info=True)
            return {
                "total_decisions": 0,
                "pending": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": None,
                "avg_confidence": None,
                "avg_return_t1": None,
                "by_sentiment_phase": {},
                "by_action": {},
            }

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
                max_tokens=4096,
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
        # Base role description — AI PM mandate (v50.0)
        base_role = (
            "You are an AI portfolio manager. The user is an execution trader. "
            "You make decisions, the user executes. You manage a real A-share portfolio "
            "and are responsible for investment outcomes. Use the provided tools to fetch "
            "real-time data, analyze, and issue professional, actionable trade instructions. "
            "All output must be in Chinese."
        )

        # Inject persona overlay if present
        overlay = ""
        if persona_config:
            overlay = persona_config.get("system_prompt_overlay", "")

        from datetime import datetime as _dt, timedelta
        from zoneinfo import ZoneInfo

        _cst = ZoneInfo("Asia/Shanghai")
        _now_cst = _dt.now(_cst)
        _today_str = _now_cst.strftime("%Y-%m-%d %H:%M CST (北京时间)")
        _weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
            _now_cst.weekday()
        ]

        # Determine last trading day (skip weekends)
        _check = _now_cst.date()
        if _now_cst.hour < 15:
            # Before market close — last trading day is previous business day
            _check -= timedelta(days=1)
        while _check.weekday() >= 5:  # Saturday=5, Sunday=6
            _check -= timedelta(days=1)
        _last_trading_day = _check.isoformat()

        # Classify request type for prompt tiering
        request_type = self._classify_request(user_message)

        parts = [base_role]
        if overlay:
            parts.append(overlay)

        # --- Universal sections (all request types) ---
        parts.extend(
            [
                "",
                f"## Current time: {_today_str} ({_weekday_cn})",
                f"## Last trading day: {_last_trading_day}",
                (
                    "Quote data is from the last trading day's close. When describing data, "
                    "say '上一交易日' or the specific date — never say '昨日' (may be inaccurate "
                    "due to weekends/holidays). Output in Chinese."
                ),
            ]
        )

        # --- Sentiment cycle injection (all types except general) ---
        if request_type != "general":
            sentiment_hint = self._build_sentiment_cycle_hints()
            if sentiment_hint:
                parts.append("")
                parts.append(sentiment_hint)

        # --- Data staleness warning (all types except general) ---
        if request_type != "general":
            parts.extend(
                [
                    "",
                    (
                        "Your training data cutoff is before today. Any information about company "
                        "news, earnings, or announcements may be outdated. You MUST use tools to "
                        "fetch current data — never rely on your memory."
                    ),
                ]
            )

        # --- Data accuracy rules (stock_analysis + trade_decision) ---
        if request_type in ("stock_analysis", "trade_decision"):
            parts.extend(
                [
                    "",
                    "## Data Accuracy Iron Rules (highest priority)",
                    (
                        "- **Never fabricate any numbers**: prices, change%, volume, capital flow, "
                        "target price, stop-loss — all values must come from tool-returned real-time data. "
                        "Never give specific numbers from memory or speculation."
                    ),
                    (
                        "- **Call tools first, then reference data**: before calling get_realtime_quote, "
                        "you must NOT mention any specific stock price or change% in your reply. "
                        "**Key: do not write any analysis outside tool_call tags. Output all tool_calls first, "
                        "then write analysis after receiving tool_results.**"
                    ),
                    (
                        "- **Stop-loss must be below current price**: if a long recommendation has "
                        "stop-loss >= current price, the analysis is wrong — fix it."
                    ),
                    (
                        "- **Target price must be reasonable**: must not deviate from current price "
                        "by more than ±30% (main board) or ±40% (ChiNext/STAR)."
                    ),
                    (
                        "- **Change% description must match data**: never describe positive gains as "
                        "drops, or small fluctuations as limit-up/limit-down."
                    ),
                    "- If data is unavailable, clearly tell the user '该数据暂不可用' — never fabricate.",
                ]
            )

        # --- Reply conventions (all types) ---
        parts.extend(
            [
                "",
                "## Reply Conventions",
                "- Reply in Chinese",
                "- Lead with conclusion, then give reasoning",
                "- Every action recommendation must include a risk warning",
                "- Do not use quant jargon (RSI/MACD/Sharpe) — use plain language alternatives",
                "- Never say '一定涨' or '一定赚' (guaranteed gain)",
            ]
        )
        if request_type in ("stock_analysis", "trade_decision"):
            parts.append(
                "- When recommending a buy, always include a stop-loss level "
                "(express as '如果跌到 XX 元建议卖出')"
            )

        # --- Tool usage instructions (tiered by request type) ---
        if request_type == "stock_analysis":
            parts.extend(
                [
                    "",
                    "## Tool Usage (strictly enforce, do not skip)",
                    "",
                    "**Preferred tool for stock analysis is deep_analyze.**",
                    "",
                    (
                        "⚠️ **First reply: output tool_call tags ONLY — no analysis text.** "
                        "Write analysis only after tool_results come back."
                    ),
                    "",
                    "**Primary path (recommended):**",
                    (
                        "Step 1: Call deep_analyze(symbol=...) — single call that returns a full "
                        "15+ dimension snapshot (quotes, capital flow, intel, quant signals, "
                        "VWAP/VPIN, multi-timeframe, reflexivity, sentiment cycle, portfolio, "
                        "risk, macro, geopolitical, thesis) plus a structured investment decision. "
                        "The returned snapshot_text contains all data you need."
                    ),
                    (
                        "Step 2: Write analysis based on the complete data from deep_analyze. "
                        "If you need the latest breaking news, supplement with search_intel or web_search."
                    ),
                    "",
                    "**Fallback path (only when deep_analyze is unavailable):**",
                    "Step 1: Call get_realtime_quote for real-time quotes",
                    "Step 2: Call search_intel(symbol=...) for local intelligence",
                    "Step 3: Call get_fund_flow for capital flow data",
                    "Step 4: Analyze based on **real data** from tool results",
                    "",
                    (
                        "⚠️ **Never write news-based analysis without first calling "
                        "search_intel and/or web_search.** "
                        "Your training data news is outdated — you must use tools for current info."
                    ),
                    "",
                    (
                        "- Do not retry search_intel more than 2 times if empty. "
                        "web_search is only for searching latest news, announcements, reports — "
                        "NOT for market data. "
                        "⚠️ Never use web_search for stock prices, volume, change%, capital flow "
                        "— market data must come from deep_analyze/get_realtime_quote system tools."
                    ),
                ]
            )
        elif request_type == "trade_decision":
            parts.extend(
                [
                    "",
                    "## Tool Usage",
                    (
                        "- **Preferred**: Call deep_analyze(symbol=...) for full snapshot + "
                        "structured decision (includes portfolio, risk gates, Bayesian posterior, "
                        "convergence score, and all context needed for a trade decision)"
                    ),
                    "- If you need to verify holding details: call get_portfolio",
                    "- If you need breaking news: call search_intel",
                    (
                        "⚠️ **First reply: output tool_calls only, no analysis.** "
                        "Write analysis after tool_results."
                    ),
                    "",
                    "## Debate Trigger Rule",
                    (
                        "When your confidence is between 0.4-0.7, "
                        "you MUST call run_debate tool for bull/bear debate."
                    ),
                ]
            )
        elif request_type == "portfolio_review":
            parts.extend(
                [
                    "",
                    "## Tool Usage — 深度持仓分析",
                    "你必须对每个持仓做完整深度分析，不能只列数字：",
                    "",
                    "Step 1: 调用 get_portfolio 获取持仓列表",
                    "Step 2: 对每个持仓股调用 deep_analyze(symbol=...) 获取15+维度快照",
                    "  包括: 实时行情、资金流向、情报、量化信号、VWAP/VPIN、",
                    "  多时间框架、反身性、情绪周期、风险、宏观、论点状态",
                    "Step 3: 调用 get_intraday_fund_flow_timeline 查看每只股今日资金流向趋势",
                    "Step 4: 调用 get_active_theses 查看持仓论点是否仍然有效",
                    "",
                    "对每个持仓给出：",
                    "- 当前状况（价格、盈亏、今日表现）",
                    "- 资金面判断（主力在买还是在卖）",
                    "- 论点是否仍有效",
                    "- 操作建议：继续持有(理由+止损位) / 减仓(理由+手数) / 清仓(理由)",
                    "",
                    "最后给出整体组合评估：集中度、行业暴露、总风险",
                    "",
                    (
                        "⚠️ **First reply: output tool_calls only, no analysis.** "
                        "Write analysis after tool_results."
                    ),
                    "",
                    "## Debate Trigger Rule",
                    (
                        "When your confidence is between 0.4-0.7, "
                        "you MUST call run_debate tool for bull/bear debate."
                    ),
                ]
            )
        elif request_type == "market_overview":
            parts.extend(
                [
                    "",
                    "## Tool Usage",
                    "- Call get_market_overview for broad market data",
                    "- If needed, call get_global_markets for global markets",
                    (
                        "⚠️ **First reply: output tool_calls only, no analysis.** "
                        "Write analysis after tool_results."
                    ),
                ]
            )

        # --- Rich Card output (all types except general) ---
        if request_type != "general":
            parts.extend(
                [
                    "",
                    "## Rich Card Output",
                    "When analysis results suit structured display, append JSON tag at end of reply:",
                    '<!--RICH_CARDS:[{"type": "stock_analysis", "props": {...}}]-->',
                    "",
                    "Supported card types:",
                ]
            )
            if request_type in ("stock_analysis",):
                parts.extend(
                    [
                        "- stock_analysis: 个股分析结果",
                        (
                            "  props: title(可选,如'贵州茅台分析'), symbol, "
                            "signal(bullish/bearish/neutral), "
                            "confidence(0~1), summary(支持 Markdown，"
                            "完整分析内容写在这里), "
                            "dimensions(数组,每项含 key/label/signal/score/reasoning), "
                            "risk_warnings(字符串数组)"
                        ),
                    ]
                )
            if request_type in ("stock_analysis", "trade_decision"):
                parts.append(
                    "- trade_decision: 交易建议（含 action, shares, price, "
                    "reasoning, risks, confidence, key_metrics, dimensions）"
                )
            if request_type in ("market_overview", "stock_analysis"):
                parts.extend(
                    [
                        "- market_overview: 市场概览",
                        (
                            "  props: title(如'市场简报'), "
                            "signal(bullish/bearish/neutral), "
                            "confidence(0~1), summary(支持 Markdown，"
                            "将完整市场分析写在 summary 中，"
                            "可以使用标题/列表/加粗等格式), "
                            "dimensions(可选), risk_warnings(可选)"
                        ),
                    ]
                )
            if request_type in ("portfolio_review", "stock_analysis"):
                parts.extend(
                    [
                        "- portfolio_summary: 持仓概览",
                        (
                            "  props: title(如'持仓诊断'), signal, confidence, "
                            "summary(支持 Markdown), "
                            "dimensions(可选), risk_warnings(可选)"
                        ),
                    ]
                )
            parts.extend(
                [
                    "",
                    (
                        "**Important**: stock_analysis/market_overview/portfolio_summary "
                        "summary fields support full Markdown. "
                        "Write all detailed analysis in summary — don't truncate. "
                        "Use ## headings, - lists, **bold** formatting."
                    ),
                ]
            )

        # --- Trade decision output spec (stock_analysis + trade_decision) ---
        if request_type in ("stock_analysis", "trade_decision"):
            parts.extend(
                [
                    "",
                    "## Trade Decision Output Spec",
                    (
                        "When recommending buy/sell on a specific stock, "
                        "you **must** output a trade_decision Rich Card:"
                    ),
                    (
                        "- Must first call get_realtime_quote for latest price — "
                        "price field **must use tool-returned real-time price**, never fabricate"
                    ),
                    "- shares must be a multiple of 100",
                    (
                        "- **On buy**: shares × price **must not exceed** user's available capital "
                        "(see user capital config). "
                        "If capital is insufficient for 100 shares, don't output trade_decision — "
                        "explain insufficient funds in text"
                    ),
                    (
                        "- **On sell**: must first call get_portfolio to confirm holdings — "
                        "shares **must not exceed** user's actual holding quantity. "
                        "If not held, don't recommend selling"
                    ),
                    "- Must include stop_loss (must be < price, i.e. below current price)",
                    "- Must include risks (at least 1 risk warning)",
                    "- Must include reasoning (trade rationale)",
                    "- Must include confidence (float 0-1)",
                    (
                        "- Recommended: key_metrics array, each with label, value, "
                        "signal(bullish/bearish/neutral)"
                    ),
                    (
                        "- Recommended: dimensions array, each with label (e.g. '技术面'), "
                        "signal(bullish/bearish/neutral), score(0-1)"
                    ),
                    "",
                    "## Consistency Rule (CRITICAL)",
                    (
                        "- If your analysis concludes HOLD or WATCH, do **NOT** output a "
                        "trade_decision card — only describe your view in text"
                    ),
                    (
                        "- If you output both stock_analysis and trade_decision cards for the "
                        "same stock, the trade_decision action **MUST** be consistent with "
                        "the stock_analysis recommendation. Never recommend SELL in "
                        "trade_decision when your analysis says HOLD/BUY, or vice versa"
                    ),
                    (
                        "- Only output trade_decision for actionable signals: BUY, ADD, "
                        "REDUCE, or SELL — never for HOLD or WATCH"
                    ),
                    "",
                    "示例：",
                    (
                        '<!--RICH_CARDS:[{"type":"trade_decision",'
                        '"props":{"symbol":"600519",'
                        '"stock_name":"贵州茅台","action":"buy",'
                        '"shares":100,"price":1680.5,'
                        '"reasoning":"...","stop_loss":1600,"risks":["..."],'
                        '"confidence":0.72,'
                        '"key_metrics":[{"label":"5日涨幅",'
                        '"value":"+3.2%","signal":"bullish"},'
                        '{"label":"主力资金",'
                        '"value":"净流入1.2亿","signal":"bullish"}],'
                        '"dimensions":[{"label":"技术面",'
                        '"signal":"bullish","score":0.75},'
                        '{"label":"资金面",'
                        '"signal":"bullish","score":0.68},'
                        '{"label":"消息面",'
                        '"signal":"neutral","score":0.5}]}}]-->'
                    ),
                ]
            )

        # --- Position management rules (stock_analysis + trade_decision) ---
        if request_type in ("stock_analysis", "trade_decision"):
            parts.extend(
                [
                    "",
                    "## Position Management Rules",
                    "- Single stock position should not exceed 20% of total capital",
                    "- risk_level=high: watch only or minimal position (<=5%)",
                    "- risk_level=medium: cautious entry (<=10%)",
                    "- risk_level=low: normal entry (<=15%)",
                    "- First entry: recommend scaling in (1/3 first, add after trend confirmation)",
                    "- Adding to profitable positions: max 50% of initial position size",
                ]
            )

        # --- Disclaimer (all types) ---
        parts.extend(
            [
                "",
                "## Disclaimer",
                (
                    "⚠ The above analysis is for research and learning purposes only — "
                    "it does not constitute investment advice. Stock markets carry risk. "
                    "Make independent decisions based on your own risk tolerance."
                ),
            ]
        )

        # Inject market session / holiday awareness
        market_hints = self._build_market_session_hints()
        if market_hints:
            parts.append("")
            parts.append("## Current Market Status")
            parts.append(market_hints)

        # Inject user capital and risk preference
        capital_hints = self._build_capital_hints()
        if capital_hints:
            parts.append("")
            parts.append("## User Capital Configuration")
            parts.append(capital_hints)

        # Inject context-specific hints from ThreadContext
        context = self._get_thread_context(thread_id)
        if context:
            context_hints = self._build_context_hints(context)
            if context_hints:
                parts.append("")
                parts.append("## Current Context")
                parts.append(context_hints)

        # Inject selected intel items
        intel_hints = self._build_intel_hints(thread_id)
        if intel_hints:
            parts.append("")
            parts.append("## User-Selected Intelligence")
            parts.append(intel_hints)

        # Auto-inject stock-related intel from intelligence hub
        stock_intel = self._build_stock_intel_context(
            user_message, thread_id, intel_hints
        )
        if stock_intel:
            parts.append("")
            parts.append("## Related Stock Intelligence (auto-retrieved)")
            parts.append(stock_intel)

        # Inject user trading behavior personality (v12.0 Phase 4)
        personality_hints = self._build_personality_hints()
        if personality_hints:
            parts.append("")
            parts.append("## User Trading Behavior Profile")
            parts.append(personality_hints)

        # Inject historical accuracy from model monitor (v18.0)
        accuracy_hints = self._build_accuracy_hints()
        if accuracy_hints:
            parts.append("")
            parts.append("## Historical Prediction Accuracy")
            parts.append(accuracy_hints)

        # Inject relevant memories (v18.0)
        memory_hints = self._build_memory_hints(thread_id)
        if memory_hints:
            parts.append("")
            parts.append("## Related Experience")
            parts.append(memory_hints)

        # Inject portfolio context + sentiment phase (v50.0 AI PM mandate)
        portfolio_ctx = self._build_portfolio_context_hints()
        if portfolio_ctx:
            parts.append("")
            parts.append("## Current Portfolio Status")
            parts.append(portfolio_ctx)

        # Inject real-time stock data for mentioned symbols (prevent hallucination)
        stock_data = self._build_realtime_stock_data(user_message)
        if stock_data:
            parts.append("")
            parts.append(
                "## Real-Time Market Data (auto-retrieved, use ONLY these numbers)"
            )
            parts.append(stock_data)

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Request classification for prompt tiering
    # ------------------------------------------------------------------

    _RE_STOCK_ANALYSIS = re.compile(r"\d{6}|[A-Za-z]股|分析|研究")
    _RE_TRADE_DECISION = re.compile(r"该不该买|要不要卖|建议|操作|加仓|减仓|止损")
    _RE_PORTFOLIO_REVIEW = re.compile(r"持仓|仓位|账户|资金|盈亏")
    _RE_MARKET_OVERVIEW = re.compile(r"大盘|市场|行情|今天|指数")

    @staticmethod
    def _classify_request(user_message: str) -> str:
        """Classify user message into a request type for prompt tiering.

        Returns one of: stock_analysis, trade_decision, portfolio_review,
        market_overview, general.

        Priority order matters — a message mentioning both a stock code and
        "该不该买" is classified as trade_decision (actionable trumps
        analytical).
        """
        if not user_message:
            return "general"
        msg = user_message.strip()
        # trade_decision checked first — actionable intent takes priority
        if AgentService._RE_TRADE_DECISION.search(msg):
            return "trade_decision"
        if AgentService._RE_STOCK_ANALYSIS.search(msg):
            return "stock_analysis"
        if AgentService._RE_PORTFOLIO_REVIEW.search(msg):
            return "portfolio_review"
        if AgentService._RE_MARKET_OVERVIEW.search(msg):
            return "market_overview"
        return "general"

    # ------------------------------------------------------------------
    # Sentiment cycle context
    # ------------------------------------------------------------------

    _SENTIMENT_GUIDANCE: dict[str, str] = {
        "freezing": ("极度谨慎，以观望为主。只在极端低估时小仓位试探，保持80%现金"),
        "ignition": ("开始关注，寻找先导板块的龙头。可小仓位参与确定性强的机会"),
        "acceleration": ("积极参与，跟随主流方向。重点关注量价配合、板块轮动的龙头"),
        "climax": ("注意风险，开始减仓。赚钱效应达到顶峰，但也是最危险的时候"),
        "ebb": ("全面防守，清仓为主。亏钱效应扩散，等待下一个冰点"),
    }

    def _build_sentiment_cycle_hints(self) -> str:
        """Build sentiment cycle context for the system prompt.

        Tries three sources in order:
        1. PortfolioStore latest snapshot (cached by trading loop)
        2. Direct SentimentCycleDetector with fresh signals
        3. Falls back to "未知" if unavailable
        """
        phase_en: str | None = None
        phase_cn: str | None = None
        confidence: float | None = None

        # Source 1: portfolio snapshot (most common path — cached data)
        try:
            from src.web.services.portfolio_store import PortfolioStore

            store = PortfolioStore()
            latest = store.get_latest_snapshot()
            if latest and latest.get("sentiment_phase"):
                phase_en = latest["sentiment_phase"]
                phase_cn = latest.get("sentiment_phase_cn")
                confidence = latest.get("sentiment_confidence")
        except Exception:
            pass

        # If we have a phase, build the hint
        if phase_en:
            if not phase_cn:
                from src.agent_loop.sentiment_cycle import _PHASE_CN

                phase_cn = _PHASE_CN.get(phase_en, phase_en)
            conf_str = f"{confidence:.0%}" if confidence is not None else "未知"
            guidance = self._SENTIMENT_GUIDANCE.get(phase_en, "")
            lines = [
                "## 当前市场情绪周期",
                f"- 阶段：{phase_cn}（{phase_en}）",
                f"- 置信度：{conf_str}",
            ]
            if guidance:
                lines.append(f"- 操作指导：{guidance}")
            return "\n".join(lines)

        # No data available
        return ""

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

    def _build_portfolio_context_hints(self) -> str:
        """Build portfolio + sentiment context for AI PM system prompt.

        Uses PortfolioStore (ground truth) + RealtimeQuoteManager for live prices.
        """
        lines: list[str] = []

        # Portfolio from PortfolioStore (ground truth, same as InvestorAgent)
        try:
            from src.web.dependencies import (
                get_portfolio_store,
                get_realtime_quote_manager,
            )

            ps = get_portfolio_store()
            positions = ps.list_positions()
            holdings = [p for p in positions if int(p.get("shares", 0)) > 0]

            if holdings:
                # Get live quotes
                symbols = [p["symbol"] for p in holdings if p.get("symbol")]
                live_quotes = {}
                try:
                    rqm = get_realtime_quote_manager()
                    if rqm and symbols:
                        df = rqm.get_quotes(symbols)
                        if hasattr(df, "iterrows"):
                            for _, row in df.iterrows():
                                live_quotes[str(row.get("symbol", ""))] = {
                                    "price": row.get("price"),
                                    "pct_change": row.get("pct_change"),
                                }
                except Exception:
                    pass

                lines.append(f"持仓 {len(holdings)} 只：")
                for p in holdings:
                    sym = p.get("symbol", "?")
                    name = p.get("name", sym)
                    shares = int(p.get("shares", 0))
                    cost = float(p.get("cost_price", 0))
                    today_bought = int(p.get("today_bought", 0))
                    available = shares - today_bought

                    q = live_quotes.get(sym, {})
                    price = q.get("price")
                    pct = q.get("pct_change")

                    line = f"  - {name}({sym}): {shares}股, 成本{cost:.3f}元"
                    if price:
                        pnl_pct = (float(price) - cost) / cost * 100 if cost > 0 else 0
                        pnl_val = (float(price) - cost) * shares
                        line += (
                            f", 现价{price}元, 浮盈亏{pnl_val:+,.0f}元({pnl_pct:+.1f}%)"
                        )
                    if pct is not None:
                        line += f", 今日{float(pct):+.2f}%"
                    line += f", 可卖{available}股"
                    if today_bought > 0:
                        line += f" (今买{today_bought}股T+1)"
                    lines.append(line)
            else:
                lines.append("当前空仓。")
        except Exception:
            # Fallback to trade_service if PortfolioStore unavailable
            if self._trade_service:
                try:
                    positions = self._trade_service.get_positions()
                    if positions:
                        lines.append(f"持仓 {len(positions)} 只：")
                        for p in positions[:8]:
                            sym = p.get("symbol", "?")
                            name = p.get("name", "?")
                            pnl = p.get("pnl_pct", 0)
                            val = p.get("market_value", 0)
                            lines.append(
                                f"  - {name}({sym}) 市值¥{val:,.0f} 盈亏{pnl:+.1%}"
                            )
                    else:
                        lines.append("当前空仓。")
                except Exception:
                    pass

        # Cash + regime from capital service
        if self._capital_service:
            try:
                bd = self._capital_service.get_breakdown()
                if bd.has_initial_deposit:
                    lines.append(f"可用现金: ¥{bd.available_cash:,.2f}")
                    lines.append(f"总资产: ¥{bd.total_assets:,.2f}")
            except Exception:
                pass

        # Sentiment phase if available via trading loop state
        try:
            from src.web.services.portfolio_store import PortfolioStore

            store = PortfolioStore()
            latest = store.get_latest_snapshot()
            if latest and latest.get("sentiment_phase"):
                phase = latest["sentiment_phase"]
                lines.append(f"情绪周期: {phase}")
        except Exception:
            pass

        return "\n".join(lines)

    def _build_realtime_stock_data(self, user_message: str) -> str:
        """Inject real-time stock data for symbols mentioned in user message.

        Prevents LLM hallucination by providing ground-truth market data
        directly in the prompt. The LLM should use ONLY these numbers.
        """
        # Extract 6-digit stock codes from user message
        import re as _re

        codes = _re.findall(r"\b[036]\d{5}\b", user_message)

        # Also include portfolio holdings
        try:
            from src.web.dependencies import get_portfolio_store

            ps = get_portfolio_store()
            for p in ps.list_positions():
                if int(p.get("shares", 0)) > 0:
                    sym = p.get("symbol", "")
                    if sym and sym not in codes:
                        codes.append(sym)
        except Exception:
            pass

        if not codes:
            return ""

        lines: list[str] = []
        try:
            from src.web.dependencies import get_realtime_quote_manager

            rqm = get_realtime_quote_manager()
            if not rqm:
                return ""

            df = rqm.get_quotes(codes[:5])
            if not hasattr(df, "iterrows") or df.empty:
                return ""

            for _, row in df.iterrows():
                sym = str(row.get("symbol", ""))
                name = str(row.get("name", sym))
                price = row.get("price")
                pct = row.get("pct_change")
                vol = row.get("volume")
                amt = row.get("amount")
                high = row.get("high")
                low = row.get("low")
                prev = row.get("prev_close")

                lines.append(f"### {name}({sym})")
                if price:
                    lines.append(f"- 最新价: {price}元")
                if pct is not None:
                    lines.append(f"- 涨跌幅: {float(pct):+.2f}%")
                if prev:
                    lines.append(f"- 昨收: {prev}元")
                if high and low:
                    lines.append(f"- 今日区间: {low}-{high}元")
                if vol:
                    vol_wan = float(vol) / 10000
                    lines.append(f"- 成交量: {vol_wan:,.0f}万股")
                if amt:
                    amt_yi = float(amt) / 100000000
                    lines.append(f"- 成交额: {amt_yi:.2f}亿元")
                lines.append("")

            if lines:
                lines.insert(
                    0,
                    "以下数据来自实时行情系统，是准确的。"
                    "请严格使用这些数据，不要使用任何其他来源的数字。\n",
                )

        except Exception:
            pass

        return "\n".join(lines)

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
            "如果以上情报不足以支撑消息面分析，请调用 web_search 联网搜索补充（仅限新闻/公告，严禁搜索行情价格）。"
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
                f"如果情报不足再调用 web_search 联网搜索 {symbol} 最新新闻（严禁搜索行情价格）。"
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
    # Text-based tool_use helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_tool_instruction(tool_definitions: list[dict[str, Any]]) -> str:
        """Build a text-based tool instruction block for the system prompt."""
        lines = [
            "## Available Tools",
            "",
            (
                "You have access to the following tools. To call a tool, output a "
                "JSON block wrapped in <tool_call> tags:"
            ),
            "",
            "```",
            '<tool_call>{"name": "tool_name", "input": {"param": "value"}}</tool_call>',
            "```",
            "",
            (
                "You may call multiple DIFFERENT tools in a single response. "
                "NEVER repeat the same tool call — each tool_call must be unique. "
                "After all tool results are returned, provide your final answer "
                "WITHOUT any tool_call tags."
            ),
            "",
            "### Tool Definitions",
            "",
        ]
        for tool in tool_definitions:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            schema = tool.get("input_schema", {})
            lines.append(f"**{name}**: {desc}")
            if schema.get("properties"):
                params = ", ".join(
                    f"`{k}` ({v.get('type', 'any')})"
                    for k, v in schema["properties"].items()
                )
                lines.append(f"  Parameters: {params}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _parse_tool_calls_from_text(text: str) -> list[dict[str, Any]]:
        """Parse <tool_call> blocks from LLM text output.

        Deduplicates identical tool calls — Gemini Web sometimes repeats
        the same ``<tool_call>`` block many times in a single response.
        """
        pattern = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
        calls: list[dict[str, Any]] = []
        seen: set[str] = set()
        for match in pattern.finditer(text):
            try:
                raw = match.group(1).strip()
                data = json.loads(raw)
                if "name" not in data:
                    continue
                # Deduplicate by (name, sorted input)
                dedup_key = json.dumps(
                    {"name": data["name"], "input": data.get("input", {})},
                    sort_keys=True,
                )
                if dedup_key in seen:
                    logger.debug("Skipping duplicate tool_call: %s", data["name"])
                    continue
                seen.add(dedup_key)
                calls.append(data)
            except (json.JSONDecodeError, TypeError):
                logger.debug("Failed to parse tool_call: %s", match.group(1)[:100])
        return calls

    @staticmethod
    def _strip_tool_call_blocks(text: str) -> str:
        """Remove <tool_call> blocks from final response text."""
        return re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL).strip()

    # ------------------------------------------------------------------
    # Output validation — cross-check LLM text against tool data
    # ------------------------------------------------------------------

    # Regex patterns to extract prices from Chinese financial text
    _PRICE_YUAN_RE = re.compile(r"(\d+\.?\d*)\s*元")
    _PRICE_CURRENT_RE = re.compile(r"当前(?:股价|价格)[\s:：]*(\d+\.?\d*)")
    _PRICE_CLOSE_RE = re.compile(r"收盘价[\s:：]*(\d+\.?\d*)")

    def _validate_output(
        self,
        text: str,
        tool_results: list[dict[str, Any]],
    ) -> str:
        """Cross-validate LLM output prices against real tool data.

        Compares price mentions in the LLM's text with actual data returned
        by tools like ``get_realtime_quote``, ``get_portfolio``, and
        ``get_capital_balance``.  If a price differs by more than 5%, a
        warning is appended to the text so the user sees the real number.

        This is best-effort: parsing failures are silently ignored.
        """
        if not text or not tool_results:
            return text

        # Step 1: Extract real prices from tool results
        real_prices: dict[str, float] = {}  # symbol -> price
        for entry in tool_results:
            try:
                tool_name = entry.get("tool_name", "")
                result_raw = entry.get("result", "")
                if not result_raw:
                    continue

                data = (
                    json.loads(result_raw)
                    if isinstance(result_raw, str)
                    else result_raw
                )

                if tool_name == "get_realtime_quote":
                    # May be a single dict or list of dicts
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        symbol = item.get("symbol") or item.get("code", "")
                        price = item.get("price") or item.get("current_price")
                        if symbol and price is not None:
                            try:
                                real_prices[str(symbol)] = float(price)
                            except (ValueError, TypeError):
                                pass

                elif tool_name in ("get_portfolio", "get_capital_balance"):
                    # Portfolio may contain positions with current prices
                    positions = []
                    if isinstance(data, dict):
                        positions = data.get("positions", data.get("holdings", []))
                    elif isinstance(data, list):
                        positions = data
                    for pos in positions:
                        if not isinstance(pos, dict):
                            continue
                        symbol = pos.get("symbol") or pos.get("code", "")
                        price = (
                            pos.get("current_price")
                            or pos.get("price")
                            or pos.get("last_price")
                        )
                        if symbol and price is not None:
                            try:
                                real_prices[str(symbol)] = float(price)
                            except (ValueError, TypeError):
                                pass

            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

        if not real_prices:
            return text

        # Step 2: Extract prices mentioned in LLM text
        llm_prices: list[float] = []
        for pattern in (
            self._PRICE_YUAN_RE,
            self._PRICE_CURRENT_RE,
            self._PRICE_CLOSE_RE,
        ):
            for m in pattern.finditer(text):
                try:
                    llm_prices.append(float(m.group(1)))
                except (ValueError, IndexError):
                    pass

        if not llm_prices:
            return text

        # Step 3: Cross-validate — for each real price, check if at least
        # one LLM-mentioned price matches.  If ANY price in the text is close
        # to the real price, the LLM is using correct data — other numbers
        # are likely indicators/targets/stops, not the current price.
        warnings: list[str] = []
        for symbol, real_price in real_prices.items():
            if real_price <= 0:
                continue
            has_match = any(
                abs(p - real_price) / real_price <= 0.05 for p in llm_prices if p > 0
            )
            if has_match:
                continue  # LLM correctly cited the real price somewhere

            # No matching price found — LLM may be using stale/fabricated data
            # Find the closest LLM price to report
            closest = min(
                (
                    p
                    for p in llm_prices
                    if p > 0 and 0.1 * real_price <= p <= 10 * real_price
                ),
                key=lambda p: abs(p - real_price),
                default=None,
            )
            if closest is not None:
                deviation = abs(closest - real_price) / real_price
                warning = (
                    f"\n\n⚠️ 数据校验提醒：工具返回 {symbol} "
                    f"价格为 {real_price} 元，请以此为准。"
                )
                if warning not in warnings:
                    warnings.append(warning)
                    logger.warning(
                        "Output validation mismatch: symbol=%s "
                        "real=%.2f llm_closest=%.2f deviation=%.1f%%",
                        symbol,
                        real_price,
                        closest,
                        deviation * 100,
                    )

        if warnings:
            text += "".join(warnings)

        return text

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
            cards = [
                RichCard(type=c.get("type", "unknown"), props=c.get("props", {}))
                for c in cards_data
                if isinstance(c, dict)
            ]
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse rich cards from agent reply")
            return []

        return self._resolve_card_conflicts(cards)

    @staticmethod
    def _resolve_card_conflicts(cards: list[RichCard]) -> list[RichCard]:
        """Remove trade_decision cards that conflict with stock_analysis cards.

        When both card types exist for the same symbol, the stock_analysis
        action is authoritative.  A trade_decision is dropped if:
        - The stock_analysis recommends hold/watch (no actionable signal), or
        - The trade_decision direction contradicts the stock_analysis
          (e.g. analysis says hold but decision says sell).
        """
        # Build a map of stock_analysis actions by symbol
        analysis_actions: dict[str, str] = {}
        for card in cards:
            if card.type == "stock_analysis":
                sym = card.props.get("symbol")
                action = card.props.get("action", "")
                if sym and action:
                    analysis_actions[sym] = action.lower()

        if not analysis_actions:
            return cards

        _HOLD_ACTIONS = {"hold", "watch"}
        _BUY_ACTIONS = {"buy", "add"}
        _SELL_ACTIONS = {"sell", "reduce"}

        filtered: list[RichCard] = []
        for card in cards:
            if card.type == "trade_decision":
                sym = card.props.get("symbol")
                analysis_action = analysis_actions.get(sym)
                if analysis_action:
                    decision_action = card.props.get("action", "").lower()
                    # Drop if analysis says hold/watch
                    if analysis_action in _HOLD_ACTIONS:
                        logger.info(
                            "Dropping trade_decision for %s: analysis=%s, "
                            "decision=%s (hold/watch → no actionable card)",
                            sym,
                            analysis_action,
                            decision_action,
                        )
                        continue
                    # Drop if directions conflict
                    if (
                        analysis_action in _BUY_ACTIONS
                        and decision_action in _SELL_ACTIONS
                    ) or (
                        analysis_action in _SELL_ACTIONS
                        and decision_action in _BUY_ACTIONS
                    ):
                        logger.warning(
                            "Dropping conflicting trade_decision for %s: "
                            "analysis=%s but decision=%s",
                            sym,
                            analysis_action,
                            decision_action,
                        )
                        continue
            filtered.append(card)
        return filtered

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
                    created_at TEXT NOT NULL,
                    gate_request_id TEXT
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

                CREATE TABLE IF NOT EXISTS decision_journal (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    symbol TEXT,
                    action TEXT,
                    confidence REAL,
                    trigger_event TEXT,
                    data_sources TEXT,
                    key_evidence TEXT,
                    sentiment_phase TEXT,
                    portfolio_context TEXT,
                    entry_price REAL,
                    stop_loss REAL,
                    target_price REAL,
                    outcome_t1 REAL,
                    outcome_t3 REAL,
                    outcome_t5 REAL,
                    outcome_status TEXT DEFAULT 'pending'
                );

                CREATE INDEX IF NOT EXISTS idx_journal_symbol
                    ON decision_journal(symbol);
                CREATE INDEX IF NOT EXISTS idx_journal_timestamp
                    ON decision_journal(timestamp);
                CREATE INDEX IF NOT EXISTS idx_journal_status
                    ON decision_journal(outcome_status);
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
            # I-107: background processing status
            if "processing_status" not in thread_cols:
                conn.execute(
                    "ALTER TABLE threads ADD COLUMN processing_status TEXT DEFAULT 'ready'"
                )

            # I-105: add gate_request_id to trades if missing
            try:
                conn.execute("ALTER TABLE trades ADD COLUMN gate_request_id TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists

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
            # Ensure thread exists before inserting message (FK constraint)
            exists = conn.execute(
                "SELECT 1 FROM threads WHERE id = ?", (thread_id,)
            ).fetchone()
            if not exists:
                logger.warning(
                    "Thread %s not found for message save — creating stub",
                    thread_id,
                )
                now = msg.timestamp or _now_iso()
                conn.execute(
                    "INSERT OR IGNORE INTO threads "
                    "(id, title, context, created_at, updated_at) "
                    "VALUES (?, ?, NULL, ?, ?)",
                    (thread_id, "(auto-created)", now, now),
                )

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

            # Execute tools concurrently (I-107 fix)
            call_tuples = [(tc.name, tc.input) for tc in llm_resp.tool_calls]
            batch_start = time.perf_counter()
            result_strs = await self._tools.execute_parallel(call_tuples)
            batch_elapsed = time.perf_counter() - batch_start

            tool_results: list[dict[str, Any]] = []
            for tc, result_str in zip(llm_resp.tool_calls, result_strs):
                elapsed = (batch_elapsed / max(len(result_strs), 1)) * 1000
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

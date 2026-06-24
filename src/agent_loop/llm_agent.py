"""Provider-agnostic LLM Agent Loop.

Implements the universal agent pattern from learn-claude-code:

    while True:
        response = LLM(messages, tools)
        if response.stop_reason != "tool_use":
            return response
        execute_tools(response.tool_calls)
        append_results_to_messages()

Works with ANY provider that implements ``complete_with_tools()``
(OpenAI, DeepSeek, Anthropic, Google). The model decides when/how
to use tools; the harness executes and feeds results back.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from src.llm.base import (
    LLMMessage,
    LLMProviderError,
    LLMToolResponse,
    ProviderName,
    ToolCall,
)
from src.utils.logger import get_logger

logger = get_logger("agent_loop.llm_agent")

_DEFAULT_MAX_TURNS = 10


@dataclass
class AgentResult:
    """Final result of an agent loop execution.

    Attributes:
        text: Final text response from the model.
        tool_calls_made: Total number of tool calls executed.
        turns: Number of LLM round-trips.
        total_input_tokens: Cumulative input tokens across all turns.
        total_output_tokens: Cumulative output tokens across all turns.
        total_cost_usd: Cumulative estimated cost.
        total_latency_ms: Cumulative LLM latency (excludes tool execution).
        provider: Which provider handled the final turn.
        model: Which model handled the final turn.
        tool_history: List of (tool_name, tool_input, tool_result) tuples.
    """

    text: str | None = None
    tool_calls_made: int = 0
    turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    provider: ProviderName | None = None
    model: str | None = None
    tool_history: list[tuple[str, dict, str]] = field(default_factory=list)


class AgentLoop:
    """Provider-agnostic agent loop with tool execution.

    The loop runs until the model returns ``stop_reason != "tool_use"``
    or ``max_turns`` is reached. Compatible with any LLM provider that
    implements ``complete_with_tools()``.

    Args:
        gateway: LLMGateway or LLMRouter instance (must have
            ``complete_with_tools()``).
        tool_executor: Async callable ``(name, input) -> str`` that
            executes a tool and returns JSON result. Typically
            ``ToolRegistry.execute``.
        tool_definitions: Anthropic-format tool schemas. If None,
            no tools are passed to the LLM.
        max_turns: Maximum LLM round-trips before forced stop.
    """

    def __init__(
        self,
        gateway: Any,
        tool_executor: Any | None = None,
        tool_definitions: list[dict[str, Any]] | None = None,
        max_turns: int = _DEFAULT_MAX_TURNS,
        max_cost_usd: float = 0.15,
        max_tool_result_chars: int = 6000,
    ) -> None:
        self._gateway = gateway
        self._tool_executor = tool_executor
        self._tool_definitions = tool_definitions or []
        self._max_turns = max_turns
        self._max_cost_usd = max_cost_usd
        self._max_tool_result_chars = max_tool_result_chars

    async def run(
        self,
        messages: list[LLMMessage],
        *,
        caller: str = "agent_loop",
        model: str | None = None,
        preferred_provider: ProviderName | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        symbol: str = "",
    ) -> AgentResult:
        """Execute the agent loop until completion or max turns.

        Args:
            messages: Initial conversation messages.
            caller: Attribution string for gateway routing.
            model: Model override.
            preferred_provider: Force a specific provider.
            max_tokens: Max output tokens per turn.
            temperature: Sampling temperature.
            symbol: Stock symbol for usage tracking.

        Returns:
            AgentResult with final text, metrics, and tool history.
        """
        result = AgentResult()
        # Work on a copy so caller's list is not mutated
        conversation = list(messages)

        for turn in range(1, self._max_turns + 1):
            result.turns = turn

            try:
                response: LLMToolResponse = self._gateway.complete_with_tools(
                    messages=conversation,
                    tools=self._tool_definitions,
                    caller=caller,
                    preferred_provider=preferred_provider,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    symbol=symbol,
                )
            except LLMProviderError as exc:
                logger.error("Agent loop LLM call failed on turn %d: %s", turn, exc)
                result.text = f"[Agent error: {exc}]"
                break

            # Accumulate metrics
            result.total_input_tokens += response.input_tokens
            result.total_output_tokens += response.output_tokens
            result.total_cost_usd += response.cost_usd
            result.total_latency_ms += response.latency_ms
            result.provider = response.provider
            result.model = response.model

            # Cost guard — stop before exceeding budget
            if self._max_cost_usd and result.total_cost_usd >= self._max_cost_usd:
                result.text = response.text or "[Agent stopped: cost budget reached]"
                logger.warning(
                    "Agent loop hit cost cap ($%.4f >= $%.4f) at turn %d",
                    result.total_cost_usd,
                    self._max_cost_usd,
                    turn,
                )
                break

            # No tool calls → model is done
            if response.stop_reason != "tool_use" or not response.tool_calls:
                result.text = response.text
                logger.info(
                    "Agent loop completed: %d turns, %d tools, $%.4f",
                    turn,
                    result.tool_calls_made,
                    result.total_cost_usd,
                )
                break

            # Execute tool calls
            tool_results = await self._execute_tools(response.tool_calls, result)

            # Build multi-turn messages for next iteration
            # 1. Append assistant message with tool_use blocks.
            #    Use raw_assistant_content if available (preserves provider-specific
            #    metadata like Gemini's thought_signature in function_call parts).
            raw = getattr(response, "raw_assistant_content", None)
            if raw is not None:
                conversation.append(LLMMessage(role="assistant", content=raw))
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
                conversation.append(
                    LLMMessage(role="assistant", content=assistant_blocks)
                )

            # 2. Append tool results as user message
            result_blocks: list[dict[str, Any]] = []
            for tc, res in zip(response.tool_calls, tool_results):
                result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": res,
                    }
                )

                # Progressive disclosure: if load_tool_schema returned a schema,
                # inject it into tool_definitions so the agent can call it next turn.
                if tc.name == "load_tool_schema":
                    try:
                        loaded = json.loads(res) if isinstance(res, str) else res
                        if (
                            isinstance(loaded, dict)
                            and loaded.get("status") == "loaded"
                        ):
                            new_def = {
                                "name": loaded["tool_name"],
                                "description": loaded["description"],
                                "input_schema": loaded["input_schema"],
                            }
                            # Avoid duplicates
                            existing = {d["name"] for d in self._tool_definitions}
                            if new_def["name"] not in existing:
                                self._tool_definitions.append(new_def)
                                logger.info(
                                    "Dynamic tool loaded: %s (now %d tools)",
                                    new_def["name"],
                                    len(self._tool_definitions),
                                )
                    except Exception:
                        pass  # Non-critical, fail silently

            # Inject deadline warning on penultimate turn so the LLM
            # knows to decide instead of calling more tools
            if turn == self._max_turns - 1:
                result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": "system_deadline",
                        "content": (
                            "[系统提醒] 下一轮是最后一轮。"
                            "必须用 submit_buy_signal / submit_sell_signal / "
                            "submit_hold_update 表达决策，或者直接给出文字结论。"
                            "不要再调用其他工具。"
                        ),
                    }
                )

            conversation.append(LLMMessage(role="user", content=result_blocks))
        else:
            # max_turns exceeded
            logger.warning(
                "Agent loop hit max_turns (%d). Returning partial result.",
                self._max_turns,
            )
            result.text = result.text or "[Agent stopped: max turns reached]"

        return result

    async def _execute_tools(
        self, tool_calls: list[ToolCall], result: AgentResult
    ) -> list[str]:
        """Execute tool calls and return results.

        Runs tools concurrently when possible. The entire batch is wrapped
        in a 90s timeout to prevent a single slow tool from blocking the
        agent loop indefinitely.
        """
        if not self._tool_executor:
            return ['{"error": "No tool executor configured"}' for _ in tool_calls]

        results: list[str] = []
        tasks = []
        for tc in tool_calls:
            logger.info("Executing tool: %s(%s)", tc.name, tc.input)
            tasks.append(self._tool_executor(tc.name, tc.input))

        start = time.perf_counter()
        try:
            executed = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=90,
            )
        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                "Tool batch timed out after 90s (%d tools, %.0fms)",
                len(tool_calls),
                elapsed,
            )
            for tc in tool_calls:
                error_str = '{"error": "tool batch timed out (90s)"}'
                results.append(error_str)
                result.tool_history.append((tc.name, tc.input, error_str))
                result.tool_calls_made += 1
            return results

        elapsed = (time.perf_counter() - start) * 1000

        for tc, res in zip(tool_calls, executed):
            if isinstance(res, Exception):
                error_str = f'{{"error": "{res}"}}'
                results.append(error_str)
                result.tool_history.append((tc.name, tc.input, error_str))
                logger.warning("Tool %s failed: %s", tc.name, res)
            else:
                text = str(res)
                # Truncate large tool results to control context size
                if (
                    self._max_tool_result_chars
                    and len(text) > self._max_tool_result_chars
                ):
                    text = (
                        text[: self._max_tool_result_chars]
                        + f"\n[... truncated, {len(str(res))} chars total]"
                    )
                results.append(text)
                result.tool_history.append((tc.name, tc.input, text))

            result.tool_calls_made += 1

        logger.info(
            "Executed %d tools in %.0fms",
            len(tool_calls),
            elapsed,
        )
        return results

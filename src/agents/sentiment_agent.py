"""Sentiment agent — dedicated news/sentiment analysis specialist.

Separated from the research agent for context isolation (Rule 3).
Uses LLM to synthesize sentiment from news data.

Part of v18.0 Agent Spec Compliance — Phase 3.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.agents.base import AgentCapability, AgentMessage, BaseAgent
from src.llm.base import LLMMessage, LLMToolResponse
from src.utils.logger import get_logger

logger = get_logger("agents.sentiment")

_MAX_TOOL_ROUNDS = 4


class SentimentAgent(BaseAgent):
    """Sentiment analysis specialist — LLM-backed.

    Capabilities:
    - News aggregation
    - Sentiment scoring [-1, +1]
    - Key event impact assessment

    Forbidden: All trade, portfolio, risk tools.
    """

    def __init__(
        self,
        capability: AgentCapability,
        tool_registry: Any,
        llm_router: Any,
        system_role: str = "",
    ) -> None:
        super().__init__(capability)
        self._tools = tool_registry
        self._llm = llm_router
        self._system_role = system_role or (
            "You are a market sentiment analyst. Extract market sentiment from news "
            "and social media data, providing a quantified sentiment score (-1 to +1) "
            "and key event impact assessments. "
            "Remain objective and neutral — distinguish noise from truly impactful information. "
            "Write all output text in Chinese."
        )

    async def _execute_impl(self, message: AgentMessage) -> AgentMessage:
        """Run sentiment analysis using news tools and LLM synthesis."""
        start = time.perf_counter()

        system_prompt = self._build_prompt(message)
        tool_defs = self._tools.get_tool_definitions()

        llm_messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=message.task),
        ]

        tool_calls_count = 0
        total_tokens = 0
        final_text = ""

        for _round in range(_MAX_TOOL_ROUNDS):
            if not self._check_budget(message, 500):
                final_text = '{"sentiment_score": 0, "sentiment_signal": "neutral", "data_gaps": ["预算不足"]}'
                break

            response: LLMToolResponse = await asyncio.to_thread(
                self._llm.complete_with_tools,
                messages=llm_messages,
                tools=tool_defs,
                caller=f"agent.{self.name}",
                max_tokens=self._capability.max_tokens,
                temperature=self._capability.temperature,
                analysis_type="agent_sentiment",
            )

            total_tokens += response.input_tokens + response.output_tokens

            if response.stop_reason == "end_turn" or not response.tool_calls:
                final_text = response.text or ""
                break

            # Build assistant message
            if response.raw_assistant_content is not None:
                assistant_content = response.raw_assistant_content
            else:
                blocks: list[dict[str, Any]] = []
                if response.text:
                    blocks.append({"type": "text", "text": response.text})
                for tc in response.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.input,
                        }
                    )
                assistant_content = blocks

            llm_messages.append(LLMMessage(role="assistant", content=assistant_content))

            # Execute tools
            tool_results: list[dict[str, Any]] = []
            for tc in response.tool_calls:
                if not self._check_tool_permission(tc.name):
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "tool_name": tc.name,
                            "content": f'{{"error": "No permission for tool: {tc.name}"}}',
                        }
                    )
                    continue

                result_str = await self._tools.execute(tc.name, tc.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "tool_name": tc.name,
                        "content": result_str,
                    }
                )
                tool_calls_count += 1

            llm_messages.append(LLMMessage(role="user", content=tool_results))
        else:
            final_text = (
                response.text or '{"sentiment_score": 0, "sentiment_signal": "neutral"}'
            )

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "SentimentAgent: %d tool calls, %d tokens, %.0fms",
            tool_calls_count,
            total_tokens,
            elapsed,
        )

        return AgentMessage(
            from_agent=self.name,
            to_agent=message.from_agent,
            task=message.task,
            context=message.context,
            budget_remaining=message.budget_remaining - total_tokens,
            result=final_text,
            tool_calls_made=tool_calls_count,
            tokens_used=total_tokens,
            delegation_chain=[*message.delegation_chain, self.name],
        )

    def _build_prompt(self, message: AgentMessage) -> str:
        """Build sentiment-specific system prompt."""
        parts = [
            self._system_role,
            "",
            "## Output Format (JSON)",
            "- sentiment_score: float (-1 to +1)",
            "- sentiment_signal: 'bullish'/'neutral'/'bearish'",
            "- key_events: [{event, impact, source}]",
            "- confidence_score: float (0-1)",
            "- key_assumptions: [str]",
            "- failure_modes: [str]",
            "- data_gaps: [str]",
        ]
        symbol = message.context.get("symbol")
        if symbol:
            parts.append(f"\n## Analysis Target: {symbol}")
        return "\n".join(parts)

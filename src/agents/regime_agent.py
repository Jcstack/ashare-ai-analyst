"""Regime agent — market regime detection + macro analysis.

Detects current market regime, assesses macro conditions,
and evaluates global market correlations.

Part of v18.0 Agent Spec Compliance — Phase 3.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.agents.base import AgentCapability, AgentMessage, BaseAgent
from src.llm.base import LLMMessage, LLMToolResponse
from src.utils.logger import get_logger

logger = get_logger("agents.regime")

_MAX_TOOL_ROUNDS = 4


class RegimeAgent(BaseAgent):
    """Market regime & macro analysis specialist.

    Uses rule-based regime detection plus LLM for macro synthesis.

    Capabilities:
    - Regime detection (rule-based)
    - Global market snapshot
    - Holiday impact assessment
    - Cross-market correlation

    Forbidden: All trade tools.
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
            "You are a macro analyst. Determine the current market regime "
            "(bull/bear/sideways/transition), assess the macro environment's impact "
            "on A-shares including global market correlations and policy factors. "
            "Output structured regime determination and macro risk factors. "
            "Write all output text in Chinese."
        )

    async def _execute_impl(self, message: AgentMessage) -> AgentMessage:
        """Run regime detection and macro analysis."""
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
                final_text = '{"current_regime": "unknown", "regime_confidence": 0.3}'
                break

            response: LLMToolResponse = await asyncio.to_thread(
                self._llm.complete_with_tools,
                messages=llm_messages,
                tools=tool_defs,
                caller=f"agent.{self.name}",
                max_tokens=self._capability.max_tokens,
                temperature=self._capability.temperature,
                analysis_type="agent_regime",
            )

            total_tokens += response.input_tokens + response.output_tokens

            if response.stop_reason == "end_turn" or not response.tool_calls:
                final_text = response.text or ""
                break

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
            final_text = response.text or '{"current_regime": "unknown"}'

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "RegimeAgent: %d tool calls, %d tokens, %.0fms",
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
        """Build regime-specific system prompt."""
        parts = [
            self._system_role,
            "",
            "## Output Format (JSON)",
            "- current_regime: 'bull'/'bear'/'sideways'/'transition'",
            "- regime_confidence: float (0-1)",
            "- transition_matrix: {from_regime: {to_regime: probability}}",
            "- macro_risk_factors: [{factor, impact, probability}]",
            "- confidence_score: float (0-1)",
            "- key_assumptions: [str]",
            "- failure_modes: [str]",
            "- data_gaps: [str]",
        ]
        return "\n".join(parts)

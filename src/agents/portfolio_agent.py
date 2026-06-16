"""Portfolio Construction agent — optimal allocation specialist.

Suggests portfolio adjustments respecting risk budgets.
Suggests only — never executes trades.

Part of v18.0 Agent Spec Compliance — Phase 3.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.agents.base import AgentCapability, AgentMessage, BaseAgent
from src.llm.base import LLMMessage, LLMToolResponse
from src.utils.logger import get_logger

logger = get_logger("agents.portfolio")

_MAX_TOOL_ROUNDS = 4


class PortfolioAgent(BaseAgent):
    """Portfolio construction specialist — LLM-backed.

    Capabilities:
    - Portfolio position retrieval
    - Capital balance query
    - Position sizing
    - VaR calculation

    Forbidden: ``execute_trade``, ``record_manual_trade``
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
            "你是一位组合构建专家。基于风险预算、相关性和信号强度，"
            "建议最优仓位配置。你只建议，不执行任何交易。"
            "所有建议必须符合 A 股 100 股整数手限制和单仓位不超过 30% 的约束。"
        )

    async def _execute_impl(self, message: AgentMessage) -> AgentMessage:
        """Generate portfolio allocation recommendations."""
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
                final_text = '{"adjustments": [], "data_gaps": ["预算不足"]}'
                break

            response: LLMToolResponse = await asyncio.to_thread(
                self._llm.complete_with_tools,
                messages=llm_messages,
                tools=tool_defs,
                caller=f"agent.{self.name}",
                max_tokens=self._capability.max_tokens,
                temperature=self._capability.temperature,
                analysis_type="agent_portfolio",
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
            final_text = response.text or '{"adjustments": []}'

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "PortfolioAgent: %d tool calls, %d tokens, %.0fms",
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
        """Build portfolio-specific system prompt."""
        parts = [
            self._system_role,
            "",
            "## 输出规范（JSON格式）",
            "- adjustments: [{symbol, action, shares, weight, reasoning}]",
            "- suggested_shares: int",
            "- suggested_weight: float",
            "- concentration_warnings: [str]",
            "- confidence_score: float (0-1)",
            "- key_assumptions: [str]",
            "- failure_modes: [str]",
            "- data_gaps: [str]",
        ]
        symbol = message.context.get("symbol")
        if symbol:
            parts.append(f"\n## 目标股票: {symbol}")
        return "\n".join(parts)

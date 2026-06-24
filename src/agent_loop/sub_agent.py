"""Sub-agent isolation — spawn focused research agents with limited scope.

Analogous to Claude Code's Task tool: the main InvestorAgent can delegate
a deep research question to a sub-agent that gets its own tool subset,
fresh context window, and independent cost budget.

The sub-agent result is returned as a summary string to the parent.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Tools allowed for research sub-agents (data + analysis, no trading)
_RESEARCH_TOOL_ALLOWLIST = {
    "get_realtime_quote",
    "get_technical_indicators",
    "get_stock_concepts",
    "get_intraday_fund_flow_timeline",
    "get_intraday_patterns",
    "get_minute_bars",
    "get_dragon_tiger",
    "get_support_resistance",
    "search_stocks",
    "get_global_markets",
    "get_trending_news",
    "analyze_cross_market",
    "capital_flow_tool",
    "get_sentiment_report",
    "deep_analyze",
    "get_belief_state",
}


class SubAgentRunner:
    """Spawn isolated sub-agents for deep research tasks.

    The parent agent calls ``spawn_research_agent`` as a tool.
    This runner creates a fresh AgentLoop with:
    - Filtered tool definitions (data + analysis only, no trading)
    - Independent cost budget (default $0.03)
    - Fewer turns (default 5)
    - Fresh message context (no parent conversation leaking in)

    Returns a summarized result string to the parent.
    """

    def __init__(
        self,
        gateway: Any,
        tool_registry: Any,
        max_cost_usd: float = 0.05,
        max_turns: int = 5,
    ) -> None:
        self._gateway = gateway
        self._tool_registry = tool_registry
        self._max_cost_usd = max_cost_usd
        self._max_turns = max_turns

    async def run(
        self,
        task_description: str,
        symbol: str = "",
    ) -> str:
        """Run a sub-agent and return its response.

        Args:
            task_description: What to research (e.g. "分析600498龙虎榜机构行为").
            symbol: Optional stock code for context.

        Returns:
            Sub-agent's analysis result as a string.
        """
        from src.agent_loop.llm_agent import AgentLoop
        from src.llm.base import LLMMessage

        # Filter tools to research-only subset
        all_tools = self._tool_registry.get_tool_definitions()
        research_tools = [t for t in all_tools if t["name"] in _RESEARCH_TOOL_ALLOWLIST]

        if not research_tools:
            return "子Agent无可用工具"

        loop = AgentLoop(
            gateway=self._gateway,
            tool_executor=self._tool_registry.execute,
            tool_definitions=research_tools,
            max_turns=self._max_turns,
            max_cost_usd=self._max_cost_usd,
        )

        system = (
            "你是一个A股研究助理。你的任务是深入研究一个具体问题并给出结论。\n"
            "使用提供的工具获取数据，分析后给出简洁明确的结论。\n"
            "输出格式：结论 + 关键证据 + 风险提示。控制在500字以内。"
        )

        user = task_description
        if symbol:
            user = f"[研究标的: {symbol}]\n{task_description}"

        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]

        try:
            result = await loop.run(
                messages,
                caller="sub_agent.research",
                max_tokens=2048,
                temperature=0.3,
                symbol=symbol,
            )
            response = result.text or "子Agent未产出结论"
            logger.info(
                "Sub-agent completed: %d turns, $%.4f, %d chars",
                result.turns,
                result.total_cost_usd,
                len(response),
            )
            return response
        except Exception as exc:
            logger.warning("Sub-agent failed: %s", exc)
            return f"子Agent研究失败: {exc}"

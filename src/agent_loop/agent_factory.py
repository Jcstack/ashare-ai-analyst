"""Agent factory — creates configured AgentLoop instances.

Wires together the LLMGateway, ToolRegistry, and AgentLoop for
common trading scenarios. Each factory method returns a ready-to-run
AgentLoop with the appropriate tools and constraints.

Usage::

    from src.agent_loop.agent_factory import create_trading_agent

    agent = create_trading_agent(gateway, tool_registry)
    result = await agent.run(
        messages=[LLMMessage("user", "分析永泰能源的持仓风险")],
        caller="trading_advisor",
        symbol="600157",
    )
    print(result.text)
"""

from __future__ import annotations

from typing import Any

from src.agent_loop.llm_agent import AgentLoop
from src.utils.logger import get_logger

logger = get_logger("agent_loop.factory")


def create_trading_agent(
    gateway: Any,
    tool_registry: Any,
    max_turns: int = 8,
) -> AgentLoop:
    """Create a full-capability trading agent.

    Has access to ALL registered tools (data, analysis, portfolio,
    risk, quant, intel, etc.). Used for complex multi-step analysis
    like trading advisor, deep analysis, and decision-making.

    Args:
        gateway: LLMGateway or LLMRouter instance.
        tool_registry: ToolRegistry with tools registered.
        max_turns: Maximum LLM round-trips.
    """
    return AgentLoop(
        gateway=gateway,
        tool_executor=tool_registry.execute,
        tool_definitions=tool_registry.get_tool_definitions(),
        max_turns=max_turns,
    )


def create_scanning_agent(
    gateway: Any,
    tool_registry: Any,
    max_turns: int = 3,
) -> AgentLoop:
    """Create a lightweight scanning agent.

    Limited to data-retrieval tools only (no LLM-backed analysis).
    Used for high-frequency market scanning where speed matters.

    Args:
        gateway: LLMGateway or LLMRouter instance.
        tool_registry: ToolRegistry with tools registered.
        max_turns: Maximum LLM round-trips (kept low for speed).
    """
    # Filter to non-LLM-backed tools only (data tools, portfolio, etc.)
    all_tools = tool_registry.get_tool_definitions()
    fast_tools = [t for t in all_tools if not tool_registry.is_llm_backed(t["name"])]
    return AgentLoop(
        gateway=gateway,
        tool_executor=tool_registry.execute,
        tool_definitions=fast_tools,
        max_turns=max_turns,
    )


def create_debate_agent(
    gateway: Any,
    tool_registry: Any,
    max_turns: int = 5,
) -> AgentLoop:
    """Create a debate agent for bull/bear analysis.

    Has access to data + analysis tools for building arguments.
    Used by the debate engine for structured multi-perspective analysis.

    Args:
        gateway: LLMGateway or LLMRouter instance.
        tool_registry: ToolRegistry with tools registered.
        max_turns: Maximum LLM round-trips.
    """
    return AgentLoop(
        gateway=gateway,
        tool_executor=tool_registry.execute,
        tool_definitions=tool_registry.get_tool_definitions(),
        max_turns=max_turns,
    )


def create_simple_agent(
    gateway: Any,
    max_turns: int = 1,
) -> AgentLoop:
    """Create a no-tool agent for pure text generation.

    Used for message formatting, Chinese output generation,
    and tasks that don't need external data.

    Args:
        gateway: LLMGateway or LLMRouter instance.
        max_turns: Maximum turns (1 = single shot).
    """
    return AgentLoop(
        gateway=gateway,
        tool_executor=None,
        tool_definitions=[],
        max_turns=max_turns,
    )

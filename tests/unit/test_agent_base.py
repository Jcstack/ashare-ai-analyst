"""Tests for agent base abstractions.

Part of v16.0 Agent Mesh layer.
"""

from __future__ import annotations

import asyncio


from src.agents.base import (
    AgentCapability,
    AgentMessage,
    BaseAgent,
    DelegationPlan,
)


# ---------------------------------------------------------------------------
# AgentCapability tests
# ---------------------------------------------------------------------------


class TestAgentCapability:
    def test_defaults(self):
        cap = AgentCapability(name="test")
        assert cap.name == "test"
        assert cap.description == ""
        assert cap.tool_whitelist == []
        assert cap.max_tokens == 2048
        assert cap.trust_zone_min == "LOW"
        assert cap.use_llm is True
        assert cap.temperature == 0.3

    def test_custom(self):
        cap = AgentCapability(
            name="analyst",
            description="Technical analyst",
            tool_whitelist=["get_realtime_quote", "get_technical_indicators"],
            max_tokens=3072,
            trust_zone_min="MEDIUM",
            use_llm=True,
            temperature=0.2,
        )
        assert cap.name == "analyst"
        assert len(cap.tool_whitelist) == 2
        assert cap.max_tokens == 3072
        assert cap.trust_zone_min == "MEDIUM"

    def test_no_llm_mode(self):
        cap = AgentCapability(name="trader", use_llm=False)
        assert cap.use_llm is False


# ---------------------------------------------------------------------------
# AgentMessage tests
# ---------------------------------------------------------------------------


class TestAgentMessage:
    def test_defaults(self):
        msg = AgentMessage()
        assert msg.from_agent == ""
        assert msg.to_agent == ""
        assert msg.task == ""
        assert msg.context == {}
        assert msg.budget_remaining == 0
        assert msg.result == ""
        assert msg.tool_calls_made == 0
        assert msg.tokens_used == 0
        assert msg.delegation_chain == []
        assert msg.timestamp != ""

    def test_custom(self):
        msg = AgentMessage(
            from_agent="master",
            to_agent="analyst",
            task="Analyze stock 600519",
            context={"symbol": "600519"},
            budget_remaining=10000,
            delegation_chain=["master"],
        )
        assert msg.from_agent == "master"
        assert msg.to_agent == "analyst"
        assert msg.context["symbol"] == "600519"
        assert msg.budget_remaining == 10000

    def test_result_populated(self):
        msg = AgentMessage(
            from_agent="analyst",
            to_agent="master",
            result="Stock is bearish",
            tokens_used=500,
            tool_calls_made=3,
        )
        assert msg.result == "Stock is bearish"
        assert msg.tokens_used == 500
        assert msg.tool_calls_made == 3


# ---------------------------------------------------------------------------
# DelegationPlan tests
# ---------------------------------------------------------------------------


class TestDelegationPlan:
    def test_defaults(self):
        plan = DelegationPlan()
        assert plan.agents == []
        assert plan.tasks == []
        assert plan.strategy == "sequential"
        assert plan.rationale == ""

    def test_custom(self):
        plan = DelegationPlan(
            agents=["analyst", "research"],
            tasks=["Analyze technicals", "Check news"],
            strategy="parallel",
            rationale="Need both data and sentiment",
        )
        assert len(plan.agents) == 2
        assert plan.strategy == "parallel"


# ---------------------------------------------------------------------------
# BaseAgent tests
# ---------------------------------------------------------------------------


class ConcreteAgent(BaseAgent):
    """Concrete implementation for testing."""

    async def _execute_impl(self, message: AgentMessage) -> AgentMessage:
        return AgentMessage(
            from_agent=self.name,
            to_agent=message.from_agent,
            result="done",
            delegation_chain=[*message.delegation_chain, self.name],
        )


class TestBaseAgent:
    def test_name(self):
        cap = AgentCapability(name="test_agent")
        agent = ConcreteAgent(capability=cap)
        assert agent.name == "test_agent"

    def test_capability(self):
        cap = AgentCapability(
            name="analyst",
            tool_whitelist=["get_realtime_quote"],
        )
        agent = ConcreteAgent(capability=cap)
        assert agent.capability.tool_whitelist == ["get_realtime_quote"]

    def test_check_tool_permission_allowed(self):
        cap = AgentCapability(
            name="analyst",
            tool_whitelist=["get_realtime_quote", "get_technical_indicators"],
        )
        agent = ConcreteAgent(capability=cap)
        assert agent._check_tool_permission("get_realtime_quote") is True

    def test_check_tool_permission_denied(self):
        cap = AgentCapability(
            name="analyst",
            tool_whitelist=["get_realtime_quote"],
        )
        agent = ConcreteAgent(capability=cap)
        assert agent._check_tool_permission("execute_trade") is False

    def test_check_budget_sufficient(self):
        cap = AgentCapability(name="test")
        agent = ConcreteAgent(capability=cap)
        msg = AgentMessage(budget_remaining=5000)
        assert agent._check_budget(msg, 500) is True

    def test_check_budget_insufficient(self):
        cap = AgentCapability(name="test")
        agent = ConcreteAgent(capability=cap)
        msg = AgentMessage(budget_remaining=100)
        assert agent._check_budget(msg, 500) is False

    def test_execute(self):
        cap = AgentCapability(name="test")
        agent = ConcreteAgent(capability=cap)
        msg = AgentMessage(
            from_agent="master",
            to_agent="test",
            task="do something",
            delegation_chain=["master"],
        )
        result = asyncio.run(agent.execute(msg))
        assert result.from_agent == "test"
        assert result.result == "done"
        assert result.delegation_chain == ["master", "test"]

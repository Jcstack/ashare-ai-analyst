"""Tests for trader agent (rule engine, no LLM).

Part of v16.0 Agent Mesh layer.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from src.agents.base import AgentCapability, AgentMessage
from src.agents.trader_agent import TraderAgent


@pytest.fixture
def trader_cap():
    return AgentCapability(
        name="trader",
        tool_whitelist=["execute_trade", "record_manual_trade", "get_trade_history"],
        max_tokens=1024,
        use_llm=False,
    )


@pytest.fixture
def mock_tools():
    tools = MagicMock()

    async def mock_execute(name, tool_input):
        return json.dumps(
            {
                "id": "trade_123",
                "symbol": tool_input.get("symbol"),
                "action": tool_input.get("action"),
                "shares": tool_input.get("shares"),
                "status": "executed",
            }
        )

    tools.execute = mock_execute
    return tools


@pytest.fixture
def trader(trader_cap, mock_tools):
    return TraderAgent(
        capability=trader_cap,
        tool_registry=mock_tools,
    )


def _run(coro):
    return asyncio.run(coro)


class TestTraderAgent:
    def test_rejects_without_risk_approval(self, trader):
        msg = AgentMessage(
            from_agent="master",
            to_agent="trader",
            task="Buy 600519",
            context={
                "trade_params": {
                    "symbol": "600519",
                    "stock_name": "贵州茅台",
                    "action": "buy",
                    "shares": 100,
                    "price": 1680.0,
                },
                "risk_approved": False,
            },
            budget_remaining=5000,
            delegation_chain=["master"],
        )

        result = _run(trader.execute(msg))
        data = json.loads(result.result)
        assert data["status"] == "rejected"
        assert "风控" in data["reason"]

    def test_executes_with_risk_approval(self, trader):
        msg = AgentMessage(
            from_agent="master",
            to_agent="trader",
            task="Buy 600519",
            context={
                "trade_params": {
                    "symbol": "600519",
                    "stock_name": "贵州茅台",
                    "action": "buy",
                    "shares": 100,
                    "price": 1680.0,
                },
                "risk_approved": True,
            },
            budget_remaining=5000,
            delegation_chain=["master"],
        )

        result = _run(trader.execute(msg))
        data = json.loads(result.result)
        assert data["status"] == "executed"

    def test_validates_shares_multiple_of_100(self, trader):
        msg = AgentMessage(
            from_agent="master",
            to_agent="trader",
            task="Buy",
            context={
                "trade_params": {
                    "symbol": "600519",
                    "stock_name": "贵州茅台",
                    "action": "buy",
                    "shares": 150,
                    "price": 1680.0,
                },
                "risk_approved": True,
            },
            budget_remaining=5000,
            delegation_chain=["master"],
        )

        result = _run(trader.execute(msg))
        data = json.loads(result.result)
        assert data["status"] == "rejected"
        assert "100" in data["reason"]

    def test_validates_missing_params(self, trader):
        msg = AgentMessage(
            from_agent="master",
            to_agent="trader",
            task="Buy",
            context={
                "trade_params": {"symbol": "600519"},
                "risk_approved": True,
            },
            budget_remaining=5000,
            delegation_chain=["master"],
        )

        result = _run(trader.execute(msg))
        data = json.loads(result.result)
        assert data["status"] == "rejected"
        assert "缺少" in data["reason"]

    def test_validates_negative_price(self, trader):
        msg = AgentMessage(
            from_agent="master",
            to_agent="trader",
            task="Buy",
            context={
                "trade_params": {
                    "symbol": "600519",
                    "stock_name": "茅台",
                    "action": "buy",
                    "shares": 100,
                    "price": -10,
                },
                "risk_approved": True,
            },
            budget_remaining=5000,
            delegation_chain=["master"],
        )

        result = _run(trader.execute(msg))
        data = json.loads(result.result)
        assert data["status"] == "rejected"
        assert "正数" in data["reason"]

    def test_validates_invalid_action(self, trader):
        msg = AgentMessage(
            from_agent="master",
            to_agent="trader",
            task="Hold",
            context={
                "trade_params": {
                    "symbol": "600519",
                    "stock_name": "茅台",
                    "action": "hold",
                    "shares": 100,
                    "price": 1680,
                },
                "risk_approved": True,
            },
            budget_remaining=5000,
            delegation_chain=["master"],
        )

        result = _run(trader.execute(msg))
        data = json.loads(result.result)
        assert data["status"] == "rejected"
        assert "无效" in data["reason"]

    def test_zero_tokens_used(self, trader):
        """Trader is a rule engine — no LLM tokens consumed."""
        msg = AgentMessage(
            from_agent="master",
            to_agent="trader",
            task="Buy",
            context={
                "trade_params": {
                    "symbol": "600519",
                    "stock_name": "茅台",
                    "action": "buy",
                    "shares": 100,
                    "price": 1680,
                },
                "risk_approved": True,
            },
            budget_remaining=5000,
            delegation_chain=["master"],
        )

        result = _run(trader.execute(msg))
        assert result.tokens_used == 0

    def test_delegation_chain(self, trader):
        msg = AgentMessage(
            from_agent="master",
            to_agent="trader",
            task="Buy",
            context={
                "trade_params": {
                    "symbol": "600519",
                    "stock_name": "茅台",
                    "action": "buy",
                    "shares": 100,
                    "price": 1680,
                },
                "risk_approved": True,
            },
            budget_remaining=5000,
            delegation_chain=["master", "risk"],
        )

        result = _run(trader.execute(msg))
        assert result.delegation_chain == ["master", "risk", "trader"]

    def test_validates_zero_shares(self, trader):
        msg = AgentMessage(
            from_agent="master",
            to_agent="trader",
            task="Buy",
            context={
                "trade_params": {
                    "symbol": "600519",
                    "stock_name": "茅台",
                    "action": "buy",
                    "shares": 0,
                    "price": 1680,
                },
                "risk_approved": True,
            },
            budget_remaining=5000,
            delegation_chain=["master"],
        )

        result = _run(trader.execute(msg))
        data = json.loads(result.result)
        assert data["status"] == "rejected"

    def test_empty_trade_params(self, trader):
        msg = AgentMessage(
            from_agent="master",
            to_agent="trader",
            task="Buy",
            context={
                "trade_params": {},
                "risk_approved": True,
            },
            budget_remaining=5000,
            delegation_chain=["master"],
        )

        result = _run(trader.execute(msg))
        data = json.loads(result.result)
        assert data["status"] == "rejected"

    def test_no_trade_params_in_context(self, trader):
        msg = AgentMessage(
            from_agent="master",
            to_agent="trader",
            task="Buy",
            context={"risk_approved": True},
            budget_remaining=5000,
            delegation_chain=["master"],
        )

        result = _run(trader.execute(msg))
        data = json.loads(result.result)
        assert data["status"] == "rejected"

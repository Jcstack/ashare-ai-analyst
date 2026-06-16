"""Tests for agent registry.

Part of v16.0 Agent Mesh layer.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch


from src.agents.registry import AgentRegistry, FilteredToolRegistry


# ---------------------------------------------------------------------------
# FilteredToolRegistry tests
# ---------------------------------------------------------------------------


class TestFilteredToolRegistry:
    def test_filters_definitions(self):
        full = MagicMock()
        full.get_tool_definitions.return_value = [
            {"name": "get_realtime_quote", "description": "a", "input_schema": {}},
            {"name": "execute_trade", "description": "b", "input_schema": {}},
            {"name": "get_portfolio", "description": "c", "input_schema": {}},
        ]

        filtered = FilteredToolRegistry(full, ["get_realtime_quote", "get_portfolio"])
        defs = filtered.get_tool_definitions()
        assert len(defs) == 2
        names = {d["name"] for d in defs}
        assert "get_realtime_quote" in names
        assert "get_portfolio" in names
        assert "execute_trade" not in names

    def test_execute_allowed(self):
        full = MagicMock()

        async def mock_execute(name, tool_input):
            return '{"ok": true}'

        full.execute = mock_execute

        filtered = FilteredToolRegistry(full, ["get_realtime_quote"])
        result = asyncio.run(
            filtered.execute("get_realtime_quote", {"symbols": ["600519"]})
        )
        assert "ok" in result

    def test_execute_blocked(self):
        full = MagicMock()

        async def mock_execute(name, tool_input):
            return '{"ok": true}'

        full.execute = mock_execute

        filtered = FilteredToolRegistry(full, ["get_realtime_quote"])
        result = asyncio.run(filtered.execute("execute_trade", {"symbol": "600519"}))
        data = json.loads(result)
        assert "error" in data
        assert "permission" in data["error"].lower()

    def test_empty_whitelist(self):
        full = MagicMock()
        full.get_tool_definitions.return_value = [
            {"name": "tool1", "description": "a", "input_schema": {}},
        ]

        filtered = FilteredToolRegistry(full, [])
        assert filtered.get_tool_definitions() == []


# ---------------------------------------------------------------------------
# AgentRegistry tests
# ---------------------------------------------------------------------------


class TestAgentRegistry:
    @patch("src.agents.registry.load_config")
    def test_load_config(self, mock_load):
        mock_load.return_value = {
            "master": {"max_tokens_per_request": 4096},
            "agents": {
                "analyst": {
                    "description": "Tech analyst",
                    "tools": ["get_realtime_quote"],
                    "max_tokens_per_request": 3072,
                    "trust_zone_min": "LOW",
                    "temperature": 0.2,
                },
            },
            "budget": {
                "max_tokens_per_thread": 50000,
                "max_tool_calls_per_agent": 8,
            },
        }

        registry = AgentRegistry()
        cap = registry.get_capability("analyst")
        assert cap is not None
        assert cap.name == "analyst"
        assert "get_realtime_quote" in cap.tool_whitelist
        assert cap.max_tokens == 3072

    @patch("src.agents.registry.load_config")
    def test_budget_config(self, mock_load):
        mock_load.return_value = {
            "agents": {},
            "budget": {
                "max_tokens_per_thread": 60000,
                "max_tool_calls_per_agent": 10,
            },
        }

        registry = AgentRegistry()
        assert registry.max_tokens_per_thread == 60000
        assert registry.max_tool_calls_per_agent == 10

    @patch("src.agents.registry.load_config")
    def test_master_config(self, mock_load):
        mock_load.return_value = {
            "master": {
                "max_tokens_per_request": 4096,
                "temperature": 0.3,
            },
            "agents": {},
            "budget": {},
        }

        registry = AgentRegistry()
        master_cfg = registry.get_master_config()
        assert master_cfg["max_tokens_per_request"] == 4096

    @patch("src.agents.registry.load_config")
    def test_list_agents_before_bootstrap(self, mock_load):
        mock_load.return_value = {"agents": {}, "budget": {}}
        registry = AgentRegistry()
        assert registry.list_agents() == []

    @patch("src.agents.registry.load_config")
    def test_get_nonexistent_agent(self, mock_load):
        mock_load.return_value = {"agents": {}, "budget": {}}
        registry = AgentRegistry()
        assert registry.get("nonexistent") is None

    @patch("src.agents.registry.load_config")
    def test_get_nonexistent_capability(self, mock_load):
        mock_load.return_value = {"agents": {}, "budget": {}}
        registry = AgentRegistry()
        assert registry.get_capability("nonexistent") is None

    @patch("src.agents.registry.load_config")
    def test_config_fallback(self, mock_load):
        mock_load.side_effect = Exception("no config")
        registry = AgentRegistry()
        assert registry.max_tokens_per_thread == 50000
        assert registry.list_agents() == []

    @patch("src.agents.registry.load_config")
    def test_bootstrap_creates_agents(self, mock_load):
        mock_load.return_value = {
            "master": {"max_tokens_per_request": 4096},
            "agents": {
                "analyst": {
                    "description": "Analyst",
                    "system_role": "You are an analyst",
                    "tools": ["get_realtime_quote"],
                    "max_tokens_per_request": 3072,
                },
                "risk": {
                    "description": "Risk",
                    "system_role": "You are risk",
                    "tools": ["get_portfolio"],
                    "max_tokens_per_request": 2048,
                },
                "trader": {
                    "description": "Trader",
                    "system_role": "Trader",
                    "tools": ["execute_trade"],
                    "max_tokens_per_request": 1024,
                    "use_llm": False,
                },
                "research": {
                    "description": "Research",
                    "system_role": "Researcher",
                    "tools": ["get_trending_news"],
                    "max_tokens_per_request": 3072,
                },
            },
            "budget": {},
        }

        mock_tool_registry = MagicMock()
        mock_tool_registry.get_tool_definitions.return_value = [
            {"name": "get_realtime_quote", "description": "a", "input_schema": {}},
            {"name": "get_portfolio", "description": "b", "input_schema": {}},
            {"name": "execute_trade", "description": "c", "input_schema": {}},
            {"name": "get_trending_news", "description": "d", "input_schema": {}},
        ]
        mock_llm = MagicMock()

        registry = AgentRegistry()
        registry.bootstrap(
            tool_registry=mock_tool_registry,
            llm_router=mock_llm,
        )

        assert len(registry.list_agents()) == 4
        assert registry.get("analyst") is not None
        assert registry.get("risk") is not None
        assert registry.get("trader") is not None
        assert registry.get("research") is not None

    @patch("src.agents.registry.load_config")
    def test_multiple_capabilities_parsed(self, mock_load):
        mock_load.return_value = {
            "agents": {
                "analyst": {
                    "tools": ["a", "b", "c"],
                    "max_tokens_per_request": 3000,
                    "trust_zone_min": "MEDIUM",
                    "temperature": 0.1,
                },
                "risk": {
                    "tools": ["d"],
                    "max_tokens_per_request": 2000,
                },
            },
            "budget": {},
        }

        registry = AgentRegistry()
        analyst = registry.get_capability("analyst")
        risk = registry.get_capability("risk")
        assert analyst is not None
        assert len(analyst.tool_whitelist) == 3
        assert analyst.trust_zone_min == "MEDIUM"
        assert risk is not None
        assert risk.max_tokens == 2000

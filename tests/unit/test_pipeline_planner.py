"""Tests for the orchestration PipelinePlanner."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from src.orchestration.planner import PipelinePlanner
from src.orchestration.primitives import PipelineSpec, StepSpec


# ── Test helpers ──────────────────────────────────────────────


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")


def _make_config(steps: dict[str, dict] | None = None) -> dict:
    """Build a minimal pipelines.yaml structure."""
    return {
        "pipelines": {
            "stock_analysis": {
                "description": "test pipeline",
                "budget_tokens": 10000,
                "require_all_outputs": ["confidence_score"],
                "steps": steps
                or {
                    "data_qa": {
                        "agent": "data_qa",
                        "task": "check {symbol}",
                        "depends_on": [],
                        "input_filter": ["symbol"],
                        "output_fields": ["data_quality_score"],
                        "required": True,
                    },
                    "analysis": {
                        "agent": "analyst",
                        "task": "analyze {symbol}",
                        "depends_on": ["data_qa"],
                        "input_filter": ["symbol", "data_quality_score"],
                        "output_fields": ["signal", "confidence_score"],
                        "required": True,
                    },
                },
            },
            "trade_decision": {
                "description": "trade pipeline",
                "steps": {
                    "risk": {
                        "agent": "risk",
                        "task": "evaluate risk",
                        "output_fields": ["risk_level"],
                    },
                },
            },
        },
    }


# ── Config loading ───────────────────────────────────────────


class TestConfigLoading:
    def test_load_from_yaml(self, tmp_path):
        config_path = tmp_path / "pipelines.yaml"
        _write_yaml(config_path, _make_config())

        planner = PipelinePlanner(config_path=config_path)

        assert "stock_analysis" in planner.predefined_pipelines
        assert "trade_decision" in planner.predefined_pipelines

        sa = planner.predefined_pipelines["stock_analysis"]
        assert sa.budget_tokens == 10000
        assert "data_qa" in sa.steps
        assert "analysis" in sa.steps
        assert sa.steps["analysis"].depends_on == ["data_qa"]
        assert sa.require_all_outputs == ["confidence_score"]

    def test_missing_config_file(self, tmp_path):
        planner = PipelinePlanner(config_path=tmp_path / "nonexistent.yaml")
        assert planner.predefined_pipelines == {}

    def test_malformed_yaml(self, tmp_path):
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("{{invalid yaml", encoding="utf-8")

        planner = PipelinePlanner(config_path=config_path)
        assert planner.predefined_pipelines == {}

    def test_retry_policy_parsing(self, tmp_path):
        config = _make_config(
            {
                "s1": {
                    "agent": "a",
                    "task": "do thing",
                    "retry": {
                        "max_retries": 3,
                        "backoff_ms": 500,
                        "retry_on": ["timeout"],
                    },
                },
            }
        )
        config_path = tmp_path / "pipelines.yaml"
        _write_yaml(config_path, config)

        planner = PipelinePlanner(config_path=config_path)
        step = planner.predefined_pipelines["stock_analysis"].steps["s1"]
        assert step.retry.max_retries == 3
        assert step.retry.backoff_ms == 500
        assert step.retry.retry_on == ["timeout"]


# ── Keyword matching ─────────────────────────────────────────


class TestKeywordMatching:
    def _planner(self, tmp_path) -> PipelinePlanner:
        config_path = tmp_path / "pipelines.yaml"
        _write_yaml(config_path, _make_config())
        return PipelinePlanner(config_path=config_path)

    def test_stock_analysis_match(self, tmp_path):
        planner = self._planner(tmp_path)
        result = asyncio.run(planner.plan("帮我分析一下贵州茅台怎么样"))
        assert result.name == "stock_analysis"

    def test_trade_decision_match(self, tmp_path):
        planner = self._planner(tmp_path)
        result = asyncio.run(planner.plan("我想买入贵州茅台"))
        assert result.name == "trade_decision"

    def test_no_match_falls_back(self, tmp_path):
        planner = self._planner(tmp_path)
        result = asyncio.run(planner.plan("hello world"))
        assert result.name == "fallback"
        assert "analyst" in [s.agent for s in result.steps.values()]

    def test_english_keywords(self, tmp_path):
        planner = self._planner(tmp_path)
        result = asyncio.run(planner.plan("analyze stock 600519"))
        assert result.name == "stock_analysis"


# ── Template substitution ────────────────────────────────────


class TestTemplateSubstitution:
    def test_symbol_substitution(self, tmp_path):
        config_path = tmp_path / "pipelines.yaml"
        _write_yaml(config_path, _make_config())
        planner = PipelinePlanner(config_path=config_path)

        result = asyncio.run(
            planner.plan(
                "分析600519",
                context={"symbol": "600519"},
            )
        )

        # Check that {symbol} was replaced in at least one step
        substituted = any(
            "600519" in step.task
            for step in result.steps.values()
            if "{symbol}" not in step.task
        )
        assert substituted or result.name == "trade_decision"


# ── Dynamic planning ─────────────────────────────────────────


class TestDynamicPlanning:
    def test_dynamic_plan_from_llm(self, tmp_path):
        """LLM generates a valid PipelineSpec."""
        config_path = tmp_path / "empty.yaml"
        _write_yaml(config_path, {"pipelines": {}})

        mock_llm = MagicMock()
        plan_json = json.dumps(
            {
                "name": "dynamic_custom",
                "steps": {
                    "s1": {
                        "agent": "analyst",
                        "task": "do analysis",
                        "output_fields": ["signal"],
                    },
                },
                "require_all_outputs": ["signal"],
            }
        )
        mock_llm.complete_with_tools.return_value = MagicMock(text=plan_json)

        planner = PipelinePlanner(
            llm_router=mock_llm,
            available_agents=["analyst", "risk"],
            config_path=config_path,
        )

        result = asyncio.run(planner.plan("something unusual"))

        assert result.name == "dynamic_custom"
        assert "s1" in result.steps
        assert result.steps["s1"].agent == "analyst"

    def test_dynamic_plan_failure_fallback(self, tmp_path):
        """LLM returns garbage → falls back to single agent."""
        config_path = tmp_path / "empty.yaml"
        _write_yaml(config_path, {"pipelines": {}})

        mock_llm = MagicMock()
        mock_llm.complete_with_tools.return_value = MagicMock(text="not json")

        planner = PipelinePlanner(
            llm_router=mock_llm,
            available_agents=["analyst"],
            config_path=config_path,
        )

        result = asyncio.run(planner.plan("something unusual"))

        assert result.name == "fallback"

    def test_llm_returns_markdown_wrapped_json(self, tmp_path):
        """LLM wraps JSON in markdown code block."""
        config_path = tmp_path / "empty.yaml"
        _write_yaml(config_path, {"pipelines": {}})

        plan_json = json.dumps(
            {
                "name": "dynamic_md",
                "steps": {
                    "s1": {"agent": "analyst", "task": "analyze"},
                },
            }
        )
        mock_llm = MagicMock()
        mock_llm.complete_with_tools.return_value = MagicMock(
            text=f"```json\n{plan_json}\n```"
        )

        planner = PipelinePlanner(
            llm_router=mock_llm,
            available_agents=["analyst"],
            config_path=config_path,
        )

        result = asyncio.run(planner.plan("unusual request"))
        assert result.name == "dynamic_md"


# ── OrchestratorAgent (master_agent.py) ──────────────────────


class TestOrchestratorAgent:
    def test_process_delegates_to_executor(self, tmp_path):
        """OrchestratorAgent plans + executes."""
        from src.agents.master_agent import MasterResult, OrchestratorAgent
        from src.orchestration.executor import PipelineExecutor

        class FixedPlanner:
            async def plan(self, msg, ctx):
                return PipelineSpec(
                    name="test",
                    steps={
                        "s1": StepSpec(agent="a", task="do it"),
                    },
                )

        agent = _FakeAgent("a", {"report_markdown": "# Result\nAll good."})
        registry = _FakeRegistry({"a": agent})
        executor = PipelineExecutor(agent_registry=registry)
        orchestrator = OrchestratorAgent(executor=executor, planner=FixedPlanner())

        result = asyncio.run(orchestrator.process("test message", {"symbol": "600519"}))

        assert isinstance(result, MasterResult)
        assert "Result" in result.text or "All good" in result.text
        assert result.pipeline_result is not None
        assert result.pipeline_result.success

    def test_backward_compatible_alias(self):
        from src.agents.master_agent import MasterAgent, OrchestratorAgent

        assert MasterAgent is OrchestratorAgent


# ── Helpers (duplicated to avoid cross-module fixtures) ──────


class _FakeAgent:
    def __init__(self, name, result=None):
        self._name = name
        self._result = result or {}
        self.calls = []

    @property
    def name(self):
        return self._name

    async def execute(self, message):
        self.calls.append(message)
        from src.agents.base import AgentMessage

        return AgentMessage(
            from_agent=self._name,
            result=json.dumps(self._result, ensure_ascii=False),
            tokens_used=50,
            delegation_chain=["orchestrator", self._name],
        )


class _FakeRegistry:
    def __init__(self, agents=None):
        self._agents = agents or {}

    def get(self, name):
        return self._agents.get(name)

    def list_agents(self):
        return list(self._agents.keys())

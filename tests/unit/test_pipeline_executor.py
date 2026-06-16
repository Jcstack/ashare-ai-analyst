"""Tests for the orchestration PipelineExecutor."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock


from src.orchestration.executor import PipelineExecutor
from src.orchestration.primitives import (
    PipelineSpec,
    RetryPolicy,
    StepSpec,
)


# ── Test helpers ──────────────────────────────────────────────


class FakeAgent:
    """Agent that returns a canned result."""

    def __init__(self, name: str, result: dict[str, Any] | None = None) -> None:
        self._name = name
        self._result = result or {}
        self.calls: list[Any] = []

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, message: Any) -> Any:
        self.calls.append(message)
        from src.agents.base import AgentMessage

        return AgentMessage(
            from_agent=self._name,
            to_agent="orchestrator",
            result=json.dumps(self._result, ensure_ascii=False),
            tokens_used=100,
            tool_calls_made=1,
            delegation_chain=["orchestrator", self._name],
        )


class FailingAgent:
    """Agent that raises an exception."""

    def __init__(self, name: str, error: str = "boom") -> None:
        self._name = name
        self._error = error

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, message: Any) -> Any:
        raise RuntimeError(self._error)


class SlowAgent:
    """Agent that takes a configurable time to respond."""

    def __init__(
        self, name: str, delay_s: float, result: dict[str, Any] | None = None
    ) -> None:
        self._name = name
        self._delay = delay_s
        self._result = result or {}

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, message: Any) -> Any:
        await asyncio.sleep(self._delay)
        from src.agents.base import AgentMessage

        return AgentMessage(
            from_agent=self._name,
            to_agent="orchestrator",
            result=json.dumps(self._result, ensure_ascii=False),
            tokens_used=50,
            tool_calls_made=0,
            delegation_chain=["orchestrator", self._name],
        )


class FakeRegistry:
    """Minimal agent registry for tests."""

    def __init__(self, agents: dict[str, Any] | None = None) -> None:
        self._agents = agents or {}

    def get(self, name: str) -> Any:
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        return list(self._agents.keys())


# ── Pipeline validation ──────────────────────────────────────


class TestPipelineSpecValidation:
    def test_empty_pipeline(self):
        spec = PipelineSpec(name="empty")
        errors = spec.validate([])
        assert "pipeline has no steps" in errors[0]

    def test_unknown_agent(self):
        spec = PipelineSpec(
            name="test",
            steps={"s1": StepSpec(agent="nonexistent")},
        )
        errors = spec.validate(["analyst"])
        assert any("unknown agent" in e for e in errors)

    def test_unknown_dependency(self):
        spec = PipelineSpec(
            name="test",
            steps={"s1": StepSpec(agent="a", depends_on=["missing"])},
        )
        errors = spec.validate(["a"])
        assert any("unknown step" in e for e in errors)

    def test_cycle_detection(self):
        spec = PipelineSpec(
            name="cycle",
            steps={
                "a": StepSpec(agent="x", depends_on=["b"]),
                "b": StepSpec(agent="x", depends_on=["a"]),
            },
        )
        errors = spec.validate(["x"])
        assert any("cycle" in e for e in errors)

    def test_valid_pipeline(self):
        spec = PipelineSpec(
            name="ok",
            steps={
                "s1": StepSpec(agent="a"),
                "s2": StepSpec(agent="b", depends_on=["s1"]),
            },
        )
        errors = spec.validate(["a", "b"])
        assert errors == []


# ── Topological levels ───────────────────────────────────────


class TestTopologicalLevels:
    def test_single_step(self):
        spec = PipelineSpec(
            name="single",
            steps={"s1": StepSpec(agent="a")},
        )
        levels = PipelineExecutor._topological_levels(spec)
        assert levels == [["s1"]]

    def test_parallel_roots(self):
        spec = PipelineSpec(
            name="parallel",
            steps={
                "a": StepSpec(agent="x"),
                "b": StepSpec(agent="y"),
                "c": StepSpec(agent="z"),
            },
        )
        levels = PipelineExecutor._topological_levels(spec)
        assert len(levels) == 1
        assert sorted(levels[0]) == ["a", "b", "c"]

    def test_sequential_chain(self):
        spec = PipelineSpec(
            name="chain",
            steps={
                "s1": StepSpec(agent="a"),
                "s2": StepSpec(agent="b", depends_on=["s1"]),
                "s3": StepSpec(agent="c", depends_on=["s2"]),
            },
        )
        levels = PipelineExecutor._topological_levels(spec)
        assert levels == [["s1"], ["s2"], ["s3"]]

    def test_diamond_dag(self):
        """A → B, A → C, B+C → D."""
        spec = PipelineSpec(
            name="diamond",
            steps={
                "a": StepSpec(agent="x"),
                "b": StepSpec(agent="x", depends_on=["a"]),
                "c": StepSpec(agent="x", depends_on=["a"]),
                "d": StepSpec(agent="x", depends_on=["b", "c"]),
            },
        )
        levels = PipelineExecutor._topological_levels(spec)
        assert levels[0] == ["a"]
        assert sorted(levels[1]) == ["b", "c"]
        assert levels[2] == ["d"]


# ── Executor integration ─────────────────────────────────────


class TestExecutor:
    def test_single_step_pipeline(self):
        agent = FakeAgent("analyst", {"signal": "bullish", "confidence_score": 0.8})
        registry = FakeRegistry({"analyst": agent})
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="simple",
            steps={
                "analysis": StepSpec(
                    agent="analyst",
                    task="analyze {symbol}",
                    output_fields=["signal", "confidence_score"],
                ),
            },
        )

        result = asyncio.run(executor.execute(pipeline, {"symbol": "600519"}))

        assert result.success
        assert result.final_output["signal"] == "bullish"
        assert result.final_output["confidence_score"] == 0.8
        assert result.total_tokens == 100
        assert result.delegation_chain == ["analyst"]
        assert len(agent.calls) == 1
        assert "600519" in agent.calls[0].task

    def test_multi_step_sequential(self):
        analyst = FakeAgent("analyst", {"signal": "bullish"})
        risk = FakeAgent("risk", {"risk_level": "medium"})
        registry = FakeRegistry({"analyst": analyst, "risk": risk})
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="seq",
            steps={
                "tech": StepSpec(
                    agent="analyst",
                    task="tech analysis",
                    output_fields=["signal"],
                ),
                "risk_eval": StepSpec(
                    agent="risk",
                    task="risk assessment",
                    depends_on=["tech"],
                    input_filter=["signal"],
                    output_fields=["risk_level"],
                ),
            },
        )

        result = asyncio.run(executor.execute(pipeline, {}))

        assert result.success
        assert result.final_output["signal"] == "bullish"
        assert result.final_output["risk_level"] == "medium"
        assert result.delegation_chain == ["analyst", "risk"]
        # Risk agent should receive signal from analyst
        risk_ctx = risk.calls[0].context
        assert risk_ctx.get("signal") == "bullish"

    def test_parallel_execution(self):
        """Independent steps run in parallel (same level)."""
        agent_a = SlowAgent("a", 0.1, {"out_a": 1})
        agent_b = SlowAgent("b", 0.1, {"out_b": 2})
        registry = FakeRegistry({"a": agent_a, "b": agent_b})
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="parallel",
            steps={
                "step_a": StepSpec(agent="a", output_fields=["out_a"]),
                "step_b": StepSpec(agent="b", output_fields=["out_b"]),
            },
        )

        result = asyncio.run(executor.execute(pipeline, {}))

        assert result.success
        assert result.final_output == {"out_a": 1, "out_b": 2}
        # Parallel execution: total time should be ~0.1s, not ~0.2s
        assert result.elapsed_ms < 300

    def test_required_step_failure(self):
        failing = FailingAgent("bad", "something broke")
        registry = FakeRegistry({"bad": failing})
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="fail",
            steps={
                "s1": StepSpec(
                    agent="bad",
                    required=True,
                    retry=RetryPolicy(max_retries=0),
                ),
            },
        )

        result = asyncio.run(executor.execute(pipeline, {}))

        assert not result.success
        assert any("required step" in e for e in result.errors)

    def test_optional_step_failure(self):
        good = FakeAgent("good", {"result": "ok"})
        bad = FailingAgent("bad", "oops")
        registry = FakeRegistry({"good": good, "bad": bad})
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="opt_fail",
            steps={
                "ok_step": StepSpec(agent="good", output_fields=["result"]),
                "bad_step": StepSpec(
                    agent="bad",
                    required=False,
                    retry=RetryPolicy(max_retries=0),
                ),
            },
        )

        result = asyncio.run(executor.execute(pipeline, {}))

        assert result.success
        assert result.final_output["result"] == "ok"

    def test_input_filtering(self):
        """Steps only receive filtered context fields."""
        agent = FakeAgent("a", {"out": 1})
        registry = FakeRegistry({"a": agent})
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="filter",
            steps={
                "s1": StepSpec(
                    agent="a",
                    input_filter=["symbol"],
                    output_fields=["out"],
                ),
            },
        )

        result = asyncio.run(
            executor.execute(
                pipeline,
                {"symbol": "600519", "secret": "should_not_pass"},
            )
        )

        assert result.success
        ctx = agent.calls[0].context
        assert "symbol" in ctx
        assert "secret" not in ctx

    def test_wildcard_input_filter(self):
        agent = FakeAgent("a", {"out": 1})
        registry = FakeRegistry({"a": agent})
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="wildcard",
            steps={
                "s1": StepSpec(
                    agent="a",
                    input_filter=["*"],
                    output_fields=["out"],
                ),
            },
        )

        asyncio.run(executor.execute(pipeline, {"x": 1, "y": 2}))
        ctx = agent.calls[0].context
        assert ctx["x"] == 1
        assert ctx["y"] == 2

    def test_missing_required_output(self):
        agent = FakeAgent("a", {"only_this": 1})
        registry = FakeRegistry({"a": agent})
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="missing_out",
            steps={
                "s1": StepSpec(agent="a", output_fields=["only_this"]),
            },
            require_all_outputs=["only_this", "missing_field"],
        )

        result = asyncio.run(executor.execute(pipeline, {}))

        assert not result.success
        assert any("missing_field" in e for e in result.errors)

    def test_retry_on_failure(self):
        """Step retries on transient failure."""
        call_count = 0

        class FlakeyAgent:
            name = "flakey"

            async def execute(self, message):
                nonlocal call_count
                call_count += 1
                if call_count < 2:
                    raise RuntimeError("tool_error: transient")
                from src.agents.base import AgentMessage

                return AgentMessage(
                    from_agent="flakey",
                    result='{"ok": true}',
                    tokens_used=10,
                    delegation_chain=["orchestrator", "flakey"],
                )

        registry = FakeRegistry({"flakey": FlakeyAgent()})
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="retry",
            steps={
                "s1": StepSpec(
                    agent="flakey",
                    retry=RetryPolicy(max_retries=2, backoff_ms=10),
                    output_fields=["ok"],
                ),
            },
        )

        result = asyncio.run(executor.execute(pipeline, {}))

        assert result.success
        assert call_count == 2
        assert result.step_results["s1"].retries == 1

    def test_timeout(self):
        slow = SlowAgent("slow", delay_s=5.0)
        registry = FakeRegistry({"slow": slow})
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="timeout",
            steps={
                "s1": StepSpec(
                    agent="slow",
                    timeout_ms=100,
                    retry=RetryPolicy(max_retries=0),
                    required=True,
                ),
            },
        )

        result = asyncio.run(executor.execute(pipeline, {}))

        assert not result.success
        assert result.step_results["s1"].error == "timeout"

    def test_audit_log_called(self):
        agent = FakeAgent("a", {"out": 1})
        registry = FakeRegistry({"a": agent})
        audit = MagicMock()
        executor = PipelineExecutor(agent_registry=registry, audit_log=audit)

        pipeline = PipelineSpec(
            name="audited",
            steps={"s1": StepSpec(agent="a")},
        )

        asyncio.run(executor.execute(pipeline, {}))

        # 2 calls: step_executed + pipeline_executed
        assert audit.log.call_count == 2
        # Last call should be pipeline_executed
        call_args = audit.log.call_args
        assert call_args[0][0] == "pipeline_executed"
        assert call_args[1]["actor"] == "orchestrator"

    def test_invalid_pipeline_returns_error(self):
        registry = FakeRegistry({})
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="bad",
            steps={"s1": StepSpec(agent="nonexistent")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))

        assert not result.success
        assert any("unknown agent" in e for e in result.errors)

    def test_diamond_dag_execution(self):
        """A → B+C (parallel) → D with data flow."""
        agents = {
            "a": FakeAgent("a", {"from_a": 10}),
            "b": FakeAgent("b", {"from_b": 20}),
            "c": FakeAgent("c", {"from_c": 30}),
            "d": FakeAgent("d", {"final": 999}),
        }
        registry = FakeRegistry(agents)
        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="diamond",
            steps={
                "step_a": StepSpec(agent="a", output_fields=["from_a"]),
                "step_b": StepSpec(
                    agent="b",
                    depends_on=["step_a"],
                    input_filter=["from_a"],
                    output_fields=["from_b"],
                ),
                "step_c": StepSpec(
                    agent="c",
                    depends_on=["step_a"],
                    input_filter=["from_a"],
                    output_fields=["from_c"],
                ),
                "step_d": StepSpec(
                    agent="d",
                    depends_on=["step_b", "step_c"],
                    input_filter=["from_b", "from_c"],
                    output_fields=["final"],
                ),
            },
        )

        result = asyncio.run(executor.execute(pipeline, {}))

        assert result.success
        assert result.final_output["from_a"] == 10
        assert result.final_output["from_b"] == 20
        assert result.final_output["from_c"] == 30
        assert result.final_output["final"] == 999

        # D should receive B and C outputs
        d_ctx = agents["d"].calls[0].context
        assert d_ctx.get("from_b") == 20
        assert d_ctx.get("from_c") == 30


# ── Result parsing ───────────────────────────────────────────


class TestResultParsing:
    def test_parse_json(self):
        assert PipelineExecutor._parse_result('{"a": 1}') == {"a": 1}

    def test_parse_markdown_json(self):
        text = 'Some text\n```json\n{"a": 1}\n```\nMore text'
        assert PipelineExecutor._parse_result(text) == {"a": 1}

    def test_parse_embedded_json(self):
        text = 'The result is {"a": 1} end'
        assert PipelineExecutor._parse_result(text) == {"a": 1}

    def test_parse_plain_text(self):
        result = PipelineExecutor._parse_result("just text")
        assert result == {"result": "just text"}

    def test_parse_empty(self):
        assert PipelineExecutor._parse_result("") == {}

    def test_parse_chinese_json(self):
        text = '{"信号": "看多", "置信度": 0.8}'
        result = PipelineExecutor._parse_result(text)
        assert result["信号"] == "看多"

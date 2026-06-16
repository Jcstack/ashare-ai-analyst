"""Phase 6 tests — Intelligence Loop Activation.

Tests cover:
1. PipelineResult intelligence fields
2. Memory injection before pipeline
3. Ensemble validation after pipeline
4. Reflection after pipeline
5. Memory store after pipeline
6. Drift alert integration
7. Error resilience (intelligence failures don't break pipeline)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

from src.orchestration.executor import PipelineExecutor
from src.orchestration.primitives import PipelineResult, PipelineSpec, StepSpec


# ── Test helpers ──────────────────────────────────────────────────


@dataclass
class FakeAgentResult:
    result: str = '{"direction": "bullish", "confidence": 0.75, "summary": "看涨"}'
    tokens_used: int = 100
    tool_calls_made: int = 1


class FakeAgent:
    """Fake agent for testing."""

    def __init__(self, name: str, output: dict | None = None) -> None:
        self._name = name
        self._output = output or {"direction": "bullish", "confidence": 0.75}

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, message: Any) -> FakeAgentResult:
        import json

        return FakeAgentResult(result=json.dumps(self._output))


class FakeRegistry:
    """Fake agent registry."""

    def __init__(self, agents: dict[str, FakeAgent]) -> None:
        self._agents = agents

    def get(self, name: str) -> FakeAgent | None:
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        return list(self._agents.keys())


@dataclass
class FakeMemory:
    memory_id: str = ""
    content: str = ""
    category: str = ""
    relevance_score: float = 0.5


@dataclass
class FakeEnsembleResult:
    consensus_score: float = 0.85
    consensus_direction: str = "bullish"
    trust_zone: str = "HIGH"
    divergence_notes: list[str] = field(default_factory=list)


@dataclass
class FakeReflectionResult:
    original_confidence: float = 0.75
    adjusted_confidence: float = 0.70
    confidence_delta: float = -0.05
    issues_found: list[str] = field(default_factory=lambda: ["高置信度需审视"])
    recommendation: str = "reduce_confidence"


# =====================================================================
# 1. PipelineResult intelligence fields
# =====================================================================


class TestPipelineResultFields:
    """Tests for new intelligence loop fields on PipelineResult."""

    def test_default_empty_intelligence_fields(self) -> None:
        result = PipelineResult(pipeline_name="test")
        assert result.ensemble_result == {}
        assert result.reflection_result == {}
        assert result.memory_context_used == []

    def test_intelligence_fields_populated(self) -> None:
        result = PipelineResult(
            pipeline_name="trade_decision",
            ensemble_result={"consensus_score": 0.8},
            reflection_result={"adjusted_confidence": 0.7},
            memory_context_used=["mem-001", "mem-002"],
        )
        assert result.ensemble_result["consensus_score"] == 0.8
        assert result.reflection_result["adjusted_confidence"] == 0.7
        assert len(result.memory_context_used) == 2


# =====================================================================
# 2. Memory injection before pipeline
# =====================================================================


class TestMemoryInjection:
    """Tests for memory retrieval and context injection."""

    def test_memory_injected_into_context(self) -> None:
        agent = FakeAgent("analyst")
        registry = FakeRegistry({"analyst": agent})
        mock_memory = MagicMock()
        mock_memory.retrieve.return_value = [
            FakeMemory(memory_id="mem-1", content="之前分析看涨", category="insight"),
            FakeMemory(memory_id="mem-2", content="注意风险", category="pattern"),
        ]

        executor = PipelineExecutor(
            agent_registry=registry,
            memory_store=mock_memory,
        )

        pipeline = PipelineSpec(
            name="stock_analysis",
            steps={"s1": StepSpec(agent="analyst", task="analyze")},
        )

        result = asyncio.run(executor.execute(pipeline, {"symbol": "600519"}))

        assert result.success
        assert result.memory_context_used == ["mem-1", "mem-2"]
        mock_memory.retrieve.assert_called_once()

    def test_no_memory_store_no_injection(self) -> None:
        agent = FakeAgent("analyst")
        registry = FakeRegistry({"analyst": agent})

        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="test",
            steps={"s1": StepSpec(agent="analyst")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.success
        assert result.memory_context_used == []

    def test_memory_retrieve_failure_doesnt_break(self) -> None:
        agent = FakeAgent("analyst")
        registry = FakeRegistry({"analyst": agent})
        mock_memory = MagicMock()
        mock_memory.retrieve.side_effect = RuntimeError("memory down")

        executor = PipelineExecutor(
            agent_registry=registry,
            memory_store=mock_memory,
        )

        pipeline = PipelineSpec(
            name="test",
            steps={"s1": StepSpec(agent="analyst")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.success
        assert result.memory_context_used == []


# =====================================================================
# 3. Ensemble validation after pipeline
# =====================================================================


class TestEnsembleIntegration:
    """Tests for ensemble validation in pipeline executor."""

    def test_ensemble_runs_for_trade_pipeline(self) -> None:
        agent = FakeAgent(
            "analyst",
            {
                "direction": "bullish",
                "confidence": 0.8,
                "provider_results": [
                    {
                        "provider": "anthropic",
                        "direction": "bullish",
                        "confidence": 0.8,
                    },
                    {"provider": "google", "direction": "bullish", "confidence": 0.7},
                ],
            },
        )
        registry = FakeRegistry({"analyst": agent})

        mock_ensemble = MagicMock()
        mock_ensemble.should_validate.return_value = True
        mock_ensemble.validate.return_value = FakeEnsembleResult()

        executor = PipelineExecutor(
            agent_registry=registry,
            ensemble_validator=mock_ensemble,
        )

        pipeline = PipelineSpec(
            name="trade_decision",
            steps={"s1": StepSpec(agent="analyst")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.success
        assert result.ensemble_result["consensus_score"] == 0.85
        assert result.ensemble_result["trust_zone"] == "HIGH"
        mock_ensemble.validate.assert_called_once()

    def test_ensemble_skipped_for_non_trade_pipeline(self) -> None:
        agent = FakeAgent("analyst")
        registry = FakeRegistry({"analyst": agent})

        mock_ensemble = MagicMock()

        executor = PipelineExecutor(
            agent_registry=registry,
            ensemble_validator=mock_ensemble,
        )

        pipeline = PipelineSpec(
            name="stock_analysis",  # Not a trade pipeline
            steps={"s1": StepSpec(agent="analyst")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.success
        assert result.ensemble_result == {}
        mock_ensemble.validate.assert_not_called()

    def test_ensemble_failure_doesnt_break_pipeline(self) -> None:
        agent = FakeAgent(
            "analyst",
            {
                "provider_results": [{"a": 1}],
            },
        )
        registry = FakeRegistry({"analyst": agent})

        mock_ensemble = MagicMock()
        mock_ensemble.should_validate.return_value = True
        mock_ensemble.validate.side_effect = RuntimeError("ensemble crash")

        executor = PipelineExecutor(
            agent_registry=registry,
            ensemble_validator=mock_ensemble,
        )

        pipeline = PipelineSpec(
            name="trade_decision",
            steps={"s1": StepSpec(agent="analyst")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.success
        assert result.ensemble_result == {}

    def test_ensemble_skipped_when_no_provider_results(self) -> None:
        agent = FakeAgent("analyst", {"direction": "bullish"})
        registry = FakeRegistry({"analyst": agent})

        mock_ensemble = MagicMock()
        mock_ensemble.should_validate.return_value = True

        executor = PipelineExecutor(
            agent_registry=registry,
            ensemble_validator=mock_ensemble,
        )

        pipeline = PipelineSpec(
            name="trade_decision",
            steps={"s1": StepSpec(agent="analyst")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.ensemble_result == {}
        mock_ensemble.validate.assert_not_called()


# =====================================================================
# 4. Reflection after pipeline
# =====================================================================


class TestReflectionIntegration:
    """Tests for reflection agent in pipeline executor."""

    def test_reflection_runs_after_pipeline(self) -> None:
        agent = FakeAgent("analyst", {"confidence": 0.85, "direction": "bullish"})
        registry = FakeRegistry({"analyst": agent})

        mock_reflection = MagicMock()
        mock_reflection.reflect.return_value = FakeReflectionResult()

        executor = PipelineExecutor(
            agent_registry=registry,
            reflection_agent=mock_reflection,
        )

        pipeline = PipelineSpec(
            name="stock_analysis",
            steps={"s1": StepSpec(agent="analyst")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.success
        assert result.reflection_result["original_confidence"] == 0.75
        assert result.reflection_result["adjusted_confidence"] == 0.70
        assert result.reflection_result["recommendation"] == "reduce_confidence"
        mock_reflection.reflect.assert_called_once()

    def test_reflection_failure_doesnt_break(self) -> None:
        agent = FakeAgent("analyst")
        registry = FakeRegistry({"analyst": agent})

        mock_reflection = MagicMock()
        mock_reflection.reflect.side_effect = RuntimeError("reflection crash")

        executor = PipelineExecutor(
            agent_registry=registry,
            reflection_agent=mock_reflection,
        )

        pipeline = PipelineSpec(
            name="test",
            steps={"s1": StepSpec(agent="analyst")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.success
        assert result.reflection_result == {}

    def test_reflection_skipped_on_pipeline_failure(self) -> None:
        agent = FakeAgent("analyst", {"bad": True})
        registry = FakeRegistry({"analyst": agent})

        mock_reflection = MagicMock()

        executor = PipelineExecutor(
            agent_registry=registry,
            reflection_agent=mock_reflection,
        )

        pipeline = PipelineSpec(
            name="test",
            steps={"s1": StepSpec(agent="analyst")},
            require_all_outputs=["missing_field"],  # Will fail
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert not result.success
        mock_reflection.reflect.assert_not_called()


# =====================================================================
# 5. Memory store after pipeline
# =====================================================================


class TestMemoryStoreIntegration:
    """Tests for memory store insight saving after pipeline."""

    def test_insights_stored_after_pipeline(self) -> None:
        agent = FakeAgent(
            "analyst",
            {
                "symbol": "600519",
                "direction": "bullish",
                "confidence": 0.8,
                "summary": "基本面强劲，技术面看涨",
            },
        )
        registry = FakeRegistry({"analyst": agent})

        mock_memory = MagicMock()
        mock_memory.retrieve.return_value = []

        executor = PipelineExecutor(
            agent_registry=registry,
            memory_store=mock_memory,
        )

        pipeline = PipelineSpec(
            name="stock_analysis",
            steps={"s1": StepSpec(agent="analyst")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.success
        mock_memory.store.assert_called_once()

        call_kwargs = mock_memory.store.call_args
        stored_content = call_kwargs[1].get("content") or call_kwargs[0][0]
        assert "stock_analysis" in stored_content
        assert "bullish" in stored_content

    def test_store_failure_doesnt_break(self) -> None:
        agent = FakeAgent("analyst", {"direction": "bearish"})
        registry = FakeRegistry({"analyst": agent})

        mock_memory = MagicMock()
        mock_memory.retrieve.return_value = []
        mock_memory.store.side_effect = RuntimeError("store crash")

        executor = PipelineExecutor(
            agent_registry=registry,
            memory_store=mock_memory,
        )

        pipeline = PipelineSpec(
            name="test",
            steps={"s1": StepSpec(agent="analyst")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.success  # Pipeline still succeeds

    def test_no_store_when_empty_output(self) -> None:
        agent = FakeAgent("analyst", {"result": ""})
        registry = FakeRegistry({"analyst": agent})

        mock_memory = MagicMock()
        mock_memory.retrieve.return_value = []

        executor = PipelineExecutor(
            agent_registry=registry,
            memory_store=mock_memory,
        )

        pipeline = PipelineSpec(
            name="test",
            steps={"s1": StepSpec(agent="analyst")},
        )

        asyncio.run(executor.execute(pipeline, {}))
        mock_memory.store.assert_not_called()


# =====================================================================
# 6. Full intelligence loop integration
# =====================================================================


class TestFullIntelligenceLoop:
    """Test all intelligence components working together."""

    def test_all_intelligence_hooks_active(self) -> None:
        agent = FakeAgent(
            "analyst",
            {
                "symbol": "600519",
                "direction": "bullish",
                "confidence": 0.8,
                "summary": "综合分析看涨",
                "provider_results": [
                    {
                        "provider": "anthropic",
                        "direction": "bullish",
                        "confidence": 0.8,
                    },
                ],
            },
        )
        registry = FakeRegistry({"analyst": agent})

        mock_memory = MagicMock()
        mock_memory.retrieve.return_value = [
            FakeMemory(memory_id="mem-x", content="historical context"),
        ]

        mock_ensemble = MagicMock()
        mock_ensemble.should_validate.return_value = True
        mock_ensemble.validate.return_value = FakeEnsembleResult()

        mock_reflection = MagicMock()
        mock_reflection.reflect.return_value = FakeReflectionResult()

        mock_audit = MagicMock()

        executor = PipelineExecutor(
            agent_registry=registry,
            audit_log=mock_audit,
            ensemble_validator=mock_ensemble,
            reflection_agent=mock_reflection,
            memory_store=mock_memory,
        )

        pipeline = PipelineSpec(
            name="trade_decision",
            steps={"s1": StepSpec(agent="analyst")},
        )

        result = asyncio.run(executor.execute(pipeline, {"symbol": "600519"}))

        assert result.success
        # Memory was retrieved and used
        assert result.memory_context_used == ["mem-x"]
        # Ensemble ran
        assert result.ensemble_result["consensus_score"] == 0.85
        # Reflection ran
        assert result.reflection_result["adjusted_confidence"] == 0.70
        # Memory stored insights
        mock_memory.store.assert_called_once()
        # Audit logged
        assert mock_audit.log.call_count >= 2  # step + pipeline


# =====================================================================
# 7. Drift alert integration
# =====================================================================


class TestDriftAlertIntegration:
    """Test drift detection emitting system alerts."""

    def test_backfill_pipeline_task_exists(self) -> None:
        """Verify the backfill task is importable."""
        from openclaw.tasks.backfill_pipeline import (
            task_backfill_predictions,
            task_detect_drift,
        )

        assert task_backfill_predictions is not None
        assert task_detect_drift is not None

    def test_pipeline_result_has_trade_pipeline_names(self) -> None:
        """Verify _TRADE_PIPELINES is defined."""
        from src.orchestration.executor import _TRADE_PIPELINES

        assert "trade_decision" in _TRADE_PIPELINES
        assert "position_change" in _TRADE_PIPELINES
        assert "stop_loss" in _TRADE_PIPELINES


# =====================================================================
# 8. Existing test compatibility
# =====================================================================


class TestBackwardsCompatibility:
    """Ensure existing executor behavior unchanged."""

    def test_executor_works_without_intelligence(self) -> None:
        """Pipeline executor works with no intelligence components."""
        agent = FakeAgent("a", {"out": 1})
        registry = FakeRegistry({"a": agent})

        executor = PipelineExecutor(agent_registry=registry)

        pipeline = PipelineSpec(
            name="simple",
            steps={"s1": StepSpec(agent="a")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.success
        assert result.ensemble_result == {}
        assert result.reflection_result == {}
        assert result.memory_context_used == []

    def test_existing_audit_still_works(self) -> None:
        """Audit log works alongside intelligence components."""
        agent = FakeAgent("a", {"out": 1})
        registry = FakeRegistry({"a": agent})
        mock_audit = MagicMock()

        executor = PipelineExecutor(
            agent_registry=registry,
            audit_log=mock_audit,
        )

        pipeline = PipelineSpec(
            name="test",
            steps={"s1": StepSpec(agent="a")},
        )

        result = asyncio.run(executor.execute(pipeline, {}))
        assert result.success
        # step_executed + pipeline_executed
        assert mock_audit.log.call_count == 2

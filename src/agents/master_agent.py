"""Orchestrator agent — thin wrapper over the PipelineExecutor.

Replaces the v16.0 hardcoded MasterAgent with a configuration-driven
orchestrator that delegates all logic to the orchestration engine.

Backward-compatible: ``MasterAgent`` is an alias for ``OrchestratorAgent``,
and ``MasterResult`` wraps ``PipelineResult`` for existing call sites.
"""

from __future__ import annotations

from typing import Any

from src.orchestration.executor import PipelineExecutor
from src.orchestration.planner import PipelinePlanner
from src.orchestration.primitives import PipelineResult
from src.utils.logger import get_logger

logger = get_logger("agents.orchestrator")


class OrchestratorAgent:
    """Configuration-driven orchestrator.

    Uses ``PipelinePlanner`` to resolve user intent to a DAG,
    then ``PipelineExecutor`` to run it.

    Usage::

        orchestrator = OrchestratorAgent(executor, planner)
        result = await orchestrator.process(user_message, thread_context)
    """

    def __init__(
        self,
        executor: PipelineExecutor,
        planner: PipelinePlanner,
    ) -> None:
        self._executor = executor
        self._planner = planner

    async def process(
        self,
        user_message: str,
        thread_context: dict[str, Any] | None = None,
    ) -> MasterResult:
        """Process a user message through the orchestration pipeline.

        Args:
            user_message: The user's input text.
            thread_context: Optional thread context (symbol, mode, etc.).

        Returns:
            MasterResult wrapping the PipelineResult.
        """
        ctx = thread_context or {}

        # Plan
        pipeline = await self._planner.plan(user_message, ctx)
        logger.info(
            "Pipeline planned: name=%s, steps=%d",
            pipeline.name,
            len(pipeline.steps),
        )

        # Execute
        result = await self._executor.execute(pipeline, ctx)

        # Extract display text from the report step or final output
        text = self._extract_display_text(result)

        logger.info(
            "Orchestrator completed: pipeline=%s, success=%s, "
            "steps=%d, tokens=%d, %.0fms",
            result.pipeline_name,
            result.success,
            len(result.step_results),
            result.total_tokens,
            result.elapsed_ms,
        )

        return MasterResult(
            text=text,
            delegation_chain=result.delegation_chain,
            agents_used=result.delegation_chain,
            total_tokens=result.total_tokens,
            total_tool_calls=result.total_tool_calls,
            plan=None,
            pipeline_result=result,
        )

    @staticmethod
    def _extract_display_text(result: PipelineResult) -> str:
        """Extract human-readable text from pipeline result.

        Priority:
        1. report_markdown from report step
        2. executive_summary from final output
        3. Concatenated raw results from all steps
        4. Error summary
        """
        fo = result.final_output

        if fo.get("report_markdown"):
            return fo["report_markdown"]

        if fo.get("executive_summary"):
            return fo["executive_summary"]

        # Concatenate step results
        parts: list[str] = []
        for sr in result.step_results.values():
            if sr.success and sr.raw_result:
                parts.append(sr.raw_result)
        if parts:
            return "\n\n---\n\n".join(parts)

        if result.errors:
            return "分析过程中出现错误：\n" + "\n".join(f"- {e}" for e in result.errors)

        return "抱歉，没有可用的分析师来处理您的问题。"


class MasterResult:
    """Result from the orchestration pipeline.

    Backward-compatible with the original MasterResult API.
    """

    def __init__(
        self,
        text: str,
        delegation_chain: list[str],
        agents_used: list[str],
        total_tokens: int = 0,
        total_tool_calls: int = 0,
        plan: Any = None,
        pipeline_result: PipelineResult | None = None,
    ) -> None:
        self.text = text
        self.delegation_chain = delegation_chain
        self.agents_used = agents_used
        self.total_tokens = total_tokens
        self.total_tool_calls = total_tool_calls
        self.plan = plan
        self.pipeline_result = pipeline_result


# Backward-compatible alias
MasterAgent = OrchestratorAgent

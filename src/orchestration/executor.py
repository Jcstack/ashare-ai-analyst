"""Pipeline executor — DAG-aware, parallel, schema-enforcing.

Resolves step dependencies via topological sort, runs independent
steps in parallel, validates I/O at every boundary, and records
lineage for the full execution.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Protocol

from src.orchestration.primitives import (
    PipelineResult,
    PipelineSpec,
    StepResult,
    StepSpec,
)
from src.utils.logger import get_logger

logger = get_logger("orchestration.executor")


# ── Protocols for optional collaborators ─────────────────────────


class AgentLike(Protocol):
    """Minimal interface an agent must satisfy."""

    @property
    def name(self) -> str: ...

    async def execute(self, message: Any) -> Any: ...


class AgentRegistryLike(Protocol):
    """Lookup agents by name."""

    def get(self, name: str) -> AgentLike | None: ...
    def list_agents(self) -> list[str]: ...


class SchemaRegistryLike(Protocol):
    """Validate agent I/O payloads."""

    def validate_input(self, agent_name: str, payload: dict) -> Any: ...
    def validate_output(self, agent_name: str, payload: dict) -> Any: ...


class LineageServiceLike(Protocol):
    """Record data lineage snapshots and nodes."""

    def create_snapshot(self, **kwargs: Any) -> Any: ...
    def record_node(self, **kwargs: Any) -> Any: ...


class AuditLogLike(Protocol):
    """Append-only audit log."""

    def log(
        self, event_type: str, payload: dict | None = None, actor: str = "system"
    ) -> Any: ...


class EnsembleValidatorLike(Protocol):
    """Multi-provider consensus validation."""

    def validate(self, provider_results: list[Any]) -> Any: ...
    def should_validate(self, decision_type: str) -> bool: ...


class ReflectionAgentLike(Protocol):
    """Analysis quality review and confidence adjustment."""

    def reflect(
        self, analysis: dict, historical_accuracy: dict | None = None
    ) -> Any: ...


class MemoryStoreLike(Protocol):
    """Experience accumulation and retrieval."""

    def store(
        self,
        content: str,
        category: str,
        symbol: str = "",
        metadata: dict | None = None,
    ) -> str: ...
    def retrieve(
        self,
        query: str,
        category: str | None = None,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[Any]: ...


# ── Intelligence loop pipeline names ─────────────────────────────

_TRADE_PIPELINES = {"trade_decision", "position_change", "stop_loss"}


# ── Executor ─────────────────────────────────────────────────────


class PipelineExecutor:
    """Executes a PipelineSpec by resolving the DAG and running steps.

    Features:
    - Topological-sort execution (Kahn's algorithm)
    - Independent steps run in parallel via asyncio.gather
    - Per-step input filtering (context isolation)
    - Per-step retry with exponential backoff
    - Budget tracking across all steps
    - Optional schema validation at every I/O boundary
    - Optional lineage recording per step
    - Optional audit logging per pipeline
    - Optional intelligence loop (ensemble, reflection, memory)
    """

    def __init__(
        self,
        agent_registry: AgentRegistryLike,
        schema_registry: SchemaRegistryLike | None = None,
        lineage_service: LineageServiceLike | None = None,
        audit_log: AuditLogLike | None = None,
        ensemble_validator: EnsembleValidatorLike | None = None,
        reflection_agent: ReflectionAgentLike | None = None,
        memory_store: MemoryStoreLike | None = None,
    ) -> None:
        self._agents = agent_registry
        self._schemas = schema_registry
        self._lineage = lineage_service
        self._audit = audit_log
        self._ensemble = ensemble_validator
        self._reflection = reflection_agent
        self._memory = memory_store

    async def execute(
        self,
        pipeline: PipelineSpec,
        initial_context: dict[str, Any],
        request_id: str | None = None,
    ) -> PipelineResult:
        """Execute the full pipeline.

        Args:
            pipeline: The DAG specification to execute.
            initial_context: Seed data (symbol, quote, etc.).
            request_id: Correlation ID (generated if omitted).

        Returns:
            PipelineResult with per-step results and merged output.
        """
        request_id = request_id or uuid.uuid4().hex[:16]
        start = time.perf_counter()

        # Validate pipeline structure
        available = self._agents.list_agents()
        errors = pipeline.validate(available)
        if errors:
            return PipelineResult(
                pipeline_name=pipeline.name,
                request_id=request_id,
                success=False,
                errors=errors,
            )

        # Memory retrieval — inject relevant memories into context
        memory_ids_used: list[str] = []
        if self._memory:
            memory_ids_used = self._inject_memories(
                initial_context,
                pipeline.name,
            )

        # Build execution levels via topological sort
        levels = self._topological_levels(pipeline)

        # Shared state
        step_results: dict[str, StepResult] = {}
        merged_output: dict[str, Any] = {}
        budget_remaining = pipeline.budget_tokens
        delegation_chain: list[str] = []
        all_errors: list[str] = []

        async def _run_all_levels() -> None:
            """Execute all DAG levels — extracted for timeout wrapping."""
            nonlocal budget_remaining

            for level in levels:
                if budget_remaining <= 0:
                    logger.warning(
                        "Budget exhausted after %d steps, skipping remaining",
                        len(step_results),
                    )
                    break

                # Run all steps in this level concurrently
                tasks = []
                for step_id in level:
                    step = pipeline.steps[step_id]
                    step_ctx = self._build_step_context(
                        step,
                        initial_context,
                        merged_output,
                        step_results,
                    )
                    tasks.append(
                        self._run_step_with_retry(
                            step_id,
                            step,
                            step_ctx,
                            budget_remaining,
                            request_id,
                        )
                    )

                results = await asyncio.gather(*tasks, return_exceptions=True)

                for step_id, result in zip(level, results):
                    step = pipeline.steps[step_id]

                    if isinstance(result, Exception):
                        sr = StepResult(
                            step_id=step_id,
                            agent_name=step.agent,
                            success=False,
                            error=str(result),
                        )
                    elif isinstance(result, StepResult):
                        sr = result
                    else:
                        sr = StepResult(
                            step_id=step_id,
                            agent_name=step.agent,
                            success=False,
                            error=f"unexpected result type: {type(result).__name__}",
                        )

                    step_results[step_id] = sr

                    if sr.success:
                        budget_remaining -= sr.tokens_used
                        delegation_chain.append(sr.agent_name)
                        merged_output.update(sr.output)
                    elif step.required:
                        all_errors.append(
                            f"required step '{step_id}' failed: {sr.error}"
                        )

        # Run all levels with pipeline-level timeout
        max_duration = pipeline.max_duration_ms / 1000  # convert to seconds
        try:
            await asyncio.wait_for(_run_all_levels(), timeout=max_duration)
        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                "Pipeline '%s' timed out after %.0fms (limit: %dms)",
                pipeline.name,
                elapsed,
                pipeline.max_duration_ms,
            )
            return PipelineResult(
                pipeline_name=pipeline.name,
                step_results=step_results,
                final_output=merged_output,
                request_id=request_id,
                total_tokens=sum(sr.tokens_used for sr in step_results.values()),
                total_tool_calls=sum(
                    sr.tool_calls_made for sr in step_results.values()
                ),
                elapsed_ms=elapsed,
                delegation_chain=delegation_chain,
                success=False,
                errors=[
                    *all_errors,
                    f"pipeline exceeded max duration of {pipeline.max_duration_ms}ms",
                ],
            )

        # Check required outputs
        for field_name in pipeline.require_all_outputs:
            if field_name not in merged_output:
                all_errors.append(f"missing required output field: '{field_name}'")

        elapsed = (time.perf_counter() - start) * 1000
        total_tokens = sum(sr.tokens_used for sr in step_results.values())
        total_tool_calls = sum(sr.tool_calls_made for sr in step_results.values())

        # Intelligence loop — post-pipeline hooks
        ensemble_result: dict[str, Any] = {}
        reflection_result: dict[str, Any] = {}

        if len(all_errors) == 0:
            # Ensemble validation (trade pipelines only)
            if self._ensemble and pipeline.name in _TRADE_PIPELINES:
                ensemble_result = self._run_ensemble(merged_output)

            # Reflection (all pipelines when enabled)
            if self._reflection:
                reflection_result = self._run_reflection(merged_output)

            # Memory store — save key insights
            if self._memory:
                self._store_insights(
                    merged_output,
                    pipeline.name,
                    request_id,
                )

        pipeline_result = PipelineResult(
            pipeline_name=pipeline.name,
            step_results=step_results,
            final_output=merged_output,
            request_id=request_id,
            total_tokens=total_tokens,
            total_tool_calls=total_tool_calls,
            elapsed_ms=elapsed,
            delegation_chain=delegation_chain,
            success=len(all_errors) == 0,
            errors=all_errors,
            ensemble_result=ensemble_result,
            reflection_result=reflection_result,
            memory_context_used=memory_ids_used,
        )

        # Audit log
        if self._audit:
            try:
                self._audit.log(
                    "pipeline_executed",
                    payload={
                        "pipeline": pipeline.name,
                        "request_id": request_id,
                        "success": pipeline_result.success,
                        "steps": len(step_results),
                        "tokens": total_tokens,
                        "elapsed_ms": round(elapsed),
                    },
                    actor="orchestrator",
                )
            except Exception:
                logger.warning("Failed to write audit log", exc_info=True)

        logger.info(
            "Pipeline '%s' completed: success=%s, steps=%d, tokens=%d, %.0fms",
            pipeline.name,
            pipeline_result.success,
            len(step_results),
            total_tokens,
            elapsed,
        )

        return pipeline_result

    # ── Step execution ───────────────────────────────────────

    async def _run_step_with_retry(
        self,
        step_id: str,
        step: StepSpec,
        context: dict[str, Any],
        budget: int,
        request_id: str,
    ) -> StepResult:
        """Execute a step with retry logic."""
        last_error = ""
        retries = 0

        for attempt in range(1 + step.retry.max_retries):
            try:
                result = await asyncio.wait_for(
                    self._run_step(step_id, step, context, budget, request_id),
                    timeout=step.timeout_ms / 1000,
                )
                result.retries = retries
                return result
            except asyncio.TimeoutError:
                last_error = "timeout"
                retries += 1
                if "timeout" not in step.retry.retry_on:
                    break
            except Exception as exc:
                last_error = str(exc)
                retries += 1
                error_type = "tool_error" if "tool" in last_error.lower() else "unknown"
                if error_type not in step.retry.retry_on:
                    break

            if attempt < step.retry.max_retries:
                delay = step.retry.backoff_ms * (2**attempt) / 1000
                logger.info(
                    "Step '%s' retry %d/%d after %.1fs: %s",
                    step_id,
                    attempt + 1,
                    step.retry.max_retries,
                    delay,
                    last_error,
                )
                await asyncio.sleep(delay)

        return StepResult(
            step_id=step_id,
            agent_name=step.agent,
            success=False,
            error=last_error,
            retries=retries,
        )

    async def _run_step(
        self,
        step_id: str,
        step: StepSpec,
        context: dict[str, Any],
        budget: int,
        request_id: str,
    ) -> StepResult:
        """Execute a single step: resolve agent, validate, run, extract output."""
        start = time.perf_counter()

        agent = self._agents.get(step.agent)
        if agent is None:
            return StepResult(
                step_id=step_id,
                agent_name=step.agent,
                success=False,
                error=f"agent '{step.agent}' not found in registry",
            )

        # Build AgentMessage (import here to avoid circular dep at module level)
        from src.agents.base import AgentMessage

        task_text = step.task
        # Template substitution from context
        for key, val in context.items():
            if isinstance(val, str):
                task_text = task_text.replace(f"{{{key}}}", val)

        message = AgentMessage(
            from_agent="orchestrator",
            to_agent=step.agent,
            task=task_text,
            context=context,
            budget_remaining=budget,
            delegation_chain=["orchestrator"],
        )

        # Schema validation (input)
        if self._schemas:
            try:
                self._schemas.validate_input(step.agent, context)
            except Exception as exc:
                logger.warning("Input schema validation for '%s': %s", step_id, exc)

        # Execute
        result_msg = await agent.execute(message)

        # Schema validation (output)
        output_dict = self._parse_result(result_msg.result)
        if self._schemas:
            try:
                self._schemas.validate_output(step.agent, output_dict)
            except Exception as exc:
                logger.warning("Output schema validation for '%s': %s", step_id, exc)

        # Extract only declared output_fields
        extracted: dict[str, Any] = {}
        if step.output_fields:
            if step.output_fields == ["*"]:
                extracted = output_dict
            else:
                for f in step.output_fields:
                    if f in output_dict:
                        extracted[f] = output_dict[f]
        else:
            extracted = output_dict

        elapsed = (time.perf_counter() - start) * 1000

        # Lineage recording
        if self._lineage:
            try:
                self._lineage.record_node(
                    operation=f"step:{step_id}",
                    operation_type="agent_execution",
                    agent_name=step.agent,
                    thread_id=request_id,
                    duration_ms=elapsed,
                    metadata={
                        "step_id": step_id,
                        "pipeline_request_id": request_id,
                        "tokens_used": result_msg.tokens_used,
                    },
                )
            except Exception:
                logger.debug("Failed to record lineage for step '%s'", step_id)

        step_result = StepResult(
            step_id=step_id,
            agent_name=step.agent,
            output=extracted,
            raw_result=result_msg.result,
            tokens_used=result_msg.tokens_used,
            tool_calls_made=result_msg.tool_calls_made,
            elapsed_ms=elapsed,
            success=True,
        )

        # Per-step audit logging
        if self._audit:
            try:
                self._audit.log(
                    "step_executed",
                    payload={
                        "step_id": step_id,
                        "agent": step.agent,
                        "pipeline_request_id": request_id,
                        "success": True,
                        "tokens_used": result_msg.tokens_used,
                        "tool_calls": result_msg.tool_calls_made,
                        "elapsed_ms": round(elapsed),
                    },
                    actor=step.agent,
                )
            except Exception:
                logger.debug("Failed to write step audit for '%s'", step_id)

        return step_result

    # ── DAG resolution ───────────────────────────────────────

    @staticmethod
    def _topological_levels(pipeline: PipelineSpec) -> list[list[str]]:
        """Compute execution levels via Kahn's algorithm.

        Steps in the same level have no inter-dependencies and
        can be executed in parallel.

        Returns:
            List of levels, each level is a list of step_ids.
        """
        step_ids = set(pipeline.steps.keys())
        in_degree: dict[str, int] = {sid: 0 for sid in step_ids}

        # Build forward adjacency: dep -> [dependents]
        dependents: dict[str, list[str]] = {sid: [] for sid in step_ids}
        for sid, step in pipeline.steps.items():
            for dep in step.depends_on:
                if dep in step_ids:
                    in_degree[sid] += 1
                    dependents[dep].append(sid)

        levels: list[list[str]] = []
        queue = [sid for sid, deg in in_degree.items() if deg == 0]

        while queue:
            # Sort for deterministic ordering within a level
            queue.sort()
            levels.append(list(queue))
            next_queue: list[str] = []
            for node in queue:
                for dep_of in dependents[node]:
                    in_degree[dep_of] -= 1
                    if in_degree[dep_of] == 0:
                        next_queue.append(dep_of)
            queue = next_queue

        return levels

    # ── Context filtering ────────────────────────────────────

    @staticmethod
    def _build_step_context(
        step: StepSpec,
        initial_context: dict[str, Any],
        merged_output: dict[str, Any],
        step_results: dict[str, StepResult],
    ) -> dict[str, Any]:
        """Build filtered context for a step.

        Combines initial context with merged output from completed steps,
        then filters to only the fields declared in ``step.input_filter``.
        """
        # Full context = initial + all prior step outputs
        full = {**initial_context, **merged_output}

        # Inject per-dependency results under dep name
        for dep_id in step.depends_on:
            if dep_id in step_results and step_results[dep_id].success:
                full[f"_{dep_id}_result"] = step_results[dep_id].output

        # Apply filter
        if not step.input_filter or step.input_filter == ["*"]:
            return full

        return {k: v for k, v in full.items() if k in step.input_filter}

    # ── Result parsing ───────────────────────────────────────

    @staticmethod
    def _parse_result(raw: str) -> dict[str, Any]:
        """Best-effort parse of agent result text into a dict."""
        if not raw:
            return {}

        # Try direct JSON parse
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        # Try extracting JSON from markdown code block
        import re

        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding a JSON object
        start = raw.find("{")
        if start >= 0:
            depth = 0
            for i in range(start, len(raw)):
                if raw[i] == "{":
                    depth += 1
                elif raw[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(raw[start : i + 1])
                        except json.JSONDecodeError:
                            break

        # Fallback: wrap text as {"result": text}
        return {"result": raw}

    # ── Intelligence loop helpers ────────────────────────────

    def _inject_memories(
        self,
        context: dict[str, Any],
        pipeline_name: str,
    ) -> list[str]:
        """Retrieve relevant memories and inject into context.

        Returns list of memory IDs used.
        """
        if not self._memory:
            return []

        try:
            symbol = context.get("symbol", "")
            query = f"{pipeline_name} {symbol}"
            memories = self._memory.retrieve(
                query=query,
                symbol=symbol or None,
                limit=3,
            )
            if memories:
                context["_memory_context"] = [
                    {
                        "memory_id": getattr(m, "memory_id", ""),
                        "content": getattr(m, "content", str(m)),
                        "category": getattr(m, "category", ""),
                    }
                    for m in memories
                ]
                return [getattr(m, "memory_id", "") for m in memories]
        except Exception:
            logger.debug("Failed to retrieve memories", exc_info=True)

        return []

    def _run_ensemble(
        self,
        merged_output: dict[str, Any],
    ) -> dict[str, Any]:
        """Run ensemble validation on pipeline output.

        Only runs if ensemble validator is configured and the pipeline
        produces provider_results or direction/confidence data.
        """
        if not self._ensemble:
            return {}

        try:
            # Check if ensemble should validate this type
            if not self._ensemble.should_validate("trade_decision"):
                return {}

            # Look for provider_results in merged output
            provider_results = merged_output.get("provider_results", [])
            if not provider_results:
                return {}

            result = self._ensemble.validate(provider_results)
            # Convert to dict for serializable storage
            return {
                "consensus_score": getattr(result, "consensus_score", 0.0),
                "consensus_direction": getattr(result, "consensus_direction", ""),
                "trust_zone": getattr(result, "trust_zone", ""),
                "divergence_notes": getattr(result, "divergence_notes", []),
            }
        except Exception:
            logger.debug("Ensemble validation failed", exc_info=True)
            return {}

    def _run_reflection(
        self,
        merged_output: dict[str, Any],
    ) -> dict[str, Any]:
        """Run reflection agent on pipeline output.

        Audits assumptions and adjusts confidence.
        """
        if not self._reflection:
            return {}

        try:
            result = self._reflection.reflect(merged_output)
            return {
                "original_confidence": getattr(result, "original_confidence", 0.0),
                "adjusted_confidence": getattr(result, "adjusted_confidence", 0.0),
                "confidence_delta": getattr(result, "confidence_delta", 0.0),
                "issues_found": getattr(result, "issues_found", []),
                "recommendation": getattr(result, "recommendation", ""),
            }
        except Exception:
            logger.debug("Reflection failed", exc_info=True)
            return {}

    def _store_insights(
        self,
        merged_output: dict[str, Any],
        pipeline_name: str,
        request_id: str,
    ) -> None:
        """Store key insights from pipeline output in memory."""
        if not self._memory:
            return

        try:
            symbol = merged_output.get("symbol", "")
            # Build insight summary from output
            direction = merged_output.get("direction", "")
            confidence = merged_output.get("confidence", "")
            summary = merged_output.get("summary", merged_output.get("result", ""))

            if not summary and not direction:
                return

            content = f"[{pipeline_name}] {symbol}: "
            if direction:
                content += f"方向={direction} 信心={confidence} "
            if isinstance(summary, str) and summary:
                content += summary[:200]

            self._memory.store(
                content=content.strip(),
                category="insight",
                symbol=symbol,
                metadata={"pipeline": pipeline_name, "request_id": request_id},
            )
        except Exception:
            logger.debug("Failed to store insights", exc_info=True)

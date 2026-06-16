"""Core data structures for the orchestration engine.

All primitives are plain dataclasses — no I/O, no side effects.
They describe *what* to execute, not *how*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RetryPolicy:
    """Per-step retry configuration.

    Attributes:
        max_retries: Maximum retry attempts (0 = no retry).
        backoff_ms: Base delay between retries (doubles each attempt).
        retry_on: Error categories that trigger a retry.
    """

    max_retries: int = 1
    backoff_ms: int = 1000
    retry_on: list[str] = field(default_factory=lambda: ["timeout", "tool_error"])


@dataclass
class StepSpec:
    """One node in an execution DAG.

    Attributes:
        agent: Agent name from registry (e.g., "analyst", "risk").
        task: Task description template.  ``{symbol}`` is substituted
            from context at runtime.
        depends_on: Step IDs this step must wait for.
        input_filter: Context field names to pass to this step.
            Empty list = pass nothing.  ``["*"]`` = pass everything.
        output_fields: Field names to extract from the step result
            and merge into the pipeline's shared output.
        required: If True, pipeline fails when this step fails.
        timeout_ms: Per-step execution timeout.
        retry: Retry policy for transient failures.
    """

    agent: str = ""
    task: str = ""
    depends_on: list[str] = field(default_factory=list)
    input_filter: list[str] = field(default_factory=list)
    output_fields: list[str] = field(default_factory=list)
    required: bool = True
    timeout_ms: int = 30_000
    retry: RetryPolicy = field(default_factory=RetryPolicy)


@dataclass
class PipelineSpec:
    """A complete execution DAG.

    Attributes:
        name: Pipeline identifier (e.g., "stock_analysis").
        steps: Mapping of step_id → StepSpec.  Order is irrelevant;
            the executor resolves execution order from ``depends_on``.
        budget_tokens: Total token budget across all steps.
        require_all_outputs: Output field names that MUST be present
            in the final merged result.  The executor fails the pipeline
            if any are missing after all steps complete.
    """

    name: str = ""
    steps: dict[str, StepSpec] = field(default_factory=dict)
    budget_tokens: int = 50_000
    max_duration_ms: int = 120_000
    require_all_outputs: list[str] = field(default_factory=list)

    # ── helpers ──────────────────────────────────────────────

    def validate(self, available_agents: list[str]) -> list[str]:
        """Check the spec for structural problems.

        Returns a list of error strings (empty = valid).
        """
        errors: list[str] = []

        if not self.steps:
            errors.append("pipeline has no steps")
            return errors

        step_ids = set(self.steps.keys())

        for sid, step in self.steps.items():
            # Agent must exist
            if step.agent and step.agent not in available_agents:
                errors.append(f"step '{sid}': unknown agent '{step.agent}'")

            # Dependencies must reference existing steps
            for dep in step.depends_on:
                if dep not in step_ids:
                    errors.append(f"step '{sid}': depends_on unknown step '{dep}'")

        # Cycle detection (Kahn's algorithm)
        in_degree: dict[str, int] = {sid: 0 for sid in step_ids}
        for sid, step in self.steps.items():
            for dep in step.depends_on:
                if dep in in_degree:
                    in_degree[sid] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        visited = 0
        temp_in = dict(in_degree)

        while queue:
            node = queue.pop(0)
            visited += 1
            for sid, step in self.steps.items():
                if node in step.depends_on:
                    temp_in[sid] -= 1
                    if temp_in[sid] == 0:
                        queue.append(sid)

        if visited < len(step_ids):
            errors.append("pipeline contains a dependency cycle")

        return errors


@dataclass
class StepResult:
    """Result from executing one pipeline step.

    Attributes:
        step_id: Which step produced this result.
        agent_name: Agent that executed the step.
        output: Extracted output dict (only ``output_fields``).
        raw_result: Full agent result text.
        tokens_used: Tokens consumed.
        tool_calls_made: Tool invocations made.
        elapsed_ms: Wall-clock time.
        success: Whether the step completed without error.
        error: Error message if ``success`` is False.
        retries: Number of retries attempted.
    """

    step_id: str = ""
    agent_name: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    raw_result: str = ""
    tokens_used: int = 0
    tool_calls_made: int = 0
    elapsed_ms: float = 0.0
    success: bool = True
    error: str = ""
    retries: int = 0


@dataclass
class PipelineResult:
    """Aggregated result from a full pipeline execution.

    Attributes:
        pipeline_name: Which pipeline was executed.
        step_results: Per-step results keyed by step_id.
        final_output: Merged output fields from all steps.
        request_id: Correlation ID for this execution.
        lineage_graph_id: ID of the lineage graph created for this run.
        total_tokens: Sum of all step token usage.
        total_tool_calls: Sum of all step tool calls.
        elapsed_ms: Total wall-clock time (includes parallel overlap).
        delegation_chain: Ordered list of agents invoked.
        success: True if all required steps succeeded.
        errors: Collected error messages from failed steps.
    """

    pipeline_name: str = ""
    step_results: dict[str, StepResult] = field(default_factory=dict)
    final_output: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    lineage_graph_id: str = ""
    total_tokens: int = 0
    total_tool_calls: int = 0
    elapsed_ms: float = 0.0
    delegation_chain: list[str] = field(default_factory=list)
    success: bool = True
    errors: list[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # Intelligence loop results (populated when enabled)
    ensemble_result: dict[str, Any] = field(default_factory=dict)
    reflection_result: dict[str, Any] = field(default_factory=dict)
    memory_context_used: list[str] = field(default_factory=list)

"""Orchestration engine — configuration-driven agent pipeline execution.

Provides DAG-based workflow orchestration that composes agents via
PipelineSpec definitions, executes them with schema validation at
every boundary, and records full lineage.

Part of agent-spec-compliance plan, Phase 1.
"""

from src.orchestration.primitives import (
    PipelineResult,
    PipelineSpec,
    RetryPolicy,
    StepResult,
    StepSpec,
)

__all__ = [
    "PipelineResult",
    "PipelineSpec",
    "RetryPolicy",
    "StepResult",
    "StepSpec",
]

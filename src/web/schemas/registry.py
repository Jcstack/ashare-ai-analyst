"""Central schema registry for agent I/O validation.

Agents register their input/output Pydantic models here.
The PipelineExecutor queries the registry at every I/O boundary
to enforce contracts and catch drift early.

Part of v18.0 Agent Spec Compliance — Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from src.utils.logger import get_logger

logger = get_logger("schemas.registry")


@dataclass
class SchemaValidationResult:
    """Outcome of validating a payload against a registered schema."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    agent_name: str = ""
    direction: str = ""  # "input" or "output"


@dataclass
class SchemaInfo:
    """Metadata about a registered schema pair."""

    agent_name: str
    version: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]


class SchemaRegistry:
    """Central registry for all agent I/O schemas.

    Usage::

        registry = SchemaRegistry()
        registry.register("analyst", "1.0.0", AnalystInput, AnalystOutput)

        result = registry.validate_output("analyst", {"signal": "buy", ...})
        if not result.passed:
            logger.warning("Schema violation: %s", result.errors)
    """

    def __init__(self) -> None:
        self._schemas: dict[str, SchemaInfo] = {}

    def register(
        self,
        agent_name: str,
        version: str,
        input_model: type[BaseModel],
        output_model: type[BaseModel],
    ) -> None:
        """Register input/output schemas for an agent.

        Args:
            agent_name: Agent identifier (e.g. "analyst", "risk").
            version: Schema version string (e.g. "1.0.0").
            input_model: Pydantic model for validating agent input.
            output_model: Pydantic model for validating agent output.
        """
        self._schemas[agent_name] = SchemaInfo(
            agent_name=agent_name,
            version=version,
            input_model=input_model,
            output_model=output_model,
        )
        logger.debug("Registered schema for agent '%s' v%s", agent_name, version)

    def validate_input(
        self, agent_name: str, payload: dict[str, Any]
    ) -> SchemaValidationResult:
        """Validate an input payload against the registered schema.

        Args:
            agent_name: The agent whose schema to use.
            payload: The data dict to validate.

        Returns:
            SchemaValidationResult with pass/fail and error details.
        """
        return self._validate(agent_name, payload, "input")

    def validate_output(
        self, agent_name: str, payload: dict[str, Any]
    ) -> SchemaValidationResult:
        """Validate an output payload against the registered schema.

        Args:
            agent_name: The agent whose schema to use.
            payload: The data dict to validate.

        Returns:
            SchemaValidationResult with pass/fail and error details.
        """
        return self._validate(agent_name, payload, "output")

    def get_schema(self, agent_name: str) -> SchemaInfo | None:
        """Look up registered schema info for an agent.

        Returns:
            SchemaInfo or None if no schema registered.
        """
        return self._schemas.get(agent_name)

    def list_schemas(self) -> dict[str, SchemaInfo]:
        """Return all registered schemas."""
        return dict(self._schemas)

    def has_schema(self, agent_name: str) -> bool:
        """Check if a schema is registered for the given agent."""
        return agent_name in self._schemas

    def _validate(
        self,
        agent_name: str,
        payload: dict[str, Any],
        direction: str,
    ) -> SchemaValidationResult:
        """Internal validation logic.

        Args:
            agent_name: Agent identifier.
            payload: Data dict to validate.
            direction: "input" or "output".

        Returns:
            SchemaValidationResult.
        """
        info = self._schemas.get(agent_name)
        if info is None:
            # No schema registered — pass by default (graceful degradation)
            return SchemaValidationResult(
                passed=True,
                agent_name=agent_name,
                direction=direction,
            )

        model = info.input_model if direction == "input" else info.output_model

        try:
            model.model_validate(payload)
            return SchemaValidationResult(
                passed=True,
                agent_name=agent_name,
                direction=direction,
            )
        except ValidationError as exc:
            errors = [
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            ]
            logger.warning(
                "Schema %s validation failed for '%s': %s",
                direction,
                agent_name,
                errors,
            )
            return SchemaValidationResult(
                passed=False,
                errors=errors,
                agent_name=agent_name,
                direction=direction,
            )

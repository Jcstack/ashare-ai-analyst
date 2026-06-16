"""Base abstractions for the multi-agent mesh.

Defines the agent protocol, capability declarations, inter-agent messages,
and the abstract BaseAgent that all specialist agents must implement.

Part of v16.0 Agent Mesh layer.
Updated in v18.0 for schema validation wrapper.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("agents.base")


@dataclass
class AgentCapability:
    """Declares what an agent can do.

    Attributes:
        name: Agent identifier (e.g., "analyst", "risk").
        description: Human-readable role description.
        tool_whitelist: Tool names this agent may invoke.
        max_tokens: Token budget per request.
        trust_zone_min: Minimum trust zone for data this agent handles.
        use_llm: Whether this agent makes LLM calls (False = rule engine).
        temperature: LLM temperature for this agent.
    """

    name: str
    description: str = ""
    tool_whitelist: list[str] = field(default_factory=list)
    max_tokens: int = 2048
    trust_zone_min: str = "LOW"
    use_llm: bool = True
    temperature: float = 0.3


@dataclass
class AgentMessage:
    """Inter-agent message for task delegation and result passing.

    Attributes:
        from_agent: Source agent name ("master", "analyst", etc.).
        to_agent: Target agent name.
        task: Task description or instruction.
        context: Shared context dict (symbol, thread info, etc.).
        budget_remaining: Remaining token budget for this delegation chain.
        result: Result payload (filled by the target agent).
        tool_calls_made: Number of tool calls executed.
        tokens_used: Tokens consumed by this agent.
        delegation_chain: Ordered list of agents in the delegation path.
        timestamp: When the message was created.
    """

    from_agent: str = ""
    to_agent: str = ""
    task: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    budget_remaining: int = 0
    result: str = ""
    tool_calls_made: int = 0
    tokens_used: int = 0
    delegation_chain: list[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class DelegationPlan:
    """Master agent's plan for delegating work to specialists.

    Attributes:
        agents: Ordered list of agent names to invoke.
        tasks: Per-agent task descriptions (parallel to agents list).
        strategy: How to combine results ("sequential", "parallel", "vote").
        rationale: Why these agents were chosen.
    """

    agents: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    strategy: str = "sequential"
    rationale: str = ""


class BaseAgent(ABC):
    """Abstract base class for all specialist agents.

    Subclasses implement ``_execute_impl`` with agent-specific logic.
    The public ``execute`` method wraps it with schema validation,
    mandatory field injection, and error handling.

    If no ``schema_registry`` is provided, validation is skipped
    and the agent behaves identically to the pre-v18.0 pattern.
    """

    def __init__(
        self,
        capability: AgentCapability,
        schema_registry: Any | None = None,
    ) -> None:
        self._capability = capability
        self._schema_registry = schema_registry

    @property
    def name(self) -> str:
        """Agent identifier."""
        return self._capability.name

    @property
    def capability(self) -> AgentCapability:
        """Agent capability declaration."""
        return self._capability

    async def execute(self, message: AgentMessage) -> AgentMessage:
        """Execute with schema validation wrapper.

        1. Validate input (if schema_registry available)
        2. Call ``_execute_impl()`` — subclass logic
        3. Inject mandatory output fields if missing
        4. Validate output (if schema_registry available)
        5. Return result

        Args:
            message: Incoming delegation message with task and context.

        Returns:
            AgentMessage with result filled in.
        """
        # Input validation
        if self._schema_registry:
            try:
                result = self._schema_registry.validate_input(
                    self.name, message.context
                )
                if not result.passed:
                    logger.warning(
                        "Input schema validation for '%s': %s",
                        self.name,
                        result.errors,
                    )
            except Exception:
                logger.debug(
                    "Input validation skipped for '%s'", self.name, exc_info=True
                )

        # Execute agent logic
        response = await self._execute_impl(message)

        # Inject mandatory output fields
        response = self._inject_mandatory_fields(response, message)

        # Output validation
        if self._schema_registry:
            try:
                output_dict = self._parse_result_dict(response.result)
                result = self._schema_registry.validate_output(self.name, output_dict)
                if not result.passed:
                    logger.warning(
                        "Output schema validation for '%s': %s",
                        self.name,
                        result.errors,
                    )
            except Exception:
                logger.debug(
                    "Output validation skipped for '%s'", self.name, exc_info=True
                )

        return response

    @abstractmethod
    async def _execute_impl(self, message: AgentMessage) -> AgentMessage:
        """Execute agent-specific logic.

        Subclasses implement this instead of ``execute()``.

        Args:
            message: Incoming delegation message with task and context.

        Returns:
            AgentMessage with result filled in.
        """

    def _inject_mandatory_fields(
        self, response: AgentMessage, request: AgentMessage
    ) -> AgentMessage:
        """Ensure the 5 mandatory fields exist in the output.

        Parses the result JSON, injects missing fields with defaults,
        and re-serializes. If the result is not JSON, wraps it.
        """
        output = self._parse_result_dict(response.result)
        if not output:
            return response

        changed = False

        # Mandatory field defaults
        defaults = {
            "confidence_score": 0.5,
            "key_assumptions": [],
            "failure_modes": [],
            "data_lineage": [],
            "data_gaps": [],
        }
        for field_name, default in defaults.items():
            if field_name not in output:
                output[field_name] = default
                changed = True

        # Inject request_id from message if available
        if "request_id" not in output and request.context.get("request_id"):
            output["request_id"] = request.context["request_id"]
            changed = True

        # Inject timestamp
        if "timestamp" not in output:
            output["timestamp"] = datetime.now(timezone.utc).isoformat()
            changed = True

        if changed:
            response.result = json.dumps(output, ensure_ascii=False)

        return response

    @staticmethod
    def _parse_result_dict(raw: str) -> dict:
        """Best-effort parse of result text into a dict."""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return {}

    def _check_tool_permission(self, tool_name: str) -> bool:
        """Check if this agent is allowed to use a tool."""
        return tool_name in self._capability.tool_whitelist

    def _check_budget(self, message: AgentMessage, tokens_needed: int) -> bool:
        """Check if there's enough budget remaining."""
        return message.budget_remaining >= tokens_needed

"""Anthropic Claude LLM provider implementation.

Wraps the Anthropic Python SDK to conform to the BaseLLMProvider
interface. Handles system message separation as required by the
Anthropic Messages API.
"""

import time
from typing import Any

import anthropic

from src.llm.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMResponse,
    LLMToolResponse,
    ProviderName,
    ToolCall,
    load_provider_pricing,
)
from src.utils.logger import get_logger

logger = get_logger("llm.anthropic")

# Hardcoded fallback — used only if config/llm.yaml cannot be loaded
_ANTHROPIC_COSTS_FALLBACK: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
    "claude-sonnet-4-5-20250929": {"input": 0.003, "output": 0.015},
    "claude-opus-4-6": {"input": 0.015, "output": 0.075},
    "claude-haiku-3-5": {"input": 0.0008, "output": 0.004},
}

# Load pricing from config/llm.yaml, merge with fallback
_ANTHROPIC_COSTS: dict[str, dict[str, float]] = {
    **_ANTHROPIC_COSTS_FALLBACK,
    **load_provider_pricing("anthropic"),
}

_DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude provider via the Messages API.

    Separates system messages from the conversation as required by
    the Anthropic API. Extracts Retry-After from rate limit errors.

    Args:
        api_key: Anthropic API key.
        default_model: Model to use when none specified.
        max_retries: Maximum retry attempts for transient failures.
    """

    def __init__(
        self,
        api_key: str,
        default_model: str = _DEFAULT_MODEL,
        max_retries: int = 3,
        request_timeout: float = 300.0,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._max_retries = max_retries
        self._client = anthropic.Anthropic(api_key=api_key, timeout=request_timeout)

        masked = api_key[:8] + "***" if len(api_key) > 8 else "***"
        logger.info(
            "AnthropicProvider initialized (key: %s, model: %s)",
            masked,
            default_model,
        )

    @property
    def provider_name(self) -> ProviderName:
        """Return ANTHROPIC provider identifier."""
        return ProviderName.ANTHROPIC

    @property
    def default_model(self) -> str:
        """Return the default Anthropic model."""
        return self._default_model

    def complete(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a completion request to the Anthropic Messages API.

        Args:
            messages: Provider-neutral messages. System messages are
                separated and passed via the ``system`` parameter.
            model: Model override (defaults to provider default).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.

        Returns:
            Standardized LLMResponse with usage and cost.

        Raises:
            LLMProviderError: On failure after all retries.
        """
        model = model or self._default_model

        # Separate system message from conversation
        system_content = ""
        conversation: list[dict[str, str]] = []
        for msg in messages:
            if msg.role == "system":
                system_content = msg.content
            else:
                conversation.append({"role": msg.role, "content": msg.content})

        def _do_call() -> LLMResponse:
            start = time.perf_counter()
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_content,
                messages=conversation,
            )
            latency = (time.perf_counter() - start) * 1000

            text = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

            cost = _estimate_cost(model, input_tokens, output_tokens)

            return LLMResponse(
                text=text,
                provider=ProviderName.ANTHROPIC,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency,
                cost_usd=cost,
            )

        return self._call_with_retry(_do_call, max_attempts=self._max_retries)

    def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMToolResponse:
        """Send a completion request with tool definitions.

        Handles the Anthropic Messages API tool_use flow. The response
        may contain text blocks, tool_use blocks, or both.

        Args:
            messages: Provider-neutral messages (system separated).
            tools: Anthropic-format tool definitions.
            model: Model override.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.

        Returns:
            LLMToolResponse with text and/or tool calls.
        """
        model = model or self._default_model

        system_content = ""
        conversation: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                system_content = msg.content if isinstance(msg.content, str) else ""
            else:
                # Content can be string (text) or list (tool_use / tool_result blocks)
                conversation.append({"role": msg.role, "content": msg.content})

        def _do_call() -> LLMToolResponse:
            start = time.perf_counter()
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_content,
                messages=conversation,
                tools=tools,
            )
            latency = (time.perf_counter() - start) * 1000

            text = None
            tool_calls: list[ToolCall] = []
            for block in response.content:
                if block.type == "text":
                    text = block.text
                elif block.type == "tool_use":
                    tool_calls.append(
                        ToolCall(
                            id=block.id,
                            name=block.name,
                            input=block.input,
                        )
                    )

            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = _estimate_cost(model, input_tokens, output_tokens)

            return LLMToolResponse(
                text=text,
                tool_calls=tool_calls,
                stop_reason=response.stop_reason,
                provider=ProviderName.ANTHROPIC,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency,
                cost_usd=cost,
            )

        return self._call_with_retry(_do_call, max_attempts=self._max_retries)

    def check_balance(self) -> dict[str, Any]:
        """Check Anthropic API key status.

        Returns:
            Dict with provider and status info.
        """
        return {
            "provider": "anthropic",
            "status": "active",
            "note": "Anthropic does not expose balance via API",
        }

    def list_models(self) -> list[str]:
        """List known Anthropic Claude models.

        Returns:
            List of model identifier strings.
        """
        return list(_ANTHROPIC_COSTS.keys())


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate API cost in USD based on token usage.

    Looks up pricing from config-loaded ``_ANTHROPIC_COSTS``. For unknown
    models, logs a warning and uses Sonnet-tier pricing as a reasonable default.

    Args:
        model: Model identifier.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD.
    """
    costs = _ANTHROPIC_COSTS.get(model)
    if costs is None:
        logger.warning(
            "Unknown Anthropic model '%s' — using Sonnet-tier pricing as fallback. "
            "Add this model to config/llm.yaml for accurate cost tracking.",
            model,
        )
        costs = {"input": 0.003, "output": 0.015}
    return input_tokens * costs["input"] / 1000 + output_tokens * costs["output"] / 1000

"""Base abstractions for multi-LLM provider support.

Defines provider-neutral data structures and the abstract base class
that all LLM providers must implement.
"""

import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("llm.base")


def load_provider_pricing(provider: str) -> dict[str, dict[str, float]]:
    """Load model pricing from config/llm.yaml for a provider.

    Returns a dict of ``{model_name: {"input": cost_per_1k, "output": cost_per_1k}}``.
    Falls back to an empty dict if the config cannot be loaded.
    """
    try:
        cfg = load_config("llm")
        models = cfg.get("providers", {}).get(provider, {}).get("models", {})
        result: dict[str, dict[str, float]] = {}
        for model_name, model_cfg in models.items():
            result[model_name] = {
                "input": model_cfg.get("cost_per_1k_input", 0.0),
                "output": model_cfg.get("cost_per_1k_output", 0.0),
            }
        return result
    except Exception:
        logger.debug("Could not load pricing from config for %s", provider)
        return {}


class ProviderName(str, Enum):
    """Supported LLM provider identifiers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    DEEPSEEK = "deepseek"
    CLAUDE_CODE = "claude_code"
    GEMINI_WEB = "gemini_web"


@dataclass
class LLMMessage:
    """Provider-neutral chat message.

    Attributes:
        role: Message role — "system", "user", or "assistant".
        content: Message text content, or a list of content blocks for
            multi-turn tool calling (tool_use / tool_result blocks).
    """

    role: str
    content: str | list[dict[str, Any]]


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider.

    Attributes:
        text: Generated text content.
        provider: Which provider produced this response.
        model: Model identifier used for generation.
        input_tokens: Number of input tokens consumed.
        output_tokens: Number of output tokens generated.
        latency_ms: Wall-clock latency in milliseconds.
        cost_usd: Estimated cost in USD.
        finish_reason: Why generation stopped — "stop" (normal) or "length" (truncated).
        timestamp: UTC timestamp of the response.
    """

    text: str
    provider: ProviderName
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    finish_reason: str = "stop"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class ToolCall:
    """A single tool invocation requested by the LLM.

    Attributes:
        id: Unique identifier for this tool call (used to match results).
        name: Name of the tool to invoke.
        input: Input parameters as a dict.
    """

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMToolResponse:
    """Response from an LLM that may include tool calls.

    Attributes:
        text: Generated text content (None if only tool calls).
        tool_calls: List of tool invocations requested by the model.
        stop_reason: Why the model stopped — "end_turn" or "tool_use".
        provider: Which provider produced this response.
        model: Model identifier used.
        input_tokens: Number of input tokens consumed.
        output_tokens: Number of output tokens generated.
        latency_ms: Wall-clock latency in milliseconds.
        cost_usd: Estimated cost in USD.
        timestamp: UTC timestamp of the response.
    """

    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: Literal["end_turn", "tool_use", "max_tokens"]
    provider: ProviderName
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    raw_assistant_content: Any = field(default=None, repr=False)
    trust_zone: str | None = field(default=None)
    regime_context: dict[str, Any] | None = field(default=None)


class LLMProviderError(Exception):
    """Raised when an LLM provider call fails after all retries.

    Attributes:
        provider: The provider that raised the error.
        retryable: Whether the error is retryable.
    """

    def __init__(
        self,
        message: str,
        provider: ProviderName | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class BaseLLMProvider(ABC):
    """Abstract base class for LLM provider implementations.

    Subclasses must implement ``complete``, ``check_balance``, and
    ``list_models``. The ``_call_with_retry`` helper provides shared
    retry logic with exponential backoff.
    """

    @property
    @abstractmethod
    def provider_name(self) -> ProviderName:
        """Return the provider identifier."""

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Return the default model name for this provider."""

    @abstractmethod
    def complete(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: List of provider-neutral messages.
            model: Model to use (defaults to provider default).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            **kwargs: Provider-specific options (e.g. ``grounding=True``
                for Google Search augmentation).

        Returns:
            Standardized LLMResponse.

        Raises:
            LLMProviderError: On failure after retries.
        """

    @abstractmethod
    def check_balance(self) -> dict[str, Any]:
        """Check API key balance / quota status.

        Returns:
            Provider-specific balance information dict.
        """

    @abstractmethod
    def list_models(self) -> list[str]:
        """List available models for this provider.

        Returns:
            List of model identifier strings.
        """

    def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMToolResponse:
        """Send a completion request with tool definitions.

        The model may respond with tool_use content blocks requesting
        that specific tools be executed. The caller is responsible for
        executing tools and sending results back.

        Args:
            messages: Provider-neutral messages.
            tools: Anthropic-format tool definitions.
            model: Model override.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.

        Returns:
            LLMToolResponse with text and/or tool calls.

        Raises:
            NotImplementedError: If the provider does not support tools.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support tool_use")

    def _call_with_retry(
        self,
        fn: Any,
        max_attempts: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> Any:
        """Execute a callable with exponential backoff retry.

        Handles rate-limit (429) responses by extracting the
        ``Retry-After`` header value when available.

        Args:
            fn: Zero-arg callable to execute.
            max_attempts: Maximum number of attempts.
            base_delay: Initial backoff delay in seconds.
            max_delay: Maximum backoff delay in seconds.

        Returns:
            The result of the callable.

        Raises:
            LLMProviderError: If all attempts are exhausted.
        """
        last_exception: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                return fn()
            except Exception as exc:
                last_exception = exc
                retry_after = _extract_retry_after(exc)

                if attempt < max_attempts:
                    if retry_after is not None:
                        delay = min(retry_after, max_delay) + random.uniform(0, 1)
                        logger.warning(
                            "Rate limited (429). Retry-After: %.1fs. "
                            "Attempt %d/%d. [%s]",
                            delay,
                            attempt,
                            max_attempts,
                            self.provider_name.value,
                        )
                    else:
                        delay = min(
                            base_delay * (2 ** (attempt - 1)), max_delay
                        ) + random.uniform(0, 1)
                        logger.warning(
                            "LLM error: %s. Retrying in %.1fs (attempt %d/%d). [%s]",
                            exc,
                            delay,
                            attempt,
                            max_attempts,
                            self.provider_name.value,
                        )
                    time.sleep(delay)
                else:
                    logger.error(
                        "All %d attempts exhausted for %s: %s",
                        max_attempts,
                        self.provider_name.value,
                        exc,
                    )

        raise LLMProviderError(
            f"{self.provider_name.value} call failed after "
            f"{max_attempts} attempts: {last_exception}",
            provider=self.provider_name,
            retryable=False,
        )


def _extract_retry_after(exc: Exception) -> float | None:
    """Extract Retry-After delay from an API rate limit exception.

    Handles:
    - Standard ``retry_after`` attribute (Anthropic/OpenAI SDKs)
    - HTTP 429 ``Retry-After`` header
    - Google SDK ``ResourceExhausted`` with ``_errors[].retry_delay``
    - Fallback: parse "retry after N" from exception message

    Returns:
        Retry delay in seconds, or ``None`` if not rate-limited.
    """
    # Standard SDK attribute
    if hasattr(exc, "retry_after"):
        retry_after = getattr(exc, "retry_after")
        if retry_after is not None:
            return float(retry_after)

    # Google SDK ResourceExhausted — _errors with retry_delay
    if hasattr(exc, "_errors"):
        for error in getattr(exc, "_errors", []):
            if hasattr(error, "retry_delay"):
                delay = error.retry_delay
                if hasattr(delay, "total_seconds"):
                    return delay.total_seconds()
                return float(delay)

    # HTTP status code based
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status_code == 429:
        response = getattr(exc, "response", None)
        if response is not None:
            headers = getattr(response, "headers", {})
            retry_header = headers.get("Retry-After") or headers.get("retry-after")
            if retry_header is not None:
                try:
                    return float(retry_header)
                except (ValueError, TypeError):
                    pass
        return 5.0

    # Fallback: parse "retry after N" from exception message
    exc_msg = str(exc).lower()
    if "resource exhausted" in exc_msg or "429" in exc_msg or "rate limit" in exc_msg:
        match = re.search(r"retry\s+after\s+(\d+)", exc_msg)
        if match:
            return float(match.group(1))
        return 5.0

    return None

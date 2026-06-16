"""OpenAI GPT LLM provider implementation.

Wraps the OpenAI Python SDK to conform to the BaseLLMProvider
interface. Maps LLMMessage to the OpenAI chat completion format.
"""

import time
from typing import Any

import openai

from src.llm.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMResponse,
    ProviderName,
)
from src.utils.logger import get_logger

logger = get_logger("llm.openai")

# Cost per 1K tokens in USD (approximate)
_OPENAI_COSTS: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
}

_DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT provider via the Chat Completions API.

    System messages are included directly in the messages array
    as OpenAI expects.

    Args:
        api_key: OpenAI API key.
        default_model: Model to use when none specified.
        max_retries: Maximum retry attempts for transient failures.
    """

    def __init__(
        self,
        api_key: str,
        default_model: str = _DEFAULT_MODEL,
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._max_retries = max_retries
        self._client = openai.OpenAI(api_key=api_key)

        masked = api_key[:8] + "***" if len(api_key) > 8 else "***"
        logger.info(
            "OpenAIProvider initialized (key: %s, model: %s)",
            masked,
            default_model,
        )

    @property
    def provider_name(self) -> ProviderName:
        """Return OPENAI provider identifier."""
        return ProviderName.OPENAI

    @property
    def default_model(self) -> str:
        """Return the default OpenAI model."""
        return self._default_model

    def complete(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a completion request to the OpenAI Chat Completions API.

        Args:
            messages: Provider-neutral messages mapped to OpenAI format.
            model: Model override (defaults to provider default).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.

        Returns:
            Standardized LLMResponse with usage and cost.

        Raises:
            LLMProviderError: On failure after all retries.
        """
        model = model or self._default_model

        # Map to OpenAI format (system messages stay in array)
        openai_messages = [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]

        def _do_call() -> LLMResponse:
            start = time.perf_counter()
            response = self._client.chat.completions.create(
                model=model,
                messages=openai_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            latency = (time.perf_counter() - start) * 1000

            text = response.choices[0].message.content or ""
            input_tokens = getattr(response.usage, "prompt_tokens", 0)
            output_tokens = getattr(response.usage, "completion_tokens", 0)

            cost = _estimate_cost(model, input_tokens, output_tokens)

            return LLMResponse(
                text=text,
                provider=ProviderName.OPENAI,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency,
                cost_usd=cost,
            )

        return self._call_with_retry(_do_call, max_attempts=self._max_retries)

    def check_balance(self) -> dict[str, Any]:
        """Check OpenAI API key status.

        Returns:
            Dict with provider and status info.
        """
        return {
            "provider": "openai",
            "status": "active",
            "note": "OpenAI does not expose balance via completions API",
        }

    def list_models(self) -> list[str]:
        """List known OpenAI GPT models.

        Returns:
            List of model identifier strings.
        """
        return list(_OPENAI_COSTS.keys())


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate API cost in USD based on token usage.

    Args:
        model: Model identifier.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD.
    """
    costs = _OPENAI_COSTS.get(model, {"input": 0.0025, "output": 0.01})
    return input_tokens * costs["input"] / 1000 + output_tokens * costs["output"] / 1000

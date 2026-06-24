"""DeepSeek V3.2 LLM provider — OpenAI-compatible API.

Reuses the OpenAI Python SDK with ``base_url`` pointed at
``https://api.deepseek.com``.  Two models available:

- ``deepseek-chat``: Non-thinking mode (fast, 8K max output)
- ``deepseek-reasoner``: Thinking mode (deep reasoning, 64K max output)

Pricing (per 1M tokens): input $0.28 / output $0.42.
Cache hit input: $0.028 (90% discount).
"""

from typing import Any

import openai

from src.llm.base import LLMMessage, LLMResponse, LLMToolResponse, ProviderName
from src.llm.openai import OpenAIProvider
from src.utils.logger import get_logger

logger = get_logger("llm.deepseek")

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

_DEEPSEEK_COSTS: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.00028, "output": 0.00042},
    "deepseek-reasoner": {"input": 0.00028, "output": 0.00042},
}


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek provider via OpenAI-compatible Chat Completions API.

    Inherits retry logic and message formatting from ``OpenAIProvider``.
    Only overrides client initialization (base_url) and provider identity.

    Args:
        api_key: DeepSeek API key.
        default_model: Model to use when none specified.
        max_retries: Maximum retry attempts for transient failures.
    """

    def __init__(
        self,
        api_key: str,
        default_model: str = "deepseek-chat",
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._max_retries = max_retries
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=_DEEPSEEK_BASE_URL,
        )

        masked = api_key[:8] + "***" if len(api_key) > 8 else "***"
        logger.info(
            "DeepSeekProvider initialized (key: %s, model: %s)",
            masked,
            default_model,
        )

    @property
    def provider_name(self) -> ProviderName:
        """Return DEEPSEEK provider identifier."""
        return ProviderName.DEEPSEEK

    def complete(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> LLMResponse:
        """Override to enforce min max_tokens for deepseek-reasoner.

        Thinking mode consumes output tokens for reasoning. If
        max_tokens is too small, all tokens go to thinking and the
        visible output is empty.
        """
        model = model or self._default_model
        if model == "deepseek-reasoner" and max_tokens < 4096:
            max_tokens = 4096
        # DeepSeek API hard limit: max_tokens ∈ [1, 8192]
        max_tokens = min(max_tokens, 8192)
        return super().complete(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMToolResponse:
        """Override to enforce min max_tokens for deepseek-reasoner."""
        model = model or self._default_model
        if model == "deepseek-reasoner" and max_tokens < 4096:
            max_tokens = 4096
        # DeepSeek API hard limit: max_tokens ∈ [1, 8192]
        max_tokens = min(max_tokens, 8192)
        return super().complete_with_tools(
            messages,
            tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def list_models(self) -> list[str]:
        """List known DeepSeek models."""
        return list(_DEEPSEEK_COSTS.keys())


def _estimate_deepseek_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate DeepSeek API cost in USD."""
    costs = _DEEPSEEK_COSTS.get(model, {"input": 0.00028, "output": 0.00042})
    return input_tokens * costs["input"] / 1000 + output_tokens * costs["output"] / 1000

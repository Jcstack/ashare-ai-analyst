"""OpenAI GPT LLM provider implementation.

Wraps the OpenAI Python SDK to conform to the BaseLLMProvider
interface. Maps LLMMessage to the OpenAI chat completion format.
"""

import json
import time
from typing import Any

import openai

from src.llm.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMResponse,
    LLMToolResponse,
    ProviderName,
    ToolCall,
)
from src.utils.logger import get_logger

logger = get_logger("llm.openai")

# Cost per 1K tokens in USD (approximate, March 2026)
_OPENAI_COSTS: dict[str, dict[str, float]] = {
    # GPT-5.4 family (March 2026)
    "gpt-5.4": {"input": 0.0025, "output": 0.015},
    "gpt-5.4-mini": {"input": 0.00075, "output": 0.0045},
    "gpt-5.4-nano": {"input": 0.0002, "output": 0.00125},
    # GPT-4.1 family
    "gpt-4.1": {"input": 0.002, "output": 0.008},
    "gpt-4.1-mini": {"input": 0.0004, "output": 0.0016},
    "gpt-4.1-nano": {"input": 0.0001, "output": 0.0004},
    # O-series reasoning models
    "o3": {"input": 0.002, "output": 0.008},
    "o4-mini": {"input": 0.0011, "output": 0.0044},
    "o3-mini": {"input": 0.0011, "output": 0.0044},
    # Legacy
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
}

_DEFAULT_MODEL = "gpt-5.4-mini"


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

        # GPT-5.x and o-series require max_completion_tokens instead of max_tokens
        use_new_param = any(model.startswith(p) for p in ("gpt-5", "o3", "o4", "o1"))

        def _do_call() -> LLMResponse:
            start = time.perf_counter()
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": openai_messages,
            }
            if use_new_param:
                kwargs["max_completion_tokens"] = max_tokens
            else:
                kwargs["max_tokens"] = max_tokens
                kwargs["temperature"] = temperature
            response = self._client.chat.completions.create(**kwargs)
            latency = (time.perf_counter() - start) * 1000

            text = response.choices[0].message.content or ""
            input_tokens = getattr(response.usage, "prompt_tokens", 0)
            output_tokens = getattr(response.usage, "completion_tokens", 0)

            cost = _estimate_cost(model, input_tokens, output_tokens)

            return LLMResponse(
                text=text,
                provider=self.provider_name,
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
        """Send a completion request with tool (function) definitions.

        Converts Anthropic-format tool definitions to OpenAI function
        calling format, then parses the response back into a
        provider-neutral ``LLMToolResponse``.

        Args:
            messages: Provider-neutral messages.
            tools: Anthropic-format tool definitions.
            model: Model override.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.

        Returns:
            LLMToolResponse with text and/or tool calls.
        """
        model = model or self._default_model

        openai_messages = _build_openai_messages(messages)
        openai_tools = _convert_tools_to_openai(tools)

        use_new_param = any(model.startswith(p) for p in ("gpt-5", "o3", "o4", "o1"))

        def _do_call() -> LLMToolResponse:
            start = time.perf_counter()
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": openai_messages,
                "tools": openai_tools if openai_tools else openai.NOT_GIVEN,
            }
            if use_new_param:
                kwargs["max_completion_tokens"] = max_tokens
            else:
                kwargs["max_tokens"] = max_tokens
                kwargs["temperature"] = temperature
            response = self._client.chat.completions.create(**kwargs)
            latency = (time.perf_counter() - start) * 1000

            choice = response.choices[0]
            text = choice.message.content
            tool_calls: list[ToolCall] = []

            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    tool_calls.append(
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            input=args,
                        )
                    )

            stop_reason = (
                "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"
            )

            input_tokens = getattr(response.usage, "prompt_tokens", 0)
            output_tokens = getattr(response.usage, "completion_tokens", 0)
            cost = _estimate_cost(model, input_tokens, output_tokens)

            return LLMToolResponse(
                text=text,
                tool_calls=tool_calls,
                stop_reason=stop_reason,
                provider=self.provider_name,
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


def _build_openai_messages(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    """Convert LLMMessages to OpenAI chat format.

    Handles multi-turn tool calling by converting Anthropic-style
    content blocks (tool_use / tool_result) to OpenAI format.
    """
    result: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg.content, str):
            result.append({"role": msg.role, "content": msg.content})
        elif isinstance(msg.content, list):
            # Multi-turn tool calling: convert Anthropic blocks → OpenAI format
            if msg.role == "assistant":
                text_parts = []
                tool_calls = []
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append(
                                {
                                    "id": block.get("id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": block.get("name", ""),
                                        "arguments": json.dumps(
                                            block.get("input", {}), ensure_ascii=False
                                        ),
                                    },
                                }
                            )
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": "\n".join(text_parts) if text_parts else None,
                }
                if tool_calls:
                    entry["tool_calls"] = tool_calls
                result.append(entry)
            elif msg.role == "user":
                # tool_result blocks → OpenAI "tool" role messages
                for block in msg.content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        content = block.get("content", "")
                        if isinstance(content, list):
                            content = json.dumps(content, ensure_ascii=False)
                        result.append(
                            {
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id", ""),
                                "content": str(content),
                            }
                        )
                    elif isinstance(block, dict) and block.get("type") == "text":
                        result.append(
                            {"role": "user", "content": block.get("text", "")}
                        )
                    else:
                        result.append({"role": "user", "content": str(block)})
        else:
            result.append({"role": msg.role, "content": str(msg.content)})
    return result


def _convert_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-format tool definitions to OpenAI function format.

    Anthropic: ``{"name", "description", "input_schema": {...}}``
    OpenAI:    ``{"type": "function", "function": {"name", "description", "parameters": {...}}}``
    """
    result = []
    for tool in tools:
        schema = tool.get("input_schema", {})
        # Strip keys unsupported by OpenAI strict mode
        clean = {k: v for k, v in schema.items() if k != "additionalProperties"}
        result.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": clean,
                },
            }
        )
    return result


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate API cost in USD based on token usage."""
    costs = _OPENAI_COSTS.get(model, {"input": 0.0025, "output": 0.01})
    return input_tokens * costs["input"] / 1000 + output_tokens * costs["output"] / 1000

"""Google Gemini LLM provider implementation.

Wraps the google-genai SDK to conform to the BaseLLMProvider
interface. Maps system messages to the ``system_instruction`` parameter.
"""

import time
from typing import Any

from google import genai
from google.genai import types

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

logger = get_logger("llm.google")

# Hardcoded fallback — used only if config/llm.yaml cannot be loaded
_GOOGLE_COSTS_FALLBACK: dict[str, dict[str, float]] = {
    "gemini-2.5-pro": {"input": 0.00125, "output": 0.01},
    "gemini-2.5-flash": {"input": 0.00015, "output": 0.0006},
    "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
}

# Load pricing from config/llm.yaml, merge with fallback
_GOOGLE_COSTS: dict[str, dict[str, float]] = {
    **_GOOGLE_COSTS_FALLBACK,
    **load_provider_pricing("google"),
}

_DEFAULT_MODEL = "gemini-2.5-flash"


class GoogleProvider(BaseLLMProvider):
    """Google Gemini provider via the google-genai SDK.

    System messages are passed as the ``system_instruction`` parameter
    in ``GenerateContentConfig``. Conversation messages are mapped to Gemini
    ``Content`` format.

    Args:
        api_key: Google AI API key.
        default_model: Model to use when none specified.
        max_retries: Maximum retry attempts for transient failures.
        request_timeout: Request timeout in seconds.
        fallback_model: Optional fallback model on primary failure.
    """

    def __init__(
        self,
        api_key: str,
        default_model: str = _DEFAULT_MODEL,
        max_retries: int = 2,
        request_timeout: float = 60.0,
        fallback_model: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._max_retries = max_retries
        self._request_timeout = request_timeout
        self._fallback_model = fallback_model
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(request_timeout * 1000)),
        )

        masked = api_key[:8] + "***" if len(api_key) > 8 else "***"
        logger.info(
            "GoogleProvider initialized (key: %s, model: %s, fallback: %s)",
            masked,
            default_model,
            fallback_model or "none",
        )

    @property
    def provider_name(self) -> ProviderName:
        """Return GOOGLE provider identifier."""
        return ProviderName.GOOGLE

    @property
    def default_model(self) -> str:
        """Return the default Google model."""
        return self._default_model

    def complete(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a completion request to the Gemini API.

        Args:
            messages: Provider-neutral messages. System messages are
                extracted and passed via ``system_instruction``.
            model: Model override (defaults to provider default).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            **kwargs: Optional ``grounding=True`` to enable Google Search
                grounding for this call.

        Returns:
            Standardized LLMResponse with usage and cost.

        Raises:
            LLMProviderError: On failure after all retries.
        """
        model = model or self._default_model
        grounding = kwargs.get("grounding", False)

        # Separate system instruction from conversation
        system_instruction = None
        conversation_parts: list[types.Content] = []
        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content
            else:
                # Gemini uses "user" and "model" roles
                role = "model" if msg.role == "assistant" else "user"
                conversation_parts.append(
                    types.Content(role=role, parts=[types.Part(text=msg.content)])
                )

        def _do_call(use_model: str = model) -> LLMResponse:
            # Grounding: augment with Google Search when requested
            tools_config = None
            if grounding:
                tools_config = [types.Tool(google_search=types.GoogleSearch())]

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=max_tokens,
                temperature=temperature,
                tools=tools_config,
                http_options=types.HttpOptions(
                    timeout=int(self._request_timeout * 1000)
                ),
            )

            start = time.perf_counter()
            response = self._client.models.generate_content(
                model=use_model,
                contents=conversation_parts,
                config=config,
            )
            latency = (time.perf_counter() - start) * 1000

            # Extract text — handle safety-blocked responses
            try:
                text = response.text or ""
            except (ValueError, AttributeError):
                text = ""

            # Extract finish_reason for truncation detection
            finish_reason = "stop"
            if response.candidates:
                raw_reason = getattr(response.candidates[0], "finish_reason", None)
                if raw_reason is not None:
                    reason_str = str(raw_reason).upper()
                    if "MAX_TOKENS" in reason_str or "LENGTH" in reason_str:
                        finish_reason = "length"
                    elif "SAFETY" in reason_str:
                        finish_reason = "safety"
                        logger.warning(
                            "Gemini response blocked by safety filter (model=%s)",
                            use_model,
                        )

            if not text and finish_reason != "stop":
                logger.warning(
                    "Gemini returned empty text: model=%s finish_reason=%s",
                    use_model,
                    finish_reason,
                )

            # Extract token usage from response metadata
            # Note: getattr default only applies when attr is missing, not when it's None
            usage = getattr(response, "usage_metadata", None)
            input_tokens = (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
            output_tokens = (
                (getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
            )

            if usage is None:
                logger.warning(
                    "Google API response missing usage_metadata — "
                    "token counts will be 0 (model: %s)",
                    use_model,
                )
            elif input_tokens == 0 and conversation_parts:
                logger.warning(
                    "Google API returned 0 input tokens despite non-empty prompt "
                    "(model: %s) — cost estimate will be inaccurate",
                    use_model,
                )

            cost = _estimate_cost(use_model, input_tokens, output_tokens)

            return LLMResponse(
                text=text,
                provider=ProviderName.GOOGLE,
                model=use_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency,
                cost_usd=cost,
                finish_reason=finish_reason,
            )

        try:
            return self._call_with_retry(_do_call, max_attempts=self._max_retries)
        except Exception:
            if self._fallback_model and self._fallback_model != model:
                logger.warning(
                    "Primary model %s failed, falling back to %s",
                    model,
                    self._fallback_model,
                )
                return self._call_with_retry(
                    lambda: _do_call(self._fallback_model),
                    max_attempts=self._max_retries,
                )
            raise

    def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMToolResponse:
        """Send a completion request with tool definitions via Gemini function calling.

        Converts Anthropic-format tool definitions to Gemini ``FunctionDeclaration``
        format, then parses function call responses back into ``ToolCall`` objects.

        Handles multi-round tool calling by converting structured content blocks
        (tool_use / tool_result) to Gemini function_call / function_response parts.

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

        # Separate system instruction from conversation
        system_instruction = None
        conversation_parts: list[types.Content] = []
        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content if isinstance(msg.content, str) else ""
            else:
                role = "model" if msg.role == "assistant" else "user"
                parts = _build_gemini_parts(msg.content, role)
                conversation_parts.append(types.Content(role=role, parts=parts))

        # Convert Anthropic tool format to Gemini FunctionDeclaration
        gemini_tools = _convert_tools_to_gemini(tools)

        def _do_call(use_model: str = model) -> LLMToolResponse:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=max_tokens,
                temperature=temperature,
                tools=gemini_tools if gemini_tools else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
                http_options=types.HttpOptions(
                    timeout=int(self._request_timeout * 1000)
                ),
            )

            start = time.perf_counter()
            response = self._client.models.generate_content(
                model=use_model,
                contents=conversation_parts,
                config=config,
            )
            latency = (time.perf_counter() - start) * 1000

            text = None
            tool_calls: list[ToolCall] = []

            parts = response.parts or []
            for part in parts:
                fc = getattr(part, "function_call", None)
                if fc and fc.name:
                    tool_calls.append(
                        ToolCall(
                            id=f"call_{fc.name}_{int(time.time() * 1000)}",
                            name=fc.name,
                            input=dict(fc.args) if fc.args else {},
                        )
                    )
                elif getattr(part, "text", None):
                    text = part.text

            stop_reason = "tool_use" if tool_calls else "end_turn"

            # Preserve raw content for multi-round tool calling
            # (Google requires thought_signature in function_call parts)
            raw_content = None
            if tool_calls and response.candidates:
                raw_content = response.candidates[0].content

            usage = getattr(response, "usage_metadata", None)
            input_tokens = (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
            output_tokens = (
                (getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
            )

            if usage is None:
                logger.warning(
                    "Google tool_use response missing usage_metadata — "
                    "token counts will be 0 (model: %s)",
                    use_model,
                )
            elif input_tokens == 0 and conversation_parts:
                logger.warning(
                    "Google tool_use returned 0 input tokens despite non-empty "
                    "prompt (model: %s) — cost estimate will be inaccurate",
                    use_model,
                )

            cost = _estimate_cost(use_model, input_tokens, output_tokens)

            return LLMToolResponse(
                text=text,
                tool_calls=tool_calls,
                stop_reason=stop_reason,
                provider=ProviderName.GOOGLE,
                model=use_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency,
                cost_usd=cost,
                raw_assistant_content=raw_content,
            )

        try:
            return self._call_with_retry(_do_call, max_attempts=self._max_retries)
        except Exception:
            if self._fallback_model and self._fallback_model != model:
                logger.warning(
                    "Primary model %s failed (tools), falling back to %s",
                    model,
                    self._fallback_model,
                )
                return self._call_with_retry(
                    lambda: _do_call(self._fallback_model),
                    max_attempts=self._max_retries,
                )
            raise

    def check_balance(self) -> dict[str, Any]:
        """Check Google AI API key status.

        Returns:
            Dict with provider and status info.
        """
        return {
            "provider": "google",
            "status": "active",
            "note": "Google AI does not expose balance via API",
        }

    def list_models(self) -> list[str]:
        """List known Google Gemini models.

        Returns:
            List of model identifier strings.
        """
        return list(_GOOGLE_COSTS.keys())


def _build_gemini_parts(content: Any, role: str) -> list[Any]:
    """Convert message content to Gemini-compatible parts.

    Handles:
    - Plain string content
    - Raw Gemini Content objects (preserved for thought_signature support)
    - Structured content blocks (tool_use / tool_result) from the agent loop

    Args:
        content: String, Gemini Content, or list of content blocks.
        role: Gemini role ("model" or "user").

    Returns:
        List of Gemini content parts.
    """
    if isinstance(content, str):
        return [types.Part(text=content)]

    # Raw Gemini Content object — use its parts directly (preserves thought_signature)
    if hasattr(content, "parts"):
        return list(content.parts)

    # Structured content blocks from the agent tool loop
    if not isinstance(content, list):
        return [types.Part(text=str(content))]

    parts: list[Any] = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(types.Part(text=str(block)))
            continue

        block_type = block.get("type", "")

        if block_type == "text":
            parts.append(types.Part(text=block["text"]))

        elif block_type == "tool_use" and role == "model":
            # Convert to Gemini function_call part
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(
                        name=block["name"],
                        args=block.get("input", {}),
                    )
                )
            )

        elif block_type == "tool_result" and role == "user":
            # Convert to Gemini function_response part
            result_content = block.get("content", "")
            func_name = block.get("tool_name") or block.get("tool_use_id", "unknown")
            parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=func_name,
                        response={"result": result_content},
                    )
                )
            )

    return parts if parts else [types.Part(text="")]


def _convert_tools_to_gemini(
    tools: list[dict[str, Any]],
) -> list[types.Tool] | None:
    """Convert Anthropic-format tool definitions to Gemini FunctionDeclaration format.

    Anthropic format: [{"name": ..., "description": ..., "input_schema": {...}}]
    Gemini format: [Tool(function_declarations=[FunctionDeclaration(...)])]

    Args:
        tools: Anthropic-format tool definitions.

    Returns:
        List of Gemini Tool objects, or None if empty.
    """
    if not tools:
        return None

    declarations = []
    for tool in tools:
        params = tool.get("input_schema", {})
        # Strip unsupported JSON Schema keys that Gemini rejects
        clean_params = _clean_schema_for_gemini(params) if params else None
        declarations.append(
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=clean_params,
            )
        )

    return [types.Tool(function_declarations=declarations)]


def _clean_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove JSON Schema keys unsupported by Gemini (additionalProperties, etc).

    Args:
        schema: JSON Schema dict.

    Returns:
        Cleaned schema dict.
    """
    unsupported = {"additionalProperties", "$schema", "default"}
    cleaned: dict[str, Any] = {}
    for k, v in schema.items():
        if k in unsupported:
            continue
        if isinstance(v, dict):
            cleaned[k] = _clean_schema_for_gemini(v)
        elif k == "properties" and isinstance(v, dict):
            cleaned[k] = {pk: _clean_schema_for_gemini(pv) for pk, pv in v.items()}
        else:
            cleaned[k] = v
    return cleaned


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate API cost in USD based on token usage.

    Looks up pricing from config-loaded ``_GOOGLE_COSTS``. For unknown
    models, logs a warning and uses Flash-tier pricing as a reasonable default.

    Args:
        model: Model identifier.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD.
    """
    costs = _GOOGLE_COSTS.get(model)
    if costs is None:
        logger.warning(
            "Unknown Google model '%s' — using Flash-tier pricing as fallback. "
            "Add this model to config/llm.yaml for accurate cost tracking.",
            model,
        )
        costs = {"input": 0.0001, "output": 0.0004}
    return input_tokens * costs["input"] / 1000 + output_tokens * costs["output"] / 1000

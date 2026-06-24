"""Claude Code Bridge LLM provider.

Wraps the Claude Code HTTP bridge (``scripts/claude_code_bridge.py``)
as a standard ``BaseLLMProvider``.  No Anthropic API key required —
uses the host-side ``claude`` CLI's own credentials.

The bridge spawns ``claude -p`` per call, so latency is higher than
direct API calls.  Best suited as a primary provider for ``complete()``
with Google or Anthropic as fallback for ``complete_with_tools()``.
"""

import os
import time
from typing import Any

import httpx

from src.llm.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    ProviderName,
)
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("llm.bridge")

_DEFAULT_MODEL = "opus"


class ClaudeCodeBridgeProvider(BaseLLMProvider):
    """LLM provider that delegates to the Claude Code HTTP bridge.

    Converts ``LLMMessage`` lists into a flat prompt and calls the
    bridge's ``POST /v1/chat`` endpoint.  Token counts are estimated
    from character length (no exact tokenizer available).

    Args:
        bridge_url: HTTP base URL of the bridge service.
        model: Claude Code model alias (``"sonnet"``, ``"opus"``, etc.).
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        bridge_url: str | None = None,
        model: str = _DEFAULT_MODEL,
        timeout: float | None = None,
    ) -> None:
        # Resolve bridge URL: env override > param > config > default
        # In Docker: use "url" (host.docker.internal); on host: use "host_url" (localhost)
        cfg: dict = {}
        if bridge_url is None:
            bridge_url = os.environ.get("CLAUDE_CODE_BRIDGE_URL", "")
        if not bridge_url:
            try:
                cfg = load_config("llm").get("claude_code_bridge", {})
                in_docker = os.path.exists("/.dockerenv")
                if in_docker:
                    bridge_url = cfg.get("url", "http://host.docker.internal:19821")
                else:
                    bridge_url = cfg.get("host_url", "http://localhost:19821")
            except Exception:
                bridge_url = "http://localhost:19821"

        # Resolve timeout: explicit param > config > 900s default
        if timeout is None:
            if not cfg:
                try:
                    cfg = load_config("llm").get("claude_code_bridge", {})
                except Exception:
                    cfg = {}
            timeout = float(cfg.get("timeout", 900))

        self._bridge_url = bridge_url.rstrip("/")
        self._model = model
        self._timeout = timeout

        logger.info(
            "ClaudeCodeBridgeProvider initialized (url: %s, model: %s)",
            self._bridge_url,
            model,
        )

    @property
    def provider_name(self) -> ProviderName:
        """Return CLAUDE_CODE provider identifier."""
        return ProviderName.CLAUDE_CODE

    @property
    def default_model(self) -> str:
        """Return the configured Claude Code model alias."""
        return self._model

    def complete(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a completion request via the Claude Code bridge.

        Converts the message list into a system prompt + user message,
        calls the bridge, and wraps the result as an ``LLMResponse``.

        Args:
            messages: Provider-neutral messages.
            model: Claude Code model alias (e.g. ``"sonnet"``, ``"opus"``).
                Falls back to the provider's default model if not provided.
            max_tokens: Ignored — bridge manages its own token limits.
            temperature: Ignored — bridge uses claude defaults.
            **kwargs: Absorbed silently (e.g. ``grounding``).

        Returns:
            Standardized LLMResponse with estimated token counts.

        Raises:
            LLMProviderError: On bridge connection, timeout, or HTTP error.
        """
        effective_model = model or self._model
        system_prompt, user_message = self._format_messages(messages)

        start = time.perf_counter()
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{self._bridge_url}/v1/chat",
                    json={
                        "message": user_message,
                        "system_prompt": system_prompt,
                        "model": effective_model,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError as exc:
            raise LLMProviderError(
                f"Claude Code bridge unreachable at {self._bridge_url}: {exc}",
                provider=ProviderName.CLAUDE_CODE,
                retryable=True,
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                f"Claude Code bridge timeout after {self._timeout}s: {exc}",
                provider=ProviderName.CLAUDE_CODE,
                retryable=True,
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                detail = exc.response.json().get("error", "")
            except Exception:
                pass
            raise LLMProviderError(
                f"Claude Code bridge HTTP {exc.response.status_code}: {detail}",
                provider=ProviderName.CLAUDE_CODE,
                retryable=exc.response.status_code >= 500,
            ) from exc

        latency = (time.perf_counter() - start) * 1000
        text = data.get("text", "")

        # Estimate tokens from character count (~4 chars/token for mixed CJK/EN)
        input_chars = len(system_prompt) + len(user_message)
        output_chars = len(text)
        est_input_tokens = max(1, input_chars // 4)
        est_output_tokens = max(1, output_chars // 4)

        return LLMResponse(
            text=text,
            provider=ProviderName.CLAUDE_CODE,
            model=f"claude_code:{self._model}",
            input_tokens=est_input_tokens,
            output_tokens=est_output_tokens,
            latency_ms=latency,
            cost_usd=0.0,  # No direct API cost — uses Claude Code subscription
        )

    def check_balance(self) -> dict[str, Any]:
        """Check bridge health status."""
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{self._bridge_url}/health")
                resp.raise_for_status()
                return {
                    "provider": "claude_code",
                    "status": "active",
                    **resp.json(),
                }
        except Exception as exc:
            return {
                "provider": "claude_code",
                "status": "unreachable",
                "error": str(exc),
            }

    def list_models(self) -> list[str]:
        """List available Claude Code model aliases."""
        return ["sonnet", "opus", "haiku"]

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _format_messages(messages: list[LLMMessage]) -> tuple[str, str]:
        """Convert LLMMessage list into (system_prompt, user_message).

        System messages are concatenated into the system prompt.
        Remaining messages are formatted as a conversation block
        passed as the user message to the bridge.
        """
        system_parts: list[str] = []
        conversation_parts: list[str] = []

        for msg in messages:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if msg.role == "system":
                system_parts.append(content)
            elif msg.role == "user":
                conversation_parts.append(content)
            elif msg.role == "assistant":
                conversation_parts.append(f"[assistant]: {content}")

        system_prompt = "\n\n".join(system_parts)

        # If there's only one user message, send it directly.
        # For multi-turn, format as conversation.
        user_messages = [m for m in messages if m.role == "user"]
        if len(user_messages) == 1 and not any(m.role == "assistant" for m in messages):
            user_message = conversation_parts[0] if conversation_parts else ""
        else:
            user_message = "\n\n".join(conversation_parts)

        return system_prompt, user_message

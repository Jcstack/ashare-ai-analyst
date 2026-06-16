"""LLM Gateway — governance wrapper around LLMRouter.

Adds audit logging, timeout enforcement, caller attribution,
usage tracking, and in-flight request deduplication to every
LLM call without requiring service rewrites.

Part of WS1: Unify Scattered AI Analysis.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from src.llm.base import (
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    LLMToolResponse,
    ProviderName,
)
from src.llm.router import LLMRouter, RoutingStrategy
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("llm.gateway")

# Audit event type constant
EVENT_LLM_CALL = "llm_call"


class LLMGateway:
    """Thin governance wrapper around ``LLMRouter``.

    Duck-type compatible with ``LLMRouter`` — callers can swap in
    ``LLMGateway`` without changing call signatures (just add the
    mandatory ``caller`` parameter).

    Features:
        - **Audit logging**: every call recorded with caller, latency,
          tokens, cost, and success/failure.
        - **Caller attribution**: mandatory ``caller`` string for
          tracing which service made each call.
        - **Timeout enforcement**: per-call timeout (default 60s).
        - **Usage tracking**: delegates to router's UsageTracker.
        - **In-flight deduplication**: identical concurrent requests
          share a single LLM call via asyncio futures.

    Args:
        router: Underlying LLMRouter instance.
        audit_log: Optional ImmutableAuditLog for recording events.
        default_timeout: Default timeout per LLM call in seconds.
    """

    def __init__(
        self,
        router: LLMRouter,
        audit_log: Any | None = None,
        default_timeout: float = 360.0,
    ) -> None:
        self._router = router
        self._audit_log = audit_log
        self._default_timeout = default_timeout
        # In-flight dedup: hash -> (Event, result/error, timestamp)
        self._dedup_lock = threading.Lock()
        self._inflight: dict[str, tuple[threading.Event, list]] = {}
        # Caller-based model routing: prefix -> model name
        self._caller_model_map: dict[str, str] = self._load_caller_model_map()
        # Dynamic upgrade rules: cost model → quality model
        self._upgrade_rules: dict[str, Any] = self._load_upgrade_rules()
        # Grounding config: which callers get Google Search augmentation
        self._grounding_cfg: dict[str, Any] = self._load_grounding_config()

    # ── Proxy properties ─────────────────────────────────────

    @property
    def available_providers(self) -> list[ProviderName]:
        return self._router.available_providers

    @property
    def usage_tracker(self):
        return self._router.usage_tracker

    def get_provider(self, name: ProviderName):
        return self._router.get_provider(name)

    def select_provider(self, strategy: RoutingStrategy):
        return self._router.select_provider(strategy)

    # ── Caller-based model routing ─────────────────────────

    @staticmethod
    def _load_caller_model_map() -> dict[str, str]:
        """Load caller → model mapping from config/llm.yaml."""
        try:
            cfg = load_config("llm")
            raw = cfg.get("caller_model_map", {})
            if isinstance(raw, dict):
                return {str(k): str(v) for k, v in raw.items()}
        except Exception:
            pass
        return {}

    @staticmethod
    def _load_upgrade_rules() -> dict[str, Any]:
        """Load dynamic upgrade rules from config/llm.yaml."""
        try:
            cfg = load_config("llm")
            raw = cfg.get("upgrade_rules", {})
            if isinstance(raw, dict) and raw.get("quality_model"):
                return {
                    "quality_model": str(raw["quality_model"]),
                    "cost_models": [str(m) for m in raw.get("cost_models", [])],
                    "keywords": [str(k) for k in raw.get("keywords", [])],
                    "context_length_threshold": int(
                        raw.get("context_length_threshold", 5000)
                    ),
                }
        except Exception:
            pass
        return {}

    @staticmethod
    def _load_grounding_config() -> dict[str, Any]:
        """Load Gemini Grounding configuration from config/llm.yaml."""
        try:
            cfg = load_config("llm")
            raw = cfg.get("grounding", {})
            if isinstance(raw, dict) and raw.get("enabled"):
                return {
                    "enabled": True,
                    "enabled_callers": [str(c) for c in raw.get("enabled_callers", [])],
                }
        except Exception:
            pass
        return {"enabled": False, "enabled_callers": []}

    def _should_ground(self, caller: str) -> bool:
        """Check if a caller should use Gemini Grounding (Google Search).

        Uses prefix matching: caller ``"review_agent.review_candidates"``
        matches enabled caller ``"review_agent"``.
        """
        if not self._grounding_cfg.get("enabled"):
            return False
        for prefix in self._grounding_cfg.get("enabled_callers", []):
            if caller.startswith(prefix):
                return True
        return False

    def _maybe_upgrade_model(
        self, model: str | None, messages: list[LLMMessage]
    ) -> str | None:
        """Upgrade a cost-tier model to quality model if content signals complexity.

        Checks two triggers:
        1. **Keyword match**: any user message contains a high-priority keyword
           (e.g. "财报分析", "估值", "DCF").
        2. **Context length**: total message content exceeds threshold (default 5000 chars).

        Only upgrades models listed in ``cost_models``. Quality-tier models and
        unresolved (None) models pass through unchanged.
        """
        if not self._upgrade_rules or not model:
            return model
        cost_models = self._upgrade_rules.get("cost_models", [])
        if model not in cost_models:
            return model

        quality_model = self._upgrade_rules["quality_model"]
        keywords = self._upgrade_rules.get("keywords", [])
        threshold = self._upgrade_rules.get("context_length_threshold", 5000)

        # Collect user message text for scanning
        total_len = 0
        for msg in messages:
            text = (
                msg.content
                if isinstance(msg.content, str)
                else json.dumps(msg.content, ensure_ascii=False)
            )
            total_len += len(text)
            # Keyword trigger — only check user messages
            if msg.role == "user" and keywords:
                for kw in keywords:
                    if kw in text:
                        logger.info(
                            "Dynamic upgrade: %s → %s (keyword '%s')",
                            model,
                            quality_model,
                            kw,
                        )
                        return quality_model

        # Context length trigger
        if total_len > threshold:
            logger.info(
                "Dynamic upgrade: %s → %s (context %d > %d)",
                model,
                quality_model,
                total_len,
                threshold,
            )
            return quality_model

        return model

    def _resolve_caller_model(self, caller: str) -> str | None:
        """Resolve a caller string to a model override via prefix matching.

        Tries longest-prefix-first matching. Returns None if no match
        (provider default will be used).
        """
        if not self._caller_model_map or not caller:
            return None
        # Exact match first, then progressively shorter prefixes
        # e.g. "trading_advisor.generate_reopen_briefing" matches before "trading_advisor"
        best_match: str | None = None
        best_len = 0
        for prefix, model in self._caller_model_map.items():
            if caller.startswith(prefix) and len(prefix) > best_len:
                best_match = model
                best_len = len(prefix)
        return best_match

    # ── Core API ─────────────────────────────────────────────

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        caller: str = "unknown",
        strategy: RoutingStrategy | None = None,
        preferred_provider: ProviderName | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        symbol: str = "",
        analysis_type: str = "",
        timeout: float | None = None,
        grounding: bool | None = None,
    ) -> LLMResponse:
        """Route a completion request with governance.

        Args:
            messages: Provider-neutral messages.
            caller: Mandatory attribution string (e.g. ``"realtime_analyzer.unified"``).
            strategy: Routing strategy override.
            preferred_provider: Force a specific provider.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            symbol: Stock symbol for usage tracking.
            analysis_type: Analysis type for usage tracking.
            timeout: Per-call timeout override in seconds.
            grounding: Enable Gemini Grounding (Google Search). If ``None``
                (default), auto-determined by caller against the
                ``grounding.enabled_callers`` config list.

        Returns:
            Standardized LLMResponse.

        Raises:
            LLMProviderError: If all providers fail or timeout.
        """
        # Auto-resolve grounding from caller config
        if grounding is None:
            grounding = self._should_ground(caller)

        # Caller-based model routing + dynamic upgrade
        model_override = self._resolve_caller_model(caller)
        if model_override:
            logger.debug("Caller %s → model override: %s", caller, model_override)
        model_override = self._maybe_upgrade_model(model_override, messages)

        # In-flight dedup: if an identical request is already running,
        # wait for its result instead of making a duplicate LLM call.
        dedup_key = self._hash_messages(messages)
        with self._dedup_lock:
            if dedup_key in self._inflight:
                event, container = self._inflight[dedup_key]
                logger.debug("Dedup hit for %s (caller=%s)", dedup_key[:8], caller)
                waiting = True
            else:
                event = threading.Event()
                container: list = []  # [result] or will raise stored error
                self._inflight[dedup_key] = (event, container)
                waiting = False

        if waiting:
            event.wait(timeout=self._default_timeout)
            if container and isinstance(container[0], Exception):
                raise container[0]
            if container:
                return container[0]
            raise LLMProviderError(f"Dedup wait timed out ({caller})")

        start = time.perf_counter()
        error_msg = ""
        response = None

        try:
            response = self._router.complete(
                messages=messages,
                strategy=strategy,
                preferred_provider=preferred_provider,
                model=model_override,
                max_tokens=max_tokens,
                temperature=temperature,
                symbol=symbol,
                analysis_type=analysis_type,
                grounding=grounding,
            )
            container.append(response)
            return response
        except LLMProviderError as exc:
            error_msg = str(exc)
            container.append(exc)
            raise
        except Exception as exc:
            error_msg = str(exc)
            wrapped = LLMProviderError(f"Gateway error ({caller}): {exc}")
            container.append(wrapped)
            raise wrapped from exc
        finally:
            event.set()
            with self._dedup_lock:
                self._inflight.pop(dedup_key, None)
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._log_call(
                caller=caller,
                call_type="complete",
                symbol=symbol,
                analysis_type=analysis_type,
                elapsed_ms=elapsed_ms,
                error=error_msg,
                response=response,
            )

    def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        *,
        caller: str = "unknown",
        preferred_provider: ProviderName | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        symbol: str = "",
        analysis_type: str = "",
        timeout: float | None = None,
    ) -> LLMToolResponse:
        """Route a tool_use completion request with governance.

        Args:
            messages: Provider-neutral messages.
            tools: Anthropic-format tool definitions.
            caller: Mandatory attribution string.
            preferred_provider: Force a specific provider.
            model: Explicit model override (takes priority over caller routing).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            symbol: Stock symbol for usage tracking.
            analysis_type: Analysis type for usage tracking.
            timeout: Per-call timeout override in seconds.

        Returns:
            LLMToolResponse with text and/or tool calls.

        Raises:
            LLMProviderError: If all providers fail or timeout.
        """
        if model:
            model_override = model
        else:
            model_override = self._resolve_caller_model(caller)
        model_override = self._maybe_upgrade_model(model_override, messages)

        start = time.perf_counter()
        error_msg = ""
        response = None

        try:
            response = self._router.complete_with_tools(
                messages=messages,
                tools=tools,
                preferred_provider=preferred_provider,
                model=model_override,
                max_tokens=max_tokens,
                temperature=temperature,
                symbol=symbol,
                analysis_type=analysis_type,
            )
            return response
        except LLMProviderError as exc:
            error_msg = str(exc)
            raise
        except Exception as exc:
            error_msg = str(exc)
            raise LLMProviderError(f"Gateway error ({caller}): {exc}") from exc
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._log_call(
                caller=caller,
                call_type="complete_with_tools",
                symbol=symbol,
                analysis_type=analysis_type,
                elapsed_ms=elapsed_ms,
                error=error_msg,
                response=response,
            )

    # ── In-flight deduplication ──────────────────────────────

    @staticmethod
    def _hash_messages(messages: list[LLMMessage]) -> str:
        """Compute a content hash for deduplication."""
        parts = []
        for m in messages:
            content = (
                m.content
                if isinstance(m.content, str)
                else json.dumps(
                    m.content,
                    sort_keys=True,
                    ensure_ascii=False,
                )
            )
            parts.append(f"{m.role}:{content}")
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ── Audit logging ────────────────────────────────────────

    def _log_call(
        self,
        caller: str,
        call_type: str,
        symbol: str,
        analysis_type: str,
        elapsed_ms: float,
        error: str,
        response: LLMResponse | LLMToolResponse | None,
    ) -> None:
        """Record an LLM call in the audit log."""
        payload: dict[str, Any] = {
            "caller": caller,
            "call_type": call_type,
            "symbol": symbol,
            "analysis_type": analysis_type,
            "elapsed_ms": round(elapsed_ms, 1),
            "success": not error,
        }

        if response is not None:
            payload["provider"] = (
                response.provider.value
                if hasattr(response.provider, "value")
                else str(response.provider)
            )
            payload["model"] = response.model
            payload["input_tokens"] = response.input_tokens
            payload["output_tokens"] = response.output_tokens
            payload["cost_usd"] = response.cost_usd

            # Extract finish_reason for truncation observability
            finish_reason = getattr(response, "finish_reason", None)
            # LLMToolResponse uses stop_reason instead
            if finish_reason is None:
                stop_reason = getattr(response, "stop_reason", None)
                if stop_reason == "max_tokens":
                    finish_reason = "length"
                elif stop_reason is not None:
                    finish_reason = "stop"
            if finish_reason:
                payload["finish_reason"] = finish_reason
            if finish_reason == "length":
                logger.warning(
                    "LLM response truncated: caller=%s model=%s output_tokens=%d — "
                    "consider increasing max_tokens for this caller",
                    caller,
                    response.model,
                    response.output_tokens,
                )

        if error:
            payload["error"] = error[:500]

        # Structured log (always emitted)
        log_fn = logger.info if not error else logger.warning
        log_fn(
            "LLM call: caller=%s type=%s symbol=%s %.0fms %s",
            caller,
            call_type,
            symbol or "-",
            elapsed_ms,
            "OK" if not error else f"ERR: {error[:100]}",
        )

        # Audit log (if available)
        if self._audit_log is not None:
            try:
                self._audit_log.log(
                    EVENT_LLM_CALL,
                    payload=payload,
                    actor=caller,
                )
            except Exception:
                logger.debug("Failed to write audit log for LLM call")

"""LLM request routing with strategy-based provider selection.

Supports COST, QUALITY, and HYBRID routing strategies with automatic
fallback when a provider fails. Uses config/llm.yaml for provider
configuration and scoring.
"""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.llm.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    LLMToolResponse,
    ProviderName,
)
from src.llm.key_manager import KeyManager
from src.llm.rate_limiter import RateLimiter
from src.llm.usage_tracker import UsageTracker
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("llm.router")


class RoutingStrategy(str, Enum):
    """Provider selection strategy."""

    COST = "cost"
    QUALITY = "quality"
    HYBRID = "hybrid"


@dataclass
class RoutingDecision:
    """Result of a provider selection decision.

    Attributes:
        provider: Selected provider name.
        model: Selected model identifier.
        strategy: Strategy used for selection.
        score: Composite score for the selection.
        reason: Human-readable explanation.
    """

    provider: ProviderName
    model: str
    strategy: RoutingStrategy
    score: float
    reason: str


class LLMRouter:
    """Routes LLM requests to providers based on strategy.

    Loads provider configuration from ``config/llm.yaml``, creates
    provider instances via ``KeyManager``, and selects the optimal
    provider based on the chosen routing strategy.

    Args:
        config_name: Config file name (without extension).
        key_manager: Optional pre-configured KeyManager instance.
    """

    def __init__(
        self,
        config_name: str = "llm",
        key_manager: KeyManager | None = None,
    ) -> None:
        self._config = load_config(config_name)
        self._key_manager = key_manager or KeyManager()
        self._usage_tracker = UsageTracker()
        self._providers: dict[ProviderName, BaseLLMProvider] = {}
        self._rate_limiters: dict[ProviderName, RateLimiter] = {}
        # Providers disabled at runtime (e.g. quota exhausted)
        self._disabled_providers: set[ProviderName] = set()
        self._init_providers()
        self._init_rate_limiters()

    def _init_providers(self) -> None:
        """Initialize enabled providers that have API keys."""
        providers_cfg = self._config.get("providers", {})

        for name, cfg in providers_cfg.items():
            if not cfg.get("enabled", False):
                continue

            try:
                provider_name = ProviderName(name)
            except ValueError:
                logger.warning("Unknown provider: %s, skipping", name)
                continue

            # Some providers (e.g. claude_code bridge) don't need an API key
            requires_key = cfg.get("requires_api_key", True)

            api_key = ""
            if requires_key:
                if not self._key_manager.has_provider(provider_name):
                    logger.info("No API key for %s, skipping", provider_name.value)
                    continue
                api_key = self._key_manager.get_key(provider_name) or ""
                if not api_key:
                    continue

            default_model = cfg.get("default_model", "")
            fallback_model = cfg.get("fallback_model")
            fallback_models = cfg.get("fallback_models")
            provider = _create_provider(
                provider_name,
                api_key,
                default_model,
                fallback_model=fallback_model,
                fallback_models=fallback_models,
            )
            if provider:
                self._providers[provider_name] = provider
                logger.info(
                    "Initialized provider: %s (model: %s)",
                    provider_name.value,
                    default_model,
                )

    def _init_rate_limiters(self) -> None:
        """Initialize per-provider rate limiters from config."""
        providers_cfg = self._config.get("providers", {})
        rate_cfg = self._config.get("rate_limiting", {})
        cache_ttl = rate_cfg.get("cache_ttl", 60)
        cache_max = rate_cfg.get("cache_max_size", 100)

        for pname in self._providers:
            pcfg = providers_cfg.get(pname.value, {})
            rpm = pcfg.get("rate_limit", {}).get("requests_per_minute", 60)
            self._rate_limiters[pname] = RateLimiter(
                requests_per_minute=rpm,
                cache_ttl=cache_ttl,
                cache_max_size=cache_max,
            )
            logger.info("Rate limiter for %s: %d RPM", pname.value, rpm)

    @property
    def available_providers(self) -> list[ProviderName]:
        """Return list of initialized provider names."""
        return list(self._providers.keys())

    @property
    def usage_tracker(self) -> UsageTracker:
        """Return the usage tracker instance."""
        return self._usage_tracker

    def get_provider(self, name: ProviderName) -> BaseLLMProvider | None:
        """Get a specific provider instance.

        Args:
            name: Provider identifier.

        Returns:
            Provider instance or None if not available.
        """
        return self._providers.get(name)

    def _maybe_disable_provider(
        self, provider_name: ProviderName, exc: Exception
    ) -> None:
        """Disable a provider for the session if it has a permanent error.

        Detects quota exhaustion (insufficient_quota) and auth errors,
        which won't resolve by retrying. Skipping the provider on
        subsequent calls avoids wasting ~15s per call on retries.
        """
        msg = str(exc).lower()
        if "insufficient_quota" in msg or "billing" in msg:
            self._disabled_providers.add(provider_name)
            logger.warning(
                "Provider %s disabled for session — quota exhausted",
                provider_name.value,
            )
        elif "invalid_api_key" in msg or "authentication" in msg:
            self._disabled_providers.add(provider_name)
            logger.warning(
                "Provider %s disabled for session — auth error",
                provider_name.value,
            )

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        caller: str = "",
        strategy: RoutingStrategy | None = None,
        preferred_provider: ProviderName | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        symbol: str = "",
        analysis_type: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        """Route a completion request to the best available provider.

        Args:
            messages: Provider-neutral messages (LLMMessage or raw dicts).
            caller: Attribution string (used by LLMGateway; ignored here).
            strategy: Routing strategy override.
            preferred_provider: Force a specific provider.
            model: Model override — passed to provider.complete(model=...).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            symbol: Stock symbol for usage tracking.
            analysis_type: Analysis type for usage tracking.
            **kwargs: Passed through to provider (e.g. ``grounding=True``).

        Returns:
            Standardized LLMResponse.

        Raises:
            LLMProviderError: If all providers fail.
        """
        if not self._providers:
            raise LLMProviderError(
                "No LLM providers available. Check API keys and config."
            )

        strategy = strategy or RoutingStrategy(
            self._config.get("routing", {}).get("default_strategy", "hybrid")
        )

        # Determine provider order
        if preferred_provider and preferred_provider in self._providers:
            ordered = [preferred_provider] + [
                p for p in self._get_fallback_order() if p != preferred_provider
            ]
        else:
            decision = self.select_provider(strategy)
            ordered = [decision.provider] + [
                p for p in self._get_fallback_order() if p != decision.provider
            ]

        # Check dedup cache first
        cache_key = RateLimiter.make_cache_key(messages)
        first_limiter = self._rate_limiters.get(ordered[0]) if ordered else None
        if first_limiter:
            cached = first_limiter.get_cached(cache_key)
            if cached is not None:
                logger.debug("Dedup cache hit for key %s", cache_key[:8])
                return cached

        # Normalize messages: accept both LLMMessage and raw dicts
        normalized: list[LLMMessage] = []
        for msg in messages:
            if isinstance(msg, LLMMessage):
                normalized.append(msg)
            elif isinstance(msg, dict):
                normalized.append(
                    LLMMessage(
                        role=msg.get("role", "user"), content=msg.get("content", "")
                    )
                )
            else:
                normalized.append(msg)
        messages = normalized

        # Try providers in order with fallback
        last_error: Exception | None = None
        for provider_name in ordered:
            if provider_name in self._disabled_providers:
                continue

            provider = self._providers.get(provider_name)
            if not provider:
                continue

            # Acquire rate limit token
            limiter = self._rate_limiters.get(provider_name)
            if limiter and not limiter.acquire(timeout=10.0):
                logger.warning(
                    "Rate limit timeout for %s, trying next provider",
                    provider_name.value,
                )
                continue

            # Only pass model name to the preferred provider.
            # Fallback providers use their own default model to avoid
            # cross-provider model name mismatches (e.g. "gpt-5.4-mini" → Google 404).
            use_model = model if provider_name == preferred_provider else None

            try:
                response = provider.complete(
                    messages=messages,
                    model=use_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )
                self._usage_tracker.record(
                    response,
                    symbol=symbol,
                    analysis_type=analysis_type,
                )
                # Cache successful response for dedup
                if limiter:
                    limiter.set_cached(cache_key, response)
                return response
            except LLMProviderError as exc:
                self._maybe_disable_provider(provider_name, exc)
                logger.warning(
                    "Provider %s failed: %s. Trying next.",
                    provider_name.value,
                    exc,
                )
                last_error = exc
            except Exception as exc:
                logger.warning(
                    "Unexpected error from %s: %s. Trying next.",
                    provider_name.value,
                    exc,
                )
                last_error = exc

        raise LLMProviderError(f"All providers failed. Last error: {last_error}")

    def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        preferred_provider: ProviderName | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        symbol: str = "",
        analysis_type: str = "",
        caller: str = "",
    ) -> LLMToolResponse:
        """Route a tool_use completion request to a provider.

        Only providers that support tool_use (currently Anthropic) will
        be tried. Falls back through available providers on failure.

        Args:
            messages: Provider-neutral messages.
            tools: Anthropic-format tool definitions.
            preferred_provider: Force a specific provider.
            model: Model override — passed to provider.complete_with_tools(model=...).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            symbol: Stock symbol for usage tracking.
            analysis_type: Analysis type for usage tracking.
            caller: Attribution string for logging/tracking.

        Returns:
            LLMToolResponse with text and/or tool calls.

        Raises:
            LLMProviderError: If all providers fail.
        """
        if not self._providers:
            raise LLMProviderError(
                "No LLM providers available. Check API keys and config."
            )

        # Determine provider order — preferred first, then fallback
        fallback = [p for p in self._get_fallback_order() if p in self._providers]
        if preferred_provider and preferred_provider in self._providers:
            ordered = [preferred_provider] + [
                p for p in fallback if p != preferred_provider
            ]
        else:
            ordered = fallback

        last_error: Exception | None = None
        for provider_name in ordered:
            if provider_name in self._disabled_providers:
                continue

            provider = self._providers.get(provider_name)
            if not provider:
                continue

            limiter = self._rate_limiters.get(provider_name)
            if limiter and not limiter.acquire(timeout=10.0):
                logger.warning(
                    "Rate limit timeout for %s, trying next provider",
                    provider_name.value,
                )
                continue

            # Only pass model name to the preferred provider (same as complete())
            use_model = model if provider_name == preferred_provider else None

            try:
                response = provider.complete_with_tools(
                    messages=messages,
                    tools=tools,
                    model=use_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                # Track usage from tool response
                self._usage_tracker.record(
                    LLMResponse(
                        text=response.text or "",
                        provider=response.provider,
                        model=response.model,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        latency_ms=response.latency_ms,
                        cost_usd=response.cost_usd,
                    ),
                    symbol=symbol,
                    analysis_type=analysis_type,
                )
                # v14.0: Attach initial trust_zone (UNTRUSTED until
                # validation runs downstream in agent_service).
                response.trust_zone = "UNTRUSTED"
                return response
            except NotImplementedError:
                logger.info(
                    "Provider %s does not support tool_use, skipping",
                    provider_name.value,
                )
                continue
            except LLMProviderError as exc:
                self._maybe_disable_provider(provider_name, exc)
                logger.warning(
                    "Provider %s failed tool_use: %s. Trying next.",
                    provider_name.value,
                    exc,
                )
                last_error = exc
            except Exception as exc:
                logger.warning(
                    "Unexpected error from %s tool_use: %s. Trying next.",
                    provider_name.value,
                    exc,
                )
                last_error = exc

        raise LLMProviderError(
            f"No provider supports tool_use or all failed. Last error: {last_error}"
        )

    def select_provider(self, strategy: RoutingStrategy) -> RoutingDecision:
        """Select the best provider based on routing strategy.

        Args:
            strategy: Routing strategy to use.

        Returns:
            RoutingDecision with provider, model, and rationale.
        """
        providers_cfg = self._config.get("providers", {})
        routing_cfg = self._config.get("routing", {})
        candidates: list[dict[str, Any]] = []

        for name in self._providers:
            cfg = providers_cfg.get(name.value, {})
            default_model = cfg.get("default_model", "")
            model_cfg = cfg.get("models", {}).get(default_model, {})

            cost_score = model_cfg.get("cost_per_1k_output", 0.01)
            quality_score = model_cfg.get("quality_score", 0.5)

            candidates.append(
                {
                    "provider": name,
                    "model": default_model,
                    "cost_per_1k": cost_score,
                    "quality": quality_score,
                }
            )

        if not candidates:
            raise LLMProviderError("No providers available for routing")

        if strategy == RoutingStrategy.COST:
            best = min(candidates, key=lambda c: c["cost_per_1k"])
            return RoutingDecision(
                provider=best["provider"],
                model=best["model"],
                strategy=strategy,
                score=best["cost_per_1k"],
                reason=f"Lowest cost: ${best['cost_per_1k']}/1K tokens",
            )

        if strategy == RoutingStrategy.QUALITY:
            best = max(candidates, key=lambda c: c["quality"])
            return RoutingDecision(
                provider=best["provider"],
                model=best["model"],
                strategy=strategy,
                score=best["quality"],
                reason=f"Highest quality: {best['quality']:.2f}",
            )

        # HYBRID: weighted composite
        weights = routing_cfg.get("hybrid_weights", {"cost": 0.4, "quality": 0.6})
        cost_weight = weights.get("cost", 0.4)
        quality_weight = weights.get("quality", 0.6)

        # Normalize cost scores (lower is better → invert)
        max_cost = max(c["cost_per_1k"] for c in candidates)
        if max_cost > 0:
            for c in candidates:
                c["cost_normalized"] = 1.0 - (c["cost_per_1k"] / max_cost)
        else:
            for c in candidates:
                c["cost_normalized"] = 1.0

        for c in candidates:
            c["hybrid_score"] = (
                cost_weight * c["cost_normalized"] + quality_weight * c["quality"]
            )

        best = max(candidates, key=lambda c: c["hybrid_score"])
        return RoutingDecision(
            provider=best["provider"],
            model=best["model"],
            strategy=strategy,
            score=best["hybrid_score"],
            reason=(
                f"Hybrid: cost_norm={best['cost_normalized']:.2f}, "
                f"quality={best['quality']:.2f}, "
                f"composite={best['hybrid_score']:.2f}"
            ),
        )

    def _get_fallback_order(self) -> list[ProviderName]:
        """Get the fallback provider order from config.

        Returns:
            Ordered list of provider names.
        """
        order = self._config.get("routing", {}).get(
            "fallback_order", ["anthropic", "openai", "google"]
        )
        result = []
        for name in order:
            try:
                pn = ProviderName(name)
                if pn in self._providers:
                    result.append(pn)
            except ValueError:
                continue
        return result


def _create_provider(
    name: ProviderName,
    api_key: str,
    default_model: str,
    fallback_model: str | None = None,
    fallback_models: list[str] | None = None,
) -> BaseLLMProvider | None:
    """Create a provider instance by name.

    Args:
        name: Provider identifier.
        api_key: API key for the provider.
        default_model: Default model to use.
        fallback_model: Optional fallback model (currently Google only).

    Returns:
        Provider instance, or None on import error.
    """
    try:
        if name == ProviderName.CLAUDE_CODE:
            from src.llm.bridge import ClaudeCodeBridgeProvider

            return ClaudeCodeBridgeProvider(model=default_model or "opus")
        if name == ProviderName.ANTHROPIC:
            from src.llm.anthropic import AnthropicProvider

            return AnthropicProvider(api_key=api_key, default_model=default_model)
        if name == ProviderName.OPENAI:
            from src.llm.openai import OpenAIProvider

            return OpenAIProvider(api_key=api_key, default_model=default_model)
        if name == ProviderName.DEEPSEEK:
            from src.llm.deepseek import DeepSeekProvider

            return DeepSeekProvider(api_key=api_key, default_model=default_model)
        if name == ProviderName.GOOGLE:
            from src.llm.google import GoogleProvider

            return GoogleProvider(
                api_key=api_key,
                default_model=default_model,
                fallback_model=fallback_model,
                fallback_models=fallback_models,
            )
        if name == ProviderName.GEMINI_WEB:
            cfg = load_config("llm").get("providers", {}).get("gemini_web", {})
            from src.llm.gemini_web import GeminiWebProvider

            in_docker = os.path.exists("/.dockerenv")
            if in_docker:
                debug_url = cfg.get(
                    "chrome_debug_url", "http://host.docker.internal:9223"
                )
            else:
                debug_url = cfg.get("chrome_debug_url_host", "http://127.0.0.1:9222")
            return GeminiWebProvider(
                chrome_debug_url=debug_url,
                gemini_url=cfg.get("gemini_url", "https://gemini.google.com/app"),
                default_model=cfg.get("default_model", "gemini-3.0-thinking"),
                timeout=float(cfg.get("timeout_per_request", 300)),
                page_load_timeout=float(cfg.get("page_load_timeout", 15)),
                max_retries=int(cfg.get("max_retries", 2)),
                retry_delay=float(cfg.get("retry_delay", 3.0)),
                use_temporary_chat=cfg.get("use_temporary_chat", True),
                use_thinking_mode=cfg.get("use_thinking_mode", True),
            )
    except ImportError as exc:
        logger.warning("Cannot create %s provider: %s", name.value, exc)
    return None

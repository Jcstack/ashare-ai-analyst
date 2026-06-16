"""Real LLM provider integration tests — NO mocks, real API calls.

Tests each LLM provider (Google Gemini, Anthropic Claude, OpenAI GPT)
with minimal prompts to verify connectivity and response quality while
controlling costs.  Also tests the LLM router and rate limiter.
"""

from __future__ import annotations

import os
import traceback

import pytest

from tests.integration_real.conftest import (
    TestResult,
    measure_time,
    requires_anthropic_key,
    requires_any_llm_key,
    requires_google_key,
    requires_openai_key,
)

pytestmark = pytest.mark.integration_real

MINIMAL_PROMPT = 'Return exactly this JSON and nothing else: {"status": "ok"}'


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------


@requires_google_key
class TestGoogleGemini:
    """Google Gemini provider — real API calls."""

    def test_gemini_flash_complete(self, llm_rate_guard, result_collector):
        """Call Gemini 2.0 Flash with a minimal prompt."""
        from src.llm.base import LLMMessage
        from src.llm.google import GoogleProvider

        llm_rate_guard.wait()
        try:
            provider = GoogleProvider(
                api_key=os.environ["GOOGLE_API_KEY"],
                default_model="gemini-2.0-flash",
            )
            with measure_time() as timing:
                response = provider.complete(
                    messages=[LLMMessage(role="user", content=MINIMAL_PROMPT)],
                    max_tokens=50,
                    temperature=0,
                )

            assert response.text, "Gemini response text is empty"
            result_collector.record(
                TestResult(
                    test_name="gemini_flash_complete",
                    category="llm",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "model": response.model,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "cost_usd": response.cost_usd,
                        "response_preview": response.text[:100],
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="gemini_flash_complete",
                    category="llm",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Gemini Flash complete failed: {exc}")


# ---------------------------------------------------------------------------
# Anthropic Claude
# ---------------------------------------------------------------------------


@requires_anthropic_key
class TestAnthropicClaude:
    """Anthropic Claude provider — real API calls."""

    def test_haiku_complete(self, llm_rate_guard, result_collector):
        """Call Claude Haiku 3.5 with a minimal prompt."""
        from src.llm.anthropic import AnthropicProvider
        from src.llm.base import LLMMessage

        llm_rate_guard.wait()
        try:
            provider = AnthropicProvider(
                api_key=os.environ["ANTHROPIC_API_KEY"],
                default_model="claude-haiku-4-5",
            )
            with measure_time() as timing:
                response = provider.complete(
                    messages=[LLMMessage(role="user", content=MINIMAL_PROMPT)],
                    max_tokens=50,
                    temperature=0,
                )

            assert response.text, "Anthropic response text is empty"
            result_collector.record(
                TestResult(
                    test_name="haiku_complete",
                    category="llm",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "model": response.model,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "cost_usd": response.cost_usd,
                        "response_preview": response.text[:100],
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="haiku_complete",
                    category="llm",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Haiku complete failed: {exc}")


# ---------------------------------------------------------------------------
# OpenAI GPT
# ---------------------------------------------------------------------------


@requires_openai_key
class TestOpenAI:
    """OpenAI GPT provider — real API calls."""

    def test_gpt4o_mini_complete(self, llm_rate_guard, result_collector):
        """Call GPT-4o-mini with a minimal prompt."""
        from src.llm.base import LLMMessage
        from src.llm.openai import OpenAIProvider

        llm_rate_guard.wait()
        try:
            provider = OpenAIProvider(
                api_key=os.environ["OPENAI_API_KEY"],
                default_model="gpt-4o-mini",
            )
            with measure_time() as timing:
                response = provider.complete(
                    messages=[LLMMessage(role="user", content=MINIMAL_PROMPT)],
                    max_tokens=50,
                    temperature=0,
                )

            assert response.text, "OpenAI response text is empty"
            result_collector.record(
                TestResult(
                    test_name="gpt4o_mini_complete",
                    category="llm",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "model": response.model,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "cost_usd": response.cost_usd,
                        "response_preview": response.text[:100],
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="gpt4o_mini_complete",
                    category="llm",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"GPT-4o-mini complete failed: {exc}")


# ---------------------------------------------------------------------------
# LLM Router
# ---------------------------------------------------------------------------


@requires_any_llm_key
class TestLLMRouter:
    """LLM Router — strategy-based provider selection with real providers."""

    def test_router_initialization(self, result_collector):
        """Verify the router initializes with at least one provider."""
        from src.llm.router import LLMRouter

        try:
            with measure_time() as timing:
                router = LLMRouter()

            assert router.available_providers, "No providers available in router"
            result_collector.record(
                TestResult(
                    test_name="router_initialization",
                    category="llm",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "available_providers": [
                            p.value for p in router.available_providers
                        ],
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="router_initialization",
                    category="llm",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Router initialization failed: {exc}")

    def test_router_complete(self, llm_rate_guard, result_collector):
        """Route a completion through the router and verify response."""
        from src.llm.base import LLMMessage
        from src.llm.router import LLMRouter

        llm_rate_guard.wait()
        try:
            router = LLMRouter()
            with measure_time() as timing:
                response = router.complete(
                    messages=[LLMMessage(role="user", content=MINIMAL_PROMPT)],
                    max_tokens=50,
                )

            assert response.text, "Router response text is empty"
            result_collector.record(
                TestResult(
                    test_name="router_complete",
                    category="llm",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "provider": response.provider.value,
                        "model": response.model,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "cost_usd": response.cost_usd,
                        "response_preview": response.text[:100],
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="router_complete",
                    category="llm",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Router complete failed: {exc}")


# ---------------------------------------------------------------------------
# Rate Limiter (pure timing — no API keys needed)
# ---------------------------------------------------------------------------


class TestRateLimiter:
    """Token bucket rate limiter — timing and cache tests."""

    def test_token_bucket_timing(self, result_collector):
        """Acquire 5 tokens at 60 RPM and verify total time is reasonable."""
        from src.llm.rate_limiter import RateLimiter

        limiter = RateLimiter(requests_per_minute=60)

        with measure_time() as timing:
            results = []
            for i in range(5):
                acquired = limiter.acquire(timeout=5.0)
                results.append(acquired)

        total_s = timing["elapsed_ms"] / 1000
        all_acquired = all(results)

        # At 60 RPM the bucket starts full, so the first batch should be fast.
        # 5 tokens from a full 60-token bucket should take well under 5 seconds.
        assert all_acquired, f"Failed to acquire all tokens: {results}"
        assert total_s < 5.0, f"Took too long: {total_s:.2f}s for 5 tokens at 60 RPM"

        result_collector.record(
            TestResult(
                test_name="token_bucket_timing",
                category="llm",
                status="pass" if all_acquired else "fail",
                latency_ms=timing["elapsed_ms"],
                details={
                    "tokens_acquired": sum(results),
                    "total_seconds": round(total_s, 3),
                    "rpm": 60,
                },
            )
        )

    def test_dedup_cache(self, result_collector):
        """Store and retrieve a cached response via the dedup cache."""
        from src.llm.rate_limiter import RateLimiter

        limiter = RateLimiter(requests_per_minute=60, cache_ttl=10.0)

        cache_key = "test_cache_key_001"
        test_response = {"text": "cached response", "provider": "test"}

        limiter.set_cached(cache_key, test_response)
        retrieved = limiter.get_cached(cache_key)

        assert retrieved is not None, "Cache returned None for a valid key"
        assert retrieved == test_response, f"Cache mismatch: {retrieved}"

        # Verify a missing key returns None
        missing = limiter.get_cached("nonexistent_key")
        assert missing is None, "Cache returned a value for a nonexistent key"

        result_collector.record(
            TestResult(
                test_name="dedup_cache",
                category="llm",
                status="pass",
                latency_ms=0.0,
                details={
                    "cache_hit": retrieved is not None,
                    "cache_miss_none": missing is None,
                },
            )
        )

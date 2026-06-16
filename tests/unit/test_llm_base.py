"""Unit tests for src/llm/base.py — LLM base abstractions.

Tests LLMMessage, LLMResponse, ProviderName, _extract_retry_after,
and BaseLLMProvider._call_with_retry.
"""

from unittest.mock import MagicMock

import pytest

from src.llm.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    ProviderName,
    _extract_retry_after,
)


class TestLLMMessage:
    """Tests for LLMMessage dataclass."""

    def test_create_message(self):
        msg = LLMMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_system_message(self):
        msg = LLMMessage(role="system", content="You are an analyst")
        assert msg.role == "system"


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_create_response(self):
        resp = LLMResponse(
            text="Test",
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=200,
            latency_ms=500.0,
            cost_usd=0.005,
        )
        assert resp.text == "Test"
        assert resp.provider == ProviderName.ANTHROPIC
        assert resp.input_tokens == 100
        assert resp.output_tokens == 200
        assert resp.cost_usd == 0.005
        assert resp.timestamp  # auto-generated

    def test_defaults(self):
        resp = LLMResponse(text="X", provider=ProviderName.OPENAI, model="gpt-4o")
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0
        assert resp.cost_usd == 0.0


class TestProviderName:
    """Tests for ProviderName enum."""

    def test_values(self):
        assert ProviderName.ANTHROPIC.value == "anthropic"
        assert ProviderName.OPENAI.value == "openai"
        assert ProviderName.GOOGLE.value == "google"

    def test_from_string(self):
        assert ProviderName("anthropic") == ProviderName.ANTHROPIC


class TestLLMProviderError:
    """Tests for LLMProviderError."""

    def test_error_with_provider(self):
        err = LLMProviderError("failed", provider=ProviderName.OPENAI, retryable=True)
        assert str(err) == "failed"
        assert err.provider == ProviderName.OPENAI
        assert err.retryable is True

    def test_error_defaults(self):
        err = LLMProviderError("msg")
        assert err.provider is None
        assert err.retryable is False


class TestExtractRetryAfter:
    """Tests for _extract_retry_after helper."""

    def test_retry_after_attribute(self):
        exc = Exception("Rate limited")
        exc.retry_after = 5.0
        assert _extract_retry_after(exc) == 5.0

    def test_retry_after_none_attribute(self):
        exc = Exception("Error")
        exc.retry_after = None
        assert _extract_retry_after(exc) is None

    def test_429_with_header(self):
        exc = Exception("Too many requests")
        exc.status_code = 429
        exc.response = MagicMock()
        exc.response.headers = {"Retry-After": "10"}
        assert _extract_retry_after(exc) == 10.0

    def test_429_without_header(self):
        exc = Exception("Too many requests")
        exc.status_code = 429
        exc.response = None
        assert _extract_retry_after(exc) == 5.0

    def test_non_rate_limit(self):
        exc = ConnectionError("Network error")
        assert _extract_retry_after(exc) is None


class _ConcreteProvider(BaseLLMProvider):
    """Minimal concrete provider for testing _call_with_retry."""

    @property
    def provider_name(self):
        return ProviderName.ANTHROPIC

    @property
    def default_model(self):
        return "test-model"

    def complete(self, messages, model=None, max_tokens=4096, temperature=0.3):
        pass

    def check_balance(self):
        return {}

    def list_models(self):
        return []


class TestCallWithRetry:
    """Tests for BaseLLMProvider._call_with_retry."""

    def test_success_first_try(self):
        provider = _ConcreteProvider()
        result = provider._call_with_retry(lambda: "ok", max_attempts=3)
        assert result == "ok"

    def test_retry_then_success(self):
        provider = _ConcreteProvider()
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("Transient")
            return "ok"

        result = provider._call_with_retry(flaky, max_attempts=3, base_delay=0)
        assert result == "ok"
        assert call_count["n"] == 3

    def test_all_retries_exhausted(self):
        provider = _ConcreteProvider()
        with pytest.raises(LLMProviderError, match="failed after 2"):
            provider._call_with_retry(
                lambda: (_ for _ in ()).throw(ConnectionError("Persistent")),
                max_attempts=2,
                base_delay=0,
            )

    def test_retry_with_rate_limit(self):
        provider = _ConcreteProvider()
        call_count = {"n": 0}

        def rate_limited():
            call_count["n"] += 1
            if call_count["n"] == 1:
                exc = Exception("Rate limited")
                exc.retry_after = 0
                raise exc
            return "ok"

        result = provider._call_with_retry(rate_limited, max_attempts=3, base_delay=0)
        assert result == "ok"
        assert call_count["n"] == 2

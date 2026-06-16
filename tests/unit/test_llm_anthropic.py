"""Unit tests for src/llm/anthropic.py — AnthropicProvider.

Tests complete(), system message separation, retry logic,
cost estimation, and model listing.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.llm.base import LLMMessage, LLMProviderError, LLMResponse, ProviderName


@pytest.fixture
def mock_anthropic_sdk():
    """Mock the anthropic.Anthropic class."""
    with patch("src.llm.anthropic.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_response():
    """Create a mock Anthropic API response."""
    response = MagicMock()
    response.content = [MagicMock(text='{"trend": "bullish"}')]
    response.usage = MagicMock(input_tokens=100, output_tokens=200)
    return response


class TestAnthropicProvider:
    """Tests for AnthropicProvider."""

    def test_complete_returns_llm_response(self, mock_anthropic_sdk, mock_response):
        mock_anthropic_sdk.messages.create.return_value = mock_response

        from src.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-test12345678")
        messages = [
            LLMMessage(role="system", content="You are an analyst"),
            LLMMessage(role="user", content="Analyze stock"),
        ]
        result = provider.complete(messages)

        assert isinstance(result, LLMResponse)
        assert result.provider == ProviderName.ANTHROPIC
        assert result.text == '{"trend": "bullish"}'
        assert result.input_tokens == 100
        assert result.output_tokens == 200
        assert result.cost_usd > 0

    def test_system_message_separated(self, mock_anthropic_sdk, mock_response):
        mock_anthropic_sdk.messages.create.return_value = mock_response

        from src.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-test12345678")
        messages = [
            LLMMessage(role="system", content="System prompt"),
            LLMMessage(role="user", content="User msg"),
        ]
        provider.complete(messages)

        call_kwargs = mock_anthropic_sdk.messages.create.call_args
        assert call_kwargs.kwargs["system"] == "System prompt"
        assert len(call_kwargs.kwargs["messages"]) == 1
        assert call_kwargs.kwargs["messages"][0]["role"] == "user"

    def test_retry_on_transient_error(self, mock_anthropic_sdk, mock_response):
        mock_anthropic_sdk.messages.create.side_effect = [
            ConnectionError("Transient"),
            mock_response,
        ]

        from src.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-test12345678", max_retries=3)
        messages = [LLMMessage(role="user", content="Test")]
        result = provider.complete(messages)

        assert result.text == '{"trend": "bullish"}'
        assert mock_anthropic_sdk.messages.create.call_count == 2

    def test_all_retries_exhausted_raises(self, mock_anthropic_sdk):
        mock_anthropic_sdk.messages.create.side_effect = ConnectionError("Persistent")

        from src.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-test12345678", max_retries=2)
        messages = [LLMMessage(role="user", content="Test")]

        with pytest.raises(LLMProviderError, match="failed after 2"):
            provider.complete(messages)

    def test_provider_name(self, mock_anthropic_sdk):
        from src.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-test12345678")
        assert provider.provider_name == ProviderName.ANTHROPIC

    def test_default_model(self, mock_anthropic_sdk):
        from src.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-test12345678")
        assert provider.default_model == "claude-sonnet-4-5-20250929"

    def test_custom_model(self, mock_anthropic_sdk, mock_response):
        mock_anthropic_sdk.messages.create.return_value = mock_response

        from src.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(
            api_key="sk-test12345678",
            default_model="claude-opus-4-6",
        )
        assert provider.default_model == "claude-opus-4-6"

    def test_check_balance(self, mock_anthropic_sdk):
        from src.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-test12345678")
        balance = provider.check_balance()
        assert balance["provider"] == "anthropic"
        assert balance["status"] == "active"

    def test_list_models(self, mock_anthropic_sdk):
        from src.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-test12345678")
        models = provider.list_models()
        assert "claude-sonnet-4-5-20250929" in models

    def test_cost_estimation(self, mock_anthropic_sdk, mock_response):
        mock_anthropic_sdk.messages.create.return_value = mock_response

        from src.llm.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="sk-test12345678")
        messages = [LLMMessage(role="user", content="Test")]
        result = provider.complete(messages)

        # 100 input * 0.003/1K + 200 output * 0.015/1K
        expected_cost = 100 * 0.003 / 1000 + 200 * 0.015 / 1000
        assert abs(result.cost_usd - expected_cost) < 0.0001

"""Unit tests for src/llm/openai.py — OpenAIProvider.

Tests complete(), message format mapping, retry logic,
cost estimation, and model listing.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.llm.base import LLMMessage, LLMProviderError, LLMResponse, ProviderName


@pytest.fixture
def mock_openai_sdk():
    """Mock the openai.OpenAI class."""
    with patch("src.llm.openai.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_response():
    """Create a mock OpenAI API response."""
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content='{"trend": "bearish"}'))]
    response.usage = MagicMock(prompt_tokens=150, completion_tokens=300)
    return response


class TestOpenAIProvider:
    """Tests for OpenAIProvider."""

    def test_complete_returns_llm_response(self, mock_openai_sdk, mock_response):
        mock_openai_sdk.chat.completions.create.return_value = mock_response

        from src.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai12345678")
        messages = [
            LLMMessage(role="system", content="You are an analyst"),
            LLMMessage(role="user", content="Analyze stock"),
        ]
        result = provider.complete(messages)

        assert isinstance(result, LLMResponse)
        assert result.provider == ProviderName.OPENAI
        assert result.text == '{"trend": "bearish"}'
        assert result.input_tokens == 150
        assert result.output_tokens == 300

    def test_system_message_in_array(self, mock_openai_sdk, mock_response):
        mock_openai_sdk.chat.completions.create.return_value = mock_response

        from src.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai12345678")
        messages = [
            LLMMessage(role="system", content="System prompt"),
            LLMMessage(role="user", content="User msg"),
        ]
        provider.complete(messages)

        call_kwargs = mock_openai_sdk.chat.completions.create.call_args
        api_messages = call_kwargs.kwargs["messages"]
        assert len(api_messages) == 2
        assert api_messages[0]["role"] == "system"
        assert api_messages[1]["role"] == "user"

    def test_retry_on_error(self, mock_openai_sdk, mock_response):
        mock_openai_sdk.chat.completions.create.side_effect = [
            ConnectionError("Transient"),
            mock_response,
        ]

        from src.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai12345678", max_retries=3)
        messages = [LLMMessage(role="user", content="Test")]
        result = provider.complete(messages)

        assert result.text == '{"trend": "bearish"}'
        assert mock_openai_sdk.chat.completions.create.call_count == 2

    def test_all_retries_exhausted(self, mock_openai_sdk):
        mock_openai_sdk.chat.completions.create.side_effect = ConnectionError(
            "Persistent"
        )

        from src.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai12345678", max_retries=2)
        messages = [LLMMessage(role="user", content="Test")]

        with pytest.raises(LLMProviderError, match="failed after 2"):
            provider.complete(messages)

    def test_provider_name(self, mock_openai_sdk):
        from src.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai12345678")
        assert provider.provider_name == ProviderName.OPENAI

    def test_default_model(self, mock_openai_sdk):
        from src.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai12345678")
        assert provider.default_model == "gpt-5.4-mini"

    def test_check_balance(self, mock_openai_sdk):
        from src.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai12345678")
        balance = provider.check_balance()
        assert balance["provider"] == "openai"

    def test_list_models(self, mock_openai_sdk):
        from src.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai12345678")
        models = provider.list_models()
        assert "gpt-4o" in models
        assert "gpt-4o-mini" in models

    def test_cost_estimation(self, mock_openai_sdk, mock_response):
        mock_openai_sdk.chat.completions.create.return_value = mock_response

        from src.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai12345678")
        messages = [LLMMessage(role="user", content="Test")]
        result = provider.complete(messages)

        expected_cost = 150 * 0.00075 / 1000 + 300 * 0.0045 / 1000
        assert abs(result.cost_usd - expected_cost) < 0.0001

    def test_empty_content_handled(self, mock_openai_sdk):
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=None))]
        response.usage = MagicMock(prompt_tokens=50, completion_tokens=0)
        mock_openai_sdk.chat.completions.create.return_value = response

        from src.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai12345678")
        messages = [LLMMessage(role="user", content="Test")]
        result = provider.complete(messages)
        assert result.text == ""

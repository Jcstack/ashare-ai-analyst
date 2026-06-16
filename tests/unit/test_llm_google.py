"""Unit tests for src/llm/google.py — GoogleProvider.

Tests complete(), system_instruction handling, retry logic,
cost estimation, and model listing.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.llm.base import LLMMessage, LLMProviderError, LLMResponse, ProviderName


@pytest.fixture
def mock_genai():
    """Mock google.genai module."""
    with patch("src.llm.google.genai") as mock_module:
        mock_client = MagicMock()
        mock_module.Client.return_value = mock_client
        mock_module.types = MagicMock()  # keep for types references
        yield mock_module


@pytest.fixture
def mock_response():
    """Create a mock Gemini API response."""
    response = MagicMock()
    response.text = '{"trend": "neutral"}'
    usage = MagicMock()
    usage.prompt_token_count = 80
    usage.candidates_token_count = 160
    response.usage_metadata = usage
    return response


class TestGoogleProvider:
    """Tests for GoogleProvider."""

    def test_complete_returns_llm_response(self, mock_genai, mock_response):
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value = mock_response

        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678")
        messages = [
            LLMMessage(role="system", content="Analyst"),
            LLMMessage(role="user", content="Analyze"),
        ]
        result = provider.complete(messages)

        assert isinstance(result, LLMResponse)
        assert result.provider == ProviderName.GOOGLE
        assert result.text == '{"trend": "neutral"}'
        assert result.input_tokens == 80
        assert result.output_tokens == 160

    def test_system_instruction_passed(self, mock_genai, mock_response):
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value = mock_response

        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678")
        messages = [
            LLMMessage(role="system", content="System instruction"),
            LLMMessage(role="user", content="User msg"),
        ]
        provider.complete(messages)

        call_kwargs = mock_client.models.generate_content.call_args
        config = call_kwargs.kwargs["config"]
        assert config.system_instruction == "System instruction"

    def test_assistant_mapped_to_model_role(self, mock_genai, mock_response):
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value = mock_response

        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678")
        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi"),
            LLMMessage(role="user", content="Analyze"),
        ]
        provider.complete(messages)

        call_kwargs = mock_client.models.generate_content.call_args
        contents = call_kwargs.kwargs["contents"]
        roles = [c.role for c in contents]
        assert roles == ["user", "model", "user"]

    def test_retry_on_error(self, mock_genai, mock_response):
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.side_effect = [
            ConnectionError("Transient"),
            mock_response,
        ]

        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678", max_retries=3)
        messages = [LLMMessage(role="user", content="Test")]
        result = provider.complete(messages)

        assert result.text == '{"trend": "neutral"}'

    def test_all_retries_exhausted(self, mock_genai):
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.side_effect = ConnectionError("Persistent")

        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678", max_retries=2)
        messages = [LLMMessage(role="user", content="Test")]

        with pytest.raises(LLMProviderError, match="failed after 2"):
            provider.complete(messages)

    def test_provider_name(self, mock_genai):
        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678")
        assert provider.provider_name == ProviderName.GOOGLE

    def test_default_model(self, mock_genai):
        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678")
        assert provider.default_model == "gemini-2.5-flash"

    def test_check_balance(self, mock_genai):
        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678")
        balance = provider.check_balance()
        assert balance["provider"] == "google"

    def test_list_models(self, mock_genai):
        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678")
        models = provider.list_models()
        assert "gemini-2.0-flash" in models

    def test_grounding_passes_google_search_tool(self, mock_genai, mock_response):
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value = mock_response

        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678")
        messages = [LLMMessage(role="user", content="Recent news on 601318")]
        provider.complete(messages, grounding=True)

        call_kwargs = mock_client.models.generate_content.call_args
        config = call_kwargs.kwargs["config"]
        # When grounding=True, tools should contain a GoogleSearch tool
        assert config.tools is not None
        assert len(config.tools) == 1

    def test_no_grounding_by_default(self, mock_genai, mock_response):
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value = mock_response

        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678")
        messages = [LLMMessage(role="user", content="Analyze")]
        provider.complete(messages)

        call_kwargs = mock_client.models.generate_content.call_args
        config = call_kwargs.kwargs["config"]
        # Default: no tools (no grounding)
        assert config.tools is None

    def test_no_usage_metadata(self, mock_genai):
        response = MagicMock()
        response.text = "test"
        response.usage_metadata = None
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value = response

        from src.llm.google import GoogleProvider

        provider = GoogleProvider(api_key="AIzaSy12345678")
        messages = [LLMMessage(role="user", content="Test")]
        result = provider.complete(messages)
        assert result.input_tokens == 0
        assert result.output_tokens == 0

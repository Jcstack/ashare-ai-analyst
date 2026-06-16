"""Unit tests for src/llm/router.py — LLMRouter.

Tests cost/quality/hybrid provider selection, fallback chains,
and routing with mocked providers.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.llm.base import (
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    ProviderName,
)
from src.llm.router import LLMRouter, RoutingDecision, RoutingStrategy


SAMPLE_LLM_CONFIG = {
    "providers": {
        "anthropic": {
            "enabled": True,
            "default_model": "claude-sonnet-4-5-20250929",
            "models": {
                "claude-sonnet-4-5-20250929": {
                    "cost_per_1k_input": 0.003,
                    "cost_per_1k_output": 0.015,
                    "quality_score": 0.92,
                },
            },
            "rate_limit": {"requests_per_minute": 50},
        },
        "openai": {
            "enabled": True,
            "default_model": "gpt-4o",
            "models": {
                "gpt-4o": {
                    "cost_per_1k_input": 0.0025,
                    "cost_per_1k_output": 0.01,
                    "quality_score": 0.90,
                },
            },
            "rate_limit": {"requests_per_minute": 60},
        },
        "google": {
            "enabled": True,
            "default_model": "gemini-2.0-flash",
            "models": {
                "gemini-2.0-flash": {
                    "cost_per_1k_input": 0.0001,
                    "cost_per_1k_output": 0.0004,
                    "quality_score": 0.82,
                },
            },
            "rate_limit": {"requests_per_minute": 60},
        },
    },
    "routing": {
        "default_strategy": "hybrid",
        "hybrid_weights": {"cost": 0.4, "quality": 0.6},
        "fallback_order": ["anthropic", "openai", "google"],
    },
    "consensus": {"enabled": False},
    "key_storage": {"method": "encrypted_file"},
}


@pytest.fixture
def mock_key_manager():
    """Mock KeyManager with keys for all providers."""
    km = MagicMock()
    km.has_provider.return_value = True
    km.get_key.return_value = "test-key-12345678"
    return km


@pytest.fixture
def mock_providers():
    """Create mock provider instances."""
    anthropic_provider = MagicMock()
    anthropic_provider.provider_name = ProviderName.ANTHROPIC
    anthropic_provider.complete.return_value = LLMResponse(
        text='{"trend": "bullish"}',
        provider=ProviderName.ANTHROPIC,
        model="claude-sonnet-4-5-20250929",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.003,
    )

    openai_provider = MagicMock()
    openai_provider.provider_name = ProviderName.OPENAI
    openai_provider.complete.return_value = LLMResponse(
        text='{"trend": "bearish"}',
        provider=ProviderName.OPENAI,
        model="gpt-4o",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.002,
    )

    google_provider = MagicMock()
    google_provider.provider_name = ProviderName.GOOGLE
    google_provider.complete.return_value = LLMResponse(
        text='{"trend": "neutral"}',
        provider=ProviderName.GOOGLE,
        model="gemini-2.0-flash",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.0001,
    )

    return {
        ProviderName.ANTHROPIC: anthropic_provider,
        ProviderName.OPENAI: openai_provider,
        ProviderName.GOOGLE: google_provider,
    }


class TestLLMRouter:
    """Tests for LLMRouter."""

    @patch("src.llm.router.load_config")
    @patch("src.llm.router._create_provider")
    def test_cost_strategy_selects_cheapest(
        self, mock_create, mock_config, mock_key_manager, mock_providers
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        def side_effect(name, key, model, **kwargs):
            return mock_providers.get(name)

        mock_create.side_effect = side_effect

        router = LLMRouter(key_manager=mock_key_manager)
        decision = router.select_provider(RoutingStrategy.COST)

        assert decision.provider == ProviderName.GOOGLE
        assert decision.strategy == RoutingStrategy.COST

    @patch("src.llm.router.load_config")
    @patch("src.llm.router._create_provider")
    def test_quality_strategy_selects_best(
        self, mock_create, mock_config, mock_key_manager, mock_providers
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        def side_effect(name, key, model, **kwargs):
            return mock_providers.get(name)

        mock_create.side_effect = side_effect

        router = LLMRouter(key_manager=mock_key_manager)
        decision = router.select_provider(RoutingStrategy.QUALITY)

        assert decision.provider == ProviderName.ANTHROPIC
        assert decision.strategy == RoutingStrategy.QUALITY

    @patch("src.llm.router.load_config")
    @patch("src.llm.router._create_provider")
    def test_hybrid_strategy(
        self, mock_create, mock_config, mock_key_manager, mock_providers
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        def side_effect(name, key, model, **kwargs):
            return mock_providers.get(name)

        mock_create.side_effect = side_effect

        router = LLMRouter(key_manager=mock_key_manager)
        decision = router.select_provider(RoutingStrategy.HYBRID)

        assert isinstance(decision, RoutingDecision)
        assert decision.strategy == RoutingStrategy.HYBRID
        assert decision.score > 0

    @patch("src.llm.router.load_config")
    @patch("src.llm.router._create_provider")
    def test_complete_routes_to_provider(
        self, mock_create, mock_config, mock_key_manager, mock_providers
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        def side_effect(name, key, model, **kwargs):
            return mock_providers.get(name)

        mock_create.side_effect = side_effect

        router = LLMRouter(key_manager=mock_key_manager)
        messages = [LLMMessage(role="user", content="Test")]
        result = router.complete(messages)

        assert isinstance(result, LLMResponse)

    @patch("src.llm.router.load_config")
    @patch("src.llm.router._create_provider")
    def test_preferred_provider(
        self, mock_create, mock_config, mock_key_manager, mock_providers
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        def side_effect(name, key, model, **kwargs):
            return mock_providers.get(name)

        mock_create.side_effect = side_effect

        router = LLMRouter(key_manager=mock_key_manager)
        messages = [LLMMessage(role="user", content="Test")]
        result = router.complete(messages, preferred_provider=ProviderName.OPENAI)

        assert result.provider == ProviderName.OPENAI

    @patch("src.llm.router.load_config")
    @patch("src.llm.router._create_provider")
    def test_fallback_on_provider_failure(
        self, mock_create, mock_config, mock_key_manager, mock_providers
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        # Make anthropic fail
        mock_providers[ProviderName.ANTHROPIC].complete.side_effect = LLMProviderError(
            "Failed"
        )

        def side_effect(name, key, model, **kwargs):
            return mock_providers.get(name)

        mock_create.side_effect = side_effect

        router = LLMRouter(key_manager=mock_key_manager)
        messages = [LLMMessage(role="user", content="Test")]
        result = router.complete(
            messages,
            strategy=RoutingStrategy.QUALITY,
        )

        # Should fall back to openai or google
        assert result.provider in (ProviderName.OPENAI, ProviderName.GOOGLE)

    @patch("src.llm.router.load_config")
    @patch("src.llm.router._create_provider")
    def test_all_providers_fail_raises(
        self, mock_create, mock_config, mock_key_manager, mock_providers
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        for p in mock_providers.values():
            p.complete.side_effect = LLMProviderError("Failed")

        def side_effect(name, key, model, **kwargs):
            return mock_providers.get(name)

        mock_create.side_effect = side_effect

        router = LLMRouter(key_manager=mock_key_manager)
        messages = [LLMMessage(role="user", content="Test")]

        with pytest.raises(LLMProviderError, match="All providers failed"):
            router.complete(messages)

    @patch("src.llm.router.load_config")
    def test_no_providers_raises(self, mock_config):
        mock_config.return_value = {
            "providers": {},
            "routing": {"default_strategy": "hybrid"},
        }
        km = MagicMock()
        km.has_provider.return_value = False

        router = LLMRouter(key_manager=km)
        messages = [LLMMessage(role="user", content="Test")]

        with pytest.raises(LLMProviderError, match="No LLM providers"):
            router.complete(messages)

    @patch("src.llm.router.load_config")
    @patch("src.llm.router._create_provider")
    def test_available_providers(
        self, mock_create, mock_config, mock_key_manager, mock_providers
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        def side_effect(name, key, model, **kwargs):
            return mock_providers.get(name)

        mock_create.side_effect = side_effect

        router = LLMRouter(key_manager=mock_key_manager)
        available = router.available_providers
        assert ProviderName.ANTHROPIC in available
        assert ProviderName.OPENAI in available
        assert ProviderName.GOOGLE in available

    @patch("src.llm.router.load_config")
    @patch("src.llm.router._create_provider")
    def test_get_provider(
        self, mock_create, mock_config, mock_key_manager, mock_providers
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        def side_effect(name, key, model, **kwargs):
            return mock_providers.get(name)

        mock_create.side_effect = side_effect

        router = LLMRouter(key_manager=mock_key_manager)
        provider = router.get_provider(ProviderName.ANTHROPIC)
        assert provider is not None


class TestRoutingStrategy:
    """Tests for RoutingStrategy enum."""

    def test_values(self):
        assert RoutingStrategy.COST.value == "cost"
        assert RoutingStrategy.QUALITY.value == "quality"
        assert RoutingStrategy.HYBRID.value == "hybrid"

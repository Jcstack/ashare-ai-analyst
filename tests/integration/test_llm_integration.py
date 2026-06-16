"""Integration tests for the LLM abstraction layer.

Tests the router → provider → parse flow with mocked external APIs.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.base import LLMMessage, LLMResponse, ProviderName
from src.llm.router import LLMRouter, RoutingStrategy


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
    },
    "routing": {
        "default_strategy": "quality",
        "hybrid_weights": {"cost": 0.4, "quality": 0.6},
        "fallback_order": ["anthropic", "openai"],
    },
    "consensus": {"enabled": False},
    "key_storage": {"method": "encrypted_file"},
}


PREDICTION_JSON = {
    "trend": "bullish",
    "signal": "buy",
    "confidence": 0.75,
    "risk_level": "medium",
    "reasoning": ["趋势向好", "MACD金叉"],
    "target_price_range": {"low": 10.5, "high": 11.8},
    "key_factors": ["均线金叉"],
    "risk_warnings": ["调整风险"],
}


@pytest.fixture
def mock_anthropic_api():
    """Mock Anthropic SDK."""
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(text=json.dumps(PREDICTION_JSON, ensure_ascii=False))
    ]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=200)

    with patch("src.llm.anthropic.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_openai_api():
    """Mock OpenAI SDK."""
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(content=json.dumps(PREDICTION_JSON, ensure_ascii=False))
        )
    ]
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=200)

    with patch("src.llm.openai.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_cls.return_value = mock_client
        yield mock_client


class TestRouterProviderFlow:
    """Tests for router → provider → response flow."""

    @patch("src.llm.router.load_config")
    def test_router_to_anthropic_complete_flow(
        self, mock_config, mock_anthropic_api, mock_openai_api
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        km = MagicMock()
        km.has_provider.return_value = True
        km.get_key.return_value = "sk-test-12345678"

        router = LLMRouter(key_manager=km)
        messages = [
            LLMMessage(role="system", content="Analyze stock"),
            LLMMessage(role="user", content="000001 data"),
        ]

        result = router.complete(messages, strategy=RoutingStrategy.QUALITY)

        assert isinstance(result, LLMResponse)
        assert result.text  # non-empty
        parsed = json.loads(result.text)
        assert parsed["trend"] == "bullish"

    @patch("src.llm.router.load_config")
    def test_router_fallback_flow(
        self, mock_config, mock_anthropic_api, mock_openai_api
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        # Make Anthropic fail
        mock_anthropic_api.messages.create.side_effect = ConnectionError("API down")

        km = MagicMock()
        km.has_provider.return_value = True
        km.get_key.return_value = "sk-test-12345678"

        router = LLMRouter(key_manager=km)
        messages = [LLMMessage(role="user", content="Test")]

        result = router.complete(messages, strategy=RoutingStrategy.QUALITY)

        # Should have fallen back to OpenAI
        assert result.provider == ProviderName.OPENAI
        assert result.text  # non-empty

    @patch("src.llm.router.load_config")
    def test_analyzer_with_router(
        self,
        mock_config,
        mock_anthropic_api,
        mock_openai_api,
        sample_ohlcv_df,
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        km = MagicMock()
        km.has_provider.return_value = True
        km.get_key.return_value = "sk-test-12345678"

        router = LLMRouter(key_manager=km)

        # Patch load_config for both prompt builder and analyzer
        with patch("src.prediction.analyzer.load_config") as mock_pred_cfg:
            with patch("src.prediction.prompts.load_config") as mock_prompt_cfg:
                pred_config = {
                    "model": {
                        "name": "claude-sonnet-4-5-20250929",
                        "max_tokens": 4096,
                        "temperature": 0.3,
                    },
                    "retry": {
                        "max_attempts": 1,
                        "base_delay_seconds": 0,
                        "max_delay_seconds": 0,
                    },
                    "output_schema": {
                        "required_fields": [
                            "trend",
                            "signal",
                            "confidence",
                            "risk_level",
                            "reasoning",
                            "target_price_range",
                            "key_factors",
                            "risk_warnings",
                        ],
                    },
                }
                mock_pred_cfg.return_value = pred_config
                mock_prompt_cfg.return_value = pred_config

                from src.prediction.analyzer import StockAnalyzer

                analyzer = StockAnalyzer(router=router)
                result = analyzer.analyze(
                    symbol="000001",
                    ohlcv_df=sample_ohlcv_df,
                    indicators={"ma5": 10.5},
                    patterns=[],
                    sr_levels=[],
                )

                assert result["trend"] == "bullish"
                assert result["symbol"] == "000001"
                assert "timestamp" in result

    @patch("src.llm.router.load_config")
    def test_usage_tracked(
        self, mock_config, mock_anthropic_api, mock_openai_api, tmp_path
    ):
        mock_config.return_value = SAMPLE_LLM_CONFIG

        km = MagicMock()
        km.has_provider.return_value = True
        km.get_key.return_value = "sk-test-12345678"

        router = LLMRouter(key_manager=km)

        # Patch usage dir to tmp
        with patch.object(router._usage_tracker, "_usage_dir", tmp_path):
            messages = [LLMMessage(role="user", content="Test")]
            router.complete(messages, symbol="000001")

            summary = router.usage_tracker.get_daily_summary()
            assert summary["total_calls"] == 1

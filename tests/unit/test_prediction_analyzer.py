"""Unit tests for src/prediction/analyzer.py — StockAnalyzer.

Test cases per PRD Section 6.2:
  - TC-P001: Mock LLM router, verify analysis output structure
  - TC-P002: Retry/failure handling via router
  - TC-P004: JSON extraction from raw text and markdown blocks
  - TC-P005: Required field validation

Per PRD Section 6.3 mock strategy:
  - Mock LLM router (replaces direct Anthropic API mocking)
  - Mock config loading
  - NEVER make real API calls
"""

import json

import pytest
from unittest.mock import MagicMock, patch

from src.llm.base import LLMProviderError, LLMResponse, ProviderName


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PREDICTION_CONFIG = {
    "model": {
        "name": "claude-sonnet-4-5-20250929",
        "max_tokens": 4096,
        "temperature": 0.3,
    },
    "retry": {
        "max_attempts": 3,
        "base_delay_seconds": 0,  # No delay in tests
        "max_delay_seconds": 0,
    },
    "evaluation": {
        "direction_accuracy_threshold": 0.6,
        "price_range_tolerance": 0.05,
        "min_confidence": 0.5,
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

VALID_PREDICTION_JSON = {
    "trend": "bullish",
    "signal": "buy",
    "confidence": 0.75,
    "risk_level": "medium",
    "reasoning": [
        "趋势分析: 短期均线向上穿越长期均线",
        "技术指标分析: RSI在正常区间，MACD金叉",
        "形态分析: 出现锤子线看涨信号",
        "综合研判: 多重技术信号共振，看涨概率较大",
    ],
    "target_price_range": {"low": 10.50, "high": 11.80},
    "key_factors": ["均线多头排列", "成交量放大", "北向资金净流入"],
    "risk_warnings": ["大盘系统性风险", "行业政策不确定性"],
}


@pytest.fixture
def sample_indicators():
    """Sample technical indicator values."""
    return {"ma5": 10.85, "rsi": 65.2}


@pytest.fixture
def sample_patterns():
    """Sample candlestick patterns."""
    return [{"name": "锤子线", "type": "bullish", "date": "2024-01-15"}]


@pytest.fixture
def sample_sr_levels():
    """Sample support/resistance levels."""
    return [{"level": 10.20, "type": "support", "strength": "strong"}]


@pytest.fixture
def mock_llm_response():
    """Mock LLM response with valid prediction JSON."""
    return LLMResponse(
        text=json.dumps(VALID_PREDICTION_JSON, ensure_ascii=False),
        provider=ProviderName.ANTHROPIC,
        model="claude-sonnet-4-5-20250929",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.003,
    )


@pytest.fixture
def mock_router(mock_llm_response):
    """Create a mock LLMRouter returning valid predictions."""
    router = MagicMock()
    router.complete.return_value = mock_llm_response
    router.available_providers = [ProviderName.ANTHROPIC]
    router.get_provider.return_value = MagicMock()
    return router


def _create_analyzer(mock_load_config, mock_router):
    """Helper to create a StockAnalyzer with mocked dependencies."""
    mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG
    from src.prediction.analyzer import StockAnalyzer

    return StockAnalyzer(router=mock_router)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnalyze:
    """Tests for StockAnalyzer.analyze()."""

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_analyze_returns_prediction_dict(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_router,
        sample_ohlcv_df,
        sample_indicators,
        sample_patterns,
        sample_sr_levels,
    ):
        """TC-P001: Mock LLM router, verify output has required fields."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG
        analyzer = _create_analyzer(mock_analyzer_config, mock_router)

        result = analyzer.analyze(
            symbol="000001",
            ohlcv_df=sample_ohlcv_df,
            indicators=sample_indicators,
            patterns=sample_patterns,
            sr_levels=sample_sr_levels,
        )

        assert isinstance(result, dict)

        # All required fields must be present
        for field in SAMPLE_PREDICTION_CONFIG["output_schema"]["required_fields"]:
            assert field in result, f"Required field '{field}' missing from result"

        # Metadata fields
        assert result["symbol"] == "000001"
        assert "timestamp" in result
        assert "model" in result

        # Router should have been called once
        mock_router.complete.assert_called_once()


class TestCallLLM:
    """Tests for StockAnalyzer._call_llm() routing."""

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_call_llm_returns_text(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_router,
    ):
        """Verify _call_llm returns the LLM response text."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG
        analyzer = _create_analyzer(mock_analyzer_config, mock_router)

        messages = [
            {"role": "system", "content": "Test system"},
            {"role": "user", "content": "Test user"},
        ]

        result = analyzer._call_llm(messages)
        assert isinstance(result, str)
        assert "bullish" in result

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_call_llm_raises_analyzer_error(
        self,
        mock_prompt_config,
        mock_analyzer_config,
    ):
        """All providers fail → AnalyzerError."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG

        router = MagicMock()
        router.complete.side_effect = LLMProviderError("All failed")
        router.available_providers = [ProviderName.ANTHROPIC]

        analyzer = _create_analyzer(mock_analyzer_config, router)
        messages = [
            {"role": "system", "content": "Test"},
            {"role": "user", "content": "Test"},
        ]

        from src.prediction.analyzer import AnalyzerError

        with pytest.raises(AnalyzerError, match="LLM call failed"):
            analyzer._call_llm(messages)


class TestParseResponse:
    """Tests for StockAnalyzer._parse_response()."""

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_parse_response_extracts_json(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_router,
    ):
        """TC-P004: Test JSON extraction from raw text."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG
        analyzer = _create_analyzer(mock_analyzer_config, mock_router)

        raw_text = json.dumps(VALID_PREDICTION_JSON, ensure_ascii=False)
        result = analyzer._parse_response(raw_text)

        assert isinstance(result, dict)
        assert result["trend"] == "bullish"
        assert result["confidence"] == 0.75

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_parse_response_handles_markdown_blocks(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_router,
    ):
        """TC-P004: Test ```json ... ``` extraction."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG
        analyzer = _create_analyzer(mock_analyzer_config, mock_router)

        json_content = json.dumps(VALID_PREDICTION_JSON, ensure_ascii=False)
        raw_text = f"Here is my analysis:\n\n```json\n{json_content}\n```\n"
        result = analyzer._parse_response(raw_text)

        assert isinstance(result, dict)
        assert result["trend"] == "bullish"
        assert result["signal"] == "buy"

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_parse_response_handles_generic_code_blocks(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_router,
    ):
        """TC-P004: Test generic ``` ... ``` code block extraction."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG
        analyzer = _create_analyzer(mock_analyzer_config, mock_router)

        json_content = json.dumps(VALID_PREDICTION_JSON, ensure_ascii=False)
        raw_text = f"Analysis result:\n\n```\n{json_content}\n```\n"
        result = analyzer._parse_response(raw_text)

        assert isinstance(result, dict)
        assert result["trend"] == "bullish"

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_parse_response_validates_required_fields(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_router,
    ):
        """TC-P005: Test validation rejects responses missing required fields."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG
        analyzer = _create_analyzer(mock_analyzer_config, mock_router)

        # JSON with missing required fields
        incomplete_json = json.dumps({"trend": "bullish", "signal": "buy"})

        from src.prediction.analyzer import ResponseParsingError

        with pytest.raises(ResponseParsingError, match="Missing required"):
            analyzer._parse_response(incomplete_json)

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_parse_response_invalid_json(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_router,
    ):
        """TC-P004: Test handling of completely invalid JSON."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG
        analyzer = _create_analyzer(mock_analyzer_config, mock_router)

        from src.prediction.analyzer import ResponseParsingError

        with pytest.raises(ResponseParsingError):
            analyzer._parse_response("This is not JSON at all")

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_parse_response_json_array_raises(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_router,
    ):
        """TC-P005: Response containing JSON array instead of object raises."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG
        analyzer = _create_analyzer(mock_analyzer_config, mock_router)

        from src.prediction.analyzer import ResponseParsingError

        with pytest.raises(ResponseParsingError):
            analyzer._parse_response('[{"trend": "bullish"}]')


class TestCallLLMTruncationRetry:
    """Tests for _call_llm() truncation retry logic."""

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_retries_on_short_truncation(
        self,
        mock_prompt_config,
        mock_analyzer_config,
    ):
        """Retry with doubled max_tokens when finish_reason=length and tokens < half."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG

        truncated_response = LLMResponse(
            text='```json\n{"trend": "bearish',
            provider=ProviderName.GOOGLE,
            model="gemini-2.5-flash",
            output_tokens=164,
            finish_reason="length",
        )
        full_response = LLMResponse(
            text=json.dumps(VALID_PREDICTION_JSON, ensure_ascii=False),
            provider=ProviderName.GOOGLE,
            model="gemini-2.5-flash",
            output_tokens=800,
            finish_reason="stop",
        )

        router = MagicMock()
        router.complete.side_effect = [truncated_response, full_response]
        router.available_providers = [ProviderName.GOOGLE]

        analyzer = _create_analyzer(mock_analyzer_config, router)
        messages = [{"role": "user", "content": "Test"}]
        result = analyzer._call_llm(messages, symbol="600519")

        assert "bullish" in result
        assert router.complete.call_count == 2
        # Second call should have doubled max_tokens
        retry_call = router.complete.call_args_list[1]
        assert retry_call.kwargs["max_tokens"] == 8192

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_no_retry_when_tokens_above_half(
        self,
        mock_prompt_config,
        mock_analyzer_config,
    ):
        """No retry when truncated but output_tokens >= half of max_tokens."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG

        response = LLMResponse(
            text=json.dumps(VALID_PREDICTION_JSON, ensure_ascii=False),
            provider=ProviderName.GOOGLE,
            model="gemini-2.5-flash",
            output_tokens=3000,  # > 4096 // 2
            finish_reason="length",
        )

        router = MagicMock()
        router.complete.return_value = response
        router.available_providers = [ProviderName.GOOGLE]

        analyzer = _create_analyzer(mock_analyzer_config, router)
        messages = [{"role": "user", "content": "Test"}]
        analyzer._call_llm(messages, symbol="600519")

        router.complete.assert_called_once()

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_no_retry_on_normal_stop(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_router,
    ):
        """No retry when finish_reason=stop (normal completion)."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG
        analyzer = _create_analyzer(mock_analyzer_config, mock_router)

        messages = [{"role": "user", "content": "Test"}]
        analyzer._call_llm(messages, symbol="600519")

        mock_router.complete.assert_called_once()


class TestExtractJsonFromText:
    """Tests for the _extract_json_from_text helper function."""

    def test_extract_from_json_code_block(self):
        """Extract JSON from ```json ... ``` fenced block."""
        from src.prediction.analyzer import _extract_json_from_text

        text = '```json\n{"key": "value"}\n```'
        result = _extract_json_from_text(text)
        assert result == '{"key": "value"}'

    def test_extract_from_generic_code_block(self):
        """Extract JSON from generic ``` ... ``` fenced block."""
        from src.prediction.analyzer import _extract_json_from_text

        text = '```\n{"key": "value"}\n```'
        result = _extract_json_from_text(text)
        assert result == '{"key": "value"}'

    def test_extract_raw_json(self):
        """Extract JSON from raw text using brace matching."""
        from src.prediction.analyzer import _extract_json_from_text

        text = 'Some text {"key": "value"} more text'
        result = _extract_json_from_text(text)
        assert result == '{"key": "value"}'

    def test_extract_from_unclosed_json_fence(self):
        """Extract JSON from truncated ```json block without closing fence."""
        from src.prediction.analyzer import _extract_json_from_text

        text = '```json\n{"key": "value", "nested": {"a": 1}}'
        result = _extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed["key"] == "value"
        assert parsed["nested"]["a"] == 1

    def test_extract_from_unclosed_generic_fence(self):
        """Extract JSON from truncated ``` block without closing fence."""
        from src.prediction.analyzer import _extract_json_from_text

        text = '```\n{"status": "ok"}'
        result = _extract_json_from_text(text)
        assert json.loads(result)["status"] == "ok"

    def test_no_json_raises(self):
        """Raise ResponseParsingError when no JSON found."""
        from src.prediction.analyzer import (
            ResponseParsingError,
            _extract_json_from_text,
        )

        with pytest.raises(ResponseParsingError, match="No JSON content"):
            _extract_json_from_text("Plain text without JSON")


class TestBatchAnalyze:
    """Tests for StockAnalyzer.batch_analyze()."""

    @patch("src.prediction.analyzer.time.sleep")
    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_batch_analyze_all_symbols(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_sleep,
        mock_router,
        sample_ohlcv_df,
        sample_indicators,
        sample_patterns,
        sample_sr_levels,
    ):
        """Verify batch_analyze processes all symbols and returns results."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG
        analyzer = _create_analyzer(mock_analyzer_config, mock_router)

        symbols = ["000001", "600519", "300750"]
        ohlcv_map = {s: sample_ohlcv_df for s in symbols}
        indicators_map = {s: sample_indicators for s in symbols}
        patterns_map = {s: sample_patterns for s in symbols}
        sr_map = {s: sample_sr_levels for s in symbols}

        results = analyzer.batch_analyze(
            symbols=symbols,
            ohlcv_map=ohlcv_map,
            indicators_map=indicators_map,
            patterns_map=patterns_map,
            sr_map=sr_map,
        )

        assert len(results) == 3
        for symbol in symbols:
            assert symbol in results
            assert results[symbol]["symbol"] == symbol
            assert "trend" in results[symbol]

        # Rate limit delay should be called between symbols (not after last)
        assert mock_sleep.call_count == 2

    @patch("src.prediction.analyzer.time.sleep")
    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_batch_analyze_handles_per_symbol_error(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_sleep,
        mock_llm_response,
        sample_ohlcv_df,
        sample_indicators,
        sample_patterns,
        sample_sr_levels,
    ):
        """Verify batch continues when one symbol fails."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG

        router = MagicMock()
        router.available_providers = [ProviderName.ANTHROPIC]
        # First call fails, second succeeds
        router.complete.side_effect = [
            LLMProviderError("API down"),
            mock_llm_response,
        ]

        analyzer = _create_analyzer(mock_analyzer_config, router)

        symbols = ["000001", "600519"]
        ohlcv_map = {s: sample_ohlcv_df for s in symbols}
        indicators_map = {s: sample_indicators for s in symbols}
        patterns_map = {s: sample_patterns for s in symbols}
        sr_map = {s: sample_sr_levels for s in symbols}

        results = analyzer.batch_analyze(
            symbols=symbols,
            ohlcv_map=ohlcv_map,
            indicators_map=indicators_map,
            patterns_map=patterns_map,
            sr_map=sr_map,
        )

        # First symbol should fail, second succeed
        assert "000001" not in results
        assert "600519" in results
        assert results["600519"]["trend"] == "bullish"

    @patch("src.prediction.analyzer.time.sleep")
    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_batch_analyze_empty_symbols(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        mock_sleep,
        mock_router,
    ):
        """Verify batch_analyze returns empty dict for empty symbols list."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG
        analyzer = _create_analyzer(mock_analyzer_config, mock_router)

        results = analyzer.batch_analyze(
            symbols=[],
            ohlcv_map={},
            indicators_map={},
            patterns_map={},
            sr_map={},
        )

        assert results == {}
        mock_sleep.assert_not_called()


class TestAnalyzeMarket:
    """Tests for StockAnalyzer.analyze_market()."""

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_analyze_market_returns_expected_fields(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        sample_ohlcv_df,
    ):
        """Verify analyze_market returns market_trend, risk, sector outlook."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG

        market_response_json = json.dumps(
            {
                "market_trend": "bullish",
                "risk_assessment": "medium",
                "sector_outlook": {
                    "leading": ["银行", "白酒"],
                    "lagging": ["房地产"],
                },
                "reasoning": ["市场整体向好", "资金面宽松"],
                "key_risks": ["政策不确定性"],
            },
            ensure_ascii=False,
        )
        router = MagicMock()
        router.complete.return_value = LLMResponse(
            text=market_response_json,
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
        )
        router.available_providers = [ProviderName.ANTHROPIC]

        analyzer = _create_analyzer(mock_analyzer_config, router)
        result = analyzer.analyze_market(
            index_data={"000001": sample_ohlcv_df},
            market_indicators={"northbound_flow": 50.0},
        )

        assert result["market_trend"] == "bullish"
        assert result["risk_assessment"] == "medium"
        assert "sector_outlook" in result
        assert "timestamp" in result
        assert "model" in result

    @patch("src.prediction.analyzer.load_config")
    @patch("src.prediction.prompts.load_config")
    def test_analyze_market_missing_fields_raises(
        self,
        mock_prompt_config,
        mock_analyzer_config,
        sample_ohlcv_df,
    ):
        """Verify ResponseParsingError when market fields are missing."""
        mock_prompt_config.return_value = SAMPLE_PREDICTION_CONFIG

        # Missing required market fields
        incomplete_json = json.dumps({"market_trend": "bullish"})
        router = MagicMock()
        router.complete.return_value = LLMResponse(
            text=incomplete_json,
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
        )
        router.available_providers = [ProviderName.ANTHROPIC]

        analyzer = _create_analyzer(mock_analyzer_config, router)

        from src.prediction.analyzer import ResponseParsingError

        with pytest.raises(ResponseParsingError, match="Missing required"):
            analyzer.analyze_market(
                index_data={"000001": sample_ohlcv_df},
                market_indicators={},
            )

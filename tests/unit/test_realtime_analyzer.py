"""Unit tests for src/prediction/realtime_analyzer.py — RealtimeAnalyzer.

Tests comprehensive analysis, quick insight, market overview, caching,
response parsing, and LLM error fallback behavior.

Per PRD v2.0 FR-AI001/AI002/AI003.
Mock strategy: Mock LLMRouter and load_config only.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.base import LLMProviderError, LLMResponse, ProviderName
from src.llm.router import RoutingStrategy


# ---------------------------------------------------------------------------
# Sample config and LLM responses
# ---------------------------------------------------------------------------
SAMPLE_AGENT_CONFIG: dict = {
    "ai_analysis": {
        "quick_cache_ttl_seconds": 300,
        "deep_cache_ttl_seconds": 1800,
        "max_tokens_quick": 512,
        "max_tokens_deep": 4096,
        "temperature": 0.3,
    },
}

SAMPLE_DEEP_RESULT = json.dumps(
    {
        "trend": "bullish",
        "signal": "bullish",
        "confidence": 0.78,
        "risk_level": "medium",
        "reasoning": ["均线多头排列", "MACD金叉确认"],
        "target_price_range": {"low": 10.5, "high": 12.0},
        "key_factors": ["成交量放大", "板块轮动"],
        "risk_warnings": ["大盘系统性风险"],
        "news_sentiment": "positive",
    }
)

SAMPLE_QUICK_RESULT = json.dumps(
    {
        "signal": "bullish",
        "confidence": 0.70,
        "summary": "短期看多，技术面支撑强",
        "risk_badge": "low",
    }
)

SAMPLE_MARKET_RESULT = json.dumps(
    {
        "market_trend": "bullish",
        "risk_assessment": "low",
        "summary": "市场整体偏强，成交量回暖",
        "key_points": ["沪指站上3000点", "北向资金持续流入"],
        "sector_outlook": {"leading": ["新能源"], "lagging": ["地产"]},
    }
)


def _make_llm_response(
    text: str, model: str = "claude-sonnet-4-5-20250929"
) -> LLMResponse:
    """Create a mock LLMResponse wrapping JSON in markdown code block."""
    return LLMResponse(
        text=f"```json\n{text}\n```",
        provider=ProviderName.ANTHROPIC,
        model=model,
        input_tokens=200,
        output_tokens=400,
        latency_ms=1200.0,
        cost_usd=0.01,
    )


@pytest.fixture
def mock_router():
    """Create a mock LLMRouter."""
    router = MagicMock()
    router.complete.return_value = _make_llm_response(SAMPLE_DEEP_RESULT)
    return router


@pytest.fixture
def analyzer(mock_router):
    """Create a RealtimeAnalyzer with mocked dependencies."""
    with patch("src.prediction.realtime_analyzer.load_config") as mock_cfg:
        mock_cfg.return_value = SAMPLE_AGENT_CONFIG
        from src.prediction.realtime_analyzer import RealtimeAnalyzer

        yield RealtimeAnalyzer(router=mock_router, config_name="agent")


class TestAnalyzeStockRealtime:
    """Tests for RealtimeAnalyzer.analyze_stock_realtime()."""

    def test_returns_dict(self, analyzer):
        """analyze_stock_realtime should return a dictionary."""
        result = analyzer.analyze_stock_realtime(symbol="000001")
        assert isinstance(result, dict)

    def test_contains_status_success(self, analyzer):
        """Successful analysis should have status='success'."""
        result = analyzer.analyze_stock_realtime(symbol="000001")
        assert result.get("status") == "success"

    def test_contains_trend_and_signal(self, analyzer):
        """Result should contain trend and signal fields."""
        result = analyzer.analyze_stock_realtime(symbol="000001")
        assert result.get("trend") == "bullish"
        assert result.get("signal") == "bullish"

    def test_contains_symbol(self, analyzer):
        """Result should contain the requested symbol."""
        result = analyzer.analyze_stock_realtime(symbol="600519")
        assert result["symbol"] == "600519"

    def test_cache_hit_avoids_llm_call(self, analyzer, mock_router):
        """Second call within TTL should use cache."""
        analyzer.analyze_stock_realtime(symbol="000001")
        mock_router.complete.reset_mock()
        analyzer.analyze_stock_realtime(symbol="000001")
        mock_router.complete.assert_not_called()

    def test_force_refresh_bypasses_cache(self, analyzer, mock_router):
        """force_refresh=True should call LLM even with cached result."""
        analyzer.analyze_stock_realtime(symbol="000001")
        mock_router.complete.reset_mock()
        analyzer.analyze_stock_realtime(symbol="000001", force_refresh=True)
        mock_router.complete.assert_called_once()

    def test_llm_error_returns_error_status(self, analyzer, mock_router):
        """LLM failure should return dict with status='error'."""
        mock_router.complete.side_effect = LLMProviderError(
            "API timeout",
            provider=ProviderName.ANTHROPIC,
        )
        result = analyzer.analyze_stock_realtime(symbol="000001", force_refresh=True)
        assert result.get("status") == "error"
        assert "message" in result

    def test_with_all_data_inputs(self, analyzer):
        """Analysis with quote, news, anomalies, and indicators should succeed."""
        result = analyzer.analyze_stock_realtime(
            symbol="000001",
            quote={"price": 10.5, "change": 0.3, "volume": 1500000},
            news_items=[{"title": "利好消息", "datetime": "2024-01-05"}],
            anomalies=[{"datetime": "2024-01-05", "description": "大单买入"}],
            indicators={"rsi": 55.0, "sma_5": 10.2, "sma_20": 10.0},
        )
        assert result.get("status") == "success"

    def test_uses_quality_strategy(self, analyzer, mock_router):
        """Deep analysis should use QUALITY routing strategy."""
        analyzer.analyze_stock_realtime(symbol="000001", force_refresh=True)
        call_kwargs = mock_router.complete.call_args
        assert call_kwargs.kwargs.get("strategy") == RoutingStrategy.QUALITY


class TestGetQuickInsight:
    """Tests for RealtimeAnalyzer.get_quick_insight()."""

    def test_returns_dict(self, analyzer, mock_router):
        """get_quick_insight should return a dictionary."""
        mock_router.complete.return_value = _make_llm_response(SAMPLE_QUICK_RESULT)
        result = analyzer.get_quick_insight(symbol="000001")
        assert isinstance(result, dict)

    def test_contains_signal_and_summary(self, analyzer, mock_router):
        """Result should contain signal and summary fields."""
        mock_router.complete.return_value = _make_llm_response(SAMPLE_QUICK_RESULT)
        result = analyzer.get_quick_insight(symbol="000001")
        assert "signal" in result
        assert "summary" in result

    def test_llm_error_returns_neutral(self, analyzer, mock_router):
        """LLM failure should return neutral signal, not raise."""
        mock_router.complete.side_effect = LLMProviderError(
            "API error",
            provider=ProviderName.ANTHROPIC,
        )
        result = analyzer.get_quick_insight(symbol="000001")
        assert result["signal"] == "neutral"
        assert result["confidence"] == 0.0

    def test_uses_cost_strategy(self, analyzer, mock_router):
        """Quick insight should use COST routing strategy."""
        mock_router.complete.return_value = _make_llm_response(SAMPLE_QUICK_RESULT)
        analyzer.get_quick_insight(symbol="000001")
        call_kwargs = mock_router.complete.call_args
        assert call_kwargs.kwargs.get("strategy") == RoutingStrategy.COST


class TestQuickInsightSectorInfo:
    """Tests for sector_info parameter in get_quick_insight."""

    def test_quick_insight_with_sector_info(self, analyzer, mock_router):
        """Quick insight with sector_info should include concept data in prompt."""
        mock_router.complete.return_value = _make_llm_response(SAMPLE_QUICK_RESULT)
        result = analyzer.get_quick_insight(
            symbol="001330",
            quote={"price": 10.5, "pct_change": 3.2},
            sector_info={
                "concepts": [
                    {"name": "影视院线", "pct_change": 3.21},
                    {"name": "文生视频", "pct_change": 5.12},
                ],
                "resonance": {
                    "level": "moderate",
                    "concepts": ["影视院线", "文生视频"],
                },
            },
        )
        assert result.get("signal") == "bullish"
        # Verify prompt included sector info
        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages", [])
        user_prompt = str(messages[-1].content) if messages else ""
        assert "影视院线" in user_prompt or "概念板块" in user_prompt

    def test_quick_insight_without_sector_info(self, analyzer, mock_router):
        """Quick insight without sector_info should still succeed."""
        mock_router.complete.return_value = _make_llm_response(SAMPLE_QUICK_RESULT)
        result = analyzer.get_quick_insight(
            symbol="000001",
            sector_info=None,
        )
        assert isinstance(result, dict)
        assert "signal" in result


class TestQuickInsightV7Upgrade:
    """Tests for P02 quick insight v7.0 upgrades (FR-PR003)."""

    def test_confidence_label_present(self, analyzer, mock_router):
        """Quick insight result should include confidence_label."""
        quick_result = json.dumps(
            {
                "signal": "bullish",
                "confidence": 0.70,
                "summary": "短期看多，RSI=55 技术面支撑强",
                "risk_badge": "low",
            }
        )
        mock_router.complete.return_value = _make_llm_response(quick_result)
        result = analyzer.get_quick_insight(symbol="000001")
        assert "confidence_label" in result
        assert result["confidence_label"]  # should not be empty

    def test_key_data_present(self, analyzer, mock_router):
        """Quick insight result should include key_data field."""
        quick_result = json.dumps(
            {
                "signal": "bullish",
                "confidence": 0.70,
                "summary": "短期看多，RSI=55",
                "risk_badge": "low",
                "key_data": ["RSI=55", "MA5>MA20"],
            }
        )
        mock_router.complete.return_value = _make_llm_response(quick_result)
        result = analyzer.get_quick_insight(symbol="000001")
        assert "key_data" in result

    def test_uses_role_definition_in_prompt(self, analyzer, mock_router):
        """Quick insight prompt should include role definition from ROLE_DEFINITIONS."""
        quick_result = json.dumps(
            {
                "signal": "neutral",
                "confidence": 0.5,
                "summary": "中性",
                "risk_badge": "medium",
            }
        )
        mock_router.complete.return_value = _make_llm_response(quick_result)
        analyzer.get_quick_insight(symbol="000001")

        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages", [])
        system_prompt = str(messages[0].content) if messages else ""
        # Should contain role definition text
        assert "即时决策" in system_prompt or "A股" in system_prompt


class TestGetMarketOverview:
    """Tests for RealtimeAnalyzer.get_market_overview()."""

    def test_returns_dict(self, analyzer, mock_router):
        """get_market_overview should return a dictionary."""
        mock_router.complete.return_value = _make_llm_response(SAMPLE_MARKET_RESULT)
        result = analyzer.get_market_overview()
        assert isinstance(result, dict)

    def test_contains_market_trend(self, analyzer, mock_router):
        """Result should contain market_trend field."""
        mock_router.complete.return_value = _make_llm_response(SAMPLE_MARKET_RESULT)
        result = analyzer.get_market_overview()
        assert "market_trend" in result

    def test_llm_error_returns_neutral_overview(self, analyzer, mock_router):
        """LLM failure should return neutral market overview."""
        mock_router.complete.side_effect = LLMProviderError(
            "timeout",
            provider=ProviderName.ANTHROPIC,
        )
        # Clear cache to ensure fresh call
        analyzer._cache.clear()
        result = analyzer.get_market_overview()
        assert result.get("market_trend") == "neutral"
        assert result.get("status") == "error"


class TestExtractJson:
    """Tests for the static _extract_json helper."""

    def test_extracts_from_code_block(self, analyzer):
        """Should extract JSON from markdown code blocks."""
        text = '```json\n{"key": "value"}\n```'
        result = analyzer._extract_json(text)
        assert result == '{"key": "value"}'

    def test_extracts_raw_json(self, analyzer):
        """Should extract JSON from raw text without code blocks."""
        text = 'Some text {"key": "value"} more text'
        result = analyzer._extract_json(text)
        assert '{"key": "value"}' in result

    def test_returns_text_if_no_json(self, analyzer):
        """Should return stripped text if no JSON found."""
        text = "plain text"
        result = analyzer._extract_json(text)
        assert result == "plain text"

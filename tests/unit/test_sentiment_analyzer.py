"""Unit tests for src/analysis/sentiment.py — SentimentAnalyzer.

Tests batch sentiment analysis, single-item classification, response
parsing, empty input handling, and LLM error fallback.

Per PRD v2.0 FR-NF003: AI-powered news sentiment analysis.
Mock strategy: Mock LLMRouter only (external LLM dependency).
"""

import json
from unittest.mock import MagicMock

import pytest

from src.llm.base import LLMProviderError, LLMResponse, ProviderName


# ---------------------------------------------------------------------------
# Sample LLM response payloads
# ---------------------------------------------------------------------------
SAMPLE_SENTIMENT_JSON = json.dumps(
    {
        "overall": "positive",
        "score": 0.6,
        "items": [
            {"index": 1, "sentiment": "positive", "impact": "high"},
            {"index": 2, "sentiment": "neutral", "impact": "low"},
            {"index": 3, "sentiment": "negative", "impact": "medium"},
        ],
        "summary": "整体偏正面，利好消息占主导",
    }
)


def _make_llm_response(text: str) -> LLMResponse:
    """Create a mock LLMResponse with the given text."""
    return LLMResponse(
        text=f"```json\n{text}\n```",
        provider=ProviderName.ANTHROPIC,
        model="claude-sonnet-4-5-20250929",
        input_tokens=50,
        output_tokens=100,
        latency_ms=300.0,
        cost_usd=0.001,
    )


@pytest.fixture
def mock_router():
    """Create a mock LLMRouter."""
    router = MagicMock()
    router.complete.return_value = _make_llm_response(SAMPLE_SENTIMENT_JSON)
    return router


@pytest.fixture
def analyzer(mock_router):
    """Create a SentimentAnalyzer with mocked LLM router."""
    from src.analysis.sentiment import SentimentAnalyzer

    return SentimentAnalyzer(router=mock_router)


class TestAnalyzeBatch:
    """Tests for SentimentAnalyzer.analyze_batch()."""

    def test_returns_dict(self, analyzer):
        """analyze_batch should return a dictionary."""
        news = [{"title": "利好消息"}, {"title": "中性消息"}, {"title": "利空消息"}]
        result = analyzer.analyze_batch(news, symbol="000001")
        assert isinstance(result, dict)

    def test_overall_sentiment_present(self, analyzer):
        """Result should contain an overall sentiment field."""
        news = [{"title": "利好消息"}]
        result = analyzer.analyze_batch(news, symbol="000001")
        assert "overall" in result
        assert result["overall"] in ("positive", "negative", "neutral")

    def test_counts_match_items(self, analyzer):
        """Positive + negative + neutral counts should sum to total_count."""
        news = [{"title": f"新闻{i}"} for i in range(3)]
        result = analyzer.analyze_batch(news, symbol="000001")
        total = (
            result["positive_count"]
            + result["negative_count"]
            + result["neutral_count"]
        )
        assert total == result["total_count"]

    def test_score_in_range(self, analyzer):
        """Sentiment score should be between -1.0 and 1.0."""
        news = [{"title": "测试新闻"}]
        result = analyzer.analyze_batch(news, symbol="000001")
        assert -1.0 <= result["score"] <= 1.0

    def test_empty_input_returns_neutral(self, analyzer):
        """Empty news list should return neutral with zero counts."""
        result = analyzer.analyze_batch([], symbol="000001")
        assert result["overall"] == "neutral"
        assert result["total_count"] == 0
        assert result["positive_count"] == 0
        assert result["items"] == []

    def test_llm_error_returns_neutral_fallback(self, analyzer, mock_router):
        """LLM failure should return neutral fallback, not raise."""
        mock_router.complete.side_effect = LLMProviderError(
            "API error",
            provider=ProviderName.ANTHROPIC,
        )
        news = [{"title": "测试"}]
        result = analyzer.analyze_batch(news, symbol="000001")
        assert result["overall"] == "neutral"
        assert result["total_count"] == 1

    def test_malformed_json_returns_neutral(self, analyzer, mock_router):
        """Unparseable JSON response should return neutral fallback."""
        mock_router.complete.return_value = _make_llm_response("not valid json {{{")
        news = [{"title": "测试"}]
        result = analyzer.analyze_batch(news, symbol="000001")
        assert result["overall"] == "neutral"

    def test_summary_present(self, analyzer):
        """Result should contain a summary field."""
        news = [{"title": "利好消息"}]
        result = analyzer.analyze_batch(news, symbol="000001")
        assert "summary" in result

    def test_calls_router_with_cost_strategy(self, analyzer, mock_router):
        """Sentiment analysis should use COST routing strategy."""
        from src.llm.router import RoutingStrategy

        news = [{"title": "测试"}]
        analyzer.analyze_batch(news, symbol="000001")
        call_kwargs = mock_router.complete.call_args
        assert call_kwargs.kwargs.get("strategy") == RoutingStrategy.COST


class TestClassifyNewsImpact:
    """Tests for SentimentAnalyzer.classify_news_impact()."""

    def test_returns_dict(self, analyzer):
        """classify_news_impact should return a dict with sentiment and impact."""
        result = analyzer.classify_news_impact({"title": "利好"})
        assert isinstance(result, dict)

    def test_single_item_delegates_to_batch(self, analyzer, mock_router):
        """classify_news_impact should call analyze_batch internally."""
        analyzer.classify_news_impact({"title": "利好"})
        mock_router.complete.assert_called_once()

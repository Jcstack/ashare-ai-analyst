"""Unit tests for src/llm/consensus.py — ConsensusAnalyzer.

Tests weighted voting, agreement calculation, and multi-provider analysis.
"""

import json
from unittest.mock import MagicMock


from src.llm.base import (
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    ProviderName,
)
from src.llm.consensus import (
    ConsensusAnalyzer,
    ConsensusResult,
)


def _make_response(provider, text, cost=0.001):
    """Create an LLMResponse with the given provider and text."""
    return LLMResponse(
        text=text,
        provider=provider,
        model="test-model",
        input_tokens=100,
        output_tokens=200,
        cost_usd=cost,
    )


def _make_provider(provider_name, text):
    """Create a mock provider returning fixed text."""
    provider = MagicMock()
    provider.provider_name = provider_name
    provider.complete.return_value = _make_response(provider_name, text)
    return provider


def _parse_fn(raw_text):
    """Simple JSON parser for testing."""
    data = json.loads(raw_text)
    return data


class TestConsensusAnalyzer:
    """Tests for ConsensusAnalyzer."""

    def test_full_agreement(self):
        providers = {
            ProviderName.ANTHROPIC: _make_provider(
                ProviderName.ANTHROPIC,
                '{"trend": "bullish", "signal": "buy", "confidence": 0.8}',
            ),
            ProviderName.OPENAI: _make_provider(
                ProviderName.OPENAI,
                '{"trend": "bullish", "signal": "buy", "confidence": 0.7}',
            ),
        }

        analyzer = ConsensusAnalyzer(
            providers=providers,
            parse_fn=_parse_fn,
            weights={"anthropic": 0.6, "openai": 0.4},
        )

        messages = [LLMMessage(role="user", content="Analyze")]
        result = analyzer.analyze_with_consensus(messages)

        assert isinstance(result, ConsensusResult)
        assert result.consensus_trend == "bullish"
        assert result.consensus_signal == "buy"
        assert result.agreement_score == 1.0
        assert len(result.individual_results) == 2

    def test_trend_agreement_signal_disagreement(self):
        providers = {
            ProviderName.ANTHROPIC: _make_provider(
                ProviderName.ANTHROPIC,
                '{"trend": "bullish", "signal": "buy", "confidence": 0.8}',
            ),
            ProviderName.OPENAI: _make_provider(
                ProviderName.OPENAI,
                '{"trend": "bullish", "signal": "hold", "confidence": 0.6}',
            ),
        }

        analyzer = ConsensusAnalyzer(providers=providers, parse_fn=_parse_fn)
        messages = [LLMMessage(role="user", content="Analyze")]
        result = analyzer.analyze_with_consensus(messages)

        assert result.consensus_trend == "bullish"
        assert result.agreement_score == 0.5

    def test_full_disagreement(self):
        providers = {
            ProviderName.ANTHROPIC: _make_provider(
                ProviderName.ANTHROPIC,
                '{"trend": "bullish", "signal": "buy", "confidence": 0.8}',
            ),
            ProviderName.OPENAI: _make_provider(
                ProviderName.OPENAI,
                '{"trend": "bearish", "signal": "sell", "confidence": 0.7}',
            ),
        }

        analyzer = ConsensusAnalyzer(providers=providers, parse_fn=_parse_fn)
        messages = [LLMMessage(role="user", content="Analyze")]
        result = analyzer.analyze_with_consensus(messages)

        assert result.agreement_score == 0.0

    def test_weighted_vote_trend(self):
        """Higher-weighted provider wins."""
        providers = {
            ProviderName.ANTHROPIC: _make_provider(
                ProviderName.ANTHROPIC,
                '{"trend": "bullish", "signal": "buy", "confidence": 0.8}',
            ),
            ProviderName.OPENAI: _make_provider(
                ProviderName.OPENAI,
                '{"trend": "bearish", "signal": "sell", "confidence": 0.7}',
            ),
            ProviderName.GOOGLE: _make_provider(
                ProviderName.GOOGLE,
                '{"trend": "bearish", "signal": "sell", "confidence": 0.6}',
            ),
        }

        # Bearish has more total weight (0.35 + 0.25 = 0.6 > 0.4)
        analyzer = ConsensusAnalyzer(
            providers=providers,
            parse_fn=_parse_fn,
            weights={"anthropic": 0.4, "openai": 0.35, "google": 0.25},
        )
        messages = [LLMMessage(role="user", content="Analyze")]
        result = analyzer.analyze_with_consensus(messages)

        assert result.consensus_trend == "bearish"

    def test_weighted_confidence(self):
        providers = {
            ProviderName.ANTHROPIC: _make_provider(
                ProviderName.ANTHROPIC,
                '{"trend": "bullish", "signal": "buy", "confidence": 0.9}',
            ),
            ProviderName.OPENAI: _make_provider(
                ProviderName.OPENAI,
                '{"trend": "bullish", "signal": "buy", "confidence": 0.7}',
            ),
        }

        analyzer = ConsensusAnalyzer(
            providers=providers,
            parse_fn=_parse_fn,
            weights={"anthropic": 0.6, "openai": 0.4},
        )
        messages = [LLMMessage(role="user", content="Analyze")]
        result = analyzer.analyze_with_consensus(messages)

        # Weighted: (0.9 * 0.6 + 0.7 * 0.4) / (0.6 + 0.4) = 0.82
        assert abs(result.consensus_confidence - 0.82) < 0.01

    def test_provider_failure_excluded(self):
        good_provider = _make_provider(
            ProviderName.ANTHROPIC,
            '{"trend": "bullish", "signal": "buy", "confidence": 0.8}',
        )
        bad_provider = MagicMock()
        bad_provider.complete.side_effect = LLMProviderError("Failed")

        providers = {
            ProviderName.ANTHROPIC: good_provider,
            ProviderName.OPENAI: bad_provider,
        }

        analyzer = ConsensusAnalyzer(providers=providers, parse_fn=_parse_fn)
        messages = [LLMMessage(role="user", content="Analyze")]
        result = analyzer.analyze_with_consensus(messages)

        assert len(result.individual_results) == 1
        assert result.consensus_trend == "bullish"

    def test_all_providers_fail(self):
        bad1 = MagicMock()
        bad1.complete.side_effect = LLMProviderError("Failed 1")
        bad2 = MagicMock()
        bad2.complete.side_effect = LLMProviderError("Failed 2")

        providers = {
            ProviderName.ANTHROPIC: bad1,
            ProviderName.OPENAI: bad2,
        }

        analyzer = ConsensusAnalyzer(providers=providers, parse_fn=_parse_fn)
        messages = [LLMMessage(role="user", content="Analyze")]
        result = analyzer.analyze_with_consensus(messages)

        assert result.consensus_trend == "unknown"
        assert result.consensus_signal == "hold"
        assert result.agreement_score == 0.0

    def test_total_cost_calculated(self):
        providers = {
            ProviderName.ANTHROPIC: _make_provider(
                ProviderName.ANTHROPIC,
                '{"trend": "bullish", "signal": "buy", "confidence": 0.8}',
            ),
            ProviderName.OPENAI: _make_provider(
                ProviderName.OPENAI,
                '{"trend": "bullish", "signal": "buy", "confidence": 0.7}',
            ),
        }

        analyzer = ConsensusAnalyzer(providers=providers, parse_fn=_parse_fn)
        messages = [LLMMessage(role="user", content="Analyze")]
        result = analyzer.analyze_with_consensus(messages)

        assert result.total_cost > 0

    def test_single_provider_agreement_1(self):
        providers = {
            ProviderName.ANTHROPIC: _make_provider(
                ProviderName.ANTHROPIC,
                '{"trend": "bullish", "signal": "buy", "confidence": 0.8}',
            ),
        }

        analyzer = ConsensusAnalyzer(providers=providers, parse_fn=_parse_fn)
        messages = [LLMMessage(role="user", content="Analyze")]
        result = analyzer.analyze_with_consensus(messages)

        assert result.agreement_score == 1.0

    def test_specific_providers_param(self):
        providers = {
            ProviderName.ANTHROPIC: _make_provider(
                ProviderName.ANTHROPIC,
                '{"trend": "bullish", "signal": "buy", "confidence": 0.8}',
            ),
            ProviderName.OPENAI: _make_provider(
                ProviderName.OPENAI,
                '{"trend": "bearish", "signal": "sell", "confidence": 0.7}',
            ),
        }

        analyzer = ConsensusAnalyzer(providers=providers, parse_fn=_parse_fn)
        messages = [LLMMessage(role="user", content="Analyze")]
        result = analyzer.analyze_with_consensus(
            messages, provider_names=[ProviderName.ANTHROPIC]
        )

        assert len(result.individual_results) == 1
        assert result.consensus_trend == "bullish"

    def test_parse_failure_handled(self):
        providers = {
            ProviderName.ANTHROPIC: _make_provider(
                ProviderName.ANTHROPIC, "not json at all"
            ),
        }

        def bad_parse(text):
            raise ValueError("Parse failed")

        analyzer = ConsensusAnalyzer(providers=providers, parse_fn=bad_parse)
        messages = [LLMMessage(role="user", content="Analyze")]
        result = analyzer.analyze_with_consensus(messages)

        # Should still have individual result, just with empty fields
        assert len(result.individual_results) == 1
        assert result.individual_results[0].trend == ""

"""Tests for ConfidenceScorer.

Part of v20.0 Market Intelligence Phase 2.
"""

from __future__ import annotations

import math
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.market_intelligence.confidence_scorer import (
    ConfidenceScorer,
    W_SOURCE_RELIABILITY,
    _FRESHNESS_HALFLIFE_MS,
)
from src.web.schemas.market_signal import (
    MarketPhase,
    MarketSignal,
    SignalType,
    SourceReference,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    *,
    signal_type: SignalType = SignalType.S1_TREND,
    confidence_score: float = 50.0,
    sources: list[SourceReference] | None = None,
    data_freshness_ms: int = 0,
    producer: str = "test",
) -> MarketSignal:
    """Build a minimal MarketSignal for testing."""
    return MarketSignal(
        signal_type=signal_type,
        timestamp=datetime.now(timezone.utc),
        assets=["600519"],
        phase=MarketPhase.CLOSED,
        confidence_score=confidence_score,
        sources=sources or [],
        producer=producer,
        summary_short="test signal",
        data_freshness_ms=data_freshness_ms,
    )


def _make_source(provider: str = "akshare") -> SourceReference:
    """Build a minimal SourceReference."""
    return SourceReference(
        source_id="src-1",
        provider=provider,
        data_type="quote",
        timestamp=datetime.now(timezone.utc),
        reliability_score=0.8,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfidenceScorer:
    """Tests for the ConfidenceScorer composite scoring logic."""

    def test_score_all_defaults(self):
        """No dependencies injected, verify score is between 0-100."""
        scorer = ConfidenceScorer()
        signal = _make_signal()

        score = scorer.score(signal)

        assert 0.0 <= score <= 100.0

    def test_source_reliability_factor(self):
        """Mock health_tracker.get_health to return success_rate=0.9.

        Factor = 0.9 * 100.0 = 90.0
        Weighted contribution = 0.25 * 90.0 = 22.5
        """
        health_tracker = MagicMock()
        health_tracker.get_health.return_value = {"success_rate": 0.9}

        scorer = ConfidenceScorer(health_tracker=health_tracker)
        signal = _make_signal(producer="test_producer")

        # Access the private method directly to verify the factor
        factor = scorer._source_reliability(signal)
        assert factor == pytest.approx(90.0)

        # Verify the weighted contribution
        weighted = W_SOURCE_RELIABILITY * factor
        assert weighted == pytest.approx(22.5)

    def test_multi_source_confirmation_zero_sources(self):
        """Signal with 0 sources, verify multi_source factor is 0."""
        scorer = ConfidenceScorer()
        signal = _make_signal(sources=[])

        factor = scorer._multi_source_confirmation(signal)
        assert factor == 0.0

    def test_multi_source_confirmation_two_sources(self):
        """Signal with 2 SourceReference objects, verify factor is 100."""
        scorer = ConfidenceScorer()
        sources = [_make_source("akshare"), _make_source("sina")]
        signal = _make_signal(sources=sources)

        factor = scorer._multi_source_confirmation(signal)
        assert factor == 100.0

    def test_data_freshness_zero_ms(self):
        """Signal with data_freshness_ms=0, verify freshness factor is 100."""
        scorer = ConfidenceScorer()
        signal = _make_signal(data_freshness_ms=0)

        factor = scorer._data_freshness(signal)
        assert factor == 100.0

    def test_data_freshness_stale(self):
        """Signal with data_freshness_ms=600_000 (10 min), verify freshness < 20.

        Expected: 100 * exp(-600_000 / 300_000) = 100 * exp(-2) ~ 13.5
        """
        scorer = ConfidenceScorer()
        signal = _make_signal(data_freshness_ms=600_000)

        factor = scorer._data_freshness(signal)
        expected = 100.0 * math.exp(-600_000 / _FRESHNESS_HALFLIFE_MS)
        assert factor == pytest.approx(expected, abs=0.1)
        assert factor < 20.0

    def test_volatility_adjustment_high(self):
        """Mock regime_detector to return high regime, verify score is ~70% of baseline."""
        regime_detector = MagicMock()
        regime_report = types.SimpleNamespace(
            current_regime=types.SimpleNamespace(regime_label="high_volatility")
        )
        regime_detector.detect.return_value = regime_report

        scorer = ConfidenceScorer(regime_detector=regime_detector)
        signal = _make_signal()
        context = {"daily_returns": [0.01, -0.02, 0.005]}

        # Score with high volatility regime
        score_high = scorer.score(signal, context)

        # Score without regime detector (adjustment = 1.0)
        scorer_base = ConfidenceScorer()
        score_base = scorer_base.score(signal)

        # High volatility multiplier is 0.7
        assert score_high == pytest.approx(score_base * 0.7, abs=0.1)

    def test_score_breakdown_keys(self):
        """Verify score_breakdown returns dict with all expected keys."""
        scorer = ConfidenceScorer()
        signal = _make_signal()

        breakdown = scorer.score_breakdown(signal)

        expected_keys = {
            "source_reliability",
            "multi_source_confirmation",
            "data_freshness",
            "historical_accuracy",
            "signal_strength",
            "volatility_adjustment",
            "composite",
        }
        assert set(breakdown.keys()) == expected_keys
        assert 0.0 <= breakdown["composite"] <= 100.0

"""Unit tests for AntiSiloEngine (v20.0 Phase 4).

Tests cover:
- Injection quota (medium diversity, 10 signals → at least 1 injection)
- Injected signals are marked is_injection=True
- Injection reason is populated
- Contrarian view generation for S1_TREND
- SYSTEM_ALERT returns None for contrarian view
- should_inject for unfollowed stock
- set_diversity_level changes injection rates
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.market_intelligence.anti_silo import AntiSiloEngine
from src.web.schemas.market_signal import MarketPhase, MarketSignal, SignalType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    *,
    signal_type: SignalType = SignalType.S1_TREND,
    assets: list[str] | None = None,
    confidence: float = 60.0,
    summary: str = "bullish trend detected",
) -> MarketSignal:
    """Build a minimal MarketSignal for testing."""
    return MarketSignal(
        signal_type=signal_type,
        timestamp=datetime.now(timezone.utc),
        assets=assets if assets is not None else ["600519"],
        phase=MarketPhase.MORNING,
        confidence_score=confidence,
        producer="test",
        summary_short=summary[:50],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine() -> AntiSiloEngine:
    """Create a medium-diversity AntiSiloEngine."""
    return AntiSiloEngine(diversity_level="medium")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInjectAddsSignals:
    """With medium diversity (15%), 10 signals → should inject at least 1."""

    def test_inject_adds_signals(self, engine: AntiSiloEngine) -> None:
        signals = [_make_signal() for _ in range(10)]

        result = engine.inject(signals, user_follows=None)

        # Original 10 + at least 1 injection
        assert len(result) > len(signals)


class TestInjectMarksInjection:
    """Injected signals have is_injection=True."""

    def test_inject_marks_injection(self, engine: AntiSiloEngine) -> None:
        signals = [_make_signal()]
        result = engine.inject(signals, user_follows=None)

        injected = [s for s in result if s.is_injection]
        assert len(injected) >= 1
        for s in injected:
            assert s.is_injection is True


class TestInjectionReasonPopulated:
    """Injected signals have injection_reason set."""

    def test_injection_reason_populated(self, engine: AntiSiloEngine) -> None:
        signals = [_make_signal()]
        result = engine.inject(signals, user_follows=None)

        injected = [s for s in result if s.is_injection]
        assert len(injected) >= 1
        for s in injected:
            assert s.injection_reason is not None
            assert len(s.injection_reason) > 0


class TestContrarianViewTrend:
    """S1_TREND signal generates contrarian with opposite summary."""

    def test_contrarian_view_trend(self, engine: AntiSiloEngine) -> None:
        signal = _make_signal(
            signal_type=SignalType.S1_TREND,
            summary="bullish trend detected",
        )

        contrarian = engine.add_contrarian_view(signal)

        assert contrarian is not None
        assert contrarian.is_injection is True
        assert contrarian.injection_reason == "contrarian_view"
        # Summary should contain "bearish" instead of "bullish"
        assert "bearish" in contrarian.summary_short.lower()
        # Confidence should be discounted by 20%
        assert contrarian.confidence_score == pytest.approx(
            signal.confidence_score * 0.8
        )


class TestContrarianViewReturnsNoneForSystem:
    """SYSTEM_ALERT returns None (not a directional type)."""

    def test_contrarian_view_returns_none_for_system(
        self, engine: AntiSiloEngine
    ) -> None:
        signal = _make_signal(
            signal_type=SignalType.SYSTEM_ALERT,
            summary="system maintenance notice",
        )

        result = engine.add_contrarian_view(signal)

        assert result is None


class TestShouldInjectOutsideFollows:
    """Signal with unfollowed stock returns True."""

    def test_should_inject_outside_follows(self, engine: AntiSiloEngine) -> None:
        signal = _make_signal(assets=["300999"])
        user_follows = {
            "stocks": ["600519", "000858"],
            "signal_types": [],
            "sectors": [],
        }

        result = engine.should_inject(signal, user_follows)

        assert result is True


class TestSetDiversityLevel:
    """Verify low/medium/high change injection rates."""

    def test_set_diversity_level(self) -> None:
        engine = AntiSiloEngine(diversity_level="low")
        signals = [_make_signal(assets=[f"00000{i}"]) for i in range(20)]
        user_follows = None

        # Low: 5% of 20 = 1, ceil → 1 injection quota
        result_low = engine.inject(signals, user_follows)

        engine.set_diversity_level("high")
        # High: 30% of 20 = 6 injection quota
        result_high = engine.inject(signals, user_follows)

        # High diversity should produce at least as many injections as low
        injected_low = len(result_low) - len(signals)
        injected_high = len(result_high) - len(signals)
        assert injected_high >= injected_low

    def test_set_diversity_level_invalid(self) -> None:
        engine = AntiSiloEngine(diversity_level="low")

        with pytest.raises(ValueError, match="Invalid diversity_level"):
            engine.set_diversity_level("extreme")

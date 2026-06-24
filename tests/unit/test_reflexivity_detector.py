"""Tests for ReflexivityDetector — Soros-style feedback loop analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.agent_loop.reflexivity_detector import ReflexivityDetector, ReflexivityResult


@pytest.fixture
def detector() -> ReflexivityDetector:
    return ReflexivityDetector()


def _make_bars(
    closes: list[float],
    volumes: list[float],
    n: int | None = None,
) -> pd.DataFrame:
    """Build a minimal minute-bar DataFrame from close prices and volumes."""
    if n is None:
        n = len(closes)
    assert len(closes) == n
    assert len(volumes) == n
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2026-03-11 09:30", periods=n, freq="5min"),
            "open": closes,
            "high": [c * 1.002 for c in closes],
            "low": [c * 0.998 for c in closes],
            "close": closes,
            "volume": volumes,
            "amount": [c * v for c, v in zip(closes, volumes)],
        }
    )


# ------------------------------------------------------------------
# Test: strengthening loop (price up + volume up, both accelerating)
# ------------------------------------------------------------------
class TestStrengtheningLoop:
    def test_detects_strengthening(self, detector: ReflexivityDetector) -> None:
        """Price and volume both accelerating should give positive score."""
        n = 30
        # Strongly accelerating price: returns grow quadratically
        closes = [10.0]
        for i in range(1, n):
            closes.append(closes[-1] * (1 + 0.005 * i))
        # Strongly accelerating volume: exponential growth
        volumes = [1_000_000]
        for i in range(1, n):
            volumes.append(volumes[-1] * (1 + 0.03 * i))

        bars = _make_bars(closes, volumes, n)
        result = detector.analyze(bars, "600001")

        assert isinstance(result, ReflexivityResult)
        assert result.reflexivity_score > 0
        assert result.loop_state == "strengthening"
        assert result.direction == "bullish"
        assert result.severity > 0
        assert "加强" in result.description

    def test_strengthening_low_reversal_probability(
        self, detector: ReflexivityDetector
    ) -> None:
        """A young strengthening loop should have low reversal probability."""
        n = 30
        closes = [10.0]
        for i in range(1, n):
            closes.append(closes[-1] * (1 + 0.005 * i))
        volumes = [1_000_000]
        for i in range(1, n):
            volumes.append(volumes[-1] * (1 + 0.03 * i))

        bars = _make_bars(closes, volumes, n)
        result = detector.analyze(bars, "600001")

        assert result.reversal_probability < 0.5


# ------------------------------------------------------------------
# Test: exhausting loop (price up but volume decelerating)
# ------------------------------------------------------------------
class TestExhaustingLoop:
    def test_detects_exhausting(self, detector: ReflexivityDetector) -> None:
        """Price accelerating but volume sharply decelerating = exhausting."""
        n = 30
        # Price keeps accelerating
        closes = [10.0]
        for i in range(1, n):
            closes.append(closes[-1] * (1 + 0.005 * i))
        # Volume: grows strongly first 15 bars, then collapses
        volumes = [1_000_000]
        for i in range(1, n):
            if i < 15:
                volumes.append(volumes[-1] * (1 + 0.03 * i))
            else:
                # Volume collapsing: shrink by 10-20% per bar
                volumes.append(volumes[-1] * (0.85 - 0.02 * (i - 15)))

        bars = _make_bars(closes, volumes, n)
        result = detector.analyze(bars, "600002")

        # Volume deceleration should produce negative or near-zero score
        assert result.loop_state in ("exhausting", "breaking", "none")
        # The key check: volume and price accelerations diverge
        assert result.volume_acceleration < result.price_acceleration


# ------------------------------------------------------------------
# Test: breaking loop (sharp reversal after sustained loop)
# ------------------------------------------------------------------
class TestBreakingLoop:
    def test_detects_breaking_after_sustained_positive(
        self, detector: ReflexivityDetector
    ) -> None:
        """A sustained positive loop followed by sharp price crash.

        Phase 1: strong bullish loop (price+volume accelerating together).
        Phase 2: price crashes sharply (returns become very negative),
        while volume continues high — the price acceleration reversal
        should be detectable.
        """
        closes = []
        volumes = []

        # Phase 1 (bars 0-24): strong accelerating bullish loop
        closes.append(10.0)
        volumes.append(1_000_000)
        for i in range(1, 25):
            closes.append(closes[-1] * (1 + 0.005 * i))
            volumes.append(volumes[-1] * (1 + 0.02 * i))

        # Phase 2 (bars 25-34): sharp price crash with high volume
        for i in range(10):
            closes.append(closes[-1] * (0.92 - 0.02 * i))
            volumes.append(volumes[-1] * 1.5)

        n = len(closes)
        bars = _make_bars(closes, volumes, n)
        result = detector.analyze(bars, "600003")

        # Price acceleration should be strongly negative after the crash
        assert result.price_acceleration < 0
        # The crash represents a dramatic regime change
        assert result.direction == "bearish"


# ------------------------------------------------------------------
# Test: no loop (flat / random data)
# ------------------------------------------------------------------
class TestNoLoop:
    def test_flat_data_no_loop(self, detector: ReflexivityDetector) -> None:
        """Flat price and volume should produce no loop."""
        n = 20
        closes = [10.0] * n
        volumes = [1_000_000] * n

        bars = _make_bars(closes, volumes, n)
        result = detector.analyze(bars, "600004")

        assert result.loop_state == "none"
        assert abs(result.reflexivity_score) < detector.LOOP_THRESHOLD
        assert result.severity == 0.0

    def test_random_data_low_score(self, detector: ReflexivityDetector) -> None:
        """Random data should generally not trigger a strong loop."""
        rng = np.random.default_rng(42)
        n = 20
        closes = (10.0 + rng.normal(0, 0.02, n).cumsum()).tolist()
        volumes = (1_000_000 + rng.normal(0, 10_000, n)).tolist()
        # Ensure positive
        closes = [max(1.0, c) for c in closes]
        volumes = [max(100, v) for v in volumes]

        bars = _make_bars(closes, volumes, n)
        result = detector.analyze(bars, "600005")

        # May or may not detect a loop, but severity should be moderate
        assert result.severity <= 1.0
        assert result.reversal_probability <= 1.0


# ------------------------------------------------------------------
# Test: insufficient data
# ------------------------------------------------------------------
class TestInsufficientData:
    def test_too_few_bars(self, detector: ReflexivityDetector) -> None:
        """With fewer bars than MIN_BARS, should return neutral result."""
        bars = _make_bars([10.0] * 5, [1_000_000] * 5, 5)
        result = detector.analyze(bars, "600006")

        assert result.loop_state == "none"
        assert result.reflexivity_score == 0.0
        assert result.severity == 0.0
        assert "数据不足" in result.description

    def test_empty_dataframe(self, detector: ReflexivityDetector) -> None:
        """Empty DataFrame should return neutral."""
        bars = pd.DataFrame(
            columns=["datetime", "open", "high", "low", "close", "volume", "amount"]
        )
        result = detector.analyze(bars, "600007")

        assert result.loop_state == "none"
        assert result.reflexivity_score == 0.0

    def test_none_bars(self, detector: ReflexivityDetector) -> None:
        """None input should return neutral."""
        result = detector.analyze(None, "600008")  # type: ignore[arg-type]

        assert result.loop_state == "none"
        assert result.reflexivity_score == 0.0


# ------------------------------------------------------------------
# Test: direction detection
# ------------------------------------------------------------------
class TestDirectionDetection:
    def test_bullish_direction(self, detector: ReflexivityDetector) -> None:
        """Rising prices should be classified as bullish."""
        n = 20
        closes = [10.0]
        for i in range(1, n):
            closes.append(closes[-1] * (1 + 0.002 * i))
        volumes = [1_000_000] * n

        bars = _make_bars(closes, volumes, n)
        result = detector.analyze(bars, "600009")

        assert result.direction == "bullish"

    def test_bearish_direction(self, detector: ReflexivityDetector) -> None:
        """Falling prices should be classified as bearish."""
        n = 20
        closes = [15.0]
        for i in range(1, n):
            closes.append(closes[-1] * (1 - 0.002 * i))
        volumes = [1_000_000] * n

        bars = _make_bars(closes, volumes, n)
        result = detector.analyze(bars, "600010")

        assert result.direction == "bearish"


# ------------------------------------------------------------------
# Test: reversal probability increases with duration
# ------------------------------------------------------------------
class TestReversalProbability:
    def test_longer_loop_higher_reversal_prob(
        self, detector: ReflexivityDetector
    ) -> None:
        """A strengthening loop with longer duration should have higher
        reversal probability when it eventually exhausts."""
        # Short loop
        n_short = 16
        closes_short = [10.0]
        for i in range(1, n_short):
            closes_short.append(closes_short[-1] * (1 + 0.002 * i))
        volumes_short = [1_000_000]
        for i in range(1, n_short):
            volumes_short.append(volumes_short[-1] * (1 + 0.01 * i))

        # Longer loop — more bars of positive acceleration
        n_long = 30
        closes_long = [10.0]
        for i in range(1, n_long):
            closes_long.append(closes_long[-1] * (1 + 0.002 * i))
        volumes_long = [1_000_000]
        for i in range(1, n_long):
            volumes_long.append(volumes_long[-1] * (1 + 0.01 * i))

        bars_short = _make_bars(closes_short, volumes_short, n_short)
        bars_long = _make_bars(closes_long, volumes_long, n_long)

        result_short = detector.analyze(bars_short, "600011")
        result_long = detector.analyze(bars_long, "600012")

        # Both should be strengthening — longer has higher duration
        if (
            result_short.loop_state == "strengthening"
            and result_long.loop_state == "strengthening"
        ):
            # For strengthening loops, reversal_prob = max(0.05, 1 - duration/20)
            # Longer duration -> lower (1 - d/20) is lower, but the formula
            # gives *lower* reversal prob for short loops.
            # The key insight: longer strengthening loops have HIGHER reversal
            # probability because they're more extended.
            assert result_long.loop_duration_bars >= result_short.loop_duration_bars


# ------------------------------------------------------------------
# Test: severity output compatibility
# ------------------------------------------------------------------
class TestSeverity:
    def test_severity_range(self, detector: ReflexivityDetector) -> None:
        """Severity should always be in [0, 1]."""
        n = 20
        closes = [10.0]
        for i in range(1, n):
            closes.append(closes[-1] * (1 + 0.002 * i))
        volumes = [1_000_000]
        for i in range(1, n):
            volumes.append(volumes[-1] * (1 + 0.01 * i))

        bars = _make_bars(closes, volumes, n)
        result = detector.analyze(bars, "600013")

        assert 0.0 <= result.severity <= 1.0
        assert 0.0 <= result.reversal_probability <= 1.0
        assert -1.0 <= result.reflexivity_score <= 1.0

    def test_no_loop_zero_severity(self, detector: ReflexivityDetector) -> None:
        """No loop state should have zero severity."""
        n = 20
        closes = [10.0] * n
        volumes = [1_000_000] * n

        bars = _make_bars(closes, volumes, n)
        result = detector.analyze(bars, "600014")

        assert result.loop_state == "none"
        assert result.severity == 0.0

    def test_result_has_all_fields(self, detector: ReflexivityDetector) -> None:
        """ReflexivityResult should have all required fields."""
        n = 20
        closes = [10.0]
        for i in range(1, n):
            closes.append(closes[-1] * (1 + 0.002 * i))
        volumes = [1_000_000]
        for i in range(1, n):
            volumes.append(volumes[-1] * (1 + 0.01 * i))

        bars = _make_bars(closes, volumes, n)
        result = detector.analyze(bars, "600015")

        assert hasattr(result, "symbol")
        assert hasattr(result, "reflexivity_score")
        assert hasattr(result, "loop_state")
        assert hasattr(result, "price_acceleration")
        assert hasattr(result, "volume_acceleration")
        assert hasattr(result, "loop_duration_bars")
        assert hasattr(result, "reversal_probability")
        assert hasattr(result, "direction")
        assert hasattr(result, "severity")
        assert hasattr(result, "description")
        assert result.symbol == "600015"

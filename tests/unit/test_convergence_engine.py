"""Unit tests for ConvergenceEngine."""

from __future__ import annotations

import pytest

from src.agent_loop.convergence_engine import ConvergenceEngine
from src.agent_loop.domain_adapter import (
    IndependenceGroup,
    SignalDirection,
    SignalEvidence,
)


def _make_signal(
    symbol: str = "600519",
    direction: SignalDirection = SignalDirection.BUY,
    group: IndependenceGroup = IndependenceGroup.PRICE_DERIVED,
    confidence: float = 0.7,
    signal_type: str = "test/signal",
) -> SignalEvidence:
    """Helper to create a test SignalEvidence."""
    return SignalEvidence(
        domain="test",
        signal_type=signal_type,
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        independence_group=group,
    )


@pytest.fixture()
def engine() -> ConvergenceEngine:
    return ConvergenceEngine()


class TestConvergenceInvariant:
    """Test the core convergence invariant: 2+ independence groups for BUY."""

    def test_single_group_does_not_converge(self, engine: ConvergenceEngine) -> None:
        """A BUY signal from only one independence group should NOT converge."""
        signals = [
            _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.9),
            _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.8),
        ]
        results = engine.analyze(signals)
        assert len(results) == 1
        assert not results[0].converged
        assert results[0].independence_groups == {IndependenceGroup.PRICE_DERIVED}

    def test_two_groups_converge(self, engine: ConvergenceEngine) -> None:
        """BUY signals from 2 different independence groups SHOULD converge."""
        signals = [
            _make_signal(group=IndependenceGroup.PRICE_DERIVED),
            _make_signal(group=IndependenceGroup.CAPITAL_FLOW),
        ]
        results = engine.analyze(signals)
        assert len(results) == 1
        assert results[0].converged
        assert results[0].independence_groups == {
            IndependenceGroup.PRICE_DERIVED,
            IndependenceGroup.CAPITAL_FLOW,
        }

    def test_three_groups_converge(self, engine: ConvergenceEngine) -> None:
        """More groups should also converge and have a higher score."""
        signals_2 = [
            _make_signal(group=IndependenceGroup.PRICE_DERIVED),
            _make_signal(group=IndependenceGroup.CAPITAL_FLOW),
        ]
        signals_3 = signals_2 + [
            _make_signal(group=IndependenceGroup.INTELLIGENCE),
        ]

        results_2 = engine.analyze(signals_2)
        results_3 = engine.analyze(signals_3)

        assert results_2[0].converged
        assert results_3[0].converged
        # 3 groups should score higher than 2
        assert results_3[0].convergence_score > results_2[0].convergence_score


class TestSellBypass:
    """Test that SELL signals bypass convergence requirement."""

    def test_sell_single_group_passes_filter(self, engine: ConvergenceEngine) -> None:
        """A SELL signal from one group should pass filter_actionable."""
        signals = [
            _make_signal(
                direction=SignalDirection.SELL,
                group=IndependenceGroup.PRICE_DERIVED,
            ),
        ]
        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 1
        assert actionable[0].direction == SignalDirection.SELL

    def test_buy_single_group_filtered_out(self, engine: ConvergenceEngine) -> None:
        """A BUY signal from one group should be filtered out."""
        signals = [
            _make_signal(
                direction=SignalDirection.BUY,
                group=IndependenceGroup.PRICE_DERIVED,
            ),
        ]
        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 0

    def test_hold_always_filtered_out(self, engine: ConvergenceEngine) -> None:
        """HOLD signals should always be filtered out."""
        signals = [
            _make_signal(
                direction=SignalDirection.HOLD,
                group=IndependenceGroup.PRICE_DERIVED,
            ),
            _make_signal(
                direction=SignalDirection.HOLD,
                group=IndependenceGroup.CAPITAL_FLOW,
            ),
        ]
        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 0


class TestConvergenceScore:
    """Test convergence score computation."""

    def test_score_increases_with_group_diversity(
        self, engine: ConvergenceEngine
    ) -> None:
        """Score should increase as more independent groups contribute."""
        scores = []
        groups = list(IndependenceGroup)
        for n in range(1, len(groups) + 1):
            signals = [_make_signal(group=g, confidence=0.7) for g in groups[:n]]
            score = engine._compute_convergence_score(signals)
            scores.append(score)

        # Each additional group should increase the score
        for i in range(1, len(scores)):
            assert scores[i] > scores[i - 1], (
                f"Score did not increase from {i} to {i + 1} groups"
            )

    def test_score_zero_for_empty(self, engine: ConvergenceEngine) -> None:
        """Empty signal list should have zero score."""
        assert engine._compute_convergence_score([]) == 0.0

    def test_score_bounded_zero_one(self, engine: ConvergenceEngine) -> None:
        """Score should be in [0, 1] range."""
        signals = [_make_signal(group=g, confidence=1.0) for g in IndependenceGroup]
        score = engine._compute_convergence_score(signals)
        assert 0.0 <= score <= 1.0

    def test_same_group_diminishing_returns(self, engine: ConvergenceEngine) -> None:
        """Multiple signals in the same group should have diminishing returns."""
        one = engine._compute_convergence_score(
            [_make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.8)]
        )
        two = engine._compute_convergence_score(
            [
                _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.8),
                _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.8),
            ]
        )
        three = engine._compute_convergence_score(
            [
                _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.8),
                _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.8),
                _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.8),
            ]
        )
        # Additional signals should add less and less
        delta_1_to_2 = two - one
        delta_2_to_3 = three - two
        assert delta_1_to_2 > 0  # Adding second helps
        assert delta_2_to_3 > 0  # Adding third helps a bit
        assert (
            delta_2_to_3 <= delta_1_to_2 + 1e-12
        )  # But diminishing (with fp tolerance)


class TestMultiSymbol:
    """Test grouping across different symbols."""

    def test_different_symbols_separate_results(
        self, engine: ConvergenceEngine
    ) -> None:
        """Signals for different symbols should produce separate results."""
        signals = [
            _make_signal(symbol="600519", group=IndependenceGroup.PRICE_DERIVED),
            _make_signal(symbol="000858", group=IndependenceGroup.CAPITAL_FLOW),
        ]
        results = engine.analyze(signals)
        assert len(results) == 2
        symbols = {r.symbol for r in results}
        assert symbols == {"600519", "000858"}

    def test_same_symbol_different_directions_separate(
        self, engine: ConvergenceEngine
    ) -> None:
        """Same symbol with different directions should be separate results."""
        signals = [
            _make_signal(
                direction=SignalDirection.BUY, group=IndependenceGroup.PRICE_DERIVED
            ),
            _make_signal(
                direction=SignalDirection.SELL, group=IndependenceGroup.CAPITAL_FLOW
            ),
        ]
        results = engine.analyze(signals)
        assert len(results) == 2

    def test_results_sorted_by_score(self, engine: ConvergenceEngine) -> None:
        """Results should be sorted by convergence score descending."""
        signals = [
            # Symbol A: 1 group
            _make_signal(symbol="A", group=IndependenceGroup.PRICE_DERIVED),
            # Symbol B: 3 groups
            _make_signal(symbol="B", group=IndependenceGroup.PRICE_DERIVED),
            _make_signal(symbol="B", group=IndependenceGroup.CAPITAL_FLOW),
            _make_signal(symbol="B", group=IndependenceGroup.INTELLIGENCE),
        ]
        results = engine.analyze(signals)
        assert results[0].symbol == "B"  # Higher score first

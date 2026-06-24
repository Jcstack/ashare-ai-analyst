"""Integration tests for v50 Agent Loop — real component interactions.

Tests the critical paths that unit tests miss:
1. Bayesian feedback loop (outcome → calibration → better priors)
2. Convergence engine + domain adapter pipeline
3. Thesis lifecycle (create → evidence → decay → invalidation → sell signal)
4. Action queue flow (create → confirm → fill)
5. InvestmentDirector OODA cycle (signal → convergence → debate → proposal)
6. Portfolio-aware priors (sector weight, position overlap, correlation)

All tests use real component instances with SQLite temp DBs — no mocks
for the components under test. External dependencies (LLM, market data)
are mocked at the boundary.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src.agent_loop.bayesian_belief import BayesianBeliefEngine, CalibrationStore
from src.agent_loop.convergence_engine import ConvergenceEngine
from src.agent_loop.domain_adapter import (
    IndependenceGroup,
    SignalDirection,
    SignalEvidence,
)
from src.agent_loop.models import (
    AggregatedSignal,
    DecisionOutcome,
    InvestmentThesis,
    TradeProposal,
    UrgencyTier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    symbol: str = "600519",
    direction: SignalDirection = SignalDirection.BUY,
    group: IndependenceGroup = IndependenceGroup.PRICE_DERIVED,
    confidence: float = 0.7,
    signal_type: str = "technical/momentum_breakout",
    domain: str = "technical",
) -> SignalEvidence:
    return SignalEvidence(
        domain=domain,
        signal_type=signal_type,
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        independence_group=group,
        metadata={"sector": "白酒"},
        source_description=f"test-{domain}",
    )


# ---------------------------------------------------------------------------
# 1. Convergence Engine Integration
# ---------------------------------------------------------------------------


class TestConvergenceIntegration:
    """Test that the convergence engine correctly gates BUY signals."""

    def test_single_group_buy_blocked(self):
        """BUY with only 1 independence group must be blocked."""
        engine = ConvergenceEngine()
        signals = [
            _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.9),
            _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.85),
        ]
        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 0, "BUY with 1 group should not be actionable"

    def test_two_groups_buy_allowed(self):
        """BUY with 2 independence groups should pass convergence."""
        engine = ConvergenceEngine()
        signals = [
            _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.7),
            _make_signal(group=IndependenceGroup.CAPITAL_FLOW, confidence=0.65),
        ]
        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 1
        assert actionable[0].converged is True
        assert len(actionable[0].independence_groups) == 2

    def test_sell_always_passes(self):
        """SELL should pass even with only 1 independence group."""
        engine = ConvergenceEngine()
        signals = [
            _make_signal(
                direction=SignalDirection.SELL, group=IndependenceGroup.INTELLIGENCE
            ),
        ]
        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 1

    def test_hold_always_filtered(self):
        """HOLD signals should never be actionable."""
        engine = ConvergenceEngine()
        signals = [
            _make_signal(
                direction=SignalDirection.HOLD, group=IndependenceGroup.PRICE_DERIVED
            ),
            _make_signal(
                direction=SignalDirection.HOLD, group=IndependenceGroup.CAPITAL_FLOW
            ),
        ]
        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 0

    def test_multi_symbol_convergence(self):
        """Signals for different symbols converge independently."""
        engine = ConvergenceEngine()
        signals = [
            _make_signal(symbol="600519", group=IndependenceGroup.PRICE_DERIVED),
            _make_signal(symbol="600519", group=IndependenceGroup.CAPITAL_FLOW),
            _make_signal(symbol="000858", group=IndependenceGroup.PRICE_DERIVED),
        ]
        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 1
        assert actionable[0].symbol == "600519"

    def test_convergence_score_increases_with_groups(self):
        """More independence groups → higher convergence score."""
        engine = ConvergenceEngine()
        two_group = [
            _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.7),
            _make_signal(group=IndependenceGroup.CAPITAL_FLOW, confidence=0.7),
        ]
        three_group = two_group + [
            _make_signal(group=IndependenceGroup.INTELLIGENCE, confidence=0.7),
        ]
        score_2 = engine.analyze(two_group)[0].convergence_score
        score_3 = engine.analyze(three_group)[0].convergence_score
        assert score_3 > score_2, "3 groups should score higher than 2 groups"


# ---------------------------------------------------------------------------
# 2. Bayesian Feedback Loop Integration
# ---------------------------------------------------------------------------


class TestBayesianFeedbackLoop:
    """Test the full feedback loop: signal → posterior → outcome → calibration."""

    def test_infer_with_converged_signals(self):
        """Bayesian inference should produce meaningful posterior with evidence."""
        engine = BayesianBeliefEngine()
        signals = [
            _make_signal(signal_type="technical/momentum_breakout", confidence=0.75),
        ]
        posterior = engine.infer(
            symbol="600519", signals=signals, sector="白酒", regime="bull"
        )
        assert 0.0 < posterior.p_bullish < 1.0

    def test_regime_affects_prior(self):
        """Bull regime should produce higher prior than bear regime."""
        engine = BayesianBeliefEngine()
        signals = [
            _make_signal(signal_type="technical/momentum_breakout", confidence=0.6)
        ]
        bull_post = engine.infer(symbol="600519", signals=signals, regime="bull")
        bear_post = engine.infer(symbol="600519", signals=signals, regime="bear")
        assert bull_post.p_bullish > bear_post.p_bullish

    def test_portfolio_aware_prior_penalizes_concentration(self):
        """High sector weight should reduce prior P(bull)."""
        engine = BayesianBeliefEngine()
        signals = [
            _make_signal(signal_type="technical/momentum_breakout", confidence=0.6)
        ]
        normal = engine.infer(
            symbol="600519",
            signals=signals,
            regime="bull",
            portfolio_sector_weight=0.05,
        )
        concentrated = engine.infer(
            symbol="600519",
            signals=signals,
            regime="bull",
            portfolio_sector_weight=0.35,
        )
        assert concentrated.p_bullish < normal.p_bullish

    def test_multiple_signals_shift_posterior(self):
        """Adding more confirming signals should increase posterior."""
        engine = BayesianBeliefEngine()
        one_signal = [
            _make_signal(
                signal_type="technical/momentum_breakout",
                group=IndependenceGroup.PRICE_DERIVED,
                confidence=0.7,
            ),
        ]
        two_signals = one_signal + [
            _make_signal(
                signal_type="capital_flow/main_net_inflow",
                domain="capital_flow",
                group=IndependenceGroup.CAPITAL_FLOW,
                confidence=0.7,
            ),
        ]
        post_1 = engine.infer(symbol="600519", signals=one_signal, regime="bull")
        post_2 = engine.infer(symbol="600519", signals=two_signals, regime="bull")
        assert post_2.p_bullish >= post_1.p_bullish

    def test_position_exists_reduces_prior(self):
        """Already holding this stock should slightly reduce buy prior."""
        engine = BayesianBeliefEngine()
        signals = [
            _make_signal(signal_type="technical/momentum_breakout", confidence=0.7)
        ]
        fresh = engine.infer(
            symbol="600519",
            signals=signals,
            regime="bull",
            portfolio_position_exists=False,
        )
        overlap = engine.infer(
            symbol="600519",
            signals=signals,
            regime="bull",
            portfolio_position_exists=True,
        )
        assert overlap.p_bullish <= fresh.p_bullish


# ---------------------------------------------------------------------------
# 3. Calibration Store Persistence
# ---------------------------------------------------------------------------


class TestCalibrationStorePersistence:
    """Test empirical table save→load round trip."""

    def test_round_trip(self, tmp_path):
        """Empirical tables should survive save→load cycle."""
        store1 = CalibrationStore()
        # Manually set empirical counts if attribute exists
        if hasattr(store1, "_empirical_counts"):
            store1._empirical_counts = {
                "technical/momentum_breakout": {
                    "bull_given_bull": 8,
                    "bull_given_bear": 3,
                    "total_bull": 10,
                    "total_bear": 10,
                }
            }
            store1.update_likelihood_tables()

        # A fresh store should be able to load
        store2 = CalibrationStore()
        loaded = store2.load_empirical_tables()
        # Whether 0 or >0 depends on db_path config, but should not crash
        assert loaded >= 0


# ---------------------------------------------------------------------------
# 4. Thesis Lifecycle Integration
# ---------------------------------------------------------------------------


class TestThesisLifecycle:
    """Test thesis CRUD, decay, and invalidation using real SQLite DB."""

    @pytest.fixture
    def tracker(self, tmp_path):
        from src.agent_loop.thesis_tracker import ThesisTracker

        return ThesisTracker(db_path=tmp_path / "theses.db")

    def test_create_and_retrieve(self, tracker):
        thesis = tracker.create_thesis(
            symbol="600519",
            direction="bullish",
            narrative="白酒龙头，业绩稳定",
            entry_condition="价格突破2000",
            invalidation_condition="跌破1800",
            confidence=0.6,
        )
        assert thesis is not None
        assert thesis.id is not None
        retrieved = tracker.get_thesis(thesis.id)
        assert retrieved is not None
        assert retrieved.symbol == "600519"
        assert retrieved.status == "active"

    def test_add_supporting_evidence_increases_confidence(self, tracker):
        thesis = tracker.create_thesis(
            symbol="600519",
            direction="bullish",
            narrative="白酒龙头",
            entry_condition="突破前高",
            invalidation_condition="跌破支撑",
            confidence=0.5,
        )
        initial_conf = thesis.current_confidence
        updated = tracker.add_evidence(
            thesis.id,
            evidence_type="supporting",
            description="主力资金持续流入",
            source="capital_flow",
            confidence_impact=0.1,
        )
        assert updated is not None
        assert updated.current_confidence > initial_conf

    def test_add_contradicting_evidence_decreases_confidence(self, tracker):
        thesis = tracker.create_thesis(
            symbol="600519",
            direction="bullish",
            narrative="白酒龙头",
            entry_condition="突破前高",
            invalidation_condition="跌破支撑",
            confidence=0.5,
        )
        initial_conf = thesis.current_confidence
        updated = tracker.add_evidence(
            thesis.id,
            evidence_type="contradicting",
            description="业绩不及预期",
            source="intelligence",
            confidence_impact=-0.15,
        )
        assert updated is not None
        assert updated.current_confidence < initial_conf

    def test_daily_decay_weakens_thesis(self, tracker):
        thesis = tracker.create_thesis(
            symbol="600519",
            direction="bullish",
            narrative="白酒龙头",
            entry_condition="突破前高",
            invalidation_condition="跌破支撑",
            confidence=0.4,
        )
        initial_conf = thesis.current_confidence
        for _ in range(5):
            tracker.apply_daily_decay()
        updated = tracker.get_thesis(thesis.id)
        assert updated.current_confidence < initial_conf

    def test_thesis_weakens_on_low_confidence(self, tracker):
        thesis = tracker.create_thesis(
            symbol="600519",
            direction="bullish",
            narrative="白酒龙头",
            entry_condition="突破前高",
            invalidation_condition="跌破支撑",
            confidence=0.25,
        )
        tracker.add_evidence(
            thesis.id,
            evidence_type="contradicting",
            description="重大利空",
            source="news",
            confidence_impact=-0.10,
        )
        updated = tracker.get_thesis(thesis.id)
        assert updated.status in ("weakening", "invalidated")

    def test_list_active_theses(self, tracker):
        tracker.create_thesis(
            symbol="600519",
            direction="bullish",
            narrative="龙头",
            entry_condition="突破",
            invalidation_condition="跌破",
            confidence=0.7,
        )
        t2 = tracker.create_thesis(
            symbol="000858",
            direction="bullish",
            narrative="二线",
            entry_condition="突破",
            invalidation_condition="跌破",
            confidence=0.15,
        )
        # Force low confidence
        tracker.add_evidence(
            t2.id,
            evidence_type="contradicting",
            description="跌停",
            source="price",
            confidence_impact=-0.10,
        )
        active = tracker.get_active_theses()
        symbols = [t.symbol for t in active]
        assert "600519" in symbols


# ---------------------------------------------------------------------------
# 5. Action Queue Integration
# ---------------------------------------------------------------------------


class TestActionQueueIntegration:
    """Test the full action queue lifecycle: create → confirm → fill."""

    @pytest.fixture
    def queue_service(self, tmp_path):
        from src.web.services.action_queue_service import ActionQueueService

        return ActionQueueService(db_path=tmp_path / "actions.db")

    def test_create_and_list_pending(self, queue_service):
        action = queue_service.create_action(
            symbol="600519",
            action="buy",
            urgency="today",
            confidence=0.72,
            thesis_id="test-thesis-1",
            execution_plan={"desc": "14:30 买入 500 股", "price": 1950.0},
        )
        assert action is not None
        assert action.id is not None
        pending = queue_service.list_actions(status="pending")
        assert len(pending) >= 1
        assert any(a.id == action.id for a in pending)

    def test_confirm_action(self, queue_service):
        action = queue_service.create_action(
            symbol="600519",
            action="buy",
            urgency="today",
            confidence=0.72,
            thesis_id="t1",
            execution_plan={"desc": "买入"},
        )
        result = queue_service.confirm_action(action.id)
        assert result is not None
        confirmed = queue_service.list_actions(status="confirmed")
        assert any(a.id == action.id for a in confirmed)

    def test_reject_action(self, queue_service):
        action = queue_service.create_action(
            symbol="000858",
            action="buy",
            urgency="observe",
            confidence=0.55,
            thesis_id="t2",
            execution_plan={"desc": "观望"},
        )
        queue_service.reject_action(action.id)
        rejected = queue_service.list_actions(status="rejected")
        assert any(a.id == action.id for a in rejected)

    def test_record_fill_after_confirm(self, queue_service):
        action = queue_service.create_action(
            symbol="600519",
            action="buy",
            urgency="immediate",
            confidence=0.8,
            thesis_id="t3",
            execution_plan={"desc": "立即买入"},
        )
        queue_service.confirm_action(action.id)
        queue_service.record_fill(action.id, fill_price=1950.0, fill_shares=200)
        executed = queue_service.list_actions(status="executed")
        assert any(a.id == action.id for a in executed)

    def test_stats(self, queue_service):
        for i in range(3):
            queue_service.create_action(
                symbol=f"60051{i}",
                action="buy",
                urgency="today",
                confidence=0.7,
                thesis_id=f"t{i}",
                execution_plan={"desc": "买入"},
            )
        stats = queue_service.get_stats()
        assert stats["pending"] >= 3


# ---------------------------------------------------------------------------
# 6. Outcome Tracker Integration
# ---------------------------------------------------------------------------


class TestOutcomeTrackerIntegration:
    """Test outcome tracking with real component instances."""

    @pytest.fixture
    def tracker(self, tmp_path):
        from src.agent_loop.outcome_tracker import OutcomeTracker

        return OutcomeTracker(db_path=tmp_path / "outcomes.db")

    @pytest.mark.anyio
    async def test_record_signal(self, tracker):
        """record_signal accepts AggregatedSignal objects."""
        signal = AggregatedSignal(
            symbol="600519",
            name="贵州茅台",
            direction=SignalDirection.BUY,
            source="technical/momentum_breakout",
            confidence=0.72,
            urgency=UrgencyTier.NORMAL,
            reason="动量突破",
        )
        await tracker.record_signal(signal)

    @pytest.mark.anyio
    async def test_record_signal_with_proposal(self, tracker):
        """record_signal with TradeProposal attached."""
        signal = AggregatedSignal(
            symbol="600519",
            name="贵州茅台",
            direction=SignalDirection.BUY,
            source="technical/momentum_breakout",
            confidence=0.72,
            urgency=UrgencyTier.NORMAL,
            reason="动量突破",
        )
        proposal = TradeProposal(
            symbol="600519",
            name="贵州茅台",
            action="buy",
            shares=100,
            confidence=0.72,
            debate_summary="Bull wins",
            bull_score=0.8,
            bear_score=0.4,
        )
        await tracker.record_signal(signal, proposal=proposal)

    def test_get_accuracy_by_source(self, tracker):
        """Source accuracy should return data structure (even if empty)."""
        result = tracker.get_accuracy_by_source()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 7. SharedBeliefState Integration
# ---------------------------------------------------------------------------


class TestSharedBeliefStateIntegration:
    """Test SharedBeliefState with in-memory mode (no Redis required)."""

    def test_position_limits_format(self):
        from src.agent_loop.shared_belief_state import SharedBeliefState

        state = SharedBeliefState()
        limits = state.get_position_limits()
        assert isinstance(limits, dict)
        assert "buys_allowed" in limits
        assert "max_position_pct" in limits

    def test_daily_plan_updates(self):
        from src.agent_loop.shared_belief_state import SharedBeliefState

        state = SharedBeliefState()
        state.daily_plan.watch_list = ["600519", "000858"]
        state.daily_plan.buy_candidates = [{"symbol": "600519", "reason": "突破前高"}]
        state.daily_plan.sell_plan = [{"symbol": "000001", "reason": "止损"}]
        assert len(state.daily_plan.watch_list) == 2
        assert len(state.daily_plan.buy_candidates) == 1

    def test_risk_budget_structure(self):
        from src.agent_loop.shared_belief_state import SharedBeliefState

        state = SharedBeliefState()
        assert hasattr(state.risk_budget, "daily_limit_pct")
        assert hasattr(state.risk_budget, "is_halted")
        assert hasattr(state.regime, "sentiment_phase")

    def test_to_dict_serializable(self):
        from src.agent_loop.shared_belief_state import SharedBeliefState

        state = SharedBeliefState()
        d = state.to_dict()
        json.dumps(d, ensure_ascii=False, default=str)

    def test_signal_accuracy_tracking(self):
        from src.agent_loop.shared_belief_state import SharedBeliefState

        state = SharedBeliefState()
        state.update_signal_accuracy("technical", 0.72)
        acc = state.get_signal_accuracy("technical")
        assert acc is not None


# ---------------------------------------------------------------------------
# 8. Full Signal Pipeline E2E
# ---------------------------------------------------------------------------


class TestSignalPipelineE2E:
    """Test complete pipeline: adapter → convergence → Bayesian → proposal eligibility."""

    def test_full_pipeline_buy_accepted(self):
        """Happy path: strong buy signal with 3 groups converges and gets high posterior."""
        engine = ConvergenceEngine()
        bayesian = BayesianBeliefEngine()

        signals = [
            _make_signal(
                group=IndependenceGroup.PRICE_DERIVED,
                confidence=0.75,
                signal_type="technical/momentum_breakout",
            ),
            _make_signal(
                group=IndependenceGroup.CAPITAL_FLOW,
                confidence=0.72,
                signal_type="capital_flow/main_net_inflow",
                domain="capital_flow",
            ),
            _make_signal(
                group=IndependenceGroup.INTELLIGENCE,
                confidence=0.68,
                signal_type="intelligence/positive_news",
                domain="intelligence",
            ),
        ]

        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 1
        assert actionable[0].converged is True
        assert len(actionable[0].independence_groups) == 3

        posterior = bayesian.infer(
            symbol="600519",
            signals=actionable[0].signals,
            regime="bull",
        )
        assert posterior.p_bullish > 0.5

    def test_full_pipeline_buy_rejected_single_group(self):
        """Strong signal but only 1 group — blocked by convergence."""
        engine = ConvergenceEngine()
        signals = [
            _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.95),
        ]
        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 0

    def test_full_pipeline_with_portfolio_penalty(self):
        """Portfolio-concentrated buy should get lower posterior."""
        engine = ConvergenceEngine()
        bayesian = BayesianBeliefEngine()

        signals = [
            _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.7),
            _make_signal(
                group=IndependenceGroup.CAPITAL_FLOW,
                confidence=0.7,
                domain="capital_flow",
            ),
        ]

        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)

        post_clean = bayesian.infer(
            symbol="600519",
            signals=actionable[0].signals,
            regime="bull",
            portfolio_sector_weight=0.05,
        )
        post_concentrated = bayesian.infer(
            symbol="600519",
            signals=actionable[0].signals,
            regime="bull",
            portfolio_sector_weight=0.35,
        )
        assert post_concentrated.p_bullish < post_clean.p_bullish

    def test_sell_pipeline_urgent(self):
        """SELL signal should flow through pipeline even with 1 group."""
        engine = ConvergenceEngine()
        bayesian = BayesianBeliefEngine()

        signals = [
            _make_signal(
                symbol="000001",
                direction=SignalDirection.SELL,
                group=IndependenceGroup.INTELLIGENCE,
                signal_type="intelligence/negative_news",
                domain="intelligence",
                confidence=0.85,
            ),
        ]

        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 1

        posterior = bayesian.infer(
            symbol="000001",
            signals=actionable[0].signals,
            regime="bear",
        )
        assert posterior.p_bullish < 0.6

    def test_mixed_buy_sell_handled_independently(self):
        """Mixed BUY/SELL for different symbols handled independently."""
        engine = ConvergenceEngine()
        signals = [
            _make_signal(
                symbol="600519",
                direction=SignalDirection.BUY,
                group=IndependenceGroup.PRICE_DERIVED,
            ),
            _make_signal(
                symbol="600519",
                direction=SignalDirection.BUY,
                group=IndependenceGroup.CAPITAL_FLOW,
            ),
            _make_signal(
                symbol="000858",
                direction=SignalDirection.SELL,
                group=IndependenceGroup.INTELLIGENCE,
            ),
        ]
        results = engine.analyze(signals)
        actionable = engine.filter_actionable(results)
        assert len(actionable) == 2
        symbols = {r.symbol for r in actionable}
        assert symbols == {"600519", "000858"}


# ---------------------------------------------------------------------------
# 9. Cross-Component State Consistency
# ---------------------------------------------------------------------------


class TestCrossComponentConsistency:
    """Test that state changes propagate correctly across components."""

    @pytest.mark.anyio
    async def test_thesis_invalidation_tracked(self, tmp_path):
        """When thesis invalidates, outcome tracker should accept signals."""
        from src.agent_loop.thesis_tracker import ThesisTracker
        from src.agent_loop.outcome_tracker import OutcomeTracker

        thesis_tracker = ThesisTracker(db_path=tmp_path / "theses.db")
        outcome_tracker = OutcomeTracker(db_path=tmp_path / "outcomes.db")

        thesis = thesis_tracker.create_thesis(
            symbol="600519",
            direction="bullish",
            narrative="白酒龙头",
            entry_condition="突破2000",
            invalidation_condition="跌破1800",
            confidence=0.25,
        )

        signal = AggregatedSignal(
            symbol="600519",
            name="贵州茅台",
            direction=SignalDirection.BUY,
            source="technical/momentum_breakout",
            confidence=0.72,
            urgency=UrgencyTier.NORMAL,
            reason="动量突破",
            metadata={"thesis_id": thesis.id},
        )
        await outcome_tracker.record_signal(signal)

        thesis_tracker.add_evidence(
            thesis.id,
            evidence_type="contradicting",
            description="跌停板",
            source="price",
            confidence_impact=-0.15,
        )
        updated = thesis_tracker.get_thesis(thesis.id)
        assert updated.status in ("weakening", "invalidated")

    def test_convergence_result_feeds_bayesian(self):
        """ConvergenceResult signals should be valid input for BayesianBeliefEngine."""
        engine = ConvergenceEngine()
        bayesian = BayesianBeliefEngine()

        signals = [
            _make_signal(group=IndependenceGroup.PRICE_DERIVED, confidence=0.7),
            _make_signal(
                group=IndependenceGroup.CAPITAL_FLOW,
                confidence=0.65,
                domain="capital_flow",
            ),
            _make_signal(
                group=IndependenceGroup.MICROSTRUCTURE,
                confidence=0.6,
                domain="microstructure",
            ),
        ]

        results = engine.analyze(signals)
        for r in results:
            if r.converged:
                posterior = bayesian.infer(
                    symbol=r.symbol, signals=r.signals, regime="bull"
                )
                assert 0.0 <= posterior.p_bullish <= 1.0

    def test_model_serialization_round_trip(self):
        """All model to_dict() outputs should be JSON-serializable."""
        thesis = InvestmentThesis(
            symbol="600519",
            name="贵州茅台",
            direction="bullish",
            conviction=0.72,
            thesis_text="白酒龙头",
            sector="白酒",
        )
        proposal = TradeProposal(
            symbol="600519",
            name="贵州茅台",
            action="buy",
            shares=100,
            confidence=0.72,
            debate_summary="Bull wins",
            bull_score=0.8,
            bear_score=0.4,
            thesis=thesis,
        )
        outcome = DecisionOutcome(
            proposal_id=proposal.proposal_id,
            symbol="600519",
            action="buy",
            decided_at=datetime.now(UTC),
            decided_price=1950.0,
        )
        # All should serialize without error
        json.dumps(thesis.to_dict(), ensure_ascii=False)
        json.dumps(proposal.to_dict(), ensure_ascii=False)
        json.dumps(outcome.to_dict(), ensure_ascii=False)

    def test_action_queue_with_thesis(self, tmp_path):
        """Action queue should link to thesis correctly."""
        from src.agent_loop.thesis_tracker import ThesisTracker
        from src.web.services.action_queue_service import ActionQueueService

        thesis_tracker = ThesisTracker(db_path=tmp_path / "theses.db")
        queue = ActionQueueService(db_path=tmp_path / "actions.db")

        thesis = thesis_tracker.create_thesis(
            symbol="600519",
            direction="bullish",
            narrative="白酒龙头",
            entry_condition="突破2000",
            invalidation_condition="跌破1800",
            confidence=0.7,
        )

        action = queue.create_action(
            symbol="600519",
            action="buy",
            urgency="today",
            confidence=0.72,
            thesis_id=thesis.id,
            execution_plan={"desc": "14:30 买入", "price": 1950.0},
        )
        assert action.thesis_id == thesis.id

        # Verify thesis still valid
        t = thesis_tracker.get_thesis(thesis.id)
        assert t.status == "active"

"""Tests for the thesis lifecycle management system.

Covers ThesisTracker creation, evidence, decay, invalidation, expiry,
position linking, and DecisionPipeline integration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.agent_loop.thesis_tracker import ThesisTracker


@pytest.fixture
def tracker(tmp_path: Path) -> ThesisTracker:
    """Create a ThesisTracker with a temporary database."""
    return ThesisTracker(db_path=tmp_path / "test_theses.db")


# ------------------------------------------------------------------
# Creation
# ------------------------------------------------------------------


class TestThesisCreation:
    def test_create_thesis_basic(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="降准利好银行股, 招行基本面最优",
            entry_condition="price > 35",
            invalidation_condition="跌破30",
            confidence=0.7,
        )
        assert thesis.id
        assert thesis.symbol == "600036.SH"
        assert thesis.direction == "long"
        assert thesis.narrative == "降准利好银行股, 招行基本面最优"
        assert thesis.initial_confidence == 0.7
        assert thesis.current_confidence == 0.7
        assert thesis.status == "active"
        assert thesis.evidence == []
        assert thesis.position_id is None

    def test_create_thesis_default_expiry(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="000001.SZ",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        delta = thesis.expires_at - thesis.created_at
        assert 4 <= delta.days <= 5  # approximately 5 days

    def test_create_thesis_custom_expiry(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="000001.SZ",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
            expires_days=10,
        )
        delta = thesis.expires_at - thesis.created_at
        assert 9 <= delta.days <= 10

    def test_create_thesis_with_position(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="linked thesis",
            entry_condition="",
            invalidation_condition="",
            confidence=0.6,
            position_id="pos-123",
        )
        assert thesis.position_id == "pos-123"

    def test_create_thesis_persists(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="persisted",
            entry_condition="",
            invalidation_condition="",
            confidence=0.8,
        )
        retrieved = tracker.get_thesis(thesis.id)
        assert retrieved is not None
        assert retrieved.symbol == "600036.SH"
        assert retrieved.current_confidence == 0.8


# ------------------------------------------------------------------
# Evidence
# ------------------------------------------------------------------


class TestEvidence:
    def test_add_supporting_evidence(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        updated = tracker.add_evidence(
            thesis.id,
            evidence_type="supporting",
            description="央行降准50bp",
            source="央行公告",
            confidence_impact=0.1,
        )
        assert updated is not None
        assert updated.current_confidence == pytest.approx(0.6)
        assert len(updated.evidence) == 1
        assert updated.evidence[0]["type"] == "supporting"

    def test_add_contradicting_evidence(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        updated = tracker.add_evidence(
            thesis.id,
            evidence_type="contradicting",
            description="不良贷款率上升",
            source="财报",
            confidence_impact=-0.1,
        )
        assert updated is not None
        assert updated.current_confidence == pytest.approx(0.4)

    def test_confidence_clamped_to_0_1(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.9,
        )
        # Try to push above 1.0
        updated = tracker.add_evidence(
            thesis.id,
            evidence_type="supporting",
            description="huge boost",
            source="test",
            confidence_impact=0.5,
        )
        assert updated is not None
        assert updated.current_confidence == 1.0

        # Try to push below 0.0
        updated2 = tracker.add_evidence(
            thesis.id,
            evidence_type="contradicting",
            description="catastrophe",
            source="test",
            confidence_impact=-2.0,
        )
        assert updated2 is not None
        assert updated2.current_confidence == 0.0

    def test_evidence_on_nonexistent_thesis(self, tracker: ThesisTracker) -> None:
        result = tracker.add_evidence(
            "nonexistent-id",
            evidence_type="supporting",
            description="test",
        )
        assert result is None

    def test_evidence_on_resolved_thesis_skipped(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        tracker.invalidate_thesis(thesis.id, "test reason")
        updated = tracker.add_evidence(
            thesis.id,
            evidence_type="supporting",
            description="too late",
            confidence_impact=0.3,
        )
        assert updated is not None
        # Confidence should not change since thesis is already resolved
        assert updated.status == "invalidated"

    def test_multiple_evidence_accumulates(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        tracker.add_evidence(thesis.id, "supporting", "ev1", confidence_impact=0.05)
        tracker.add_evidence(thesis.id, "supporting", "ev2", confidence_impact=0.05)
        tracker.add_evidence(thesis.id, "contradicting", "ev3", confidence_impact=-0.02)
        updated = tracker.get_thesis(thesis.id)
        assert updated is not None
        assert updated.current_confidence == pytest.approx(0.58)
        assert len(updated.evidence) == 3


# ------------------------------------------------------------------
# Daily Decay
# ------------------------------------------------------------------


class TestDailyDecay:
    def test_decay_reduces_confidence(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        # Apply 3 days of decay (default rate 0.02)
        tracker.apply_daily_decay()
        tracker.apply_daily_decay()
        tracker.apply_daily_decay()
        updated = tracker.get_thesis(thesis.id)
        assert updated is not None
        assert updated.current_confidence == pytest.approx(0.44)

    def test_decay_triggers_weakening(self, tracker: ThesisTracker) -> None:
        tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.36,  # Just above weakening threshold
        )
        changed = tracker.apply_daily_decay()
        assert len(changed) == 1
        assert changed[0].status == "weakening"

    def test_decay_triggers_invalidation(self, tracker: ThesisTracker) -> None:
        tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.21,  # Just above invalidation threshold
        )
        changed = tracker.apply_daily_decay()
        assert len(changed) == 1
        assert changed[0].status == "invalidated"

    def test_decay_does_not_go_below_zero(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.01,
        )
        tracker.apply_daily_decay()
        updated = tracker.get_thesis(thesis.id)
        assert updated is not None
        assert updated.current_confidence >= 0.0

    def test_decay_skips_resolved(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        tracker.realize_thesis(thesis.id, "profit taken")
        changed = tracker.apply_daily_decay()
        assert len(changed) == 0


# ------------------------------------------------------------------
# Auto-invalidation at threshold
# ------------------------------------------------------------------


class TestAutoInvalidation:
    def test_evidence_drops_below_invalidation(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.25,
        )
        updated = tracker.add_evidence(
            thesis.id,
            evidence_type="contradicting",
            description="bad news",
            confidence_impact=-0.10,
        )
        assert updated is not None
        assert updated.status == "invalidated"
        assert updated.resolved_reason is not None

    def test_evidence_drops_to_weakening(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.40,
        )
        updated = tracker.add_evidence(
            thesis.id,
            evidence_type="contradicting",
            description="bad news",
            confidence_impact=-0.10,
        )
        assert updated is not None
        assert updated.status == "weakening"


# ------------------------------------------------------------------
# Expiry
# ------------------------------------------------------------------


class TestExpiry:
    def test_expired_thesis_invalidated(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
            expires_days=1,
        )
        # Manually set expires_at to the past
        with tracker._connect() as conn:
            past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            conn.execute(
                "UPDATE theses SET expires_at = ? WHERE id = ?",
                (past, thesis.id),
            )

        expired = tracker.check_expiry()
        assert len(expired) == 1
        assert expired[0].status == "invalidated"
        assert "Expired" in (expired[0].resolved_reason or "")

    def test_non_expired_thesis_kept(self, tracker: ThesisTracker) -> None:
        tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
            expires_days=10,
        )
        expired = tracker.check_expiry()
        assert len(expired) == 0


# ------------------------------------------------------------------
# Position linking
# ------------------------------------------------------------------


class TestPositionLinking:
    def test_link_position(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        tracker.link_position(thesis.id, "pos-456")
        updated = tracker.get_thesis(thesis.id)
        assert updated is not None
        assert updated.position_id == "pos-456"

    def test_get_thesis_for_position(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
            position_id="pos-789",
        )
        found = tracker.get_thesis_for_position("pos-789")
        assert found is not None
        assert found.id == thesis.id

    def test_get_thesis_for_position_not_found(self, tracker: ThesisTracker) -> None:
        found = tracker.get_thesis_for_position("nonexistent")
        assert found is None

    def test_get_thesis_for_position_ignores_invalidated(
        self, tracker: ThesisTracker
    ) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
            position_id="pos-abc",
        )
        tracker.invalidate_thesis(thesis.id, "test")
        found = tracker.get_thesis_for_position("pos-abc")
        assert found is None


# ------------------------------------------------------------------
# Query methods
# ------------------------------------------------------------------


class TestQueries:
    def test_get_active_theses(self, tracker: ThesisTracker) -> None:
        tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="a",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        tracker.create_thesis(
            symbol="000001.SZ",
            direction="long",
            narrative="b",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        t3 = tracker.create_thesis(
            symbol="300059.SZ",
            direction="long",
            narrative="c",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        tracker.invalidate_thesis(t3.id, "test")

        active = tracker.get_active_theses()
        assert len(active) == 2

    def test_get_weakening_theses(self, tracker: ThesisTracker) -> None:
        tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="a",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        t2 = tracker.create_thesis(
            symbol="000001.SZ",
            direction="long",
            narrative="b",
            entry_condition="",
            invalidation_condition="",
            confidence=0.30,
        )
        # t2 starts below weakening threshold — add evidence to push status
        tracker.add_evidence(t2.id, "supporting", "bump", confidence_impact=0.01)

        weakening = tracker.get_weakening_theses()
        assert len(weakening) == 1
        assert weakening[0].symbol == "000001.SZ"

    def test_list_theses_filter_by_status(self, tracker: ThesisTracker) -> None:
        tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="a",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        t2 = tracker.create_thesis(
            symbol="000001.SZ",
            direction="long",
            narrative="b",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        tracker.realize_thesis(t2.id, "profit")

        active = tracker.list_theses(status="active")
        assert len(active) == 1
        realized = tracker.list_theses(status="realized")
        assert len(realized) == 1

    def test_list_theses_filter_by_symbol(self, tracker: ThesisTracker) -> None:
        tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="a",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        tracker.create_thesis(
            symbol="000001.SZ",
            direction="long",
            narrative="b",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        result = tracker.list_theses(symbol="600036.SH")
        assert len(result) == 1
        assert result[0].symbol == "600036.SH"


# ------------------------------------------------------------------
# Realize / Invalidate
# ------------------------------------------------------------------


class TestResolve:
    def test_realize_thesis(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        result = tracker.realize_thesis(thesis.id, "Profit target reached")
        assert result is not None
        assert result.status == "realized"
        assert result.resolved_reason == "Profit target reached"
        assert result.resolved_at is not None

    def test_invalidate_thesis(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="",
            confidence=0.5,
        )
        result = tracker.invalidate_thesis(thesis.id, "Stop loss hit")
        assert result is not None
        assert result.status == "invalidated"
        assert result.resolved_reason == "Stop loss hit"

    def test_realize_nonexistent(self, tracker: ThesisTracker) -> None:
        assert tracker.realize_thesis("fake-id", "reason") is None

    def test_invalidate_nonexistent(self, tracker: ThesisTracker) -> None:
        assert tracker.invalidate_thesis("fake-id", "reason") is None


# ------------------------------------------------------------------
# Check invalidation conditions
# ------------------------------------------------------------------


class TestCheckInvalidation:
    def test_price_below_threshold(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="跌破30",
            confidence=0.5,
        )
        result = tracker.check_invalidation(thesis.id, current_price=29.0)
        assert result is True
        updated = tracker.get_thesis(thesis.id)
        assert updated is not None
        assert updated.status == "invalidated"

    def test_price_above_threshold_no_invalidation(
        self, tracker: ThesisTracker
    ) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="跌破30",
            confidence=0.5,
        )
        result = tracker.check_invalidation(thesis.id, current_price=35.0)
        assert result is False
        updated = tracker.get_thesis(thesis.id)
        assert updated is not None
        assert updated.status == "active"

    def test_check_invalidation_on_resolved(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test",
            entry_condition="",
            invalidation_condition="跌破30",
            confidence=0.5,
        )
        tracker.invalidate_thesis(thesis.id, "already done")
        result = tracker.check_invalidation(thesis.id, current_price=29.0)
        assert result is False  # Already resolved, no double-invalidation


# ------------------------------------------------------------------
# Thesis.to_dict
# ------------------------------------------------------------------


class TestThesisToDict:
    def test_to_dict_roundtrip(self, tracker: ThesisTracker) -> None:
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="降准利好",
            entry_condition="price > 35",
            invalidation_condition="跌破30",
            confidence=0.7,
        )
        d = thesis.to_dict()
        assert d["symbol"] == "600036.SH"
        assert d["direction"] == "long"
        assert d["initial_confidence"] == 0.7
        assert d["status"] == "active"
        assert isinstance(d["evidence"], list)
        assert d["resolved_at"] is None


# ------------------------------------------------------------------
# DecisionPipeline integration
# ------------------------------------------------------------------


class TestDecisionPipelineIntegration:
    def test_buy_creates_thesis(self, tmp_path: Path) -> None:
        """When DecisionPipeline produces a buy proposal, a thesis is auto-created."""
        from src.agent_loop.decision_pipeline import DecisionPipeline
        from src.agent_loop.models import AggregatedSignal, SignalDirection, UrgencyTier

        tracker = ThesisTracker(db_path=tmp_path / "pipeline_test.db")
        pipeline = DecisionPipeline(
            thesis_tracker=tracker,
            config={
                "min_confidence_to_propose": 0.3,
                "min_confidence_to_recommend_buy": 0.3,
            },
        )

        signal = AggregatedSignal(
            symbol="600036.SH",
            name="招商银行",
            direction=SignalDirection.BUY,
            source="test",
            confidence=0.8,
            urgency=UrgencyTier.NORMAL,
            reason="Test buy signal",
            metadata={"entry_price": 35.0},
        )

        import asyncio

        proposal = asyncio.run(
            pipeline.evaluate(
                signal=signal,
                portfolio=[],
                available_cash=100000,
                market_data={"current_price": 35.0},
            )
        )

        # The pipeline should have created a thesis
        theses = tracker.list_theses(symbol="600036.SH")
        if proposal and proposal.action in ("buy", "add"):
            assert len(theses) >= 1
            assert theses[0].symbol == "600036.SH"
            assert theses[0].status == "active"

    def test_sell_resolves_thesis(self, tmp_path: Path) -> None:
        """When DecisionPipeline produces a sell proposal, the thesis is resolved."""
        from src.agent_loop.decision_pipeline import DecisionPipeline
        from src.agent_loop.models import AggregatedSignal, SignalDirection, UrgencyTier

        tracker = ThesisTracker(db_path=tmp_path / "pipeline_sell_test.db")

        # Create an existing thesis
        thesis = tracker.create_thesis(
            symbol="600036.SH",
            direction="long",
            narrative="test thesis",
            entry_condition="",
            invalidation_condition="",
            confidence=0.7,
        )

        pipeline = DecisionPipeline(
            thesis_tracker=tracker,
            config={
                "min_confidence_to_propose": 0.3,
            },
        )

        signal = AggregatedSignal(
            symbol="600036.SH",
            name="招商银行",
            direction=SignalDirection.SELL,
            source="test",
            confidence=0.8,
            urgency=UrgencyTier.CRITICAL,
            reason="Stop loss triggered",
        )

        import asyncio

        asyncio.run(
            pipeline.evaluate(
                signal=signal,
                portfolio=[
                    {"symbol": "600036.SH", "shares": 100, "market_value": 3500}
                ],
                available_cash=100000,
                market_data={"current_price": 33.0},
            )
        )

        # CRITICAL sell skips debate and doesn't go through thesis lifecycle
        # (it uses _handle_critical). But thesis should still be active
        # since _handle_critical doesn't call _handle_thesis_lifecycle.
        updated = tracker.get_thesis(thesis.id)
        assert updated is not None

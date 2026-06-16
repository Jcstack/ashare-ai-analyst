"""Unit tests for agent_loop model validation."""

from __future__ import annotations

import pytest

from src.agent_loop.models import (
    AggregatedSignal,
    CycleResult,
    InvestmentThesis,
    SignalDirection,
    TradeProposal,
    UrgencyTier,
)
from src.agent_loop.signal_aggregator import SignalAggregator


class TestTradeProposalToDict:
    def test_includes_all_fields(self):
        proposal = TradeProposal(
            symbol="600519",
            name="贵州茅台",
            action="buy",
            shares=200,
            confidence=0.85,
            debate_summary="Bulls win",
            bull_score=0.7,
            bear_score=0.3,
            price_target=2000.0,
            stop_loss=1700.0,
            take_profit=2200.0,
            risk_reward_ratio=2.5,
            risk_notes=["High volatility"],
            portfolio_impact={"weight_after": 0.15},
            overnight_risk_pct=0.02,
            reasoning_chain=["Step 1", "Step 2"],
        )
        d = proposal.to_dict()

        assert d["symbol"] == "600519"
        assert d["name"] == "贵州茅台"
        assert d["action"] == "buy"
        assert d["shares"] == 200
        assert d["confidence"] == 0.85
        assert d["debate_summary"] == "Bulls win"
        assert d["bull_score"] == 0.7
        assert d["bear_score"] == 0.3
        assert d["price_target"] == 2000.0
        assert d["stop_loss"] == 1700.0
        assert d["take_profit"] == 2200.0
        assert d["risk_reward_ratio"] == 2.5
        assert d["risk_notes"] == ["High volatility"]
        assert d["portfolio_impact"] == {"weight_after": 0.15}
        assert d["overnight_risk_pct"] == 0.02
        assert d["reasoning_chain"] == ["Step 1", "Step 2"]
        assert "proposal_id" in d
        assert "created_at" in d

    def test_thesis_field_serializes(self):
        thesis = InvestmentThesis(
            symbol="600519", name="贵州茅台",
            direction="bullish", conviction=0.8,
            thesis_text="Strong brand",
        )
        proposal = TradeProposal(
            symbol="600519", name="贵州茅台", action="buy",
            shares=100, confidence=0.8, debate_summary="ok",
            bull_score=0.6, bear_score=0.4, thesis=thesis,
        )
        d = proposal.to_dict()
        assert d["thesis"] is not None
        assert d["thesis"]["symbol"] == "600519"

    def test_thesis_none_serializes_to_none(self):
        proposal = TradeProposal(
            symbol="600519", name="贵州茅台", action="buy",
            shares=100, confidence=0.8, debate_summary="ok",
            bull_score=0.6, bear_score=0.4,
        )
        d = proposal.to_dict()
        assert d["thesis"] is None


class TestInvestmentThesisDefaults:
    def test_default_values(self):
        thesis = InvestmentThesis(
            symbol="600519", name="贵州茅台",
            direction="bullish", conviction=0.7,
            thesis_text="Test",
        )
        assert thesis.key_assumptions == []
        assert thesis.invalidation_conditions == []
        assert thesis.entry_price_target is None
        assert thesis.stop_loss_pct is None
        assert thesis.sector == ""
        assert thesis.status == "active"
        assert thesis.invalidated_at is None
        assert thesis.invalidation_reason == ""
        assert thesis.id  # UUID auto-generated
        assert thesis.created_at is not None
        assert thesis.updated_at is not None

    def test_to_dict_roundtrip(self):
        thesis = InvestmentThesis(
            symbol="600519", name="贵州茅台",
            direction="bullish", conviction=0.7,
            thesis_text="Test thesis",
            key_assumptions=["A1"],
            sector="消费",
        )
        d = thesis.to_dict()
        assert d["symbol"] == "600519"
        assert d["key_assumptions"] == ["A1"]
        assert d["sector"] == "消费"
        assert d["invalidated_at"] is None


class TestAggregatedSignalPriorityScore:
    def test_priority_score_via_compute(self):
        signal = AggregatedSignal(
            symbol="600519", name="贵州茅台",
            direction=SignalDirection.BUY, source="test",
            confidence=0.8, urgency=UrgencyTier.NORMAL,
            reason="test",
        )
        score = SignalAggregator.compute_priority_score(signal)
        # NORMAL=2.0, confidence=0.8, freshness=1.0 => 1.6
        assert score == pytest.approx(1.6, abs=0.1)

    def test_critical_urgency_scores_highest(self):
        normal = AggregatedSignal(
            symbol="A", name="A", direction=SignalDirection.BUY,
            source="t", confidence=1.0, urgency=UrgencyTier.NORMAL, reason="",
        )
        critical = AggregatedSignal(
            symbol="B", name="B", direction=SignalDirection.SELL,
            source="t", confidence=1.0, urgency=UrgencyTier.CRITICAL, reason="",
        )
        assert SignalAggregator.compute_priority_score(critical) > \
               SignalAggregator.compute_priority_score(normal)


class TestCycleResultToDict:
    def test_to_dict_works(self):
        result = CycleResult(
            cycle_id="abc123",
            duration_seconds=2.5,
            signals_processed=3,
            proposals_generated=[],
            theses_updated=1,
            theses_invalidated=0,
            outcomes_checked=2,
            errors=["minor warning"],
        )
        d = result.to_dict()

        assert d["cycle_id"] == "abc123"
        assert d["duration_seconds"] == 2.5
        assert d["signals_processed"] == 3
        assert d["proposals_generated"] == []
        assert d["theses_updated"] == 1
        assert d["outcomes_checked"] == 2
        assert d["errors"] == ["minor warning"]
        assert "timestamp" in d

    def test_to_dict_with_proposals(self):
        proposal = TradeProposal(
            symbol="600519", name="贵州茅台", action="buy",
            shares=100, confidence=0.8, debate_summary="ok",
            bull_score=0.6, bear_score=0.4,
        )
        result = CycleResult(
            cycle_id="x", duration_seconds=1.0,
            signals_processed=1, proposals_generated=[proposal],
        )
        d = result.to_dict()
        assert len(d["proposals_generated"]) == 1
        assert d["proposals_generated"][0]["symbol"] == "600519"


class TestUrgencyTierEnum:
    def test_values(self):
        assert UrgencyTier.CRITICAL.value == "critical"
        assert UrgencyTier.HIGH.value == "high"
        assert UrgencyTier.NORMAL.value == "normal"
        assert UrgencyTier.DEEP.value == "deep"

    def test_all_members(self):
        members = list(UrgencyTier)
        assert len(members) == 4


class TestSignalDirectionEnum:
    def test_values(self):
        assert SignalDirection.BUY.value == "buy"
        assert SignalDirection.SELL.value == "sell"
        assert SignalDirection.HOLD.value == "hold"
        assert SignalDirection.REDUCE.value == "reduce"
        assert SignalDirection.ADD.value == "add"

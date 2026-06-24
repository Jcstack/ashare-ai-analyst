"""Tests for InvestmentDirector lifecycle methods."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.agent_loop.investment_director import InvestmentDirector
from src.agent_loop.models import (
    AggregatedSignal,
    InvestmentThesis,
    SignalDirection,
    TradeProposal,
    UrgencyTier,
)
from src.agent_loop.shared_belief_state import SharedBeliefState


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def belief() -> SharedBeliefState:
    return SharedBeliefState()


@pytest.fixture
def mock_portfolio_store():
    store = MagicMock()
    store.list_positions.return_value = [
        {
            "symbol": "000001",
            "name": "平安银行",
            "shares": 1000,
            "avg_cost": 10.0,
            "current_price": 10.5,
            "market_value": 10500,
            "daily_pnl": 200,
            "pnl_pct": 0.05,
            "sector": "银行",
        },
    ]
    return store


@pytest.fixture
def mock_capital_service():
    svc = MagicMock()
    bal = MagicMock()
    bal.available = 50000.0
    svc.get_balance.return_value = bal
    return svc


@pytest.fixture
def mock_global_market():
    fetcher = MagicMock()
    fetcher.get_cached_snapshot.return_value = {
        "indices": [
            {"name": "道琼斯", "change_pct": 0.5},
            {"name": "标普500", "change_pct": 0.3},
            {"name": "纳斯达克", "change_pct": -0.2},
        ]
    }
    return fetcher


@pytest.fixture
def mock_thesis_store():
    store = MagicMock()
    thesis = InvestmentThesis(
        symbol="000001",
        name="平安银行",
        direction="bullish",
        conviction=0.75,
        thesis_text="银行板块估值修复",
        sector="银行",
    )
    store.get_active.return_value = [thesis]
    store.get.return_value = thesis
    store.decay_stale.return_value = 0
    return store


@pytest.fixture
def mock_notifier():
    return MagicMock()


@pytest.fixture
def mock_decision_log():
    log = MagicMock()
    log.get_accuracy_stats.return_value = {
        "total_decisions": 10,
        "direction_accuracy": 0.6,
        "avg_t3_return": 0.02,
    }
    log.get_pending_outcomes.return_value = []
    return log


@pytest.fixture
def mock_regime_detector():
    detector = MagicMock()
    detector.detect.return_value = {
        "regime": "bull",
        "probability": 0.75,
        "sentiment_phase": "ignition",
        "sentiment_phase_cn": "点燃",
        "reflexivity": "strengthening",
    }
    return detector


@pytest.fixture
def mock_signal_aggregator():
    agg = MagicMock()
    agg.rank_and_deduplicate.return_value = []
    return agg


@pytest.fixture
def mock_decision_pipeline():
    pipeline = MagicMock()

    async def mock_evaluate(**kwargs):
        signal = kwargs.get("signal")
        if signal and signal.direction == SignalDirection.BUY:
            return TradeProposal(
                symbol=signal.symbol,
                name=signal.name,
                action="buy",
                shares=100,
                confidence=0.75,
                debate_summary="辩论通过",
                bull_score=0.7,
                bear_score=0.3,
                price_target=11.0,
            )
        return None

    pipeline.evaluate = mock_evaluate
    return pipeline


@pytest.fixture
def director(
    belief,
    mock_portfolio_store,
    mock_capital_service,
    mock_global_market,
    mock_thesis_store,
    mock_notifier,
    mock_decision_log,
    mock_regime_detector,
    mock_signal_aggregator,
    mock_decision_pipeline,
):
    return InvestmentDirector(
        belief_state=belief,
        signal_aggregator=mock_signal_aggregator,
        decision_pipeline=mock_decision_pipeline,
        portfolio_store=mock_portfolio_store,
        capital_service=mock_capital_service,
        notification_dispatcher=mock_notifier,
        regime_detector=mock_regime_detector,
        thesis_store=mock_thesis_store,
        global_market_fetcher=mock_global_market,
        decision_log=mock_decision_log,
        config={"min_confidence_to_propose": 0.6},
    )


# ------------------------------------------------------------------
# Pre-market brief
# ------------------------------------------------------------------


class TestPreMarketBrief:
    @pytest.mark.anyio
    async def test_produces_daily_plan(self, director: InvestmentDirector):
        result = await director.pre_market_brief()

        assert "daily_plan" in result
        assert "global_summary" in result
        assert "regime" in result

        # Check daily plan was set on belief state
        plan = director.belief_state.daily_plan
        assert plan.date != ""
        assert "000001" in plan.watch_list

    @pytest.mark.anyio
    async def test_resets_daily_state(self, director: InvestmentDirector):
        # Simulate prior day losses
        director.belief_state.update_risk_budget(realized_loss=0.02)
        assert director.belief_state.risk_budget.realized_losses_today > 0

        await director.pre_market_brief()

        assert director.belief_state.risk_budget.realized_losses_today == 0.0
        assert not director.belief_state.risk_budget.is_halted

    @pytest.mark.anyio
    async def test_updates_regime(self, director: InvestmentDirector):
        await director.pre_market_brief()

        assert director.belief_state.regime.hmm_state == "bull"
        assert director.belief_state.regime.sentiment_phase == "ignition"

    @pytest.mark.anyio
    async def test_pushes_notification(self, director, mock_notifier):
        await director.pre_market_brief()
        mock_notifier.dispatch.assert_called()
        call_args = mock_notifier.dispatch.call_args
        assert call_args[1]["event_type"] == "morning_briefing"

    @pytest.mark.anyio
    async def test_global_summary_included(self, director: InvestmentDirector):
        result = await director.pre_market_brief()
        assert "道琼斯" in result["global_summary"]

    @pytest.mark.anyio
    async def test_buy_candidates_from_bullish_theses(self, director):
        await director.pre_market_brief()
        plan = director.belief_state.daily_plan
        # 000001 thesis is bullish with 0.75 conviction (>= 0.6)
        assert any(c["symbol"] == "000001" for c in plan.buy_candidates)


# ------------------------------------------------------------------
# Late session
# ------------------------------------------------------------------


class TestLateSession:
    @pytest.mark.anyio
    async def test_generates_proposals(self, director: InvestmentDirector):
        # Set up a buy candidate
        director.belief_state.daily_plan.buy_candidates = [
            {"symbol": "600519", "name": "贵州茅台", "conviction": 0.8},
        ]
        director._signal_agg.rank_and_deduplicate.return_value = [
            AggregatedSignal(
                symbol="600519",
                name="贵州茅台",
                direction=SignalDirection.BUY,
                source="daily_plan",
                confidence=0.8,
                urgency=UrgencyTier.NORMAL,
                reason="test buy",
            )
        ]

        result = await director.late_session()

        assert "proposals" in result
        assert len(result["proposals"]) == 1
        assert result["proposals"][0]["symbol"] == "600519"

    @pytest.mark.anyio
    async def test_risk_halt_blocks_buys(self, director: InvestmentDirector):
        director.belief_state.risk_budget.is_halted = True
        result = await director.late_session()

        assert result["risk_halted"] is True
        assert len(result.get("proposals", [])) == 0

    @pytest.mark.anyio
    async def test_ebb_phase_blocks_buys(self, director: InvestmentDirector):
        director.belief_state.update_regime(sentiment_phase="ebb")
        result = await director.late_session()

        assert len(result.get("blocked", [])) > 0
        assert len(result.get("proposals", [])) == 0


# ------------------------------------------------------------------
# Post-market review
# ------------------------------------------------------------------


class TestPostMarketReview:
    @pytest.mark.anyio
    async def test_produces_review(self, director: InvestmentDirector):
        result = await director.post_market_review()

        assert "date" in result
        assert "daily_pnl" in result
        assert "outcomes" in result
        assert "calibration" in result

    @pytest.mark.anyio
    async def test_updates_calibration(self, director, mock_decision_log):
        result = await director.post_market_review()

        mock_decision_log.get_accuracy_stats.assert_called_once()
        assert "direction_accuracy" in result.get("calibration", {})

    @pytest.mark.anyio
    async def test_pushes_evening_review(self, director, mock_notifier):
        await director.post_market_review()
        calls = [
            c
            for c in mock_notifier.dispatch.call_args_list
            if c[1].get("event_type") == "evening_review"
        ]
        assert len(calls) == 1

    @pytest.mark.anyio
    async def test_thesis_decay_runs(self, director, mock_thesis_store):
        await director.post_market_review()
        mock_thesis_store.decay_stale.assert_called()


# ------------------------------------------------------------------
# Event handler
# ------------------------------------------------------------------


class TestHandleEvent:
    @pytest.mark.anyio
    async def test_low_severity_ignored(self, director: InvestmentDirector):
        result = await director.handle_event(
            {
                "type": "volume_spike",
                "severity": 0.1,
                "symbol": "000001",
            }
        )
        assert result is None

    @pytest.mark.anyio
    async def test_black_swan_triggers_alert(self, director: InvestmentDirector):
        result = await director.handle_event(
            {
                "type": "black_swan",
                "severity": 0.9,
                "symbol": "000001",
                "name": "平安银行",
                "message": "重大利空",
            }
        )

        assert result is not None
        assert result["action"] == "critical_sell"

    @pytest.mark.anyio
    async def test_irrelevant_symbol_ignored(self, director: InvestmentDirector):
        result = await director.handle_event(
            {
                "type": "volume_spike",
                "severity": 0.8,
                "symbol": "999999",
            }
        )
        assert result is None

    @pytest.mark.anyio
    async def test_thesis_invalidation_event(self, director: InvestmentDirector):
        director.belief_state.daily_plan.watch_list = ["600519"]
        result = await director.handle_event(
            {
                "type": "thesis_invalidation",
                "severity": 0.7,
                "symbol": "600519",
                "reason": "业绩不及预期",
            }
        )
        assert result is not None
        assert result["action"] == "thesis_review"


# ------------------------------------------------------------------
# Call auction monitor
# ------------------------------------------------------------------


class TestCallAuctionMonitor:
    @pytest.mark.anyio
    async def test_without_provider_passes_through_candidates(self, director):
        director.belief_state.daily_plan.buy_candidates = [
            {"symbol": "000001", "name": "平安银行", "conviction": 0.8},
        ]
        director.belief_state.daily_plan.watch_list = ["000001"]

        result = await director.call_auction_monitor()
        assert len(result["confirmed"]) == 1

    @pytest.mark.anyio
    async def test_empty_watch_list(self, director):
        director.belief_state.daily_plan.watch_list = []
        result = await director.call_auction_monitor()
        assert result["confirmed"] == []
        assert result["rejected"] == []


# ------------------------------------------------------------------
# Morning session
# ------------------------------------------------------------------


class TestMorningSession:
    @pytest.mark.anyio
    async def test_regime_confirmed(self, director: InvestmentDirector):
        # Pre-set same phase as detector returns
        director.belief_state.update_regime(sentiment_phase="ignition")
        result = await director.morning_session()
        assert result["regime_confirmed"] is True

    @pytest.mark.anyio
    async def test_regime_shift_detected(self, director, mock_regime_detector):
        # Set pre-market phase to something different
        director.belief_state.update_regime(sentiment_phase="freezing")
        # Detector returns "ignition"
        result = await director.morning_session()
        assert result["regime_confirmed"] is False
        assert len(result["alerts"]) > 0


# ------------------------------------------------------------------
# Close briefing
# ------------------------------------------------------------------


class TestCloseBriefing:
    @pytest.mark.anyio
    async def test_produces_briefing(self, director: InvestmentDirector):
        result = await director.close_briefing()
        assert "date" in result
        assert "position_count" in result
        assert "daily_pnl" in result
        assert result["position_count"] == 1

    @pytest.mark.anyio
    async def test_pushes_notification(self, director, mock_notifier):
        await director.close_briefing()
        calls = [
            c
            for c in mock_notifier.dispatch.call_args_list
            if c[1].get("event_type") == "close_briefing"
        ]
        assert len(calls) == 1


# ------------------------------------------------------------------
# Belief state property
# ------------------------------------------------------------------


class TestBeliefStateAccess:
    def test_belief_state_accessible(self, director: InvestmentDirector):
        assert director.belief_state is not None
        assert isinstance(director.belief_state, SharedBeliefState)


# ------------------------------------------------------------------
# Research team
# ------------------------------------------------------------------


class TestRunResearchTeam:
    @pytest.mark.anyio
    async def test_returns_empty_when_no_knowledge_graph(
        self, director: InvestmentDirector
    ):
        """When knowledge_graph is None, _run_research_team returns []."""
        assert director._knowledge_graph is None
        result = await director._run_research_team()
        assert result == []

    @pytest.mark.anyio
    async def test_returns_empty_when_no_active_events(self):
        """When knowledge graph has no active events, returns []."""
        mock_kg = MagicMock()
        mock_kg.get_active_events.return_value = []

        d = InvestmentDirector(knowledge_graph=mock_kg)
        result = await d._run_research_team()
        assert result == []
        mock_kg.get_active_events.assert_called_once()

    @pytest.mark.anyio
    async def test_processes_events_into_chains(self):
        """When knowledge graph has events and constructor matches, returns chains."""
        from unittest.mock import AsyncMock

        from src.intelligence.causal_chain import CausalChain, ImpactChainLink

        mock_kg = MagicMock()
        mock_kg.get_active_events.return_value = [
            {
                "event_id": "evt-001",
                "node_type": "event",
                "title": "央行降准50个基点",
                "event_type": "monetary_policy",
                "severity": 0.8,
            }
        ]

        # Build a real CausalChain to return
        chain = CausalChain(
            event_id="evt-001",
            event_description="央行降准50个基点",
            event_type="monetary_policy",
            base_confidence=0.8,
            chain=[
                ImpactChainLink(
                    order=1,
                    impact="银行流动性增加",
                    sectors=["银行"],
                    direction="bullish",
                    confidence=0.7,
                    affected_stocks=["601398"],
                ),
            ],
        )

        mock_constructor = MagicMock()
        mock_constructor.construct_chain_async = AsyncMock(return_value=chain)

        d = InvestmentDirector(
            knowledge_graph=mock_kg,
            causal_chain_constructor=mock_constructor,
        )
        result = await d._run_research_team()

        assert len(result) == 1
        assert result[0]["event_id"] == "evt-001"
        assert result[0]["event_type"] == "monetary_policy"
        assert len(result[0]["chain"]) == 1
        mock_constructor.construct_chain_async.assert_called_once()

    @pytest.mark.anyio
    async def test_skips_chains_without_stocks_or_sectors(self):
        """Chains with no stocks and no sectors are filtered out."""
        from unittest.mock import AsyncMock

        from src.intelligence.causal_chain import CausalChain

        mock_kg = MagicMock()
        mock_kg.get_active_events.return_value = [
            {
                "event_id": "evt-002",
                "title": "Some vague event",
                "event_type": "unknown",
                "severity": 0.5,
            }
        ]

        # Chain with empty sectors and stocks
        chain = CausalChain(
            event_id="evt-002",
            event_description="Some vague event",
            event_type="unknown",
            base_confidence=0.5,
            chain=[],  # No links = no stocks or sectors
        )

        mock_constructor = MagicMock()
        mock_constructor.construct_chain_async = AsyncMock(return_value=chain)

        d = InvestmentDirector(
            knowledge_graph=mock_kg,
            causal_chain_constructor=mock_constructor,
        )
        result = await d._run_research_team()
        assert result == []

    @pytest.mark.anyio
    async def test_updates_daily_plan_key_events(self):
        """Research briefs populate daily_plan.key_events."""
        from unittest.mock import AsyncMock

        from src.intelligence.causal_chain import CausalChain, ImpactChainLink

        mock_kg = MagicMock()
        mock_kg.get_active_events.return_value = [
            {
                "event_id": "evt-003",
                "title": "美联储加息",
                "event_type": "monetary_policy",
                "severity": 0.9,
            }
        ]

        chain = CausalChain(
            event_id="evt-003",
            event_description="美联储加息",
            event_type="monetary_policy",
            base_confidence=0.9,
            chain=[
                ImpactChainLink(
                    order=1,
                    impact="外资流出压力",
                    sectors=["金融"],
                    direction="bearish",
                    confidence=0.7,
                ),
            ],
        )

        mock_constructor = MagicMock()
        mock_constructor.construct_chain_async = AsyncMock(return_value=chain)

        belief = SharedBeliefState()
        d = InvestmentDirector(
            belief_state=belief,
            knowledge_graph=mock_kg,
            causal_chain_constructor=mock_constructor,
        )
        result = await d._run_research_team(belief)

        assert len(result) == 1
        assert "美联储加息" in belief.daily_plan.key_events[0]

    @pytest.mark.anyio
    async def test_handles_constructor_error_gracefully(self):
        """If construct_chain_async raises, that event is skipped."""
        from unittest.mock import AsyncMock

        mock_kg = MagicMock()
        mock_kg.get_active_events.return_value = [
            {
                "event_id": "evt-err",
                "title": "Bad event",
                "event_type": "test",
                "severity": 0.5,
            }
        ]

        mock_constructor = MagicMock()
        mock_constructor.construct_chain_async = AsyncMock(
            side_effect=Exception("LLM timeout")
        )

        d = InvestmentDirector(
            knowledge_graph=mock_kg,
            causal_chain_constructor=mock_constructor,
        )
        result = await d._run_research_team()
        assert result == []

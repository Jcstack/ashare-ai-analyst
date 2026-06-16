"""Unit tests for AutonomousTradingLoop with mocked dependencies."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent_loop.models import CycleResult
from src.agent_loop.trading_loop import AutonomousTradingLoop


@pytest.fixture()
def mock_deps():
    """Create mocked dependencies for the trading loop."""
    thesis_store = MagicMock()
    thesis_store.get_active.return_value = []
    thesis_store.get.return_value = None
    thesis_store.decay_stale.return_value = 0

    signal_agg = MagicMock()
    signal_agg.clear.return_value = None
    signal_agg.rank_and_deduplicate.return_value = []

    decision_pipeline = AsyncMock()
    decision_pipeline.evaluate.return_value = None

    portfolio_store = MagicMock()
    portfolio_store.list_positions.return_value = []

    capital_service = MagicMock()
    balance = MagicMock()
    balance.available = 100_000.0
    capital_service.get_balance.return_value = balance

    regime_detector = MagicMock()
    regime_detector.detect.return_value = {"regime": "bull"}

    notification_dispatcher = MagicMock()

    return dict(
        thesis_store=thesis_store,
        signal_aggregator=signal_agg,
        decision_pipeline=decision_pipeline,
        portfolio_store=portfolio_store,
        capital_service=capital_service,
        regime_detector=regime_detector,
        notification_dispatcher=notification_dispatcher,
    )


@pytest.fixture()
def loop(mock_deps):
    return AutonomousTradingLoop(**mock_deps)


class TestRunCycle:
    @pytest.mark.anyio
    async def test_completes_without_errors(self, loop):
        result = await loop.run_cycle()

        assert isinstance(result, CycleResult)
        assert len(result.errors) == 0
        assert result.duration_seconds >= 0

    @pytest.mark.anyio
    async def test_calls_sense_orient_act_learn(self, loop, mock_deps):
        await loop.run_cycle()

        # SENSE: portfolio + capital + regime + theses queried
        mock_deps["portfolio_store"].list_positions.assert_called_once()
        mock_deps["capital_service"].get_balance.assert_called_once()
        mock_deps["regime_detector"].detect.assert_called_once()
        mock_deps["thesis_store"].get_active.assert_called()

        # ORIENT: decay checked
        mock_deps["thesis_store"].decay_stale.assert_called_once()

        # Signal aggregator cleared and ranked
        mock_deps["signal_aggregator"].clear.assert_called_once()
        mock_deps["signal_aggregator"].rank_and_deduplicate.assert_called_once()


class TestRunPremarket:
    @pytest.mark.anyio
    async def test_returns_briefing_string(self, loop):
        result = await loop.run_premarket()
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.anyio
    async def test_dispatches_notification(self, loop, mock_deps):
        await loop.run_premarket()
        mock_deps["notification_dispatcher"].dispatch.assert_called_once()
        call_kwargs = mock_deps["notification_dispatcher"].dispatch.call_args
        assert call_kwargs[1]["notification_type"] == "morning_briefing" or \
               call_kwargs[0][0] == "morning_briefing" if call_kwargs[0] else True


class TestRunPostmarket:
    @pytest.mark.anyio
    async def test_returns_review_string(self, loop):
        result = await loop.run_postmarket()
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.anyio
    async def test_dispatches_evening_review(self, loop, mock_deps):
        await loop.run_postmarket()
        mock_deps["notification_dispatcher"].dispatch.assert_called_once()


class TestRunCycleWithErrors:
    @pytest.mark.anyio
    async def test_handles_portfolio_failure_gracefully(self, mock_deps):
        mock_deps["portfolio_store"].list_positions.side_effect = Exception("DB down")
        loop = AutonomousTradingLoop(**mock_deps)
        result = await loop.run_cycle()
        # Should complete without raising; errors may or may not be logged
        assert isinstance(result, CycleResult)

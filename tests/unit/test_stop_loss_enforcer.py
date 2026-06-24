"""Tests for StopLossEnforcer — monitors positions against thesis stop prices.

Part of v19.0 Production Hardening — Phase 3.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.trading.stop_loss_enforcer import StopLossEnforcer
from src.trading.execution_bridge import ExecutionResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge.process_proposal.return_value = ExecutionResult(
        status="submitted",
        gate_request_id="gate-sl-001",
        broker_order_id="ORD-SL-001",
    )
    return bridge


@pytest.fixture
def mock_portfolio() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_thesis_store() -> MagicMock:
    return MagicMock()


def _make_enforcer(
    bridge: MagicMock,
    portfolio: MagicMock,
    thesis_store: MagicMock | None = None,
) -> StopLossEnforcer:
    return StopLossEnforcer(
        execution_bridge=bridge,
        portfolio_service=portfolio,
        thesis_store=thesis_store,
    )


# ---------------------------------------------------------------------------
# Tests — position below stop price triggers sell
# ---------------------------------------------------------------------------


class TestStopLossTriggered:
    def test_position_below_stop_triggers_sell(
        self, mock_bridge: MagicMock, mock_portfolio: MagicMock
    ):
        # Cost 100, default stop 5% -> stop price = 95
        # Current price 90 < 95 -> triggers
        mock_portfolio.get_portfolio.return_value = {
            "positions": [
                {
                    "symbol": "600498",
                    "name": "星湖科技",
                    "shares": 1000,
                    "cost_price": 100.0,
                    "current_price": 90.0,
                }
            ]
        }
        enforcer = _make_enforcer(mock_bridge, mock_portfolio)
        results = enforcer.check_and_enforce()

        assert len(results) == 1
        assert results[0]["symbol"] == "600498"
        assert results[0]["status"] == "submitted"
        mock_bridge.process_proposal.assert_called_once()
        call_kwargs = mock_bridge.process_proposal.call_args.kwargs
        assert call_kwargs["symbol"] == "600498"
        assert call_kwargs["action"] == "sell"
        assert call_kwargs["shares"] == 1000
        assert call_kwargs["price"] == 90.0

    def test_multiple_positions_below_stop(
        self, mock_bridge: MagicMock, mock_portfolio: MagicMock
    ):
        mock_portfolio.get_portfolio.return_value = {
            "positions": [
                {
                    "symbol": "600498",
                    "name": "A",
                    "shares": 500,
                    "cost_price": 100.0,
                    "current_price": 90.0,
                },
                {
                    "symbol": "601318",
                    "name": "B",
                    "shares": 200,
                    "cost_price": 50.0,
                    "current_price": 46.0,
                },
            ]
        }
        enforcer = _make_enforcer(mock_bridge, mock_portfolio)
        results = enforcer.check_and_enforce()

        assert len(results) == 2
        assert mock_bridge.process_proposal.call_count == 2


# ---------------------------------------------------------------------------
# Tests — position above stop price does nothing
# ---------------------------------------------------------------------------


class TestNoTrigger:
    def test_position_above_stop_does_nothing(
        self, mock_bridge: MagicMock, mock_portfolio: MagicMock
    ):
        # Cost 100, stop = 95, current 98 > 95 -> no trigger
        mock_portfolio.get_portfolio.return_value = {
            "positions": [
                {
                    "symbol": "600498",
                    "name": "星湖科技",
                    "shares": 1000,
                    "cost_price": 100.0,
                    "current_price": 98.0,
                }
            ]
        }
        enforcer = _make_enforcer(mock_bridge, mock_portfolio)
        results = enforcer.check_and_enforce()

        assert len(results) == 0
        mock_bridge.process_proposal.assert_not_called()

    def test_empty_portfolio(self, mock_bridge: MagicMock, mock_portfolio: MagicMock):
        mock_portfolio.get_portfolio.return_value = {"positions": []}
        enforcer = _make_enforcer(mock_bridge, mock_portfolio)
        results = enforcer.check_and_enforce()
        assert len(results) == 0

    def test_portfolio_error_returns_empty(
        self, mock_bridge: MagicMock, mock_portfolio: MagicMock
    ):
        mock_portfolio.get_portfolio.side_effect = RuntimeError("DB error")
        enforcer = _make_enforcer(mock_bridge, mock_portfolio)
        results = enforcer.check_and_enforce()
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Tests — default 5% stop-loss when no thesis
# ---------------------------------------------------------------------------


class TestDefaultStopLoss:
    def test_default_5_percent_stop(
        self, mock_bridge: MagicMock, mock_portfolio: MagicMock
    ):
        # Cost 100, 5% stop -> stop price = 95.0
        mock_portfolio.get_portfolio.return_value = {
            "positions": [
                {
                    "symbol": "600498",
                    "name": "测试",
                    "shares": 100,
                    "cost_price": 100.0,
                    "current_price": 95.0,  # Exactly at stop
                }
            ]
        }
        # No thesis store at all
        enforcer = _make_enforcer(mock_bridge, mock_portfolio, thesis_store=None)
        results = enforcer.check_and_enforce()

        assert len(results) == 1
        assert results[0]["stop_price"] == 95.0

    def test_just_above_default_stop_no_trigger(
        self, mock_bridge: MagicMock, mock_portfolio: MagicMock
    ):
        # Cost 100, stop = 95, current = 95.01 -> no trigger
        mock_portfolio.get_portfolio.return_value = {
            "positions": [
                {
                    "symbol": "600498",
                    "name": "测试",
                    "shares": 100,
                    "cost_price": 100.0,
                    "current_price": 95.01,
                }
            ]
        }
        enforcer = _make_enforcer(mock_bridge, mock_portfolio, thesis_store=None)
        results = enforcer.check_and_enforce()
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Tests — thesis stop_loss_pct used when available
# ---------------------------------------------------------------------------


class TestThesisStopLoss:
    def test_thesis_stop_loss_used(
        self,
        mock_bridge: MagicMock,
        mock_portfolio: MagicMock,
        mock_thesis_store: MagicMock,
    ):
        # Thesis says 10% stop -> stop price = 90.0
        thesis = MagicMock()
        thesis.stop_loss_pct = 0.10
        mock_thesis_store.get_by_symbol.return_value = thesis

        mock_portfolio.get_portfolio.return_value = {
            "positions": [
                {
                    "symbol": "600498",
                    "name": "测试",
                    "shares": 200,
                    "cost_price": 100.0,
                    "current_price": 89.0,  # Below 90
                }
            ]
        }
        enforcer = _make_enforcer(mock_bridge, mock_portfolio, mock_thesis_store)
        results = enforcer.check_and_enforce()

        assert len(results) == 1
        assert results[0]["stop_price"] == 90.0

    def test_no_thesis_for_symbol_uses_default(
        self,
        mock_bridge: MagicMock,
        mock_portfolio: MagicMock,
        mock_thesis_store: MagicMock,
    ):
        mock_thesis_store.get_by_symbol.return_value = None

        mock_portfolio.get_portfolio.return_value = {
            "positions": [
                {
                    "symbol": "600498",
                    "name": "测试",
                    "shares": 100,
                    "cost_price": 100.0,
                    "current_price": 90.0,
                }
            ]
        }
        enforcer = _make_enforcer(mock_bridge, mock_portfolio, mock_thesis_store)
        results = enforcer.check_and_enforce()

        assert len(results) == 1
        # Default 5% -> stop at 95, current 90 < 95
        assert results[0]["stop_price"] == 95.0

    def test_thesis_store_error_uses_default(
        self,
        mock_bridge: MagicMock,
        mock_portfolio: MagicMock,
        mock_thesis_store: MagicMock,
    ):
        mock_thesis_store.get_by_symbol.side_effect = RuntimeError("DB error")

        mock_portfolio.get_portfolio.return_value = {
            "positions": [
                {
                    "symbol": "600498",
                    "name": "测试",
                    "shares": 100,
                    "cost_price": 100.0,
                    "current_price": 90.0,
                }
            ]
        }
        enforcer = _make_enforcer(mock_bridge, mock_portfolio, mock_thesis_store)
        results = enforcer.check_and_enforce()

        assert len(results) == 1
        assert results[0]["stop_price"] == 95.0  # Default 5%


# ---------------------------------------------------------------------------
# Tests — shares rounded to lot size
# ---------------------------------------------------------------------------


class TestLotSizeRounding:
    def test_shares_rounded_down_to_lot(
        self, mock_bridge: MagicMock, mock_portfolio: MagicMock
    ):
        mock_portfolio.get_portfolio.return_value = {
            "positions": [
                {
                    "symbol": "600498",
                    "name": "测试",
                    "shares": 350,  # 350 -> round to 300
                    "cost_price": 100.0,
                    "current_price": 90.0,
                }
            ]
        }
        enforcer = _make_enforcer(mock_bridge, mock_portfolio)
        results = enforcer.check_and_enforce()

        assert len(results) == 1
        assert results[0]["shares"] == 300
        call_kwargs = mock_bridge.process_proposal.call_args.kwargs
        assert call_kwargs["shares"] == 300

    def test_shares_below_100_skipped(
        self, mock_bridge: MagicMock, mock_portfolio: MagicMock
    ):
        mock_portfolio.get_portfolio.return_value = {
            "positions": [
                {
                    "symbol": "600498",
                    "name": "测试",
                    "shares": 50,  # Below minimum lot
                    "cost_price": 100.0,
                    "current_price": 90.0,
                }
            ]
        }
        enforcer = _make_enforcer(mock_bridge, mock_portfolio)
        results = enforcer.check_and_enforce()

        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert "minimum lot" in results[0]["reason"]
        mock_bridge.process_proposal.assert_not_called()

    def test_exact_lot_size_preserved(
        self, mock_bridge: MagicMock, mock_portfolio: MagicMock
    ):
        mock_portfolio.get_portfolio.return_value = {
            "positions": [
                {
                    "symbol": "600498",
                    "name": "测试",
                    "shares": 500,
                    "cost_price": 100.0,
                    "current_price": 90.0,
                }
            ]
        }
        enforcer = _make_enforcer(mock_bridge, mock_portfolio)
        results = enforcer.check_and_enforce()

        assert len(results) == 1
        assert results[0]["shares"] == 500


# ---------------------------------------------------------------------------
# Tests — no bridge
# ---------------------------------------------------------------------------


class TestNoBridge:
    def test_no_bridge_returns_empty(self, mock_portfolio: MagicMock):
        enforcer = StopLossEnforcer(
            execution_bridge=None,
            portfolio_service=mock_portfolio,
        )
        results = enforcer.check_and_enforce()
        assert results == []

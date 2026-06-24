"""Tests for OrderLifecycleManager — broker fill/rejection polling.

Part of v19.0 Production Hardening — Phase 2.1.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import MagicMock

from src.trading.order_lifecycle import OrderLifecycleManager
from src.web.services.broker_interface import OrderStatus


# ---------------------------------------------------------------------------
# Helper to build a mock gate request
# ---------------------------------------------------------------------------


def _make_gate_req(
    request_id: str = "gate-100",
    symbol: str = "600498",
    trade_type: str = "buy",
    broker_order_id: str = "ORD-001",
    extra_meta: dict | None = None,
) -> MagicMock:
    req = MagicMock()
    req.request_id = request_id
    req.symbol = symbol
    req.trade_type = trade_type
    meta = {"broker_order_id": broker_order_id, "stock_name": "测试股票"}
    if extra_meta:
        meta.update(extra_meta)
    req.metadata = json.dumps(meta)
    return req


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_broker() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_gate() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_trade_service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def manager(
    mock_broker: MagicMock,
    mock_gate: MagicMock,
    mock_trade_service: MagicMock,
) -> OrderLifecycleManager:
    return OrderLifecycleManager(
        broker=mock_broker,
        gate=mock_gate,
        trade_service=mock_trade_service,
    )


# ---------------------------------------------------------------------------
# Tests — filled order
# ---------------------------------------------------------------------------


class TestFilledOrder:
    def test_filled_order_calls_trade_service(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_trade_service: MagicMock,
        manager: OrderLifecycleManager,
    ):
        gate_req = _make_gate_req()
        mock_gate.get_pending_requests.return_value = [gate_req]
        mock_broker.get_order_status.return_value = OrderStatus(
            order_id="ORD-001",
            symbol="600498",
            action="buy",
            shares=100,
            price=25.50,
            status="filled",
        )

        results = manager.poll_pending_orders()

        assert len(results) == 1
        assert results[0]["new_status"] == "filled"
        assert results[0]["fill_price"] == 25.50
        assert results[0]["fill_shares"] == 100

        # Gate should be verified
        mock_gate.mark_verified.assert_called_once()

        # Trade service should record the fill
        mock_trade_service.execute_trade.assert_called_once_with(
            symbol="600498",
            stock_name="测试股票",
            action="buy",
            shares=100,
            price=25.50,
            reasoning="",
            gate_request_id="gate-100",
        )


# ---------------------------------------------------------------------------
# Tests — rejected order
# ---------------------------------------------------------------------------


class TestRejectedOrder:
    def test_rejected_order_calls_gate_reject(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        manager: OrderLifecycleManager,
    ):
        gate_req = _make_gate_req()
        mock_gate.get_pending_requests.return_value = [gate_req]
        mock_broker.get_order_status.return_value = OrderStatus(
            order_id="ORD-001",
            symbol="600498",
            action="buy",
            shares=100,
            price=25.0,
            status="rejected",
            message="Market closed",
        )

        results = manager.poll_pending_orders()

        assert len(results) == 1
        assert results[0]["new_status"] == "rejected"
        assert results[0]["message"] == "Market closed"
        mock_gate.reject.assert_called_once()

    def test_cancelled_order_calls_gate_reject(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        manager: OrderLifecycleManager,
    ):
        gate_req = _make_gate_req()
        mock_gate.get_pending_requests.return_value = [gate_req]
        mock_broker.get_order_status.return_value = OrderStatus(
            order_id="ORD-001",
            symbol="600498",
            action="buy",
            shares=100,
            price=25.0,
            status="cancelled",
            message="User cancelled",
        )

        results = manager.poll_pending_orders()

        assert len(results) == 1
        assert results[0]["new_status"] == "cancelled"
        mock_gate.reject.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — dry-run orders skipped
# ---------------------------------------------------------------------------


class TestDryRunSkipped:
    def test_dry_run_order_id_is_skipped(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        manager: OrderLifecycleManager,
    ):
        gate_req = _make_gate_req(broker_order_id="dry-run")
        mock_gate.get_pending_requests.return_value = [gate_req]

        results = manager.poll_pending_orders()

        assert len(results) == 0
        mock_broker.get_order_status.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — missing broker_order_id skipped
# ---------------------------------------------------------------------------


class TestMissingBrokerOrderId:
    def test_no_broker_order_id_skipped(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        manager: OrderLifecycleManager,
    ):
        req = MagicMock()
        req.request_id = "gate-200"
        req.metadata = json.dumps({"stock_name": "test"})  # No broker_order_id
        mock_gate.get_pending_requests.return_value = [req]

        results = manager.poll_pending_orders()

        assert len(results) == 0
        mock_broker.get_order_status.assert_not_called()

    def test_empty_metadata_skipped(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        manager: OrderLifecycleManager,
    ):
        req = MagicMock()
        req.request_id = "gate-201"
        req.metadata = ""  # Empty metadata
        mock_gate.get_pending_requests.return_value = [req]

        results = manager.poll_pending_orders()

        assert len(results) == 0


# ---------------------------------------------------------------------------
# Tests — broker error handled gracefully
# ---------------------------------------------------------------------------


class TestBrokerError:
    def test_broker_exception_returns_poll_error(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        manager: OrderLifecycleManager,
    ):
        gate_req = _make_gate_req()
        mock_gate.get_pending_requests.return_value = [gate_req]
        mock_broker.get_order_status.side_effect = ConnectionError("network down")

        results = manager.poll_pending_orders()

        assert len(results) == 1
        assert results[0]["new_status"] == "poll_error"
        assert "network down" in results[0]["error"]

        # Gate should NOT be transitioned on poll error
        mock_gate.mark_verified.assert_not_called()
        mock_gate.reject.assert_not_called()

    def test_trade_service_error_does_not_crash(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_trade_service: MagicMock,
        manager: OrderLifecycleManager,
    ):
        gate_req = _make_gate_req()
        mock_gate.get_pending_requests.return_value = [gate_req]
        mock_broker.get_order_status.return_value = OrderStatus(
            order_id="ORD-001",
            symbol="600498",
            action="buy",
            shares=100,
            price=25.50,
            status="filled",
        )
        mock_trade_service.execute_trade.side_effect = RuntimeError("DB error")

        # Should not raise — error is logged internally
        results = manager.poll_pending_orders()

        assert len(results) == 1
        assert results[0]["new_status"] == "filled"


# ---------------------------------------------------------------------------
# Tests — no pending orders
# ---------------------------------------------------------------------------


class TestNoPendingOrders:
    def test_empty_list_when_no_executed_requests(
        self,
        mock_gate: MagicMock,
        manager: OrderLifecycleManager,
    ):
        mock_gate.get_pending_requests.return_value = []
        results = manager.poll_pending_orders()
        assert results == []

    def test_none_list_when_no_executed_requests(
        self,
        mock_gate: MagicMock,
        manager: OrderLifecycleManager,
    ):
        mock_gate.get_pending_requests.return_value = None
        results = manager.poll_pending_orders()
        assert results == []

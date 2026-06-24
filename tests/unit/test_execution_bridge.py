"""Tests for ExecutionBridge — routes agent proposals through the execution pipeline.

Part of v19.0 Production Hardening — Phase 1.2.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import MagicMock

from src.trading.execution_bridge import ExecutionBridge
from src.trading.preflight import PreflightResult
from src.web.services.broker_interface import OrderStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_broker() -> MagicMock:
    broker = MagicMock()
    broker.submit_order.return_value = OrderStatus(
        order_id="ORD-001",
        symbol="600498",
        action="buy",
        shares=100,
        price=25.0,
        status="pending",
        message="Order accepted",
    )
    return broker


@pytest.fixture
def mock_gate() -> MagicMock:
    gate = MagicMock()
    gate_req = MagicMock()
    gate_req.request_id = "gate-123"
    gate.create_request.return_value = gate_req
    return gate


@pytest.fixture
def mock_preflight() -> MagicMock:
    pf = MagicMock()
    pf.check.return_value = PreflightResult(
        passed=True,
        checks=[{"name": "kill_switch", "passed": True, "reason": ""}],
    )
    return pf


@pytest.fixture
def mock_kill_switch() -> MagicMock:
    ks = MagicMock()
    ks.is_active.return_value = False
    return ks


def _make_bridge(
    broker: MagicMock,
    gate: MagicMock,
    preflight: MagicMock,
    kill_switch: MagicMock,
    mode: str = "dry_run",
) -> ExecutionBridge:
    return ExecutionBridge(
        broker=broker,
        gate=gate,
        preflight=preflight,
        kill_switch=kill_switch,
        execution_mode=mode,
    )


# ---------------------------------------------------------------------------
# Tests — dry_run mode
# ---------------------------------------------------------------------------


class TestDryRunMode:
    def test_dry_run_logs_but_does_not_call_broker(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="dry_run"
        )
        result = bridge.process_proposal(
            symbol="600498", action="buy", shares=100, price=25.0
        )

        assert result.status == "dry_run_logged"
        assert result.gate_request_id == "gate-123"
        mock_broker.submit_order.assert_not_called()
        mock_gate.confirm_user.assert_called_once()
        mock_gate.mark_executed.assert_called_once()

    def test_is_live_mode_false_for_dry_run(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="dry_run"
        )
        assert bridge.is_live_mode() is False


# ---------------------------------------------------------------------------
# Tests — confirm mode
# ---------------------------------------------------------------------------


class TestConfirmMode:
    def test_confirm_mode_leaves_at_risk_approved(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="confirm"
        )
        result = bridge.process_proposal(
            symbol="600498", action="buy", shares=100, price=25.0
        )

        assert result.status == "awaiting_confirmation"
        assert result.gate_request_id == "gate-123"
        mock_broker.submit_order.assert_not_called()
        # Should NOT auto-confirm for human
        mock_gate.confirm_user.assert_not_called()

    def test_is_live_mode_true_for_confirm(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="confirm"
        )
        assert bridge.is_live_mode() is True


# ---------------------------------------------------------------------------
# Tests — auto mode
# ---------------------------------------------------------------------------


class TestAutoMode:
    def test_auto_mode_calls_broker_submit(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="auto"
        )
        result = bridge.process_proposal(
            symbol="600498", action="buy", shares=100, price=25.0
        )

        assert result.status == "submitted"
        assert result.broker_order_id == "ORD-001"
        mock_broker.submit_order.assert_called_once_with(
            symbol="600498",
            action="buy",
            shares=100,
            price=25.0,
            gate_request_id="gate-123",
        )
        mock_gate.confirm_user.assert_called_once()
        mock_gate.mark_executed.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — kill switch blocks all modes
# ---------------------------------------------------------------------------


class TestKillSwitchBlocks:
    @pytest.mark.parametrize("mode", ["dry_run", "confirm", "auto"])
    def test_kill_switch_blocks(
        self,
        mode: str,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        mock_kill_switch.is_active.return_value = True
        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode=mode
        )
        result = bridge.process_proposal(
            symbol="600498", action="buy", shares=100, price=25.0
        )

        assert result.status == "blocked"
        assert result.reason == "kill_switch_active"
        mock_broker.submit_order.assert_not_called()
        mock_gate.create_request.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — preflight failure rejects
# ---------------------------------------------------------------------------


class TestPreflightFailure:
    def test_preflight_failure_rejects(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        mock_preflight.check.return_value = PreflightResult(
            passed=False,
            checks=[
                {
                    "name": "lot_size",
                    "passed": False,
                    "reason": "Shares 150 not a positive multiple of 100",
                }
            ],
        )
        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="auto"
        )
        result = bridge.process_proposal(
            symbol="600498", action="buy", shares=150, price=25.0
        )

        assert result.status == "rejected"
        assert "lot_size" in result.reason
        mock_broker.submit_order.assert_not_called()
        mock_gate.create_request.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — execute_confirmed
# ---------------------------------------------------------------------------


class TestExecuteConfirmed:
    def test_submits_to_broker(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        # Set up gate request in USER_CONFIRMED stage
        gate_req = MagicMock()
        gate_req.request_id = "gate-456"
        gate_req.current_stage = "USER_CONFIRMED"
        gate_req.symbol = "600498"
        gate_req.trade_type = "buy"
        gate_req.quantity = 100
        gate_req.price = 25.0
        gate_req.metadata = json.dumps({"stock_name": "test"})
        mock_gate.get_request.return_value = gate_req

        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="confirm"
        )
        result = bridge.execute_confirmed("gate-456")

        assert result.status == "submitted"
        assert result.broker_order_id == "ORD-001"
        mock_broker.submit_order.assert_called_once()

    def test_rejects_if_not_user_confirmed(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        gate_req = MagicMock()
        gate_req.request_id = "gate-789"
        gate_req.current_stage = "RISK_APPROVED"
        mock_gate.get_request.return_value = gate_req

        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="confirm"
        )
        result = bridge.execute_confirmed("gate-789")

        assert result.status == "rejected"
        assert "USER_CONFIRMED" in result.reason
        mock_broker.submit_order.assert_not_called()

    def test_rejects_if_gate_not_found(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        mock_gate.get_request.return_value = None

        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="confirm"
        )
        result = bridge.execute_confirmed("gate-nonexistent")

        assert result.status == "rejected"
        assert "not found" in result.reason


# ---------------------------------------------------------------------------
# Tests — idempotent resubmission
# ---------------------------------------------------------------------------


class TestIdempotentResubmission:
    def test_duplicate_submission_returns_existing_order(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        gate_req = MagicMock()
        gate_req.request_id = "gate-dup"
        gate_req.current_stage = "USER_CONFIRMED"
        gate_req.metadata = json.dumps({"broker_order_id": "ORD-EXISTING"})
        mock_gate.get_request.return_value = gate_req

        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="auto"
        )
        result = bridge.execute_confirmed("gate-dup")

        assert result.status == "submitted"
        assert result.broker_order_id == "ORD-EXISTING"
        assert "idempotent" in result.reason.lower()
        mock_broker.submit_order.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — broker rejection in auto mode
# ---------------------------------------------------------------------------


class TestBrokerRejection:
    def test_broker_rejects_order(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        mock_broker.submit_order.return_value = OrderStatus(
            order_id="",
            symbol="600498",
            action="buy",
            shares=100,
            price=25.0,
            status="rejected",
            message="Insufficient margin",
        )
        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="auto"
        )
        result = bridge.process_proposal(
            symbol="600498", action="buy", shares=100, price=25.0
        )

        assert result.status == "rejected"
        assert "Insufficient margin" in result.reason
        mock_gate.reject.assert_called_once()

    def test_broker_exception_rejects(
        self,
        mock_broker: MagicMock,
        mock_gate: MagicMock,
        mock_preflight: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        mock_broker.submit_order.side_effect = ConnectionError("network error")
        bridge = _make_bridge(
            mock_broker, mock_gate, mock_preflight, mock_kill_switch, mode="auto"
        )
        result = bridge.process_proposal(
            symbol="600498", action="buy", shares=100, price=25.0
        )

        assert result.status == "rejected"
        assert "network error" in result.reason
        mock_gate.reject.assert_called_once()

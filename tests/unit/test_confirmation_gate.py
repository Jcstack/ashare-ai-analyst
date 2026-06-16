"""Tests for ConfirmationGate — multi-stage trade approval workflow.

Part of v19.0 Production Hardening.
"""

from __future__ import annotations

import pytest

from src.workflow.confirmation_gate import (
    ConfirmationGate,
    GateConfig,
    GateStage,
)


@pytest.fixture
def gate(tmp_path):
    """Create a confirmation gate with a temp DB."""
    config = GateConfig(db_path=str(tmp_path / "test_gate.db"))
    return ConfirmationGate(config=config)


@pytest.fixture
def auto_approve_gate(tmp_path):
    """Gate that auto-approves trades below 10,000."""
    config = GateConfig(
        db_path=str(tmp_path / "test_gate_auto.db"),
        auto_approve_threshold=10000.0,
    )
    return ConfirmationGate(config=config)


class TestCreateRequest:
    """Tests for request creation."""

    def test_create_basic(self, gate):
        req = gate.create_request("buy", "600519", 100, price=1800.0)
        assert req.request_id != ""
        assert req.trade_type == "buy"
        assert req.symbol == "600519"
        assert req.quantity == 100
        assert req.price == 1800.0
        assert req.current_stage == GateStage.PENDING.value

    def test_create_market_order(self, gate):
        req = gate.create_request("sell", "300750", 200)
        assert req.price is None
        assert req.current_stage == GateStage.PENDING.value

    def test_create_with_metadata(self, gate):
        meta = {"reason": "技术面看好", "agent": "analyst"}
        req = gate.create_request("buy", "600519", 100, price=1800.0, metadata=meta)
        assert req.metadata == meta

    def test_create_with_thread_id(self, gate):
        req = gate.create_request("buy", "600519", 100, thread_id="t-123")
        assert req.thread_id == "t-123"

    def test_stage_history_recorded(self, gate):
        req = gate.create_request("buy", "600519", 100)
        assert len(req.stage_history) == 1
        assert req.stage_history[0].stage == GateStage.PENDING.value
        assert req.stage_history[0].actor == "system"

    def test_auto_approve_below_threshold(self, auto_approve_gate):
        """Trades below threshold should start at RISK_APPROVED."""
        req = auto_approve_gate.create_request("buy", "600519", 5, price=1800.0)
        # 5 * 1800 = 9000 < 10000 threshold
        assert req.current_stage == GateStage.RISK_APPROVED.value

    def test_auto_approve_above_threshold(self, auto_approve_gate):
        """Trades above threshold should start at PENDING."""
        req = auto_approve_gate.create_request("buy", "600519", 100, price=1800.0)
        # 100 * 1800 = 180000 > 10000 threshold
        assert req.current_stage == GateStage.PENDING.value

    def test_no_risk_approval_required(self, tmp_path):
        config = GateConfig(
            db_path=str(tmp_path / "no_risk.db"),
            require_risk_approval=False,
        )
        gate = ConfirmationGate(config=config)
        req = gate.create_request("buy", "600519", 100)
        assert req.current_stage == GateStage.RISK_APPROVED.value


class TestStateTransitions:
    """Tests for the state machine transitions."""

    def test_full_happy_path(self, gate):
        """PENDING → RISK_APPROVED → USER_CONFIRMED → EXECUTED → VERIFIED."""
        req = gate.create_request("buy", "600519", 100, price=1800.0)

        assert gate.approve_risk(req.request_id, notes="VaR within limits") is True
        assert gate.confirm_user(req.request_id, notes="确认买入") is True
        assert gate.mark_executed(req.request_id, execution_id="T12345") is True
        assert gate.mark_verified(req.request_id, actual_price=1800.5) is True

        final = gate.get_request(req.request_id)
        assert final.current_stage == GateStage.VERIFIED.value
        assert len(final.stage_history) == 5  # PENDING + 4 transitions

    def test_reject_from_pending(self, gate):
        req = gate.create_request("buy", "600519", 100)
        assert gate.reject(req.request_id, reason="风控不通过") is True

        final = gate.get_request(req.request_id)
        assert final.current_stage == GateStage.REJECTED.value

    def test_reject_from_risk_approved(self, gate):
        req = gate.create_request("buy", "600519", 100)
        gate.approve_risk(req.request_id)
        assert gate.reject(req.request_id, actor="user", reason="取消操作") is True

        final = gate.get_request(req.request_id)
        assert final.current_stage == GateStage.REJECTED.value

    def test_reject_from_executed(self, gate):
        req = gate.create_request("buy", "600519", 100)
        gate.approve_risk(req.request_id)
        gate.confirm_user(req.request_id)
        gate.mark_executed(req.request_id)
        assert gate.reject(req.request_id, reason="执行异常") is True

    def test_invalid_transition_skip_stage(self, gate):
        """Cannot skip from PENDING to USER_CONFIRMED."""
        req = gate.create_request("buy", "600519", 100)
        assert gate.confirm_user(req.request_id) is False

    def test_invalid_transition_from_terminal(self, gate):
        """Cannot transition from VERIFIED."""
        req = gate.create_request("buy", "600519", 100)
        gate.approve_risk(req.request_id)
        gate.confirm_user(req.request_id)
        gate.mark_executed(req.request_id)
        gate.mark_verified(req.request_id)

        # Try to reject after verified — should fail
        assert gate.reject(req.request_id) is False

    def test_invalid_transition_from_rejected(self, gate):
        """Cannot transition from REJECTED."""
        req = gate.create_request("buy", "600519", 100)
        gate.reject(req.request_id)
        assert gate.approve_risk(req.request_id) is False

    def test_nonexistent_request(self, gate):
        assert gate.approve_risk("nonexistent") is False
        assert gate.reject("nonexistent") is False


class TestGetRequest:
    """Tests for request retrieval."""

    def test_get_with_history(self, gate):
        req = gate.create_request("sell", "300750", 50, price=250.0)
        gate.approve_risk(req.request_id, notes="OK")
        gate.confirm_user(req.request_id, notes="确认")

        result = gate.get_request(req.request_id)
        assert result.symbol == "300750"
        assert result.trade_type == "sell"
        assert len(result.stage_history) == 3

        stages = [h.stage for h in result.stage_history]
        assert stages == [
            GateStage.PENDING.value,
            GateStage.RISK_APPROVED.value,
            GateStage.USER_CONFIRMED.value,
        ]

    def test_get_nonexistent(self, gate):
        assert gate.get_request("nonexistent") is None


class TestGetPendingRequests:
    """Tests for pending request queries."""

    def test_get_by_stage(self, gate):
        r1 = gate.create_request("buy", "600519", 100)
        r2 = gate.create_request("sell", "300750", 50)
        gate.approve_risk(r2.request_id)

        pending = gate.get_pending_requests(stage=GateStage.PENDING.value)
        assert len(pending) == 1
        assert pending[0].request_id == r1.request_id

        approved = gate.get_pending_requests(stage=GateStage.RISK_APPROVED.value)
        assert len(approved) == 1
        assert approved[0].request_id == r2.request_id

    def test_get_all_non_terminal(self, gate):
        r1 = gate.create_request("buy", "600519", 100)
        r2 = gate.create_request("sell", "300750", 50)
        gate.reject(r2.request_id, reason="取消")

        active = gate.get_pending_requests()
        assert len(active) == 1
        assert active[0].request_id == r1.request_id

    def test_limit(self, gate):
        for i in range(5):
            gate.create_request("buy", f"60000{i}", 100)
        results = gate.get_pending_requests(limit=2)
        assert len(results) == 2


class TestCount:
    """Tests for counting requests."""

    def test_count_all(self, gate):
        assert gate.count() == 0
        gate.create_request("buy", "600519", 100)
        gate.create_request("sell", "300750", 50)
        assert gate.count() == 2

    def test_count_by_stage(self, gate):
        r1 = gate.create_request("buy", "600519", 100)
        gate.create_request("sell", "300750", 50)
        gate.approve_risk(r1.request_id)

        assert gate.count(stage=GateStage.PENDING.value) == 1
        assert gate.count(stage=GateStage.RISK_APPROVED.value) == 1


class TestExecutionNotes:
    """Tests for execution-specific notes."""

    def test_mark_executed_with_id(self, gate):
        req = gate.create_request("buy", "600519", 100)
        gate.approve_risk(req.request_id)
        gate.confirm_user(req.request_id)
        gate.mark_executed(req.request_id, execution_id="T12345", notes="成功")

        result = gate.get_request(req.request_id)
        exec_record = result.stage_history[-1]
        assert "执行ID: T12345" in exec_record.notes
        assert "成功" in exec_record.notes

    def test_mark_verified_with_price(self, gate):
        req = gate.create_request("buy", "600519", 100, price=1800.0)
        gate.approve_risk(req.request_id)
        gate.confirm_user(req.request_id)
        gate.mark_executed(req.request_id)
        gate.mark_verified(req.request_id, actual_price=1800.5, notes="滑点正常")

        result = gate.get_request(req.request_id)
        verify_record = result.stage_history[-1]
        assert "实际成交价: 1800.5" in verify_record.notes
        assert "滑点正常" in verify_record.notes

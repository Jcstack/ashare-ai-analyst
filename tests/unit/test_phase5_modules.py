"""Phase 5 tests — Simulation-First Execution Flow & Audit.

Tests cover:
1. ImmutableAuditLog event type constants
2. ConfirmationGate auto_risk_check + audit integration
3. TradeService gate_request_id
4. Gate API endpoints
5. Executor per-step audit
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# =====================================================================
# 1. Audit Event Type Constants
# =====================================================================


class TestAuditEventTypes:
    """Tests for audit event type constants."""

    def test_event_constants_exist(self) -> None:
        from src.audit.immutable_log import (
            EVENT_AGENT_RESPONSE,
            EVENT_GATE_TRANSITION,
            EVENT_PIPELINE_EXECUTED,
            EVENT_STEP_EXECUTED,
            EVENT_TOOL_CALLED,
            EVENT_TRADE_EXECUTED,
            EVENT_TRADE_SIMULATED,
        )

        assert EVENT_PIPELINE_EXECUTED == "pipeline_executed"
        assert EVENT_STEP_EXECUTED == "step_executed"
        assert EVENT_GATE_TRANSITION == "gate_transition"
        assert EVENT_TRADE_SIMULATED == "trade_simulated"
        assert EVENT_TRADE_EXECUTED == "trade_executed"
        assert EVENT_TOOL_CALLED == "tool_called"
        assert EVENT_AGENT_RESPONSE == "agent_response"

    def test_audit_log_with_event_constants(self, tmp_path: Path) -> None:
        from src.audit.immutable_log import (
            EVENT_GATE_TRANSITION,
            EVENT_STEP_EXECUTED,
            ImmutableAuditLog,
            AuditConfig,
        )

        log = ImmutableAuditLog(AuditConfig(db_path=str(tmp_path / "audit.db")))
        entry1 = log.log(EVENT_STEP_EXECUTED, {"step": "data_qa"}, actor="data_qa")
        entry2 = log.log(
            EVENT_GATE_TRANSITION, {"from": "PENDING", "to": "RISK_APPROVED"}
        )
        assert entry1.entry_id
        assert entry2.entry_id
        assert log.count(EVENT_STEP_EXECUTED) == 1


# =====================================================================
# 3. ConfirmationGate — auto_risk_check + audit
# =====================================================================


class TestConfirmationGateAudit:
    """Tests for ConfirmationGate with audit log and auto_risk_check."""

    def _make_gate(self, tmp_path: Path, audit_log: Any = None) -> Any:
        from src.workflow.confirmation_gate import ConfirmationGate, GateConfig

        cfg = GateConfig(db_path=str(tmp_path / "gate.db"))
        return ConfirmationGate(config=cfg, audit_log=audit_log)

    def test_auto_risk_check_approves(self, tmp_path: Path) -> None:
        gate = self._make_gate(tmp_path)
        req = gate.create_request("buy", "600519", 100, price=50.0)
        assert req.current_stage == "PENDING"

        result = gate.auto_risk_check(req.request_id)
        assert result is True

        updated = gate.get_request(req.request_id)
        assert updated is not None
        assert updated.current_stage == "RISK_APPROVED"

    def test_auto_risk_check_with_provided_result_reject(self, tmp_path: Path) -> None:
        gate = self._make_gate(tmp_path)
        req = gate.create_request("buy", "600519", 100, price=50.0)

        result = gate.auto_risk_check(
            req.request_id,
            risk_result={"approved": False, "reason": "VaR exceeded"},
        )
        assert result is False

        updated = gate.get_request(req.request_id)
        assert updated is not None
        assert updated.current_stage == "REJECTED"

    def test_auto_risk_check_with_provided_result_approve(self, tmp_path: Path) -> None:
        gate = self._make_gate(tmp_path)
        req = gate.create_request("sell", "000001", 200, price=15.0)

        result = gate.auto_risk_check(
            req.request_id,
            risk_result={"approved": True, "notes": "Within limits"},
        )
        assert result is True

        updated = gate.get_request(req.request_id)
        assert updated is not None
        assert updated.current_stage == "RISK_APPROVED"

    def test_auto_risk_check_nonexistent_request(self, tmp_path: Path) -> None:
        gate = self._make_gate(tmp_path)
        result = gate.auto_risk_check("nonexistent")
        assert result is False

    def test_auto_risk_check_wrong_stage(self, tmp_path: Path) -> None:
        gate = self._make_gate(tmp_path)
        req = gate.create_request("buy", "600519", 100, price=50.0)
        gate.approve_risk(req.request_id)  # Move to RISK_APPROVED

        result = gate.auto_risk_check(req.request_id)
        assert result is False

    def test_audit_log_called_on_transition(self, tmp_path: Path) -> None:
        mock_audit = MagicMock()
        gate = self._make_gate(tmp_path, audit_log=mock_audit)

        req = gate.create_request("buy", "600519", 100, price=50.0)
        gate.approve_risk(req.request_id, notes="OK")

        # audit_log.log should have been called
        mock_audit.log.assert_called()
        call_args = mock_audit.log.call_args
        assert call_args[0][0] == "gate_transition"
        payload = call_args[1].get("payload") or call_args[0][1]
        assert payload["to_stage"] == "RISK_APPROVED"

    def test_audit_log_exception_doesnt_break_transition(self, tmp_path: Path) -> None:
        mock_audit = MagicMock()
        mock_audit.log.side_effect = RuntimeError("audit down")
        gate = self._make_gate(tmp_path, audit_log=mock_audit)

        req = gate.create_request("buy", "600519", 100, price=50.0)
        result = gate.approve_risk(req.request_id)
        assert result is True  # Transition still succeeds

    def test_full_gate_flow_with_audit(self, tmp_path: Path) -> None:
        mock_audit = MagicMock()
        gate = self._make_gate(tmp_path, audit_log=mock_audit)

        req = gate.create_request("buy", "600519", 100, price=1800.0)
        gate.auto_risk_check(req.request_id)
        gate.confirm_user(req.request_id)
        gate.mark_executed(req.request_id, execution_id="T123")
        gate.mark_verified(req.request_id, actual_price=1800.5)

        updated = gate.get_request(req.request_id)
        assert updated is not None
        assert updated.current_stage == "VERIFIED"

        # 4 transitions logged: RISK_APPROVED, USER_CONFIRMED, EXECUTED, VERIFIED
        assert mock_audit.log.call_count == 4

    def test_auto_risk_check_large_amount_has_warnings(self, tmp_path: Path) -> None:
        gate = self._make_gate(tmp_path)
        req = gate.create_request("buy", "600519", 200, price=1800.0)
        # Amount = 360,000 > 100,000 threshold

        result = gate.auto_risk_check(req.request_id)
        assert result is True

        updated = gate.get_request(req.request_id)
        assert updated is not None
        assert updated.current_stage == "RISK_APPROVED"
        # Check that stage history has warnings in notes
        risk_stage = [s for s in updated.stage_history if s.stage == "RISK_APPROVED"]
        assert len(risk_stage) == 1
        assert "10 万" in risk_stage[0].notes


# =====================================================================
# 4. TradeService gate_request_id
# =====================================================================


class TestTradeServiceGate:
    """Tests for TradeService with gate_request_id."""

    def test_execute_trade_with_gate_id(self, tmp_path: Path) -> None:
        from src.web.services.trade_service import TradeService

        svc = TradeService(db_path=tmp_path / "trades.db")
        trade = svc.execute_trade(
            symbol="600519",
            stock_name="贵州茅台",
            action="buy",
            shares=100,
            price=1800.0,
            gate_request_id="gate-abc123",
        )
        assert trade.gate_request_id == "gate-abc123"

    def test_execute_trade_without_gate_id(self, tmp_path: Path) -> None:
        from src.web.services.trade_service import TradeService

        svc = TradeService(db_path=tmp_path / "trades.db")
        trade = svc.execute_trade(
            symbol="600519",
            stock_name="贵州茅台",
            action="buy",
            shares=100,
            price=1800.0,
        )
        assert trade.gate_request_id is None

    def test_trade_history_includes_gate_id(self, tmp_path: Path) -> None:
        from src.web.services.trade_service import TradeService

        svc = TradeService(db_path=tmp_path / "trades.db")
        svc.execute_trade(
            symbol="600519",
            stock_name="贵州茅台",
            action="buy",
            shares=100,
            price=1800.0,
            gate_request_id="gate-xyz",
        )
        trades = svc.get_trade_history()
        assert len(trades) == 1
        assert trades[0].gate_request_id == "gate-xyz"


# =====================================================================
# 5. Gate API Endpoints
# =====================================================================


class TestGateEndpoints:
    """Tests for gate REST endpoints via FastAPI TestClient."""

    @pytest.fixture
    def client(self, tmp_path: Path) -> Any:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.web.routes.api_v1.trades import router
        from src.workflow.confirmation_gate import ConfirmationGate, GateConfig

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        gate = ConfirmationGate(config=GateConfig(db_path=str(tmp_path / "gate.db")))

        # Override dependencies
        from src.web.dependencies import get_confirmation_gate, get_trade_service
        from src.web.routes.api_v1.trades import require_market_open
        from src.web.services.trade_service import TradeService

        trade_svc = TradeService(db_path=tmp_path / "trades.db")

        app.dependency_overrides[get_confirmation_gate] = lambda: gate
        app.dependency_overrides[get_trade_service] = lambda: trade_svc
        app.dependency_overrides[require_market_open] = lambda: None

        return TestClient(app)

    def test_create_gate(self, client: Any) -> None:
        resp = client.post(
            "/api/v1/trades/gate",
            json={
                "trade_type": "buy",
                "symbol": "600519",
                "quantity": 100,
                "price": 50.0,
                "auto_risk_check": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "600519"
        assert data["current_stage"] == "RISK_APPROVED"  # auto risk check passed

    def test_create_gate_no_auto_risk(self, client: Any) -> None:
        resp = client.post(
            "/api/v1/trades/gate",
            json={
                "trade_type": "sell",
                "symbol": "000001",
                "quantity": 200,
                "auto_risk_check": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_stage"] == "PENDING"

    def test_confirm_gate(self, client: Any) -> None:
        # Create with auto risk check
        resp = client.post(
            "/api/v1/trades/gate",
            json={
                "trade_type": "buy",
                "symbol": "600519",
                "quantity": 100,
                "price": 50.0,
            },
        )
        request_id = resp.json()["request_id"]

        # Confirm
        resp = client.post(
            f"/api/v1/trades/gate/{request_id}/confirm",
            json={"feedback": "LGTM"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_stage"] == "USER_CONFIRMED"

    def test_get_gate(self, client: Any) -> None:
        resp = client.post(
            "/api/v1/trades/gate",
            json={
                "trade_type": "buy",
                "symbol": "600519",
                "quantity": 100,
                "price": 50.0,
            },
        )
        request_id = resp.json()["request_id"]

        resp = client.get(f"/api/v1/trades/gate/{request_id}")
        assert resp.status_code == 200
        assert resp.json()["request_id"] == request_id

    def test_get_gate_not_found(self, client: Any) -> None:
        resp = client.get("/api/v1/trades/gate/nonexistent")
        assert resp.status_code == 404

    def test_confirm_gate_wrong_stage(self, client: Any) -> None:
        # Create without auto risk check → stays PENDING
        resp = client.post(
            "/api/v1/trades/gate",
            json={
                "trade_type": "buy",
                "symbol": "600519",
                "quantity": 100,
                "auto_risk_check": False,
            },
        )
        request_id = resp.json()["request_id"]

        # Try to confirm from PENDING (should fail — needs RISK_APPROVED first)
        resp = client.post(
            f"/api/v1/trades/gate/{request_id}/confirm",
            json={},
        )
        assert resp.status_code == 400


# =====================================================================
# 6. Executor per-step audit
# =====================================================================


class TestExecutorAudit:
    """Tests for per-step audit logging in PipelineExecutor."""

    def test_step_audit_logged(self) -> None:
        from src.orchestration.executor import PipelineExecutor
        from src.orchestration.primitives import PipelineSpec, StepSpec

        # Mock agent
        mock_agent = MagicMock()
        mock_agent.name = "test_agent"

        result_msg = MagicMock()
        result_msg.result = '{"answer": "test"}'
        result_msg.tokens_used = 100
        result_msg.tool_calls_made = 2

        async def fake_execute(msg: Any) -> Any:
            return result_msg

        mock_agent.execute = fake_execute

        # Mock registry
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_agent
        mock_registry.list_agents.return_value = ["test_agent"]

        # Mock audit
        mock_audit = MagicMock()

        executor = PipelineExecutor(
            agent_registry=mock_registry,
            audit_log=mock_audit,
        )

        pipeline = PipelineSpec(
            name="test_pipeline",
            steps={
                "step1": StepSpec(
                    agent="test_agent",
                    task="do something",
                ),
            },
        )

        result = asyncio.run(executor.execute(pipeline, {"symbol": "600519"}))

        assert result.success
        # Should have 2 audit calls: step_executed + pipeline_executed
        assert mock_audit.log.call_count == 2

        # Check step_executed call
        step_call = mock_audit.log.call_args_list[0]
        assert step_call[0][0] == "step_executed"
        payload = step_call[1].get("payload") or step_call[0][1]
        assert payload["step_id"] == "step1"
        assert payload["agent"] == "test_agent"
        assert payload["success"] is True

        # Check pipeline_executed call
        pipeline_call = mock_audit.log.call_args_list[1]
        assert pipeline_call[0][0] == "pipeline_executed"

    def test_step_audit_exception_doesnt_break_execution(self) -> None:
        from src.orchestration.executor import PipelineExecutor
        from src.orchestration.primitives import PipelineSpec, StepSpec

        mock_agent = MagicMock()
        mock_agent.name = "agent_a"

        result_msg = MagicMock()
        result_msg.result = '{"ok": true}'
        result_msg.tokens_used = 50
        result_msg.tool_calls_made = 0

        async def fake_execute(msg: Any) -> Any:
            return result_msg

        mock_agent.execute = fake_execute

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_agent
        mock_registry.list_agents.return_value = ["agent_a"]

        # Audit log that raises
        mock_audit = MagicMock()
        mock_audit.log.side_effect = RuntimeError("audit crash")

        executor = PipelineExecutor(
            agent_registry=mock_registry,
            audit_log=mock_audit,
        )

        pipeline = PipelineSpec(
            name="test",
            steps={
                "s1": StepSpec(agent="agent_a", task="test"),
            },
        )

        # Should still succeed despite audit failure
        result = asyncio.run(executor.execute(pipeline, {}))
        # Pipeline still completes (audit failure is logged but not fatal)
        # Note: pipeline_executed audit also fails, but that's OK
        assert result.pipeline_name == "test"

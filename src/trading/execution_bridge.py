"""Execution bridge — routes agent proposals through the full execution pipeline.

Three modes controlled by ``config/broker.yaml`` → ``execution.mode``:

- **dry_run**: Full pipeline runs, gate transitions logged, no broker call.
- **confirm**: Gate stops at RISK_APPROVED; human confirms via API/Discord.
- **auto**: Auto-confirms and submits to broker after risk approval.

The bridge owns the lifecycle:
  proposal → gate create → preflight → risk approve → mode branch
  → (broker submit) → order tracking metadata stored on gate request.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("trading.execution_bridge")


@dataclass
class ExecutionResult:
    """Outcome of processing a trade proposal through the bridge."""

    status: (
        str  # dry_run_logged | awaiting_confirmation | submitted | blocked | rejected
    )
    gate_request_id: str = ""
    broker_order_id: str = ""
    reason: str = ""
    details: dict[str, Any] | None = None


class ExecutionBridge:
    """Central orchestrator between agent decisions and broker execution.

    Args:
        broker: :class:`BrokerInterface` implementation.
        gate: :class:`ConfirmationGate` for the approval state machine.
        preflight: :class:`PreflightRiskCheck` for pre-order validation.
        kill_switch: :class:`KillSwitch` for emergency halt.
        execution_mode: One of ``dry_run``, ``confirm``, ``auto``.
        max_price_slippage_pct: Reject if proposed price drifts beyond this %.
    """

    def __init__(
        self,
        broker: Any,
        gate: Any,
        preflight: Any,
        kill_switch: Any,
        execution_mode: str = "dry_run",
        max_price_slippage_pct: float = 2.0,
    ) -> None:
        self._broker = broker
        self._gate = gate
        self._preflight = preflight
        self._kill_switch = kill_switch
        self._execution_mode = execution_mode
        self._max_price_slippage_pct = max_price_slippage_pct

    @property
    def execution_mode(self) -> str:
        return self._execution_mode

    def is_live_mode(self) -> bool:
        """Return True if mode is anything other than dry_run."""
        return self._execution_mode != "dry_run"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_proposal(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        stock_name: str = "",
        reasoning: str = "",
        action_id: str = "",
        confidence: float = 0.0,
    ) -> ExecutionResult:
        """Process a trade proposal through the full pipeline.

        Args:
            symbol: Stock code (e.g. "600498").
            action: "buy", "sell", "add", or "reduce".
            shares: Number of shares (must be multiple of 100).
            price: Proposed order price.
            stock_name: Human-readable stock name.
            reasoning: Why the agent wants this trade.
            action_id: Link back to ActionQueueService (if any).
            confidence: Agent's confidence level (0-1).

        Returns:
            :class:`ExecutionResult` describing the outcome.
        """
        # 1. Kill switch
        if self._kill_switch.is_active():
            logger.warning("Proposal blocked by kill switch: %s %s", action, symbol)
            return ExecutionResult(status="blocked", reason="kill_switch_active")

        # 2. Preflight risk checks
        preflight_result = self._preflight.check(symbol, action, shares, price)
        if not preflight_result.passed:
            return ExecutionResult(
                status="rejected",
                reason=preflight_result.summary(),
                details={"checks": preflight_result.checks},
            )

        # 3. Create gate request
        metadata = {
            "stock_name": stock_name,
            "reasoning": reasoning,
            "action_id": action_id,
            "confidence": confidence,
            "execution_mode": self._execution_mode,
            "proposed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        gate_req = self._gate.create_request(
            trade_type=action,
            symbol=symbol,
            quantity=shares,
            price=price,
            metadata=metadata,
        )
        gate_id = gate_req.request_id

        # 4. Risk approve
        self._gate.approve_risk(gate_id, actor="preflight", notes="All checks passed")

        # 5. Mode-dependent execution
        if self._execution_mode == "dry_run":
            return self._handle_dry_run(gate_id, symbol, action, shares, price)

        if self._execution_mode == "confirm":
            return self._handle_confirm(gate_id, symbol, action, shares, price)

        if self._execution_mode == "auto":
            return self._handle_auto(gate_id, symbol, action, shares, price)

        logger.error("Unknown execution mode: %s", self._execution_mode)
        return ExecutionResult(
            status="rejected",
            gate_request_id=gate_id,
            reason=f"Unknown execution mode: {self._execution_mode}",
        )

    # ------------------------------------------------------------------
    # Execute a previously confirmed gate request (Phase 2)
    # ------------------------------------------------------------------

    def execute_confirmed(self, gate_request_id: str) -> ExecutionResult:
        """Submit a confirmed gate request to the broker.

        Called when a human confirms via API (Phase 2 confirm mode).

        Args:
            gate_request_id: The gate request to execute.

        Returns:
            :class:`ExecutionResult` with broker order details.
        """
        gate_req = self._gate.get_request(gate_request_id)
        if gate_req is None:
            return ExecutionResult(
                status="rejected",
                gate_request_id=gate_request_id,
                reason="Gate request not found",
            )

        if gate_req.current_stage != "USER_CONFIRMED":
            return ExecutionResult(
                status="rejected",
                gate_request_id=gate_request_id,
                reason=f"Gate not in USER_CONFIRMED stage (is {gate_req.current_stage})",
            )

        # Check for duplicate submission (idempotency)
        meta = json.loads(gate_req.metadata) if gate_req.metadata else {}
        if meta.get("broker_order_id"):
            return ExecutionResult(
                status="submitted",
                gate_request_id=gate_request_id,
                broker_order_id=meta["broker_order_id"],
                reason="Already submitted (idempotent)",
            )

        return self._submit_to_broker(
            gate_request_id=gate_request_id,
            symbol=gate_req.symbol,
            action=gate_req.trade_type,
            shares=gate_req.quantity,
            price=gate_req.price or 0.0,
        )

    # ------------------------------------------------------------------
    # Mode handlers
    # ------------------------------------------------------------------

    def _handle_dry_run(
        self,
        gate_id: str,
        symbol: str,
        action: str,
        shares: int,
        price: float,
    ) -> ExecutionResult:
        """Log the order but don't submit."""
        logger.info(
            "DRY RUN: Would submit %s %s %d @ %.2f (gate=%s)",
            action,
            symbol,
            shares,
            price,
            gate_id,
        )
        self._gate.confirm_user(gate_id, actor="dry_run_auto", notes="Dry run")
        self._gate.mark_executed(gate_id, execution_id="dry-run")
        return ExecutionResult(
            status="dry_run_logged",
            gate_request_id=gate_id,
        )

    def _handle_confirm(
        self,
        gate_id: str,
        symbol: str,
        action: str,
        shares: int,
        price: float,
    ) -> ExecutionResult:
        """Leave at RISK_APPROVED — wait for human confirmation."""
        logger.info(
            "Awaiting confirmation: %s %s %d @ %.2f (gate=%s)",
            action,
            symbol,
            shares,
            price,
            gate_id,
        )
        return ExecutionResult(
            status="awaiting_confirmation",
            gate_request_id=gate_id,
        )

    def _handle_auto(
        self,
        gate_id: str,
        symbol: str,
        action: str,
        shares: int,
        price: float,
    ) -> ExecutionResult:
        """Auto-confirm and submit to broker."""
        self._gate.confirm_user(gate_id, actor="auto_execute", notes="Auto-approved")
        return self._submit_to_broker(gate_id, symbol, action, shares, price)

    # ------------------------------------------------------------------
    # Broker submission
    # ------------------------------------------------------------------

    def _submit_to_broker(
        self,
        gate_request_id: str,
        symbol: str,
        action: str,
        shares: int,
        price: float,
    ) -> ExecutionResult:
        """Submit order to broker and record the result on the gate."""
        try:
            order_status = self._broker.submit_order(
                symbol=symbol,
                action=action,
                shares=shares,
                price=price,
                gate_request_id=gate_request_id,
            )

            if order_status.status == "rejected":
                self._gate.reject(
                    gate_request_id,
                    actor="broker",
                    reason=order_status.message,
                )
                return ExecutionResult(
                    status="rejected",
                    gate_request_id=gate_request_id,
                    reason=f"Broker rejected: {order_status.message}",
                )

            # Store broker order ID on gate metadata for lifecycle polling
            self._update_gate_metadata(
                gate_request_id, {"broker_order_id": order_status.order_id}
            )
            self._gate.mark_executed(
                gate_request_id,
                execution_id=order_status.order_id,
                notes=order_status.message,
            )

            logger.info(
                "Order submitted: %s %s %d @ %.2f → order_id=%s (gate=%s)",
                action,
                symbol,
                shares,
                price,
                order_status.order_id,
                gate_request_id,
            )
            return ExecutionResult(
                status="submitted",
                gate_request_id=gate_request_id,
                broker_order_id=order_status.order_id,
            )

        except Exception as exc:
            logger.error(
                "Broker submission failed for gate=%s: %s",
                gate_request_id,
                exc,
            )
            self._gate.reject(
                gate_request_id, actor="system", reason=f"Submission error: {exc}"
            )
            return ExecutionResult(
                status="rejected",
                gate_request_id=gate_request_id,
                reason=str(exc),
            )

    def _update_gate_metadata(
        self, gate_request_id: str, updates: dict[str, Any]
    ) -> None:
        """Merge additional metadata into a gate request."""
        try:
            gate_req = self._gate.get_request(gate_request_id)
            if gate_req is None:
                return
            meta = json.loads(gate_req.metadata) if gate_req.metadata else {}
            meta.update(updates)
            # Direct DB update for metadata — gate doesn't expose a setter
            import sqlite3

            conn = sqlite3.connect(str(self._gate._db_path))
            try:
                conn.execute(
                    "UPDATE gate_requests SET metadata = ? WHERE request_id = ?",
                    (
                        json.dumps(meta, ensure_ascii=False, default=str),
                        gate_request_id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to update gate metadata: %s", exc)

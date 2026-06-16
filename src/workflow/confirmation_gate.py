"""Confirmation gate — multi-stage approval workflow for trade decisions.

Part of v19.0 Production Hardening.

Implements a state machine for trade execution approval:
PENDING → RISK_APPROVED → USER_CONFIRMED → EXECUTED → VERIFIED

Any stage can reject, which transitions to REJECTED (terminal).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class GateStage(str, Enum):
    """Stages of the confirmation workflow."""

    PENDING = "PENDING"
    RISK_APPROVED = "RISK_APPROVED"
    USER_CONFIRMED = "USER_CONFIRMED"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# Valid transitions
_TRANSITIONS: dict[GateStage, list[GateStage]] = {
    GateStage.PENDING: [GateStage.RISK_APPROVED, GateStage.REJECTED],
    GateStage.RISK_APPROVED: [GateStage.USER_CONFIRMED, GateStage.REJECTED],
    GateStage.USER_CONFIRMED: [GateStage.EXECUTED, GateStage.REJECTED],
    GateStage.EXECUTED: [GateStage.VERIFIED, GateStage.REJECTED],
    GateStage.VERIFIED: [],  # Terminal
    GateStage.REJECTED: [],  # Terminal
}


@dataclass
class StageRecord:
    """Record of a stage transition."""

    stage: str
    actor: str  # "risk_agent", "user", "system"
    timestamp: str  # ISO datetime
    notes: str = ""


@dataclass
class GateRequest:
    """A confirmation gate request (trade decision awaiting approval)."""

    request_id: str
    trade_type: str  # "buy", "sell", "add", "reduce"
    symbol: str
    quantity: int
    price: float | None  # None = market order
    current_stage: str
    created_at: str
    updated_at: str
    thread_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    stage_history: list[StageRecord] = field(default_factory=list)


@dataclass
class GateConfig:
    """Configuration for confirmation gates."""

    db_path: str = "data/audit.db"
    # Require risk approval for all trades
    require_risk_approval: bool = True
    # Auto-approve trades below this amount (0 = require approval for all)
    auto_approve_threshold: float = 0.0
    # Timeout in minutes before a pending request expires
    pending_timeout_minutes: int = 60


class ConfirmationGate:
    """Multi-stage approval workflow for trade decisions.

    State machine:
        PENDING → RISK_APPROVED → USER_CONFIRMED → EXECUTED → VERIFIED
                ↘                ↘                ↘           ↘
                  REJECTED        REJECTED        REJECTED    REJECTED

    Usage:
        gate = ConfirmationGate()
        req = gate.create_request("buy", "600519", 100, price=1800.0)
        gate.approve_risk(req.request_id, "risk_agent", notes="VaR within limits")
        gate.confirm_user(req.request_id, "user")
        gate.mark_executed(req.request_id, execution_id="T12345")
        gate.mark_verified(req.request_id, actual_price=1800.5)
    """

    def __init__(
        self,
        config: GateConfig | None = None,
        audit_log: Any | None = None,
    ):
        self.config = config or GateConfig()
        self._db_path = Path(self.config.db_path)
        self._audit_log = audit_log
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create database tables if needed."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gate_requests (
                    request_id TEXT PRIMARY KEY,
                    trade_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL,
                    current_stage TEXT NOT NULL DEFAULT 'PENDING',
                    thread_id TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gate_stage_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (request_id) REFERENCES gate_requests(request_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_gate_stage
                ON gate_requests(current_stage)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def create_request(
        self,
        trade_type: str,
        symbol: str,
        quantity: int,
        price: float | None = None,
        thread_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> GateRequest:
        """Create a new confirmation gate request.

        Starts in PENDING stage. If auto-approve is configured and
        the trade value is below threshold, skips risk approval.
        """
        request_id = str(uuid.uuid4())[:12]
        now = datetime.now().isoformat()
        meta = metadata or {}

        # Check auto-approve
        initial_stage = GateStage.PENDING
        if not self.config.require_risk_approval:
            initial_stage = GateStage.RISK_APPROVED

        if (
            self.config.auto_approve_threshold > 0
            and price is not None
            and price * quantity <= self.config.auto_approve_threshold
        ):
            initial_stage = GateStage.RISK_APPROVED

        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                """
                INSERT INTO gate_requests
                    (request_id, trade_type, symbol, quantity, price,
                     current_stage, thread_id, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    trade_type,
                    symbol,
                    quantity,
                    price,
                    initial_stage.value,
                    thread_id,
                    json.dumps(meta, ensure_ascii=False, default=str),
                    now,
                    now,
                ),
            )
            # Record initial stage
            conn.execute(
                """
                INSERT INTO gate_stage_history
                    (request_id, stage, actor, notes, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (request_id, initial_stage.value, "system", "请求创建", now),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info(
            "Gate request %s: %s %s x%d @ %s → %s",
            request_id,
            trade_type,
            symbol,
            quantity,
            price,
            initial_stage.value,
        )

        return GateRequest(
            request_id=request_id,
            trade_type=trade_type,
            symbol=symbol,
            quantity=quantity,
            price=price,
            current_stage=initial_stage.value,
            created_at=now,
            updated_at=now,
            thread_id=thread_id,
            metadata=meta,
            stage_history=[
                StageRecord(
                    stage=initial_stage.value,
                    actor="system",
                    timestamp=now,
                    notes="请求创建",
                )
            ],
        )

    def approve_risk(
        self,
        request_id: str,
        actor: str = "risk_agent",
        notes: str = "",
    ) -> bool:
        """Risk agent approves the trade request.

        Transitions: PENDING → RISK_APPROVED
        """
        return self._transition(request_id, GateStage.RISK_APPROVED, actor, notes)

    def confirm_user(
        self,
        request_id: str,
        actor: str = "user",
        notes: str = "",
    ) -> bool:
        """User confirms the trade request.

        Transitions: RISK_APPROVED → USER_CONFIRMED
        """
        return self._transition(request_id, GateStage.USER_CONFIRMED, actor, notes)

    def mark_executed(
        self,
        request_id: str,
        execution_id: str = "",
        notes: str = "",
    ) -> bool:
        """Mark trade as executed.

        Transitions: USER_CONFIRMED → EXECUTED
        """
        extra_notes = notes
        if execution_id:
            extra_notes = f"执行ID: {execution_id}. {notes}".strip()
        return self._transition(request_id, GateStage.EXECUTED, "system", extra_notes)

    def mark_verified(
        self,
        request_id: str,
        actual_price: float | None = None,
        notes: str = "",
    ) -> bool:
        """Mark trade as verified (post-execution check).

        Transitions: EXECUTED → VERIFIED
        """
        extra_notes = notes
        if actual_price is not None:
            extra_notes = f"实际成交价: {actual_price}. {notes}".strip()
        return self._transition(request_id, GateStage.VERIFIED, "system", extra_notes)

    def reject(
        self,
        request_id: str,
        actor: str = "system",
        reason: str = "",
    ) -> bool:
        """Reject the trade request at any stage.

        Transitions: any non-terminal → REJECTED
        """
        return self._transition(request_id, GateStage.REJECTED, actor, reason)

    def auto_risk_check(
        self,
        request_id: str,
        risk_result: dict[str, Any] | None = None,
    ) -> bool:
        """Run automated risk check and transition accordingly.

        If risk_result is provided, uses it directly. Otherwise performs
        basic risk checks (position size, trade amount).

        Returns True if risk approved, False if rejected.
        """
        req = self.get_request(request_id)
        if req is None:
            logger.warning("auto_risk_check: request %s not found", request_id)
            return False

        if req.current_stage != GateStage.PENDING.value:
            logger.warning(
                "auto_risk_check: request %s not in PENDING (is %s)",
                request_id,
                req.current_stage,
            )
            return False

        # Use provided risk result or run basic checks
        if risk_result:
            approved = risk_result.get("approved", False)
            notes = risk_result.get("notes", "")
            if not approved:
                reason = risk_result.get("reason", "风险检查未通过")
                self.reject(request_id, actor="risk_agent", reason=reason)
                return False
            return self.approve_risk(request_id, actor="risk_agent", notes=notes)

        # Basic built-in risk checks
        warnings: list[str] = []
        amount = (req.price or 0) * req.quantity
        if amount > 100_000:
            warnings.append(f"交易金额 {amount:.0f} 超过 10 万")
        if req.quantity > 10_000:
            warnings.append(f"交易数量 {req.quantity} 超过 1 万股")

        # Auto-approve threshold check
        if (
            self.config.auto_approve_threshold > 0
            and amount <= self.config.auto_approve_threshold
        ):
            return self.approve_risk(
                request_id,
                actor="risk_agent",
                notes=f"自动审批: 金额 {amount:.0f} 低于阈值",
            )

        # Pass with warnings
        notes = "; ".join(warnings) if warnings else "风险检查通过"
        return self.approve_risk(request_id, actor="risk_agent", notes=notes)

    def get_request(self, request_id: str) -> GateRequest | None:
        """Get a specific gate request with full stage history."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM gate_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if not row:
                return None

            history_rows = conn.execute(
                "SELECT * FROM gate_stage_history WHERE request_id = ? ORDER BY id ASC",
                (request_id,),
            ).fetchall()

            try:
                meta = json.loads(row["metadata"])
            except (json.JSONDecodeError, TypeError):
                meta = {}

            return GateRequest(
                request_id=row["request_id"],
                trade_type=row["trade_type"],
                symbol=row["symbol"],
                quantity=row["quantity"],
                price=row["price"],
                current_stage=row["current_stage"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                thread_id=row["thread_id"],
                metadata=meta,
                stage_history=[
                    StageRecord(
                        stage=h["stage"],
                        actor=h["actor"],
                        timestamp=h["timestamp"],
                        notes=h["notes"],
                    )
                    for h in history_rows
                ],
            )
        finally:
            conn.close()

    def get_pending_requests(
        self,
        stage: str | None = None,
        limit: int = 20,
    ) -> list[GateRequest]:
        """Get requests at a specific stage (or all non-terminal)."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            if stage:
                rows = conn.execute(
                    "SELECT * FROM gate_requests WHERE current_stage = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (stage, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM gate_requests "
                    "WHERE current_stage NOT IN ('VERIFIED', 'REJECTED') "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()

            results = []
            for row in rows:
                try:
                    meta = json.loads(row["metadata"])
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                results.append(
                    GateRequest(
                        request_id=row["request_id"],
                        trade_type=row["trade_type"],
                        symbol=row["symbol"],
                        quantity=row["quantity"],
                        price=row["price"],
                        current_stage=row["current_stage"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                        thread_id=row["thread_id"],
                        metadata=meta,
                    )
                )
            return results
        finally:
            conn.close()

    def count(self, stage: str | None = None) -> int:
        """Count gate requests."""
        conn = sqlite3.connect(str(self._db_path))
        try:
            if stage:
                row = conn.execute(
                    "SELECT COUNT(*) FROM gate_requests WHERE current_stage = ?",
                    (stage,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM gate_requests").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def _transition(
        self,
        request_id: str,
        target_stage: GateStage,
        actor: str,
        notes: str,
    ) -> bool:
        """Execute a state transition."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT current_stage FROM gate_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if not row:
                logger.warning("Gate request %s not found", request_id)
                return False

            current = GateStage(row["current_stage"])
            valid_targets = _TRANSITIONS.get(current, [])

            if target_stage not in valid_targets:
                logger.warning(
                    "Invalid transition: %s → %s for request %s",
                    current.value,
                    target_stage.value,
                    request_id,
                )
                return False

            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE gate_requests SET current_stage = ?, updated_at = ? "
                "WHERE request_id = ?",
                (target_stage.value, now, request_id),
            )
            conn.execute(
                """
                INSERT INTO gate_stage_history
                    (request_id, stage, actor, notes, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (request_id, target_stage.value, actor, notes, now),
            )
            conn.commit()

            logger.info(
                "Gate %s: %s → %s by %s",
                request_id,
                current.value,
                target_stage.value,
                actor,
            )

            # Audit log integration
            if self._audit_log:
                try:
                    self._audit_log.log(
                        "gate_transition",
                        payload={
                            "request_id": request_id,
                            "from_stage": current.value,
                            "to_stage": target_stage.value,
                            "actor": actor,
                            "notes": notes,
                        },
                        actor=actor,
                    )
                except Exception:
                    logger.debug("Failed to write gate audit log", exc_info=True)

            return True
        finally:
            conn.close()

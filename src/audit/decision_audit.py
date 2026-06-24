"""Decision audit trail — full evidence chain from signal to outcome.

Records the complete reasoning path: signal → market snapshot →
debate record → LLM prompt/response → final decision → outcome.

Uses ImmutableAuditLog for tamper-proof storage with SHA-256 hash chain.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Event types for the decision chain
EVENT_SIGNAL_RECEIVED = "decision.signal_received"
EVENT_DEBATE_COMPLETED = "decision.debate_completed"
EVENT_LLM_EXCHANGE = "decision.llm_exchange"
EVENT_DECISION_MADE = "decision.decision_made"


class DecisionAuditTrail:
    """Records the complete decision evidence chain.

    Each decision gets a ``chain_id`` that links all evidence:
    signal → debate → LLM exchanges → final decision.

    Backed by :class:`ImmutableAuditLog` for tamper-proof storage.
    """

    def __init__(self, audit_log: Any = None) -> None:
        self._log = audit_log
        if not self._log:
            self._log = self._default_log()

    @staticmethod
    def _default_log() -> Any:
        try:
            from src.audit.immutable_log import AuditConfig, ImmutableAuditLog

            config = AuditConfig(
                db_path="data/decision_audit.db",
                capture_events=[
                    EVENT_SIGNAL_RECEIVED,
                    EVENT_DEBATE_COMPLETED,
                    EVENT_LLM_EXCHANGE,
                    EVENT_DECISION_MADE,
                ],
            )
            return ImmutableAuditLog(config=config)
        except Exception as exc:
            logger.warning("DecisionAuditTrail: audit log unavailable: %s", exc)
            return None

    def new_chain(self) -> str:
        """Create a new chain_id for linking decision events."""
        return str(uuid.uuid4())[:12]

    def record_signal(
        self,
        chain_id: str,
        signal: dict[str, Any],
    ) -> None:
        """Record incoming signal as the start of the evidence chain."""
        if not self._log:
            return
        try:
            self._log.log(
                EVENT_SIGNAL_RECEIVED,
                payload={
                    "chain_id": chain_id,
                    "symbol": signal.get("symbol", ""),
                    "source": signal.get("source", ""),
                    "direction": signal.get("direction", ""),
                    "confidence": signal.get("confidence", 0),
                    "reason": signal.get("reason", "")[:200],
                },
                actor="decision_pipeline",
            )
        except Exception as exc:
            logger.debug("Audit record_signal failed: %s", exc)

    def record_debate(
        self,
        chain_id: str,
        debate_record: dict[str, Any],
    ) -> None:
        """Record the debate with all arguments and verdict."""
        if not self._log:
            return
        try:
            # Compress arguments to key claims only
            bull_claims = [
                a.get("claim", "") for a in debate_record.get("bull_arguments", [])
            ]
            bear_claims = [
                a.get("claim", "") for a in debate_record.get("bear_arguments", [])
            ]
            verdict = debate_record.get("verdict") or {}

            self._log.log(
                EVENT_DEBATE_COMPLETED,
                payload={
                    "chain_id": chain_id,
                    "debate_id": debate_record.get("debate_id", ""),
                    "symbol": debate_record.get("symbol", ""),
                    "bull_claims": bull_claims,
                    "bear_claims": bear_claims,
                    "verdict_action": verdict.get("action", ""),
                    "verdict_reasoning": verdict.get("reasoning", "")[:300],
                    "risk_veto": debate_record.get("risk_veto", False),
                    "final_action": debate_record.get("final_action", ""),
                },
                actor="debate_engine",
            )
        except Exception as exc:
            logger.debug("Audit record_debate failed: %s", exc)

    def record_llm_exchange(
        self,
        chain_id: str,
        prompt_summary: str,
        response_summary: str,
        model: str = "",
        cost_usd: float = 0.0,
    ) -> None:
        """Record an LLM prompt/response exchange."""
        if not self._log:
            return
        try:
            self._log.log(
                EVENT_LLM_EXCHANGE,
                payload={
                    "chain_id": chain_id,
                    "prompt_preview": prompt_summary[:500],
                    "response_preview": response_summary[:500],
                    "model": model,
                    "cost_usd": cost_usd,
                },
                actor="llm_agent",
            )
        except Exception as exc:
            logger.debug("Audit record_llm_exchange failed: %s", exc)

    def record_decision(
        self,
        chain_id: str,
        proposal: dict[str, Any] | None,
        rejection_reason: str = "",
    ) -> None:
        """Record the final decision (proposal or rejection)."""
        if not self._log:
            return
        try:
            if proposal:
                payload = {
                    "chain_id": chain_id,
                    "decided": True,
                    "symbol": proposal.get("symbol", ""),
                    "action": proposal.get("action", ""),
                    "confidence": proposal.get("confidence", 0),
                    "entry_price": proposal.get("entry_price", 0),
                    "quantity": proposal.get("quantity", 0),
                }
            else:
                payload = {
                    "chain_id": chain_id,
                    "decided": False,
                    "rejection_reason": rejection_reason[:200],
                }

            self._log.log(
                EVENT_DECISION_MADE,
                payload=payload,
                actor="decision_pipeline",
            )
        except Exception as exc:
            logger.debug("Audit record_decision failed: %s", exc)

    def get_chain(self, chain_id: str) -> list[dict[str, Any]]:
        """Retrieve all events for a decision chain."""
        if not self._log:
            return []
        try:
            import sqlite3

            conn = sqlite3.connect(str(self._log._db_path))
            try:
                rows = conn.execute(
                    "SELECT * FROM audit_log WHERE payload LIKE ? ORDER BY rowid",
                    (f'%"chain_id": "{chain_id}"%',),
                ).fetchall()
                return [
                    {
                        "entry_id": r[0],
                        "timestamp": r[1],
                        "event_type": r[2],
                        "actor": r[3],
                        "payload": json.loads(r[4]) if r[4] else {},
                    }
                    for r in rows
                ]
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("Audit get_chain failed: %s", exc)
            return []

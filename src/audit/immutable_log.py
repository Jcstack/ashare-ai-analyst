"""Immutable audit log — hash-chain tamper-proof event recording.

Part of v19.0 Production Hardening.

Every audit entry contains a SHA-256 hash of (prev_hash + payload),
forming an append-only chain. On startup the chain integrity can be
verified by re-computing hashes from the genesis entry.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_GENESIS_HASH = "0" * 64  # SHA-256 zero hash for the first entry

# ── Standard event types ─────────────────────────────────────────
# Use these constants instead of raw strings for consistency.

EVENT_PIPELINE_EXECUTED = "pipeline_executed"
EVENT_STEP_EXECUTED = "step_executed"
EVENT_GATE_TRANSITION = "gate_transition"
EVENT_TRADE_SIMULATED = "trade_simulated"
EVENT_TRADE_EXECUTED = "trade_executed"
EVENT_TOOL_CALLED = "tool_called"
EVENT_AGENT_RESPONSE = "agent_response"

# ── v20.0 Phase 7: Market Intelligence signal event types ────────
EVENT_SIGNAL_PUBLISHED = "signal_published"
EVENT_SIGNAL_CONFIRMED = "signal_confirmed"
EVENT_SIGNAL_BLOCKED = "signal_blocked"
EVENT_NOTIFICATION_DISPATCHED = "notification_dispatched"
EVENT_NOTIFICATION_SUPPRESSED = "notification_suppressed"
EVENT_PHASE_TRANSITION = "phase_transition"

# All signal-related event types (used by admin audit endpoint)
SIGNAL_EVENT_TYPES = frozenset(
    {
        EVENT_SIGNAL_PUBLISHED,
        EVENT_SIGNAL_CONFIRMED,
        EVENT_SIGNAL_BLOCKED,
        EVENT_NOTIFICATION_DISPATCHED,
        EVENT_NOTIFICATION_SUPPRESSED,
        EVENT_PHASE_TRANSITION,
    }
)


@dataclass
class AuditEntry:
    """A single audit log entry."""

    entry_id: str
    timestamp: str  # ISO datetime
    event_type: str  # e.g. "trade_executed", "tool_called", "agent_response"
    actor: str  # "system", "user", agent name
    payload: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = ""
    entry_hash: str = ""


@dataclass
class IntegrityReport:
    """Result of chain integrity verification."""

    valid: bool
    total_entries: int
    verified_entries: int
    first_invalid_id: str | None = None
    error_message: str = ""


@dataclass
class AuditConfig:
    """Configuration for audit logging."""

    db_path: str = "data/audit.db"
    # Maximum entries before rotation (0 = unlimited)
    max_entries: int = 0
    # Event types to capture (empty = capture all)
    capture_events: list[str] = field(default_factory=list)


class ImmutableAuditLog:
    """Append-only hash-chain audit log.

    Each entry's hash = SHA-256(prev_hash + json(payload)).
    Chain starts from a genesis entry with prev_hash = "000...0".

    Provides:
    - log(): Append a new entry to the chain
    - verify_integrity(): Walk the chain and verify all hashes
    - get_entries(): Query entries with filtering
    - get_entry(): Get a specific entry by ID
    - count(): Count total entries
    """

    def __init__(self, config: AuditConfig | None = None):
        self.config = config or AuditConfig()
        self._db_path = Path(self.config.db_path)
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create database and tables if needed."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    entry_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system',
                    payload TEXT NOT NULL DEFAULT '{}',
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_event_type
                ON audit_log(event_type)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                ON audit_log(timestamp)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def log(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> AuditEntry:
        """Append a new entry to the audit chain.

        Args:
            event_type: Type of event (e.g. "trade_executed").
            payload: Event data dictionary.
            actor: Who triggered the event.

        Returns:
            The created AuditEntry with computed hash.
        """
        # Check capture filter
        if self.config.capture_events and event_type not in self.config.capture_events:
            # Event type not in capture list — skip silently
            entry = AuditEntry(
                entry_id="",
                timestamp=datetime.now().isoformat(),
                event_type=event_type,
                actor=actor,
                payload=payload or {},
            )
            return entry

        payload = payload or {}
        entry_id = str(uuid.uuid4())[:12]
        timestamp = datetime.now().isoformat()

        conn = sqlite3.connect(str(self._db_path))
        try:
            # Get the last entry's hash (or genesis hash)
            row = conn.execute(
                "SELECT entry_hash FROM audit_log ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            prev_hash = row[0] if row else _GENESIS_HASH

            # Compute this entry's hash
            entry_hash = _compute_hash(prev_hash, payload)

            conn.execute(
                """
                INSERT INTO audit_log
                    (entry_id, timestamp, event_type, actor, payload, prev_hash, entry_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    timestamp,
                    event_type,
                    actor,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    prev_hash,
                    entry_hash,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        entry = AuditEntry(
            entry_id=entry_id,
            timestamp=timestamp,
            event_type=event_type,
            actor=actor,
            payload=payload,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )

        logger.debug(
            "Audit: %s [%s] by %s — %s",
            event_type,
            entry_id,
            actor,
            entry_hash[:16],
        )
        return entry

    def verify_integrity(self) -> IntegrityReport:
        """Walk the entire chain and verify hash consistency.

        Returns:
            IntegrityReport with verification results.
        """
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY rowid ASC").fetchall()

            if not rows:
                return IntegrityReport(
                    valid=True,
                    total_entries=0,
                    verified_entries=0,
                )

            expected_prev = _GENESIS_HASH
            verified = 0

            for row in rows:
                # Check prev_hash chain
                if row["prev_hash"] != expected_prev:
                    return IntegrityReport(
                        valid=False,
                        total_entries=len(rows),
                        verified_entries=verified,
                        first_invalid_id=row["entry_id"],
                        error_message=(
                            f"链断裂: entry {row['entry_id']} 的 prev_hash 不匹配"
                        ),
                    )

                # Re-compute hash and verify
                try:
                    payload = json.loads(row["payload"])
                except (json.JSONDecodeError, TypeError):
                    payload = {}

                expected_hash = _compute_hash(row["prev_hash"], payload)
                if row["entry_hash"] != expected_hash:
                    return IntegrityReport(
                        valid=False,
                        total_entries=len(rows),
                        verified_entries=verified,
                        first_invalid_id=row["entry_id"],
                        error_message=(
                            f"哈希篡改: entry {row['entry_id']} 的 hash 不匹配"
                        ),
                    )

                expected_prev = row["entry_hash"]
                verified += 1

            return IntegrityReport(
                valid=True,
                total_entries=len(rows),
                verified_entries=verified,
            )
        finally:
            conn.close()

    def get_entries(
        self,
        event_type: str | None = None,
        actor: str | None = None,
        limit: int = 50,
        since: str | None = None,
    ) -> list[AuditEntry]:
        """Query audit entries with optional filtering.

        Args:
            event_type: Filter by event type.
            actor: Filter by actor.
            limit: Maximum entries to return.
            since: ISO datetime — only entries after this time.

        Returns:
            List of AuditEntry sorted by time descending.
        """
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            where_clauses = ["1=1"]
            params: list[Any] = []

            if event_type:
                where_clauses.append("event_type = ?")
                params.append(event_type)
            if actor:
                where_clauses.append("actor = ?")
                params.append(actor)
            if since:
                where_clauses.append("timestamp >= ?")
                params.append(since)

            where = " AND ".join(where_clauses)
            rows = conn.execute(
                f"SELECT * FROM audit_log WHERE {where} "  # noqa: S608
                f"ORDER BY rowid DESC LIMIT ?",
                [*params, limit],
            ).fetchall()

            results = []
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                results.append(
                    AuditEntry(
                        entry_id=row["entry_id"],
                        timestamp=row["timestamp"],
                        event_type=row["event_type"],
                        actor=row["actor"],
                        payload=payload,
                        prev_hash=row["prev_hash"],
                        entry_hash=row["entry_hash"],
                    )
                )
            return results
        finally:
            conn.close()

    def get_entry(self, entry_id: str) -> AuditEntry | None:
        """Get a specific audit entry by ID."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM audit_log WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if not row:
                return None

            try:
                payload = json.loads(row["payload"])
            except (json.JSONDecodeError, TypeError):
                payload = {}

            return AuditEntry(
                entry_id=row["entry_id"],
                timestamp=row["timestamp"],
                event_type=row["event_type"],
                actor=row["actor"],
                payload=payload,
                prev_hash=row["prev_hash"],
                entry_hash=row["entry_hash"],
            )
        finally:
            conn.close()

    def count(self, event_type: str | None = None) -> int:
        """Count total audit entries."""
        conn = sqlite3.connect(str(self._db_path))
        try:
            if event_type:
                row = conn.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE event_type = ?",
                    (event_type,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()


def _compute_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    """Compute SHA-256 hash for an audit entry.

    hash = SHA-256(prev_hash + canonical_json(payload))
    """
    payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    data = f"{prev_hash}{payload_str}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()

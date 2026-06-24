"""SQLite-backed action queue for pending user actions.

Central queue for AI-generated trade actions awaiting user confirmation.
Each action flows through: pending -> confirmed -> executed (or rejected/expired).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger("web.action_queue_service")

_DB_PATH = Path("data/agent.db")

# Urgency ordering for sort priority (lower = more urgent)
_URGENCY_ORDER = {"immediate": 0, "today": 1, "observe": 2}


@dataclass
class ActionItem:
    """A single action in the queue."""

    id: str
    symbol: str
    action: str  # "buy" | "sell" | "reduce" | "hold"
    urgency: str  # "immediate" | "today" | "observe"
    session: str | None  # "call_auction" | "morning" | "late_session"
    confidence: float
    thesis_id: str | None
    execution_plan: dict
    status: str  # "pending" | "confirmed" | "executed" | "rejected" | "expired"
    created_at: datetime
    confirmed_at: datetime | None = None
    executed_at: datetime | None = None
    fill_price: float | None = None
    fill_shares: int | None = None

    def to_dict(self) -> dict:
        """Serialize to JSON-friendly dict."""
        d = asdict(self)
        for key in ("created_at", "confirmed_at", "executed_at"):
            val = d[key]
            if isinstance(val, datetime):
                d[key] = val.isoformat()
        return d


class ActionQueueService:
    """CRUD operations for the ``action_queue`` table.

    Uses the shared ``data/agent.db`` database alongside other services.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._ensure_tables()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def create_action(
        self,
        symbol: str,
        action: str,
        urgency: str,
        confidence: float,
        execution_plan: dict,
        thesis_id: str | None = None,
        session: str | None = None,
    ) -> ActionItem:
        """Create a new pending action in the queue."""
        action_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO action_queue "
                "(id, symbol, action, urgency, session, confidence, thesis_id, "
                "execution_plan, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    action_id,
                    symbol,
                    action,
                    urgency,
                    session,
                    confidence,
                    thesis_id,
                    json.dumps(execution_plan, ensure_ascii=False),
                    "pending",
                    now.isoformat(),
                ),
            )

        logger.info(
            "Action created: %s %s %s (confidence=%.2f, urgency=%s)",
            action_id,
            action,
            symbol,
            confidence,
            urgency,
        )
        return self.get_action(action_id)  # type: ignore[return-value]

    def confirm_action(self, action_id: str) -> ActionItem | None:
        """Mark an action as confirmed by the user."""
        item = self.get_action(action_id)
        if not item:
            return None
        if item.status != "pending":
            logger.warning(
                "Cannot confirm action %s: status is %s", action_id, item.status
            )
            return item

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE action_queue SET status = ?, confirmed_at = ? WHERE id = ?",
                ("confirmed", now, action_id),
            )
        logger.info("Action confirmed: %s", action_id)
        return self.get_action(action_id)

    def reject_action(self, action_id: str) -> ActionItem | None:
        """Mark an action as rejected by the user."""
        item = self.get_action(action_id)
        if not item:
            return None
        if item.status not in ("pending", "confirmed"):
            logger.warning(
                "Cannot reject action %s: status is %s", action_id, item.status
            )
            return item

        with self._connect() as conn:
            conn.execute(
                "UPDATE action_queue SET status = ? WHERE id = ?",
                ("rejected", action_id),
            )
        logger.info("Action rejected: %s", action_id)
        return self.get_action(action_id)

    def record_fill(
        self, action_id: str, fill_price: float, fill_shares: int
    ) -> ActionItem | None:
        """Record execution fill for a confirmed action."""
        item = self.get_action(action_id)
        if not item:
            return None
        if item.status != "confirmed":
            logger.warning(
                "Cannot record fill for action %s: status is %s",
                action_id,
                item.status,
            )
            return item

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE action_queue SET status = ?, executed_at = ?, "
                "fill_price = ?, fill_shares = ? WHERE id = ?",
                ("executed", now, fill_price, fill_shares, action_id),
            )
        logger.info(
            "Action executed: %s — %d shares @ %.2f",
            action_id,
            fill_shares,
            fill_price,
        )
        return self.get_action(action_id)

    def expire_old_actions(self) -> int:
        """Expire pending actions older than the current trading session.

        Actions older than 4 hours are considered stale and expired.
        Returns the count of expired actions.
        """
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE action_queue SET status = ? "
                "WHERE status = ? AND created_at < ?",
                ("expired", "pending", cutoff),
            )
        count = cursor.rowcount
        if count > 0:
            logger.info("Expired %d stale actions", count)
        return count

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_pending(self) -> list[ActionItem]:
        """Return pending actions sorted by urgency (desc) x confidence (desc)."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM action_queue WHERE status = ? "
                "ORDER BY "
                "  CASE urgency "
                "    WHEN 'immediate' THEN 0 "
                "    WHEN 'today' THEN 1 "
                "    WHEN 'observe' THEN 2 "
                "    ELSE 3 "
                "  END ASC, "
                "  confidence DESC",
                ("pending",),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def list_actions(self, status: str | None = None) -> list[ActionItem]:
        """Return actions filtered by optional status."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM action_queue WHERE status = ? "
                    "ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM action_queue ORDER BY created_at DESC"
                ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_action(self, action_id: str) -> ActionItem | None:
        """Return a single action by ID, or None."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM action_queue WHERE id = ?",
                (action_id,),
            ).fetchone()
        return self._row_to_item(row) if row else None

    def get_stats(self) -> dict:
        """Return counts by status."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM action_queue GROUP BY status"
            ).fetchall()
        stats = {
            "pending": 0,
            "confirmed": 0,
            "executed": 0,
            "rejected": 0,
            "expired": 0,
        }
        for row in rows:
            stats[row[0]] = row[1]
        stats["total"] = sum(stats.values())
        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ActionItem:
        """Convert a SQLite Row to an ActionItem dataclass."""
        execution_plan = {}
        raw_plan = row["execution_plan"]
        if raw_plan:
            try:
                execution_plan = json.loads(raw_plan)
            except (json.JSONDecodeError, TypeError):
                execution_plan = {}

        def _parse_dt(val: str | None) -> datetime | None:
            if not val:
                return None
            try:
                return datetime.fromisoformat(val)
            except (ValueError, TypeError):
                return None

        return ActionItem(
            id=row["id"],
            symbol=row["symbol"],
            action=row["action"],
            urgency=row["urgency"],
            session=row["session"],
            confidence=row["confidence"] or 0.0,
            thesis_id=row["thesis_id"],
            execution_plan=execution_plan,
            status=row["status"],
            created_at=_parse_dt(row["created_at"]) or datetime.now(timezone.utc),
            confirmed_at=_parse_dt(row["confirmed_at"]),
            executed_at=_parse_dt(row["executed_at"]),
            fill_price=row["fill_price"],
            fill_shares=row["fill_shares"],
        )

    def _connect(self) -> sqlite3.Connection:
        """Open a connection to the shared SQLite database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_tables(self) -> None:
        """Create the ``action_queue`` table if it does not exist."""
        with self._connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS action_queue (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    urgency TEXT NOT NULL DEFAULT 'today',
                    session TEXT,
                    confidence REAL,
                    thesis_id TEXT,
                    execution_plan TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMP NOT NULL,
                    confirmed_at TIMESTAMP,
                    executed_at TIMESTAMP,
                    fill_price REAL,
                    fill_shares INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_action_queue_status "
                "ON action_queue(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_action_queue_symbol "
                "ON action_queue(symbol)"
            )

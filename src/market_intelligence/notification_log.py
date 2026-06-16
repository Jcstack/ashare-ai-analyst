"""SQLite-backed notification delivery log.

Records every notification decision made by NotificationOrchestrator,
enabling audit, stats dashboards, and post-hoc analysis of push vs.
suppress vs. block ratios.

Part of v20.0 Market Intelligence Phase 3.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_DB_PATH = Path("data/notification_log.db")


class NotificationLog:
    """Persistent log of notification routing decisions.

    Uses the same SQLite patterns as ``SignalStore``: WAL mode,
    thread-safe new-connection-per-method, ``datetime(UTC)``.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DB_PATH
        self._ensure_db()

    # ------------------------------------------------------------------
    # Database setup
    # ------------------------------------------------------------------

    def _ensure_db(self) -> None:
        """Create database and table if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA journal_size_limit=67108864")  # 64 MB

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    push_decision TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    confidence_score REAL,
                    risk_level TEXT,
                    dispatched INTEGER DEFAULT 0,
                    dispatch_result TEXT,
                    reason TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notif_log_created
                ON notification_log(created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notif_log_signal_id
                ON notification_log(signal_id)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection (thread-safe pattern)."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def log(
        self,
        signal_id: str,
        signal_type: str,
        push_decision: str,
        phase: str,
        confidence_score: float,
        risk_level: str,
        dispatched: bool,
        dispatch_result: str | None = None,
        reason: str = "",
    ) -> None:
        """Record a notification decision."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO notification_log
                    (signal_id, signal_type, push_decision, phase,
                     confidence_score, risk_level, dispatched,
                     dispatch_result, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id,
                    signal_type,
                    push_decision,
                    phase,
                    confidence_score,
                    risk_level,
                    int(dispatched),
                    dispatch_result,
                    reason,
                ),
            )
            conn.commit()
            logger.debug(
                "Logged notification decision: signal=%s decision=%s dispatched=%s",
                signal_id,
                push_decision,
                dispatched,
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent log entries, newest first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM notification_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_stats(self, window_days: int = 1) -> dict[str, Any]:
        """Get decision stats for the window.

        Returns counts by push_decision and dispatch success rate.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()

        conn = self._connect()
        try:
            # Counts by decision type
            rows = conn.execute(
                """
                SELECT push_decision, COUNT(*) as cnt
                FROM notification_log
                WHERE created_at >= ?
                GROUP BY push_decision
                """,
                (cutoff,),
            ).fetchall()
            by_decision: dict[str, int] = {r["push_decision"]: r["cnt"] for r in rows}

            # Dispatch success rate
            dispatch_row = conn.execute(
                """
                SELECT
                    COUNT(*) as total_dispatched,
                    SUM(CASE WHEN dispatch_result = 'ok' THEN 1 ELSE 0 END) as success
                FROM notification_log
                WHERE created_at >= ? AND dispatched = 1
                """,
                (cutoff,),
            ).fetchone()

            total_dispatched = dispatch_row["total_dispatched"] if dispatch_row else 0
            success = dispatch_row["success"] if dispatch_row else 0
            success_rate = (
                round(success / total_dispatched, 4) if total_dispatched > 0 else None
            )

            total = sum(by_decision.values())

            return {
                "window_days": window_days,
                "total": total,
                "by_decision": by_decision,
                "total_dispatched": total_dispatched,
                "dispatch_success": success,
                "dispatch_success_rate": success_rate,
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup(self, days: int = 30) -> int:
        """Delete entries older than N days. Returns count deleted."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM notification_log WHERE created_at < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            logger.info(
                "Cleaned up %d notification log entries older than %d days",
                deleted,
                days,
            )
            return deleted
        finally:
            conn.close()

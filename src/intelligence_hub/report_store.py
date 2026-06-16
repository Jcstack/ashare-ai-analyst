"""SQLite-backed persistence for intelligence-driven analysis reports.

Part of v25.0 Intel-Portfolio Analysis. Pattern follows info_store.py —
WAL mode, thread-safe connections, CRUD operations.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DB_PATH = Path("data/agent.db")


class IntelReportStore:
    """SQLite-backed storage for IntelReport records.

    Uses the shared ``data/agent.db`` database alongside agent/capital tables.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DB_PATH
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the intel_reports table if it doesn't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intel_reports (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    stock_name TEXT NOT NULL DEFAULT '',
                    intel_item_ids TEXT NOT NULL DEFAULT '[]',
                    refresh_cycle TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'hold',
                    signal TEXT NOT NULL DEFAULT 'neutral',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    summary TEXT NOT NULL DEFAULT '',
                    factors TEXT NOT NULL DEFAULT '[]',
                    position_context TEXT DEFAULT 'null',
                    risk_warnings TEXT NOT NULL DEFAULT '[]',
                    outlook TEXT NOT NULL DEFAULT '',
                    reasoning TEXT NOT NULL DEFAULT '[]',
                    intel_summary TEXT NOT NULL DEFAULT '',
                    model_used TEXT DEFAULT '',
                    generated_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    thread_id TEXT DEFAULT NULL,
                    is_read INTEGER DEFAULT 0
                )
                """
            )
            # v33.0 migration: add affected_sectors column for macro reports
            self._migrate_affected_sectors(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reports_symbol ON intel_reports(symbol)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reports_created "
                "ON intel_reports(created_at DESC)"
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate_affected_sectors(conn: sqlite3.Connection) -> None:
        """Add affected_sectors column if missing (v33.0 macro reports)."""
        cursor = conn.execute("PRAGMA table_info(intel_reports)")
        existing = {row[1] for row in cursor.fetchall()}
        if "affected_sectors" not in existing:
            conn.execute(
                "ALTER TABLE intel_reports ADD COLUMN affected_sectors TEXT DEFAULT '{}'"
            )
            logger.info("Migrated: added affected_sectors column to intel_reports")

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection (thread-safe pattern)."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def store(self, report: dict[str, Any]) -> None:
        """Insert a new report. Duplicate id is silently ignored."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO intel_reports
                    (id, symbol, stock_name, intel_item_ids, refresh_cycle,
                     action, signal, confidence, summary, factors,
                     position_context, risk_warnings, outlook, reasoning,
                     intel_summary, model_used, generated_at, thread_id, is_read,
                     affected_sectors)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report["id"],
                    report["symbol"],
                    report.get("stock_name", ""),
                    json.dumps(report.get("intel_item_ids", []), ensure_ascii=False),
                    report.get("refresh_cycle", ""),
                    report.get("action", "hold"),
                    report.get("signal", "neutral"),
                    report.get("confidence", 0.5),
                    report.get("summary", ""),
                    json.dumps(report.get("factors", []), ensure_ascii=False),
                    json.dumps(report.get("position_context"), ensure_ascii=False),
                    json.dumps(report.get("risk_warnings", []), ensure_ascii=False),
                    report.get("outlook", ""),
                    json.dumps(report.get("reasoning", []), ensure_ascii=False),
                    report.get("intel_summary", ""),
                    report.get("model_used", ""),
                    report.get("generated_at", ""),
                    report.get("thread_id"),
                    int(report.get("is_read", False)),
                    json.dumps(report.get("affected_sectors", {}), ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        """Fetch a single report by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM intel_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def get_reports(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Query reports with optional filters, paginated."""
        where_clauses: list[str] = []
        params: list[Any] = []

        if symbol is not None:
            where_clauses.append("symbol = ?")
            params.append(symbol)

        if unread_only:
            where_clauses.append("is_read = 0")

        where = " AND ".join(where_clauses) if where_clauses else "1=1"
        params.extend([limit, offset])

        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM intel_reports WHERE {where} "  # noqa: S608
                f"ORDER BY created_at DESC "
                f"LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get_total_count(
        self,
        *,
        symbol: str | None = None,
        unread_only: bool = False,
    ) -> int:
        """Return total count matching filters."""
        where_clauses: list[str] = []
        params: list[Any] = []

        if symbol is not None:
            where_clauses.append("symbol = ?")
            params.append(symbol)
        if unread_only:
            where_clauses.append("is_read = 0")

        where = " AND ".join(where_clauses) if where_clauses else "1=1"
        conn = self._connect()
        try:
            row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM intel_reports WHERE {where}",  # noqa: S608
                params,
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    def get_unread_count(self) -> int:
        """Return count of unread reports."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM intel_reports WHERE is_read = 0"
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    def mark_read(self, report_id: str) -> bool:
        """Mark a report as read. Returns True if report existed."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE intel_reports SET is_read = 1 WHERE id = ?",
                (report_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete(self, report_id: str) -> bool:
        """Delete a report. Returns True if report existed."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM intel_reports WHERE id = ?",
                (report_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def link_thread(self, report_id: str, thread_id: str) -> bool:
        """Link a chat thread to a report. Returns True if report existed."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE intel_reports SET thread_id = ? WHERE id = ?",
                (thread_id, report_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def cleanup(self, days: int = 30) -> int:
        """Delete reports older than N days. Returns count deleted."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM intel_reports WHERE created_at < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            if deleted:
                logger.info(
                    "Cleaned up %d intel reports older than %d days", deleted, days
                )
            return deleted
        finally:
            conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a SQLite row to a dict with parsed JSON fields."""
        d = dict(row)
        for key in (
            "intel_item_ids",
            "factors",
            "risk_warnings",
            "reasoning",
        ):
            if isinstance(d.get(key), str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    d[key] = []
        if isinstance(d.get("position_context"), str):
            try:
                d["position_context"] = json.loads(d["position_context"])
            except (json.JSONDecodeError, TypeError):
                d["position_context"] = None
        if isinstance(d.get("affected_sectors"), str):
            try:
                d["affected_sectors"] = json.loads(d["affected_sectors"])
            except (json.JSONDecodeError, TypeError):
                d["affected_sectors"] = {}
        d["is_read"] = bool(d.get("is_read", 0))
        d["is_macro"] = d.get("symbol") == "MACRO"
        return d

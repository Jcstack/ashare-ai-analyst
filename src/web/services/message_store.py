"""SQLite-backed persistence for assistant inbox messages.

Follows RecStore pattern — WAL mode, thread-safe connections, structured queries.
Translates AI agent outputs into plain Chinese messages for retail investors.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DB_PATH = Path("data/messages.db")


class MessageStore:
    """SQLite-backed storage for assistant inbox messages."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DB_PATH
        self._ensure_db()

    # ------------------------------------------------------------------
    # Database setup
    # ------------------------------------------------------------------

    def _ensure_db(self) -> None:
        """Create database and tables if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA journal_size_limit=67108864")  # 64 MB
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content TEXT,
                    priority TEXT NOT NULL DEFAULT 'medium',
                    action_advice TEXT,
                    risk_note TEXT,
                    detail_analysis TEXT,
                    stock_recommendations TEXT,
                    post_market_data TEXT,
                    raw_data_ref TEXT,
                    data_freshness TEXT NOT NULL DEFAULT 'realtime',
                    data_collected_at TEXT,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    read_at TEXT
                )
                """
            )
            # Migrate: add columns if upgrading from older schema
            for col, coldef in [
                ("content", "TEXT"),
                ("priority", "TEXT NOT NULL DEFAULT 'medium'"),
                ("stock_recommendations", "TEXT"),
                ("post_market_data", "TEXT"),
                ("expires_at", "TEXT"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {coldef}")
                except sqlite3.OperationalError:
                    pass  # column already exists
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_msg_type
                ON messages(type, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_msg_created
                ON messages(created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_msg_unread
                ON messages(is_read, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_msg_symbol
                ON messages(symbol, created_at DESC)
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

    def create_message(
        self,
        *,
        symbol: str | None = None,
        msg_type: str,
        title: str,
        summary: str,
        content: str | None = None,
        priority: str = "medium",
        action_advice: str | None = None,
        risk_note: str | None = None,
        detail_analysis: str | None = None,
        stock_recommendations: list[dict] | None = None,
        post_market_data: dict | None = None,
        raw_data_ref: dict | None = None,
        data_freshness: str = "realtime",
        data_collected_at: str | None = None,
        expires_at: str | None = None,
    ) -> int:
        """Insert a new message. Returns the message ID."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO messages
                    (symbol, type, title, summary, content, priority,
                     action_advice, risk_note, detail_analysis,
                     stock_recommendations, post_market_data,
                     raw_data_ref, data_freshness, data_collected_at,
                     expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    msg_type,
                    title,
                    summary,
                    content,
                    priority,
                    action_advice,
                    risk_note,
                    detail_analysis,
                    json.dumps(stock_recommendations, ensure_ascii=False)
                    if stock_recommendations
                    else None,
                    json.dumps(post_market_data, ensure_ascii=False)
                    if post_market_data
                    else None,
                    json.dumps(raw_data_ref, ensure_ascii=False)
                    if raw_data_ref
                    else None,
                    data_freshness,
                    data_collected_at,
                    expires_at,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_message(self, message_id: int) -> dict[str, Any] | None:
        """Fetch a single message by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def list_messages(
        self,
        *,
        msg_type: str | None = None,
        symbol: str | None = None,
        unread_only: bool = False,
        include_expired: bool = False,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """Query messages with pagination and filters.

        Expired messages (past ``expires_at``) are excluded by default.
        Returns (items, total_count).
        """
        where_clauses: list[str] = []
        params: list[Any] = []

        if symbol is not None:
            where_clauses.append("symbol = ?")
            params.append(symbol.strip())

        if msg_type is not None:
            types = [t.strip() for t in msg_type.split(",") if t.strip()]
            if len(types) == 1:
                where_clauses.append("type = ?")
                params.append(types[0])
            elif types:
                placeholders = ",".join("?" for _ in types)
                where_clauses.append(f"type IN ({placeholders})")
                params.extend(types)

        if unread_only:
            where_clauses.append("is_read = 0")

        if not include_expired:
            where_clauses.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(datetime.now(UTC).isoformat())

        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        conn = self._connect()
        try:
            # Count total
            count_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM messages {where}",  # noqa: S608
                params,
            ).fetchone()
            total = count_row["cnt"] if count_row else 0

            # Fetch page
            offset = (page - 1) * per_page
            page_params = [*params, per_page, offset]
            rows = conn.execute(
                f"SELECT * FROM messages {where} "  # noqa: S608
                f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                page_params,
            ).fetchall()

            return [self._row_to_dict(r) for r in rows], total
        finally:
            conn.close()

    def count_unread(self) -> int:
        """Count unread non-expired messages."""
        now = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM messages "
                "WHERE is_read = 0 AND (expires_at IS NULL OR expires_at > ?)",
                (now,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def mark_read(self, message_id: int) -> bool:
        """Mark a message as read. Returns True if found and updated."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE messages SET is_read = 1, read_at = ? WHERE id = ? AND is_read = 0",
                (datetime.now(UTC).isoformat(), message_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def expire_old_messages(self, days: int = 30) -> int:
        """Delete messages older than N days. Returns count deleted."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM messages WHERE created_at < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            if deleted:
                logger.info("Expired %d messages older than %d days", deleted, days)
            return deleted
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a Row to dict with parsed JSON fields."""
        d = dict(row)
        d["is_read"] = bool(d.get("is_read", 0))
        # Frontend expects "read" not "is_read"
        d["read"] = d["is_read"]
        # Parse JSON columns
        for key in ("raw_data_ref", "stock_recommendations", "post_market_data"):
            val = d.get(key)
            if isinstance(val, str):
                try:
                    d[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        # Default priority if missing (old rows)
        if not d.get("priority"):
            d["priority"] = "medium"
        # Default content from summary if missing
        if not d.get("content"):
            d["content"] = d.get("detail_analysis") or d.get("summary", "")
        # Compute expired flag for frontend
        expires_at = d.get("expires_at")
        if expires_at:
            d["expired"] = expires_at < datetime.now(UTC).isoformat()
        else:
            d["expired"] = False
        return d

"""SQLite-backed persistence for Intelligence Hub information items.

Part of v21.0 Intelligence Hub. Pattern follows signal_store.py — WAL mode,
thread-safe connections, INSERT OR IGNORE for dedup.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.intelligence_hub.models import InfoItem

logger = logging.getLogger(__name__)

_DB_PATH = Path("data/info_items.db")


class InfoStore:
    """SQLite-backed storage for InfoItem records."""

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
            # Flush stale WAL from previous container (macOS Docker bind-mount).
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS info_items (
                    item_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT,
                    url TEXT,
                    category TEXT NOT NULL DEFAULT 'market',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    tags TEXT DEFAULT '[]',
                    related_symbols TEXT DEFAULT '[]',
                    published_at TEXT,
                    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
                    is_bookmarked INTEGER DEFAULT 0,
                    is_read INTEGER DEFAULT 0,
                    extra TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_info_category_published
                ON info_items(category, published_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_info_source_published
                ON info_items(source_id, published_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_info_priority_published
                ON info_items(priority, published_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_info_bookmarked
                ON info_items(is_bookmarked)
                """
            )
            # v23.0 migration: add content_score and score_explain columns
            self._migrate_score_columns(conn)
            # Normalize existing published_at to ISO format for correct sorting
            self._migrate_published_at(conn)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate_score_columns(conn: sqlite3.Connection) -> None:
        """Add content_score and score_explain columns if missing (v23.0)."""
        cursor = conn.execute("PRAGMA table_info(info_items)")
        existing = {row[1] for row in cursor.fetchall()}
        if "content_score" not in existing:
            conn.execute("ALTER TABLE info_items ADD COLUMN content_score REAL")
            logger.info("Migrated: added content_score column")
        if "score_explain" not in existing:
            conn.execute(
                "ALTER TABLE info_items ADD COLUMN score_explain TEXT DEFAULT '{}'"
            )
            logger.info("Migrated: added score_explain column")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_info_score "
            "ON info_items(content_score DESC)"
        )

    @staticmethod
    def _migrate_published_at(conn: sqlite3.Connection) -> None:
        """Normalize non-ISO published_at values in existing rows.

        Converts RFC 2822 dates and other formats to 'YYYY-MM-DD HH:MM:SS'
        so that SQLite string comparison works correctly for time filtering.
        """
        from email.utils import parsedate_to_datetime

        # Find rows where published_at is non-empty and not ISO-like
        rows = conn.execute(
            "SELECT item_id, published_at, fetched_at FROM info_items "
            "WHERE published_at IS NOT NULL AND published_at != '' "
            "AND substr(published_at, 5, 1) != '-'"
        ).fetchall()
        if not rows:
            return

        updates: list[tuple[str, str]] = []
        for row in rows:
            raw = row[1]
            fetched = row[2] or ""
            # Try RFC 2822 parsing
            try:
                dt = parsedate_to_datetime(raw)
                updates.append((dt.strftime("%Y-%m-%d %H:%M:%S"), row[0]))
            except Exception:
                # Unparseable (e.g. garbage HTML) — fallback to fetched_at
                if fetched:
                    updates.append((fetched[:19], row[0]))

        if updates:
            conn.executemany(
                "UPDATE info_items SET published_at = ? WHERE item_id = ?",
                updates,
            )
            logger.info(
                "Migrated published_at: normalized %d rows to ISO format", len(updates)
            )

        # Also normalize ISO dates with T separator (e.g. "2026-02-15T14:00:00Z")
        conn.execute(
            "UPDATE info_items SET published_at = "
            "substr(replace(published_at, 'T', ' '), 1, 19) "
            "WHERE published_at LIKE '____-__-__T%'"
        )

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection (thread-safe pattern)."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def checkpoint(self) -> None:
        """Flush WAL data to the main database file.

        Ensures cross-process visibility when SQLite is accessed from
        multiple Docker containers sharing a bind-mount volume (macOS
        Docker's virtiofs/gRPC-FUSE layer can break WAL's mmap-based
        shared-memory coordination).
        """
        conn = self._connect()
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def store(self, item: InfoItem) -> None:
        """Insert an InfoItem. Duplicate item_id is silently ignored."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO info_items
                    (item_id, source_id, source_name, title, summary, url,
                     category, priority, tags, related_symbols,
                     published_at, fetched_at, is_bookmarked, is_read, extra,
                     content_score, score_explain)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.item_id,
                    item.source_id,
                    item.source_name,
                    item.title,
                    item.summary,
                    item.url,
                    item.category,
                    item.priority,
                    json.dumps(item.tags, ensure_ascii=False),
                    json.dumps(item.related_symbols, ensure_ascii=False),
                    item.published_at,
                    item.fetched_at,
                    int(item.is_bookmarked),
                    int(item.is_read),
                    json.dumps(item.extra, ensure_ascii=False),
                    item.content_score,
                    json.dumps(item.score_explain, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def store_batch(self, items: list[InfoItem]) -> tuple[int, list[str]]:
        """Insert multiple items in a single transaction.

        Returns:
            Tuple of (count_stored, new_item_ids).
        """
        if not items:
            return 0, []
        conn = self._connect()
        try:
            # Pre-check which IDs already exist to identify truly new items
            all_ids = [it.item_id for it in items]
            placeholders = ",".join("?" for _ in all_ids)
            existing = {
                row[0]
                for row in conn.execute(
                    f"SELECT item_id FROM info_items WHERE item_id IN ({placeholders})",  # noqa: S608
                    all_ids,
                ).fetchall()
            }
            new_ids = [iid for iid in all_ids if iid not in existing]

            conn.executemany(
                """
                INSERT OR IGNORE INTO info_items
                    (item_id, source_id, source_name, title, summary, url,
                     category, priority, tags, related_symbols,
                     published_at, fetched_at, is_bookmarked, is_read, extra,
                     content_score, score_explain)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        it.item_id,
                        it.source_id,
                        it.source_name,
                        it.title,
                        it.summary,
                        it.url,
                        it.category,
                        it.priority,
                        json.dumps(it.tags, ensure_ascii=False),
                        json.dumps(it.related_symbols, ensure_ascii=False),
                        it.published_at,
                        it.fetched_at,
                        int(it.is_bookmarked),
                        int(it.is_read),
                        json.dumps(it.extra, ensure_ascii=False),
                        it.content_score,
                        json.dumps(it.score_explain, ensure_ascii=False),
                    )
                    for it in items
                ],
            )
            conn.commit()
            return len(new_ids), new_ids
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        """Fetch a single item by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM info_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_items_by_ids(self, item_ids: list[str]) -> list[dict[str, Any]]:
        """Batch fetch items by IDs."""
        if not item_ids:
            return []
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in item_ids)
            rows = conn.execute(
                f"SELECT * FROM info_items WHERE item_id IN ({placeholders})",  # noqa: S608
                item_ids,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_feed(
        self,
        *,
        category: str | None = None,
        priority: str | None = None,
        search: str | None = None,
        bookmarked: bool | None = None,
        symbol: str | None = None,
        limit: int = 50,
        offset: int = 0,
        days: int = 30,
        sort_by: str = "time",
    ) -> list[dict[str, Any]]:
        """Query items with optional filters, paginated.

        Args:
            sort_by: "time" (default) or "score" for content_score desc.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        where_clauses = ["published_at >= ?"]
        params: list[Any] = [cutoff]

        if category is not None:
            where_clauses.append("category = ?")
            params.append(category)

        if priority is not None:
            where_clauses.append("priority = ?")
            params.append(priority)

        if search is not None:
            where_clauses.append("(title LIKE ? OR summary LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        if bookmarked is not None:
            where_clauses.append("is_bookmarked = ?")
            params.append(int(bookmarked))

        if symbol is not None:
            # Support comma-separated multi-symbol filter (I-093 "与我相关")
            symbols = [s.strip() for s in symbol.split(",") if s.strip()]
            if len(symbols) == 1:
                where_clauses.append("related_symbols LIKE ?")
                params.append(f'%"{symbols[0]}"%')
            elif symbols:
                sym_clauses = ["related_symbols LIKE ?" for _ in symbols]
                where_clauses.append(f"({' OR '.join(sym_clauses)})")
                params.extend(f'%"{s}"%' for s in symbols)

        where = " AND ".join(where_clauses)
        params.extend([limit, offset])

        if sort_by == "score":
            order = "CASE WHEN content_score IS NULL THEN 1 ELSE 0 END, content_score DESC, published_at DESC"
        else:
            order = "published_at DESC, fetched_at DESC"

        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM info_items WHERE {where} "  # noqa: S608
                f"ORDER BY {order} "
                f"LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_category_counts(self, days: int = 30) -> dict[str, dict[str, int]]:
        """Return per-category total and unread counts."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT category,
                       COUNT(*) as total,
                       SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) as unread
                FROM info_items
                WHERE published_at >= ?
                GROUP BY category
                """,
                (cutoff,),
            ).fetchall()
            return {
                row["category"]: {"total": row["total"], "unread": row["unread"]}
                for row in rows
            }
        finally:
            conn.close()

    def get_overview(self, days: int = 30) -> dict[str, Any]:
        """Return summary stats for the feed."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn = self._connect()
        try:
            total_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM info_items WHERE published_at >= ?",
                (cutoff,),
            ).fetchone()
            total = total_row["cnt"] if total_row else 0

            source_row = conn.execute(
                "SELECT COUNT(DISTINCT source_id) as cnt FROM info_items WHERE published_at >= ?",
                (cutoff,),
            ).fetchone()
            sources_count = source_row["cnt"] if source_row else 0

            categories = self.get_category_counts(days=days)

            return {
                "total_items": total,
                "sources_count": sources_count,
                "categories": categories,
            }
        finally:
            conn.close()

    def count_since(self, since: str) -> int:
        """Count items created after the given ISO timestamp."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM info_items WHERE created_at >= ?",
                (since,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def toggle_bookmark(self, item_id: str) -> bool | None:
        """Toggle bookmark status. Returns new value, or None if not found."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT is_bookmarked FROM info_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if not row:
                return None
            new_val = 0 if row["is_bookmarked"] else 1
            conn.execute(
                "UPDATE info_items SET is_bookmarked = ? WHERE item_id = ?",
                (new_val, item_id),
            )
            conn.commit()
            return bool(new_val)
        finally:
            conn.close()

    def mark_read(self, item_id: str) -> bool:
        """Mark an item as read. Returns True if item existed."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE info_items SET is_read = 1 WHERE item_id = ?",
                (item_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------

    def update_related_symbols(self, item_id: str, symbols: list[str]) -> bool:
        """Update the related_symbols JSON array for a single item.

        Returns True if a row was updated.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE info_items SET related_symbols = ? WHERE item_id = ?",
                (json.dumps(symbols, ensure_ascii=False), item_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_items_missing_symbols(
        self, limit: int = 500, days: int = 30
    ) -> list[dict[str, Any]]:
        """Return items with empty related_symbols within the time window.

        Used by the backfill pipeline to re-extract symbols for old items.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT item_id, title, summary FROM info_items "
                "WHERE related_symbols IN ('[]', '') "
                "AND published_at >= ? "
                "ORDER BY published_at DESC "
                "LIMIT ?",
                (cutoff, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def query_by_keywords(
        self,
        keywords: list[str],
        *,
        min_source_weight: float = 0.0,
        hours: int = 24,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query items by keyword matching in title+summary (not stock codes).

        Used by MacroRadarService to find geopolitical/policy/macro news
        without depending on stock code matching.

        Args:
            keywords: List of keywords to search for in title and summary.
            min_source_weight: Minimum content_score threshold (0.0 to skip).
            hours: Look back window in hours.
            limit: Max results to return.

        Returns:
            List of matching items sorted by published_at DESC.
        """
        if not keywords:
            return []

        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # Build keyword LIKE clauses (any keyword match)
        keyword_clauses = []
        params: list[Any] = [cutoff]
        for kw in keywords:
            keyword_clauses.append("(title LIKE ? OR summary LIKE ?)")
            params.extend([f"%{kw}%", f"%{kw}%"])

        keyword_where = " OR ".join(keyword_clauses)

        score_clause = ""
        if min_source_weight > 0:
            score_clause = " AND content_score >= ?"
            params.append(min_source_weight)

        params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM info_items "  # noqa: S608
                f"WHERE published_at >= ? AND ({keyword_where}){score_clause} "
                f"ORDER BY published_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def is_empty(self) -> bool:
        """Return True if the store has no items at all (cold start check)."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT 1 FROM info_items LIMIT 1").fetchone()
            return row is None
        finally:
            conn.close()

    def get_recent_ids(self, since: str, limit: int = 50) -> list[str]:
        """Return item_ids created after *since*, newest first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT item_id FROM info_items "
                "WHERE created_at >= ? "
                "ORDER BY created_at DESC LIMIT ?",
                (since, limit),
            ).fetchall()
            return [row["item_id"] for row in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup(self, days: int = 30) -> int:
        """Delete items older than N days, preserving bookmarked items.

        Returns number of items deleted.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM info_items WHERE fetched_at < ? AND is_bookmarked = 0",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            logger.info("Cleaned up %d info items older than %d days", deleted, days)
            return deleted
        finally:
            conn.close()

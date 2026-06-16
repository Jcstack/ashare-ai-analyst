"""SQLite-backed tracker for delivery events (displayed, clicked, analyzed).

Part of v23.0 Intelligence Hub Phase 3. Tracks which InfoItems users
display, click, and analyze for engagement metrics.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


_DB_PATH = Path("data/delivery.db")


class DeliveryTracker:
    """Tracks item delivery events: displayed, clicked, analyzed."""

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

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_delivery_item_id
                ON delivery_events(item_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_delivery_event_timestamp
                ON delivery_events(event_type, timestamp)
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
    # Track
    # ------------------------------------------------------------------

    def track(self, item_id: str, event_type: str) -> None:
        """Record a delivery event.

        Args:
            item_id: The InfoItem identifier.
            event_type: One of 'displayed', 'clicked', 'analyzed'.
        """
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO delivery_events (item_id, event_type) VALUES (?, ?)",
                (item_id, event_type),
            )
            conn.commit()
        finally:
            conn.close()

    def track_batch(self, item_ids: list[str], event_type: str) -> int:
        """Record batch delivery events (e.g. all items on a page displayed).

        Returns:
            Number of events inserted.
        """
        if not item_ids:
            return 0
        conn = self._connect()
        try:
            conn.executemany(
                "INSERT INTO delivery_events (item_id, event_type) VALUES (?, ?)",
                [(iid, event_type) for iid in item_ids],
            )
            conn.commit()
            return len(item_ids)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_item_stats(self, item_id: str) -> dict[str, int]:
        """Return per-event-type counts for a single item.

        Returns:
            {"displayed": N, "clicked": N, "analyzed": N}
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT event_type, COUNT(*) as cnt
                FROM delivery_events
                WHERE item_id = ?
                GROUP BY event_type
                """,
                (item_id,),
            ).fetchall()
            counts = {r["event_type"]: r["cnt"] for r in rows}
            return {
                "displayed": counts.get("displayed", 0),
                "clicked": counts.get("clicked", 0),
                "analyzed": counts.get("analyzed", 0),
            }
        finally:
            conn.close()

    def get_stats(self, days: int = 7) -> dict:
        """Return aggregate delivery stats within time window.

        Returns:
            {
                "total_displayed": N,
                "total_clicked": N,
                "total_analyzed": N,
                "click_through_rate": float,
                "unique_items_displayed": N,
            }
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT event_type, COUNT(*) as cnt
                FROM delivery_events
                WHERE timestamp >= ?
                GROUP BY event_type
                """,
                (cutoff,),
            ).fetchall()
            counts = {r["event_type"]: r["cnt"] for r in rows}

            total_displayed = counts.get("displayed", 0)
            total_clicked = counts.get("clicked", 0)
            total_analyzed = counts.get("analyzed", 0)

            ctr = (total_clicked / total_displayed) if total_displayed > 0 else 0.0

            unique_row = conn.execute(
                """
                SELECT COUNT(DISTINCT item_id) as cnt
                FROM delivery_events
                WHERE timestamp >= ? AND event_type = 'displayed'
                """,
                (cutoff,),
            ).fetchone()
            unique_items = unique_row["cnt"] if unique_row else 0

            return {
                "total_displayed": total_displayed,
                "total_clicked": total_clicked,
                "total_analyzed": total_analyzed,
                "click_through_rate": round(ctr, 4),
                "unique_items_displayed": unique_items,
            }
        finally:
            conn.close()

    def get_popular_items(self, limit: int = 20, days: int = 7) -> list[dict]:
        """Return most-clicked items within time window.

        Each dict: {item_id, click_count, display_count}
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    item_id,
                    SUM(CASE WHEN event_type = 'clicked' THEN 1 ELSE 0 END) as click_count,
                    SUM(CASE WHEN event_type = 'displayed' THEN 1 ELSE 0 END) as display_count
                FROM delivery_events
                WHERE timestamp >= ?
                GROUP BY item_id
                HAVING click_count > 0
                ORDER BY click_count DESC
                LIMIT ?
                """,
                (cutoff, limit),
            ).fetchall()
            return [
                {
                    "item_id": r["item_id"],
                    "click_count": r["click_count"],
                    "display_count": r["display_count"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup(self, days: int = 30) -> int:
        """Delete events older than N days.

        Returns:
            Number of events deleted.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM delivery_events WHERE timestamp < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            logger.info(
                "Cleaned up %d delivery events older than %d days", deleted, days
            )
            return deleted
        finally:
            conn.close()

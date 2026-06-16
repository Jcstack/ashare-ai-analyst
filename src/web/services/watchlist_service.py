"""SQLite-backed watchlist service.

Manages the user's stock watchlist in ``data/agent.db``, replacing the
previous ``config/stocks.yaml`` persistence.  Follows the same patterns
as :class:`CapitalService` (WAL mode, new connection per operation).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger("web.watchlist_service")

_DB_PATH = Path("data/agent.db")


class WatchlistService:
    """CRUD operations for the SQLite ``watchlist`` table."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._ensure_tables()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_all(self) -> list[dict]:
        """Return all watchlist items ordered by ``added_at``."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT symbol, name, board, added_at FROM watchlist ORDER BY added_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def contains(self, symbol: str) -> bool:
        """Check whether *symbol* is in the watchlist."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM watchlist WHERE symbol = ?", (symbol,)
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(self, symbol: str, name: str, board: str = "main") -> dict:
        """Add a stock to the watchlist (no-op if already present).

        Returns the inserted/existing item dict.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (symbol, name, board, added_at) "
                "VALUES (?, ?, ?, ?)",
                (symbol, name, board, now),
            )
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT symbol, name, board, added_at FROM watchlist WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        item = (
            dict(row)
            if row
            else {"symbol": symbol, "name": name, "board": board, "added_at": now}
        )
        logger.info("Watchlist add: %s (%s)", symbol, name)
        return item

    def remove(self, symbol: str) -> bool:
        """Remove a stock from the watchlist. Returns True if a row was deleted."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Watchlist remove: %s", symbol)
        return deleted

    def bulk_replace(self, items: list[dict]) -> list[dict]:
        """Replace the entire watchlist with *items*.

        Each item must have ``symbol`` and ``name``; ``board`` defaults to
        ``'main'``.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM watchlist")
            for item in items:
                conn.execute(
                    "INSERT OR IGNORE INTO watchlist (symbol, name, board, added_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        item["symbol"],
                        item["name"],
                        item.get("board", "main"),
                        item.get("added_at", now),
                    ),
                )
        logger.info("Watchlist bulk-replaced with %d items", len(items))
        return self.list_all()

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def maybe_migrate_from_yaml(self) -> bool:
        """One-time migration: seed from ``config/stocks.yaml``.

        Uses the ``_migrations`` table to track completion so the migration
        is never re-run — even if the user later empties the watchlist.

        Returns True if migration was performed.
        """
        migration_name = "watchlist_from_yaml"
        with self._connect() as conn:
            done = conn.execute(
                "SELECT 1 FROM _migrations WHERE name = ?", (migration_name,)
            ).fetchone()
            if done:
                return False

            # Upgrade path: existing DB already has data → set flag, skip import
            count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
            if count > 0:
                conn.execute(
                    "INSERT OR IGNORE INTO _migrations (name, completed_at) VALUES (?, ?)",
                    (migration_name, datetime.now(timezone.utc).isoformat()),
                )
                return False

        try:
            from src.utils.config import load_config

            stocks_config = load_config("stocks")
            watchlist = stocks_config.get("watchlist", [])

            now = datetime.now(timezone.utc).isoformat()
            with self._connect() as conn:
                for item in watchlist:
                    conn.execute(
                        "INSERT OR IGNORE INTO watchlist (symbol, name, board, added_at) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            item["symbol"],
                            item["name"],
                            item.get("board", "main"),
                            now,
                        ),
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO _migrations (name, completed_at) VALUES (?, ?)",
                    (migration_name, now),
                )
            logger.info("Migrated %d watchlist items from stocks.yaml", len(watchlist))
            return True
        except Exception:
            logger.warning("Failed to migrate watchlist from YAML", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a connection to the shared SQLite database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_tables(self) -> None:
        """Create the ``watchlist`` and ``_migrations`` tables if they don't exist."""
        with self._connect() as conn:
            # Flush stale WAL from previous container so _migrations flags
            # and user data survive Docker restarts (macOS bind-mount issue).
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    board TEXT NOT NULL DEFAULT 'main',
                    added_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _migrations (
                    name TEXT PRIMARY KEY,
                    completed_at TEXT NOT NULL
                )
                """
            )

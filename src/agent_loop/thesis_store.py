"""SQLite-backed persistent investment thesis management.

The agent NEVER trades without an active thesis. This module stores and
manages :class:`InvestmentThesis` objects in ``data/thesis.db``, supporting
conviction decay, invalidation tracking, and full CRUD operations.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.agent_loop.models import InvestmentThesis

logger = logging.getLogger(__name__)

_DB_PATH = Path("data/thesis.db")


class ThesisStore:
    """CRUD operations for the ``theses`` table."""

    def __init__(self, db_path: str = "data/thesis.db") -> None:
        self._db_path = Path(db_path)
        self._ensure_table()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, symbol: str) -> InvestmentThesis | None:
        """Get active thesis for *symbol*. Returns ``None`` if not found."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM theses WHERE symbol = ? AND status = 'active'",
                (symbol,),
            ).fetchone()
            return self._row_to_thesis(row) if row else None
        finally:
            conn.close()

    def get_active(self) -> list[InvestmentThesis]:
        """Get all active theses."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM theses WHERE status = 'active' ORDER BY updated_at DESC",
            ).fetchall()
            return [self._row_to_thesis(r) for r in rows]
        finally:
            conn.close()

    def get_all(self, include_invalidated: bool = False) -> list[InvestmentThesis]:
        """Get all theses, optionally including invalidated ones."""
        conn = self._connect()
        try:
            if include_invalidated:
                rows = conn.execute(
                    "SELECT * FROM theses ORDER BY updated_at DESC",
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM theses WHERE status = 'active' "
                    "ORDER BY updated_at DESC",
                ).fetchall()
            return [self._row_to_thesis(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def save(self, thesis: InvestmentThesis) -> None:
        """Insert or update thesis (upsert by symbol).

        If a thesis for the same symbol already exists, all fields are
        overwritten and ``updated_at`` is refreshed.
        """
        now = datetime.now(UTC).isoformat()
        thesis.updated_at = datetime.now(UTC)

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO theses (
                    id, symbol, name, direction, conviction, thesis_text,
                    key_assumptions, invalidation_conditions,
                    entry_price_target, stop_loss_pct, sector, status,
                    created_at, updated_at, invalidated_at, invalidation_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    id = excluded.id,
                    name = excluded.name,
                    direction = excluded.direction,
                    conviction = excluded.conviction,
                    thesis_text = excluded.thesis_text,
                    key_assumptions = excluded.key_assumptions,
                    invalidation_conditions = excluded.invalidation_conditions,
                    entry_price_target = excluded.entry_price_target,
                    stop_loss_pct = excluded.stop_loss_pct,
                    sector = excluded.sector,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    invalidated_at = excluded.invalidated_at,
                    invalidation_reason = excluded.invalidation_reason
                """,
                (
                    thesis.id,
                    thesis.symbol,
                    thesis.name,
                    thesis.direction,
                    thesis.conviction,
                    thesis.thesis_text,
                    json.dumps(thesis.key_assumptions, ensure_ascii=False),
                    json.dumps(thesis.invalidation_conditions, ensure_ascii=False),
                    thesis.entry_price_target,
                    thesis.stop_loss_pct,
                    thesis.sector,
                    thesis.status,
                    thesis.created_at.isoformat(),
                    now,
                    thesis.invalidated_at.isoformat()
                    if thesis.invalidated_at
                    else None,
                    thesis.invalidation_reason,
                ),
            )
            conn.commit()
            logger.info(
                "Thesis saved: %s (%s) conviction=%.2f direction=%s",
                thesis.symbol,
                thesis.name,
                thesis.conviction,
                thesis.direction,
            )
        finally:
            conn.close()

    def invalidate(self, symbol: str, reason: str) -> None:
        """Mark thesis as invalidated with reason and timestamp."""
        now = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                UPDATE theses
                SET status = 'invalidated',
                    invalidated_at = ?,
                    invalidation_reason = ?,
                    updated_at = ?
                WHERE symbol = ? AND status = 'active'
                """,
                (now, reason, now, symbol),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("Thesis invalidated: %s — %s", symbol, reason)
            else:
                logger.warning("No active thesis found to invalidate for %s", symbol)
        finally:
            conn.close()

    def update_conviction(self, symbol: str, delta: float, reason: str) -> None:
        """Adjust conviction by *delta*, clamp to ``[0, 1]``.

        Appends the adjustment reason to ``thesis_text`` for audit trail.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT conviction, thesis_text FROM theses "
                "WHERE symbol = ? AND status = 'active'",
                (symbol,),
            ).fetchone()
            if not row:
                logger.warning(
                    "No active thesis for %s — cannot update conviction", symbol
                )
                return

            old_conviction = row["conviction"]
            new_conviction = max(0.0, min(1.0, old_conviction + delta))
            now = datetime.now(UTC).isoformat()

            updated_text = (
                f"{row['thesis_text']}\n"
                f"[{now}] Conviction {old_conviction:.2f} → {new_conviction:.2f}: {reason}"
            )

            conn.execute(
                """
                UPDATE theses
                SET conviction = ?,
                    thesis_text = ?,
                    updated_at = ?
                WHERE symbol = ? AND status = 'active'
                """,
                (new_conviction, updated_text, now, symbol),
            )
            conn.commit()
            logger.info(
                "Conviction updated: %s %.2f → %.2f (%s)",
                symbol,
                old_conviction,
                new_conviction,
                reason,
            )
        finally:
            conn.close()

    def decay_stale(self, max_age_hours: int = 72, decay_rate: float = 0.05) -> int:
        """Decay conviction of theses older than *max_age_hours*.

        Applies *decay_rate* per day of staleness. Auto-invalidates any
        thesis whose conviction drops below 0.1.

        Returns:
            Count of decayed theses.
        """
        cutoff = (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat()
        now = datetime.now(UTC)
        now_iso = now.isoformat()

        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, symbol, conviction, updated_at FROM theses "
                "WHERE status = 'active' AND updated_at < ?",
                (cutoff,),
            ).fetchall()

            decayed = 0
            for row in rows:
                updated_at = datetime.fromisoformat(row["updated_at"])
                stale_days = (now - updated_at).total_seconds() / 86400.0
                decay_amount = decay_rate * stale_days
                new_conviction = max(0.0, row["conviction"] - decay_amount)

                if new_conviction < 0.1:
                    conn.execute(
                        """
                        UPDATE theses
                        SET conviction = ?,
                            status = 'invalidated',
                            invalidated_at = ?,
                            invalidation_reason = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            new_conviction,
                            now_iso,
                            f"Auto-invalidated: conviction decayed to {new_conviction:.3f} "
                            f"after {stale_days:.1f} days stale",
                            now_iso,
                            row["id"],
                        ),
                    )
                    logger.info(
                        "Thesis auto-invalidated (decay): %s conviction=%.3f",
                        row["symbol"],
                        new_conviction,
                    )
                else:
                    conn.execute(
                        "UPDATE theses SET conviction = ?, updated_at = ? WHERE id = ?",
                        (new_conviction, now_iso, row["id"]),
                    )
                    logger.debug(
                        "Thesis decayed: %s %.2f → %.2f (%.1f days stale)",
                        row["symbol"],
                        row["conviction"],
                        new_conviction,
                        stale_days,
                    )
                decayed += 1

            conn.commit()
            if decayed:
                logger.info("Decayed %d stale theses", decayed)
            return decayed
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_thesis(row: sqlite3.Row) -> InvestmentThesis:
        """Convert a DB row to :class:`InvestmentThesis`."""
        return InvestmentThesis(
            id=row["id"],
            symbol=row["symbol"],
            name=row["name"],
            direction=row["direction"],
            conviction=row["conviction"],
            thesis_text=row["thesis_text"],
            key_assumptions=json.loads(row["key_assumptions"])
            if row["key_assumptions"]
            else [],
            invalidation_conditions=json.loads(row["invalidation_conditions"])
            if row["invalidation_conditions"]
            else [],
            entry_price_target=row["entry_price_target"],
            stop_loss_pct=row["stop_loss_pct"],
            sector=row["sector"] or "",
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            invalidated_at=datetime.fromisoformat(row["invalidated_at"])
            if row["invalidated_at"]
            else None,
            invalidation_reason=row["invalidation_reason"] or "",
        )

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection (thread-safe pattern)."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_table(self) -> None:
        """Create the ``theses`` table if it does not exist."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS theses (
                    id TEXT NOT NULL,
                    symbol TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    conviction REAL NOT NULL,
                    thesis_text TEXT NOT NULL DEFAULT '',
                    key_assumptions TEXT NOT NULL DEFAULT '[]',
                    invalidation_conditions TEXT NOT NULL DEFAULT '[]',
                    entry_price_target REAL,
                    stop_loss_pct REAL,
                    sector TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    invalidated_at TEXT,
                    invalidation_reason TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_theses_status ON theses(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_theses_updated ON theses(updated_at)"
            )
            conn.commit()
        finally:
            conn.close()

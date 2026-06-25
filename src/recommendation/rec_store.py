"""SQLite-backed persistence for stock recommendations.

Follows InfoStore pattern — WAL mode, thread-safe connections, structured queries.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.recommendation.models import Recommendation

logger = logging.getLogger(__name__)

_DB_PATH = Path("data/recommendations.db")


class RecStore:
    """SQLite-backed storage for Recommendation records."""

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
                CREATE TABLE IF NOT EXISTS recommendations (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'buy',
                    style TEXT NOT NULL,
                    session TEXT NOT NULL,
                    score REAL NOT NULL,
                    confidence TEXT NOT NULL DEFAULT 'medium',
                    reason TEXT,
                    risk_notes TEXT,
                    entry_price REAL,
                    target_price REAL,
                    stop_loss REAL,
                    factors TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    status TEXT NOT NULL DEFAULT 'active'
                )
                """
            )
            # Migration: add confidence/entry_price if upgrading from v1 schema
            self._migrate_new_columns(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rec_style_status
                ON recommendations(style, status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rec_created
                ON recommendations(created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rec_session
                ON recommendations(session, created_at DESC)
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recommendation_outcomes (
                    rec_id TEXT PRIMARY KEY REFERENCES recommendations(id),
                    entry_price REAL,
                    actual_price_t1 REAL,
                    actual_change_t1 REAL,
                    correct_t1 INTEGER,
                    actual_price_t3 REAL,
                    actual_change_t3 REAL,
                    correct_t3 INTEGER,
                    actual_price_t5 REAL,
                    actual_change_t5 REAL,
                    correct_t5 INTEGER,
                    actual_price_t10 REAL,
                    actual_change_t10 REAL,
                    correct_t10 INTEGER,
                    backfilled_at TEXT
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rec_id TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    action TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (rec_id) REFERENCES recommendations(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_feedback_rec
                ON user_feedback(rec_id)
                """
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate_new_columns(conn: sqlite3.Connection) -> None:
        """Add confidence and entry_price columns if missing (v28.0 migration)."""
        cursor = conn.execute("PRAGMA table_info(recommendations)")
        existing = {row[1] for row in cursor.fetchall()}
        if "confidence" not in existing:
            conn.execute(
                "ALTER TABLE recommendations ADD COLUMN confidence TEXT NOT NULL DEFAULT 'medium'"
            )
            logger.info("Migrated: added confidence column")
        if "entry_price" not in existing:
            conn.execute("ALTER TABLE recommendations ADD COLUMN entry_price REAL")
            logger.info("Migrated: added entry_price column")
        if "ai_analyzed" not in existing:
            conn.execute(
                "ALTER TABLE recommendations ADD COLUMN ai_analyzed INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("Migrated: added ai_analyzed column")
        if "run_id" not in existing:
            conn.execute("ALTER TABLE recommendations ADD COLUMN run_id TEXT")
            logger.info("Migrated: added run_id column")
        if "sub_scores" not in existing:
            conn.execute("ALTER TABLE recommendations ADD COLUMN sub_scores TEXT")
            logger.info("Migrated: added sub_scores column")

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection (thread-safe pattern)."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def save_recommendation(self, rec: Recommendation) -> None:
        """Insert a recommendation. Duplicate id is silently ignored."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO recommendations
                    (id, symbol, name, action, style, session, score,
                     confidence, reason, risk_notes, entry_price,
                     target_price, stop_loss,
                     factors, created_at, status, ai_analyzed, run_id,
                     sub_scores)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.id,
                    rec.symbol,
                    rec.name,
                    rec.action,
                    rec.style,
                    rec.session,
                    rec.score,
                    rec.confidence,
                    rec.reason,
                    rec.risk_notes,
                    rec.entry_price,
                    rec.target_price,
                    rec.stop_loss,
                    json.dumps(rec.factors, ensure_ascii=False),
                    rec.created_at,
                    rec.status,
                    1 if rec.ai_analyzed else 0,
                    rec.run_id,
                    json.dumps(rec.sub_scores, ensure_ascii=False)
                    if rec.sub_scores
                    else None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def save_batch(self, recs: list[Recommendation]) -> int:
        """Insert multiple recommendations. Returns count stored."""
        if not recs:
            return 0
        conn = self._connect()
        try:
            conn.executemany(
                """
                INSERT OR IGNORE INTO recommendations
                    (id, symbol, name, action, style, session, score,
                     confidence, reason, risk_notes, entry_price,
                     target_price, stop_loss,
                     factors, created_at, status, ai_analyzed, run_id,
                     sub_scores)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r.id,
                        r.symbol,
                        r.name,
                        r.action,
                        r.style,
                        r.session,
                        r.score,
                        r.confidence,
                        r.reason,
                        r.risk_notes,
                        r.entry_price,
                        r.target_price,
                        r.stop_loss,
                        json.dumps(r.factors, ensure_ascii=False),
                        r.created_at,
                        r.status,
                        1 if r.ai_analyzed else 0,
                        r.run_id,
                        json.dumps(r.sub_scores, ensure_ascii=False)
                        if r.sub_scores
                        else None,
                    )
                    for r in recs
                ],
            )
            conn.commit()
            return len(recs)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_recommendation(self, rec_id: str) -> dict[str, Any] | None:
        """Fetch a single recommendation by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM recommendations WHERE id = ?",
                (rec_id,),
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def get_recommendations(
        self,
        *,
        style: str | None = None,
        session: str | None = None,
        limit: int = 20,
        status: str = "active",
    ) -> list[dict[str, Any]]:
        """Query recommendations with optional filters."""
        where_clauses = ["status = ?"]
        params: list[Any] = [status]

        if style is not None:
            where_clauses.append("style = ?")
            params.append(style)

        if session is not None:
            where_clauses.append("session = ?")
            params.append(session)

        where = " AND ".join(where_clauses)
        params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM recommendations WHERE {where} "  # noqa: S608
                f"ORDER BY score DESC, created_at DESC "
                f"LIMIT ?",
                params,
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def _today_cutoff_utc() -> str:
        """Return start of today (CST) as a UTC ISO timestamp for SQL comparison."""
        _cst = ZoneInfo("Asia/Shanghai")
        today_start = datetime.now(_cst).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return today_start.astimezone(UTC).isoformat()

    def get_today_recommendations(
        self, *, style: str | None = None
    ) -> list[dict[str, Any]]:
        """Get today's recommendations (latest run only).

        Uses CST (Asia/Shanghai) to define "today".  When run_id data is
        available, only returns records from the most recent run so that
        multiple pipeline executions within the same day don't accumulate.
        Falls back to returning all of today's records when no run_id exists
        (backward compat with pre-migration data).
        """
        cutoff = self._today_cutoff_utc()

        conn = self._connect()
        try:
            # Find the latest run_id for today
            latest_run_row = conn.execute(
                "SELECT run_id FROM recommendations "
                "WHERE created_at >= ? AND status = 'active' AND run_id IS NOT NULL "
                "ORDER BY created_at DESC LIMIT 1",
                (cutoff,),
            ).fetchone()
            latest_run_id = latest_run_row["run_id"] if latest_run_row else None

            where_clauses = ["created_at >= ?", "status = 'active'"]
            params: list[Any] = [cutoff]

            if latest_run_id:
                where_clauses.append("run_id = ?")
                params.append(latest_run_id)

            if style is not None:
                where_clauses.append("style = ?")
                params.append(style)

            where = " AND ".join(where_clauses)

            rows = conn.execute(
                f"SELECT * FROM recommendations WHERE {where} "  # noqa: S608
                f"ORDER BY score DESC, created_at DESC",
                params,
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def count_today_active(self) -> int:
        """Count today's active recommendations (distinct symbols, latest run only)."""
        cutoff = self._today_cutoff_utc()
        conn = self._connect()
        try:
            # Find the latest run_id for today
            latest_run_row = conn.execute(
                "SELECT run_id FROM recommendations "
                "WHERE created_at >= ? AND status = 'active' AND run_id IS NOT NULL "
                "ORDER BY created_at DESC LIMIT 1",
                (cutoff,),
            ).fetchone()
            latest_run_id = latest_run_row["run_id"] if latest_run_row else None

            if latest_run_id:
                row = conn.execute(
                    "SELECT COUNT(DISTINCT symbol) as cnt FROM recommendations "
                    "WHERE created_at >= ? AND status = 'active' AND run_id = ?",
                    (cutoff, latest_run_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(DISTINCT symbol) as cnt FROM recommendations "
                    "WHERE created_at >= ? AND status = 'active'",
                    (cutoff,),
                ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def dismiss_recommendation(self, rec_id: str) -> bool:
        """Dismiss a recommendation. Returns True if found and updated."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE recommendations SET status = 'dismissed' WHERE id = ? AND status = 'active'",
                (rec_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def expire_old_recommendations(self, days: int = 3) -> int:
        """Expire recommendations older than N days. Returns count expired."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE recommendations SET status = 'expired' "
                "WHERE created_at < ? AND status = 'active'",
                (cutoff,),
            )
            expired = cursor.rowcount
            conn.commit()
            if expired:
                logger.info(
                    "Expired %d recommendations older than %d days", expired, days
                )
            return expired
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    def save_feedback(
        self,
        rec_id: str,
        user_id: str,
        action: str,
        notes: str | None = None,
    ) -> None:
        """Save user feedback for a recommendation."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO user_feedback (rec_id, user_id, action, notes, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    rec_id,
                    user_id,
                    action,
                    notes,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Outcomes / backfill (FR-REC041)
    # ------------------------------------------------------------------

    def get_pending_backfills(self, window: int) -> list[dict[str, Any]]:
        """Get recommendations old enough for T+N backfill but missing that window's data.

        Args:
            window: Trading day window (1, 3, 5, or 10).

        Returns:
            List of dicts with rec_id, symbol, entry_price, created_at.
        """
        col = f"actual_price_t{window}"
        # Recs created at least `window` calendar days ago (conservative; real trading days are fewer)
        cutoff = (datetime.now(UTC) - timedelta(days=window + 2)).strftime("%Y-%m-%d")

        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT r.id, r.symbol, r.entry_price, r.created_at
                FROM recommendations r
                LEFT JOIN recommendation_outcomes o ON r.id = o.rec_id
                WHERE r.created_at <= ?
                  AND r.status IN ('active', 'expired', 'dismissed')
                  AND r.entry_price IS NOT NULL
                  AND (o.rec_id IS NULL OR o.{col} IS NULL)
                ORDER BY r.created_at ASC
                LIMIT 200
                """,  # noqa: S608
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def backfill_outcome(
        self,
        rec_id: str,
        window: int,
        actual_price: float,
        actual_change: float,
    ) -> bool:
        """Write a T+N outcome for a recommendation.

        Returns True if the row was inserted/updated.
        """
        price_col = f"actual_price_t{window}"
        change_col = f"actual_change_t{window}"
        correct_col = f"correct_t{window}"
        correct = 1 if actual_change > 0 else 0
        now = datetime.now(UTC).isoformat()

        conn = self._connect()
        try:
            # Fetch entry_price from recommendation
            row = conn.execute(
                "SELECT entry_price FROM recommendations WHERE id = ?",
                (rec_id,),
            ).fetchone()
            entry_price = row["entry_price"] if row else None

            conn.execute(
                f"""
                INSERT INTO recommendation_outcomes (rec_id, entry_price, {price_col}, {change_col}, {correct_col}, backfilled_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(rec_id) DO UPDATE SET
                    {price_col} = ?,
                    {change_col} = ?,
                    {correct_col} = ?,
                    backfilled_at = ?
                """,  # noqa: S608
                (
                    rec_id,
                    entry_price,
                    actual_price,
                    actual_change,
                    correct,
                    now,
                    actual_price,
                    actual_change,
                    correct,
                    now,
                ),
            )
            conn.commit()
            return True
        except Exception as exc:
            logger.error("Failed to backfill outcome for %s: %s", rec_id, exc)
            return False
        finally:
            conn.close()

    def get_performance_stats(
        self,
        *,
        style: str | None = None,
        session: str | None = None,
        days: int = 90,
    ) -> dict[str, Any]:
        """Aggregate performance statistics from recommendation outcomes.

        Returns dict with total_recs, win rates and avg returns per window.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        where_clauses = ["r.created_at >= ?"]
        params: list[Any] = [cutoff]

        if style is not None:
            where_clauses.append("r.style = ?")
            params.append(style)
        if session is not None:
            where_clauses.append("r.session = ?")
            params.append(session)

        where = " AND ".join(where_clauses)

        conn = self._connect()
        try:
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) as total_recs,
                    SUM(CASE WHEN o.correct_t1 IS NOT NULL THEN 1 ELSE 0 END) as filled_t1,
                    SUM(o.correct_t1) as wins_t1,
                    AVG(o.actual_change_t1) as avg_return_t1,
                    SUM(CASE WHEN o.correct_t3 IS NOT NULL THEN 1 ELSE 0 END) as filled_t3,
                    SUM(o.correct_t3) as wins_t3,
                    AVG(o.actual_change_t3) as avg_return_t3,
                    SUM(CASE WHEN o.correct_t5 IS NOT NULL THEN 1 ELSE 0 END) as filled_t5,
                    SUM(o.correct_t5) as wins_t5,
                    AVG(o.actual_change_t5) as avg_return_t5,
                    SUM(CASE WHEN o.correct_t10 IS NOT NULL THEN 1 ELSE 0 END) as filled_t10,
                    SUM(o.correct_t10) as wins_t10,
                    AVG(o.actual_change_t10) as avg_return_t10
                FROM recommendations r
                LEFT JOIN recommendation_outcomes o ON r.id = o.rec_id
                WHERE {where}
                """,  # noqa: S608
                params,
            ).fetchone()

            stats = dict(row) if row else {}
            result: dict[str, Any] = {
                "total_recs": stats.get("total_recs", 0),
                "windows": {},
            }

            for w in [1, 3, 5, 10]:
                filled = stats.get(f"filled_t{w}", 0) or 0
                wins = stats.get(f"wins_t{w}", 0) or 0
                avg_ret = stats.get(f"avg_return_t{w}")
                result["windows"][f"t{w}"] = {
                    "filled": filled,
                    "wins": wins,
                    "win_rate": round(wins / filled * 100, 1) if filled > 0 else None,
                    "avg_return": round(avg_ret, 2) if avg_ret is not None else None,
                }

            return result
        finally:
            conn.close()

    def get_outcome(self, rec_id: str) -> dict[str, Any] | None:
        """Fetch outcome data for a single recommendation."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM recommendation_outcomes WHERE rec_id = ?",
                (rec_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Intel feedback (I-089 Phase 3) — closed-loop win rate analysis
    # ------------------------------------------------------------------

    def get_style_win_rates(self, days: int = 30) -> dict[str, dict[str, Any]]:
        """Get per-style win rates for feedback loop.

        Returns dict like: {"momentum": {"win_rate_t1": 0.6, "avg_return_t1": 1.2, "count": 15}}
        Used by IntelChainEngine to adjust chain confidence weights.
        """
        conn = self._connect()
        try:
            cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
            rows = conn.execute(
                """
                SELECT r.style,
                       COUNT(*) as count,
                       SUM(CASE WHEN o.correct_t1 = 1 THEN 1 ELSE 0 END) as wins_t1,
                       AVG(o.actual_change_t1) as avg_return_t1,
                       SUM(CASE WHEN o.correct_t3 = 1 THEN 1 ELSE 0 END) as wins_t3,
                       AVG(o.actual_change_t3) as avg_return_t3
                FROM recommendations r
                JOIN recommendation_outcomes o ON r.id = o.rec_id
                WHERE r.created_at >= ?
                  AND o.actual_change_t1 IS NOT NULL
                GROUP BY r.style
                """,
                (cutoff,),
            ).fetchall()

            result: dict[str, dict[str, Any]] = {}
            for row in rows:
                d = dict(row)
                style = d["style"]
                count = d["count"] or 0
                wins_t1 = d["wins_t1"] or 0
                result[style] = {
                    "count": count,
                    "win_rate_t1": round(wins_t1 / count, 4) if count > 0 else None,
                    "avg_return_t1": round(d["avg_return_t1"], 4)
                    if d["avg_return_t1"] is not None
                    else None,
                    "wins_t3": d["wins_t3"] or 0,
                    "win_rate_t3": round((d["wins_t3"] or 0) / count, 4)
                    if count > 0
                    else None,
                    "avg_return_t3": round(d["avg_return_t3"], 4)
                    if d["avg_return_t3"] is not None
                    else None,
                }
            return result
        except Exception as exc:
            logger.warning("Failed to get style win rates: %s", exc)
            return {}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a Row to dict with parsed JSON fields."""
        d = dict(row)
        factors_raw = d.get("factors", "{}")
        if isinstance(factors_raw, str):
            try:
                d["factors"] = json.loads(factors_raw)
            except (json.JSONDecodeError, TypeError):
                d["factors"] = {}
        d["ai_analyzed"] = bool(d.get("ai_analyzed", 0))
        sub_raw = d.get("sub_scores")
        if isinstance(sub_raw, str):
            try:
                d["sub_scores"] = json.loads(sub_raw)
            except (json.JSONDecodeError, TypeError):
                d["sub_scores"] = None
        return d

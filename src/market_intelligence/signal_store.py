"""SQLite-backed signal persistence + T+3/T+5 accuracy backfill tracking.

Part of v20.0 Market Intelligence pipeline.

Stores every MarketSignal produced by the signal pipeline and tracks
prediction accuracy via T+3/T+5 outcome backfill.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.web.schemas.market_signal import MarketSignal

logger = logging.getLogger(__name__)

# Signal types that have clear directional predictions (eligible for backfill)
_DIRECTIONAL_TYPES = frozenset(
    {
        "S1_TREND",
        "S2_MOMENTUM_SHIFT",
        "S4_ANOMALY",
        "S5_VOLATILITY",
        "STOCK_ALERT",
    }
)

# Keywords used to infer predicted direction from summary_short
_BULLISH_KEYWORDS = re.compile(
    r"bullish|看多|上涨|上行|利好|反弹|突破|涨|买入|做多",
    re.IGNORECASE,
)
_BEARISH_KEYWORDS = re.compile(
    r"bearish|看空|下跌|下行|利空|回调|跌破|跌|卖出|做空",
    re.IGNORECASE,
)


_DB_PATH = Path("data/signals.db")


class SignalStore:
    """SQLite-backed signal persistence + T+3/T+5 accuracy backfill."""

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
                CREATE TABLE IF NOT EXISTS signals (
                    signal_id TEXT PRIMARY KEY,
                    signal_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    assets TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    risk_level TEXT NOT NULL,
                    risk_context TEXT,
                    summary_short TEXT NOT NULL,
                    summary_detailed TEXT,
                    sources TEXT NOT NULL,
                    producer TEXT NOT NULL,
                    confirmed INTEGER DEFAULT 0,
                    is_injection INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_outcomes (
                    signal_id TEXT PRIMARY KEY REFERENCES signals(signal_id),
                    actual_change_t3 REAL,
                    actual_change_t5 REAL,
                    correct_t3 INTEGER,
                    correct_t5 INTEGER,
                    backfilled_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_signals_type_timestamp
                ON signals(signal_type, timestamp)
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
    # Store
    # ------------------------------------------------------------------

    def store(self, signal: MarketSignal) -> None:
        """Insert a MarketSignal into the signals table.

        Serializes complex fields (assets, sources, risk_context) as JSON.
        Duplicate signal_id is silently ignored (INSERT OR IGNORE).
        """
        risk_context_json: str | None = None
        if signal.risk_context is not None:
            risk_context_json = signal.risk_context.model_dump_json()

        sources_json = json.dumps(
            [s.model_dump(mode="json") for s in signal.sources],
            ensure_ascii=False,
        )
        assets_json = json.dumps(signal.assets, ensure_ascii=False)

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO signals
                    (signal_id, signal_type, timestamp, assets, phase,
                     confidence_score, risk_level, risk_context,
                     summary_short, summary_detailed, sources, producer,
                     confirmed, is_injection)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.signal_id,
                    signal.signal_type.value,
                    signal.timestamp.isoformat(),
                    assets_json,
                    signal.phase.value,
                    signal.confidence_score,
                    signal.risk_level.value,
                    risk_context_json,
                    signal.summary_short,
                    signal.summary_detailed,
                    sources_json,
                    signal.producer,
                    int(signal.confirmed),
                    int(signal.is_injection),
                ),
            )
            conn.commit()
            logger.info(
                "Stored signal %s [%s] confidence=%.0f%%",
                signal.signal_id,
                signal.signal_type.value,
                signal.confidence_score,
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_signal(self, signal_id: str) -> dict[str, Any] | None:
        """Fetch a single signal by ID. Returns None if not found."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM signals WHERE signal_id = ?",
                (signal_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_signals(
        self,
        signal_type: str | None = None,
        asset: str | None = None,
        phase: str | None = None,
        limit: int = 100,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Query signals with optional filters.

        Only returns signals from the last *days* calendar days.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        where_clauses = ["timestamp >= ?"]
        params: list[Any] = [cutoff]

        if signal_type is not None:
            where_clauses.append("signal_type = ?")
            params.append(signal_type)

        if asset is not None:
            # assets is a JSON array — use LIKE for containment check
            where_clauses.append("assets LIKE ?")
            params.append(f'%"{asset}"%')

        if phase is not None:
            where_clauses.append("phase = ?")
            params.append(phase)

        where = " AND ".join(where_clauses)
        params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM signals WHERE {where} "  # noqa: S608
                f"ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------

    def get_pending_backfills(self, window: int = 3) -> list[dict[str, Any]]:
        """Return signals that need T+{window} backfill.

        Only includes directional signal types. Uses calendar-day
        approximation: 3 trading days ~ 5 calendar days,
        5 trading days ~ 8 calendar days.
        """
        if window not in (3, 5):
            logger.warning("Unsupported backfill window: %d (use 3 or 5)", window)
            return []

        col = f"actual_change_t{window}"
        calendar_days = {3: 5, 5: 8}[window]
        cutoff = (datetime.now(UTC) - timedelta(days=calendar_days)).isoformat()

        # Build placeholders for directional types
        type_placeholders = ", ".join("?" for _ in _DIRECTIONAL_TYPES)
        params: list[Any] = list(_DIRECTIONAL_TYPES)
        params.append(cutoff)

        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT s.signal_id, s.signal_type, s.timestamp, "  # noqa: S608
                f"       s.assets, s.summary_short, s.confidence_score "
                f"FROM signals s "
                f"LEFT JOIN signal_outcomes o ON s.signal_id = o.signal_id "
                f"WHERE s.signal_type IN ({type_placeholders}) "
                f"  AND s.timestamp <= ? "
                f"  AND (o.{col} IS NULL OR o.signal_id IS NULL) "
                f"ORDER BY s.timestamp ASC",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def backfill_outcome(
        self,
        signal_id: str,
        window: int,
        actual_pct_change: float,
    ) -> bool:
        """Fill in actual_change_t{window} and correct_t{window}.

        Correctness is determined by comparing the signal's summary_short
        direction keywords against the sign of actual_pct_change.

        Args:
            signal_id: The signal to backfill.
            window: 3 or 5 (trading days after signal).
            actual_pct_change: Actual percentage price change.

        Returns:
            True if backfill was successful.
        """
        if window not in (3, 5):
            logger.warning("Invalid backfill window: %d", window)
            return False

        col_pct = f"actual_change_t{window}"
        col_correct = f"correct_t{window}"

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT summary_short FROM signals WHERE signal_id = ?",
                (signal_id,),
            ).fetchone()
            if not row:
                logger.warning("Signal %s not found", signal_id)
                return False

            summary = row["summary_short"]
            correct = _infer_correctness(summary, actual_pct_change)

            # Upsert into signal_outcomes
            conn.execute(
                f"""
                INSERT INTO signal_outcomes (signal_id, {col_pct}, {col_correct}, backfilled_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(signal_id) DO UPDATE SET
                    {col_pct} = excluded.{col_pct},
                    {col_correct} = excluded.{col_correct},
                    backfilled_at = excluded.backfilled_at
                """,  # noqa: S608
                (signal_id, actual_pct_change, correct),
            )
            conn.commit()

            correct_label = (
                "correct" if correct == 1 else "wrong" if correct == 0 else "unclear"
            )
            logger.info(
                "Backfilled %s T+%d: %.2f%% (%s)",
                signal_id,
                window,
                actual_pct_change * 100,
                correct_label,
            )
            return True
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Accuracy
    # ------------------------------------------------------------------

    def get_signal_accuracy(
        self,
        signal_type: str | None = None,
        window_days: int = 30,
    ) -> dict[str, Any]:
        """Return accuracy stats over the given window.

        If sample_count < 20, returns ``insufficient_data: true``
        and uses default accuracy 0.5.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()

        where_clauses = ["s.timestamp >= ?"]
        params: list[Any] = [cutoff]

        if signal_type is not None:
            where_clauses.append("s.signal_type = ?")
            params.append(signal_type)

        where = " AND ".join(where_clauses)

        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT o.correct_t3, o.correct_t5 "  # noqa: S608
                f"FROM signals s "
                f"JOIN signal_outcomes o ON s.signal_id = o.signal_id "
                f"WHERE {where}",
                params,
            ).fetchall()

            total = len(rows)
            correct_t3_vals = [
                r["correct_t3"] for r in rows if r["correct_t3"] is not None
            ]
            correct_t5_vals = [
                r["correct_t5"] for r in rows if r["correct_t5"] is not None
            ]

            sample_count = max(len(correct_t3_vals), len(correct_t5_vals))

            if sample_count < 20:
                return {
                    "signal_type": signal_type or "ALL",
                    "total": total,
                    "correct_t3": sum(correct_t3_vals) if correct_t3_vals else 0,
                    "correct_t5": sum(correct_t5_vals) if correct_t5_vals else 0,
                    "accuracy_t3": 0.5,
                    "accuracy_t5": 0.5,
                    "sample_count": sample_count,
                    "insufficient_data": True,
                }

            accuracy_t3 = (
                round(sum(correct_t3_vals) / len(correct_t3_vals), 4)
                if correct_t3_vals
                else None
            )
            accuracy_t5 = (
                round(sum(correct_t5_vals) / len(correct_t5_vals), 4)
                if correct_t5_vals
                else None
            )

            return {
                "signal_type": signal_type or "ALL",
                "total": total,
                "correct_t3": sum(correct_t3_vals),
                "correct_t5": sum(correct_t5_vals),
                "accuracy_t3": accuracy_t3,
                "accuracy_t5": accuracy_t5,
                "sample_count": sample_count,
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup(self, days: int = 90) -> int:
        """Delete signals (and their outcomes) older than N days.

        Returns the number of signals deleted.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        conn = self._connect()
        try:
            # Delete outcomes first (foreign key)
            conn.execute(
                """
                DELETE FROM signal_outcomes
                WHERE signal_id IN (
                    SELECT signal_id FROM signals WHERE timestamp < ?
                )
                """,
                (cutoff,),
            )
            cursor = conn.execute(
                "DELETE FROM signals WHERE timestamp < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            logger.info("Cleaned up %d signals older than %d days", deleted, days)
            return deleted
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_correctness(summary: str, actual_pct: float) -> int | None:
    """Infer if a signal's predicted direction was correct.

    Returns:
        1 if correct, 0 if wrong, None if direction unclear.
    """
    is_bullish = bool(_BULLISH_KEYWORDS.search(summary))
    is_bearish = bool(_BEARISH_KEYWORDS.search(summary))

    # If both or neither keyword matched, direction is ambiguous
    if is_bullish == is_bearish:
        return None

    if is_bullish:
        return 1 if actual_pct > 0 else 0
    else:  # is_bearish
        return 1 if actual_pct < 0 else 0

"""SQLite-backed decision outcome tracking for confidence calibration.

The LEARN phase of the OODA cycle: every trade decision is recorded and
its T+1/T+3/T+5 outcomes are backfilled as market data becomes available.
Accuracy statistics feed back into the agent's confidence calibration.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.agent_loop.models import DecisionOutcome

logger = logging.getLogger(__name__)

_VALID_HORIZONS = {"t1", "t3", "t5"}

# A-share transaction cost constants
COMMISSION_RATE = 0.0003  # 0.03% each way (broker commission)
STAMP_TAX_RATE = 0.001  # 0.1% sell only (government stamp tax)
SLIPPAGE_RATE = 0.0005  # 0.05% estimated slippage each way
ROUND_TRIP_COST = COMMISSION_RATE * 2 + STAMP_TAX_RATE + SLIPPAGE_RATE * 2  # ~0.21%


class DecisionLog:
    """CRUD operations for the ``decisions`` table in ``data/decisions.db``."""

    def __init__(self, db_path: str = "data/decisions.db") -> None:
        self._db_path = Path(db_path)
        self._ensure_table()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def record(
        self,
        proposal_id: str,
        symbol: str,
        action: str,
        price: float,
        sector: str = "",
    ) -> str:
        """Record a new decision. Returns the generated decision_id."""
        decision_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO decisions (
                    decision_id, proposal_id, symbol, action,
                    decided_at, decided_price, sector
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (decision_id, proposal_id, symbol, action, now, price, sector),
            )
            conn.commit()
            logger.info(
                "Decision recorded: %s %s %s @ %.4f (id=%s)",
                action,
                symbol,
                proposal_id,
                price,
                decision_id,
            )
        finally:
            conn.close()

        return decision_id

    def backfill_outcome(self, decision_id: str, horizon: str, price: float) -> None:
        """Backfill T+N outcome price and computed return/direction.

        Args:
            decision_id: UUID of the decision to update.
            horizon: One of ``'t1'``, ``'t3'``, ``'t5'``.
            price: The observed closing price at T+N.
        """
        if horizon not in _VALID_HORIZONS:
            raise ValueError(
                f"Invalid horizon {horizon!r}; must be one of {_VALID_HORIZONS}"
            )

        price_col = f"{horizon}_price"
        return_col = f"{horizon}_return_pct"

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT decided_price, action FROM decisions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
            if not row:
                logger.warning("Decision not found for backfill: %s", decision_id)
                return

            decided_price: float = row["decided_price"]
            action: str = row["action"]

            gross_return = (price - decided_price) / decided_price
            # Apply transaction costs for buy/add (implies future round-trip sell)
            if action.lower() in ("buy", "add"):
                net_return = gross_return - ROUND_TRIP_COST
            else:
                net_return = gross_return
            return_pct = net_return * 100.0
            direction_correct = self._check_direction(action, return_pct)

            conn.execute(
                f"""
                UPDATE decisions
                SET {price_col} = ?,
                    {return_col} = ?,
                    direction_correct = ?
                WHERE decision_id = ?
                """,
                (price, return_pct, direction_correct, decision_id),
            )
            conn.commit()
            logger.info(
                "Backfilled %s for %s: price=%.4f return=%.2f%% correct=%s",
                horizon,
                decision_id,
                price,
                return_pct,
                direction_correct,
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_pending_backfill(
        self, horizon: str, max_age_days: int = 30
    ) -> list[DecisionOutcome]:
        """Get decisions needing T+N backfill (price is NULL for that horizon).

        Only returns decisions within *max_age_days* to avoid stale backfills.
        """
        if horizon not in _VALID_HORIZONS:
            raise ValueError(
                f"Invalid horizon {horizon!r}; must be one of {_VALID_HORIZONS}"
            )

        price_col = f"{horizon}_price"
        cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()

        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM decisions
                WHERE {price_col} IS NULL
                  AND decided_at >= ?
                ORDER BY decided_at ASC
                """,
                (cutoff,),
            ).fetchall()
            return [self._row_to_outcome(r) for r in rows]
        finally:
            conn.close()

    def get_accuracy_stats(self, lookback_days: int = 30) -> dict:
        """Return accuracy statistics over the lookback window.

        Returns:
            Dictionary with keys: ``direction_accuracy``, ``avg_t1_return``,
            ``avg_t3_return``, ``avg_t5_return``, ``total_decisions``,
            ``profitable_decisions``, ``by_action``.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=lookback_days)).isoformat()

        conn = self._connect()
        try:
            # Overall stats
            overall = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN direction_correct = 1 THEN 1 ELSE 0 END)
                        AS correct,
                    SUM(CASE WHEN direction_correct IS NOT NULL THEN 1 ELSE 0 END)
                        AS evaluated,
                    SUM(CASE WHEN t1_return_pct > 0 THEN 1 ELSE 0 END)
                        AS profitable,
                    AVG(t1_return_pct) AS avg_t1,
                    AVG(t3_return_pct) AS avg_t3,
                    AVG(t5_return_pct) AS avg_t5
                FROM decisions
                WHERE decided_at >= ?
                """,
                (cutoff,),
            ).fetchone()

            total = overall["total"] or 0
            evaluated = overall["evaluated"] or 0
            correct = overall["correct"] or 0

            # Per-action breakdown
            action_rows = conn.execute(
                """
                SELECT
                    action,
                    COUNT(*) AS count,
                    SUM(CASE WHEN direction_correct = 1 THEN 1 ELSE 0 END)
                        AS correct,
                    SUM(CASE WHEN direction_correct IS NOT NULL THEN 1 ELSE 0 END)
                        AS evaluated
                FROM decisions
                WHERE decided_at >= ?
                GROUP BY action
                """,
                (cutoff,),
            ).fetchall()

            by_action: dict[str, dict] = {}
            for row in action_rows:
                act_evaluated = row["evaluated"] or 0
                by_action[row["action"]] = {
                    "count": row["count"],
                    "accuracy": (row["correct"] / act_evaluated)
                    if act_evaluated > 0
                    else None,
                }

            return {
                "direction_accuracy": (correct / evaluated) if evaluated > 0 else None,
                "avg_t1_return": overall["avg_t1"],
                "avg_t3_return": overall["avg_t3"],
                "avg_t5_return": overall["avg_t5"],
                "total_decisions": total,
                "profitable_decisions": overall["profitable"] or 0,
                "by_action": by_action,
            }
        finally:
            conn.close()

    def get_sector_stats(
        self, sector: str, lookback_days: int = 60
    ) -> dict[str, float] | None:
        """Compute win rate statistics for a given sector.

        Args:
            sector: Sector name to filter by.
            lookback_days: How far back to look.

        Returns:
            Dictionary with ``win_rate`` and ``sample_count``, or None if
            the sector column has no data.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=lookback_days)).isoformat()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN direction_correct = 1 THEN 1 ELSE 0 END)
                        AS correct,
                    SUM(CASE WHEN direction_correct IS NOT NULL THEN 1 ELSE 0 END)
                        AS evaluated
                FROM decisions
                WHERE sector = ? AND decided_at >= ?
                """,
                (sector, cutoff),
            ).fetchone()

            evaluated = row["evaluated"] or 0
            if evaluated == 0:
                return None

            return {
                "win_rate": (row["correct"] or 0) / evaluated,
                "sample_count": evaluated,
            }
        except Exception as exc:
            logger.warning("Failed to get sector stats for %s: %s", sector, exc)
            return None
        finally:
            conn.close()

    def get_historical_stats(
        self, action: str, lookback_days: int = 90
    ) -> dict[str, float]:
        """Compute win/loss statistics from completed outcomes for Kelly sizing.

        Args:
            action: Trade action to filter by (e.g. ``'buy'``, ``'sell'``).
            lookback_days: How far back to look for completed decisions.

        Returns:
            Dictionary with keys: ``win_rate``, ``avg_win``, ``avg_loss``,
            ``sample_count``.  If sample_count < 20, returns conservative
            defaults to avoid overfitting on sparse data.
        """
        conservative_defaults = {
            "win_rate": 0.45,
            "avg_win": 0.03,
            "avg_loss": 0.03,
            "sample_count": 0,
        }

        cutoff = (datetime.now(UTC) - timedelta(days=lookback_days)).isoformat()
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT t1_return_pct
                FROM decisions
                WHERE action IN (?, ?)
                  AND t1_return_pct IS NOT NULL
                  AND decided_at >= ?
                """,
                (action.lower(), action.capitalize(), cutoff),
            ).fetchall()

            if len(rows) < 20:
                conservative_defaults["sample_count"] = len(rows)
                return conservative_defaults

            returns = [r["t1_return_pct"] / 100.0 for r in rows]  # convert to decimal
            wins = [r for r in returns if r > 0]
            losses = [r for r in returns if r <= 0]

            win_rate = len(wins) / len(returns) if returns else 0.45
            avg_win = sum(wins) / len(wins) if wins else 0.03
            avg_loss = abs(sum(losses) / len(losses)) if losses else 0.03

            return {
                "win_rate": round(win_rate, 4),
                "avg_win": round(avg_win, 4),
                "avg_loss": round(avg_loss, 4),
                "sample_count": len(returns),
            }
        except Exception as exc:
            logger.warning("Failed to compute historical stats: %s", exc)
            return conservative_defaults
        finally:
            conn.close()

    def get_recent(self, limit: int = 20) -> list[DecisionOutcome]:
        """Get the most recent decisions, ordered newest-first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM decisions ORDER BY decided_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_outcome(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_direction(action: str, return_pct: float) -> bool:
        """Determine if the action's direction was correct.

        Buy/add are correct when return > 0; sell/reduce when return < 0.
        """
        action_lower = action.lower()
        if action_lower in ("buy", "add"):
            return return_pct > 0
        if action_lower in ("sell", "reduce"):
            return return_pct < 0
        # hold — correct if price didn't move significantly
        return abs(return_pct) < 1.0

    @staticmethod
    def _row_to_outcome(row: sqlite3.Row) -> DecisionOutcome:
        """Convert a DB row to :class:`DecisionOutcome`."""
        # sector column may not exist in older DBs before migration runs
        try:
            sector = row["sector"] or ""
        except (IndexError, KeyError):
            sector = ""
        return DecisionOutcome(
            decision_id=row["decision_id"],
            proposal_id=row["proposal_id"],
            symbol=row["symbol"],
            action=row["action"],
            decided_at=datetime.fromisoformat(row["decided_at"]),
            decided_price=row["decided_price"],
            t1_price=row["t1_price"],
            t3_price=row["t3_price"],
            t5_price=row["t5_price"],
            t1_return_pct=row["t1_return_pct"],
            t3_return_pct=row["t3_return_pct"],
            t5_return_pct=row["t5_return_pct"],
            direction_correct=bool(row["direction_correct"])
            if row["direction_correct"] is not None
            else None,
            sector=sector,
        )

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection (thread-safe pattern)."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_table(self) -> None:
        """Create the ``decisions`` table if it does not exist."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    decided_price REAL NOT NULL,
                    t1_price REAL,
                    t3_price REAL,
                    t5_price REAL,
                    t1_return_pct REAL,
                    t3_return_pct REAL,
                    t5_return_pct REAL,
                    direction_correct INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON decisions(symbol)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_decided_at "
                "ON decisions(decided_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_proposal "
                "ON decisions(proposal_id)"
            )
            # v-next migration: add sector column for sector-level calibration
            self._migrate_sector_column(conn)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate_sector_column(conn: sqlite3.Connection) -> None:
        """Add ``sector`` column if missing."""
        cursor = conn.execute("PRAGMA table_info(decisions)")
        existing = {row[1] for row in cursor.fetchall()}
        if "sector" not in existing:
            conn.execute("ALTER TABLE decisions ADD COLUMN sector TEXT DEFAULT ''")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_sector ON decisions(sector)"
            )
            logger.info("Migrated: added sector column to decisions")

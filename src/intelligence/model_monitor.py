"""Model monitoring — prediction recording, accuracy backfill, drift detection.

Part of v18.0 Intelligence Loop.

Tracks every prediction the system makes, back-fills actual outcomes
after T+3/T+5/T+10 trading days, and detects when model accuracy
drifts below the historical baseline.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DB_DIR = Path("data")


@dataclass
class PredictionRecord:
    """A recorded prediction with optional backfilled accuracy."""

    prediction_id: str
    symbol: str
    predicted_at: str  # ISO date
    predicted_direction: str  # "bullish", "bearish", "neutral"
    predicted_confidence: float
    agent_name: str = ""
    context_snapshot: str = ""  # JSON string of analysis context

    # Backfilled fields (None until backfill runs)
    actual_pct_t3: float | None = None
    actual_pct_t5: float | None = None
    actual_pct_t10: float | None = None
    correct_t3: bool | None = None
    correct_t5: bool | None = None
    correct_t10: bool | None = None


@dataclass
class DriftReport:
    """Result of drift detection analysis."""

    window_days: int
    total_predictions: int
    accuracy_t3: float | None  # Rolling accuracy at T+3
    accuracy_t5: float | None
    accuracy_t10: float | None
    baseline_accuracy: float
    drift_detected: bool
    drift_amount: float  # How much accuracy dropped from baseline
    warnings: list[str] = field(default_factory=list)


@dataclass
class MonitorConfig:
    """Configuration for model monitoring."""

    backfill_windows: list[int] = field(default_factory=lambda: [3, 5, 10])
    drift_window: int = 30
    baseline_accuracy: float = 0.50
    drift_threshold: float = 0.15
    min_predictions: int = 20
    db_path: str = "data/monitor.db"


class ModelMonitor:
    """Tracks predictions, backfills accuracy, detects drift.

    Stores all predictions in SQLite. On backfill, compares
    predicted direction against actual price movement.
    """

    def __init__(self, config: MonitorConfig | None = None):
        self.config = config or MonitorConfig()
        self._db_path = Path(self.config.db_path)
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create database tables if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    prediction_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    predicted_at TEXT NOT NULL,
                    predicted_direction TEXT NOT NULL,
                    predicted_confidence REAL NOT NULL,
                    agent_name TEXT DEFAULT '',
                    context_snapshot TEXT DEFAULT '',
                    actual_pct_t3 REAL,
                    actual_pct_t5 REAL,
                    actual_pct_t10 REAL,
                    correct_t3 INTEGER,
                    correct_t5 INTEGER,
                    correct_t10 INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_predictions_symbol_date
                ON predictions(symbol, predicted_at)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def record_prediction(
        self,
        symbol: str,
        direction: str,
        confidence: float,
        agent_name: str = "",
        context: dict[str, Any] | None = None,
        prediction_date: date | None = None,
    ) -> str:
        """Record a new prediction. Returns prediction_id."""
        prediction_id = str(uuid.uuid4())[:12]
        pred_date = (prediction_date or date.today()).isoformat()
        context_json = json.dumps(context or {}, ensure_ascii=False)

        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                """
                INSERT INTO predictions
                    (prediction_id, symbol, predicted_at, predicted_direction,
                     predicted_confidence, agent_name, context_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prediction_id,
                    symbol,
                    pred_date,
                    direction,
                    confidence,
                    agent_name,
                    context_json,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info(
            "Recorded prediction %s: %s %s (%.0f%%)",
            prediction_id,
            symbol,
            direction,
            confidence * 100,
        )
        return prediction_id

    def backfill_outcome(
        self,
        prediction_id: str,
        window: int,
        actual_pct_change: float,
    ) -> bool:
        """Backfill actual outcome for a prediction at T+window.

        Args:
            prediction_id: The prediction to update.
            window: 3, 5, or 10 (trading days after prediction).
            actual_pct_change: Actual percentage price change.

        Returns:
            True if backfill was successful.
        """
        if window not in (3, 5, 10):
            logger.warning("Invalid backfill window: %d", window)
            return False

        col_pct = f"actual_pct_t{window}"
        col_correct = f"correct_t{window}"

        conn = sqlite3.connect(str(self._db_path))
        try:
            row = conn.execute(
                "SELECT predicted_direction FROM predictions WHERE prediction_id = ?",
                (prediction_id,),
            ).fetchone()
            if not row:
                logger.warning("Prediction %s not found", prediction_id)
                return False

            direction = row[0]
            correct = _check_direction_correct(direction, actual_pct_change)

            conn.execute(
                f"UPDATE predictions SET {col_pct} = ?, {col_correct} = ? WHERE prediction_id = ?",  # noqa: S608
                (actual_pct_change, int(correct), prediction_id),
            )
            conn.commit()
            logger.info(
                "Backfilled %s T+%d: %.2f%% (%s)",
                prediction_id,
                window,
                actual_pct_change * 100,
                "correct" if correct else "wrong",
            )
            return True
        finally:
            conn.close()

    def get_pending_backfills(self, window: int) -> list[dict[str, Any]]:
        """Get predictions that need T+window backfill.

        Returns predictions where the predicted_at date is at least
        `window` trading days ago and the actual outcome hasn't been filled.
        """
        col_pct = f"actual_pct_t{window}"
        cutoff = (date.today() - timedelta(days=window + 5)).isoformat()

        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"SELECT prediction_id, symbol, predicted_at FROM predictions "  # noqa: S608
                f"WHERE {col_pct} IS NULL AND predicted_at <= ?",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def detect_drift(
        self,
        symbol: str | None = None,
    ) -> DriftReport:
        """Detect accuracy drift over the rolling window.

        Compares recent accuracy against baseline.
        If accuracy drops by more than drift_threshold, triggers alert.
        """
        window = self.config.drift_window
        cutoff = (date.today() - timedelta(days=window + 5)).isoformat()

        conn = sqlite3.connect(str(self._db_path))
        try:
            where = "predicted_at >= ?"
            params: list[Any] = [cutoff]
            if symbol:
                where += " AND symbol = ?"
                params.append(symbol)

            rows = conn.execute(
                f"SELECT correct_t3, correct_t5, correct_t10 "  # noqa: S608
                f"FROM predictions WHERE {where}",
                params,
            ).fetchall()

            total = len(rows)
            warnings: list[str] = []

            if total < self.config.min_predictions:
                warnings.append(
                    f"预测样本不足: {total} < {self.config.min_predictions}"
                )
                return DriftReport(
                    window_days=window,
                    total_predictions=total,
                    accuracy_t3=None,
                    accuracy_t5=None,
                    accuracy_t10=None,
                    baseline_accuracy=self.config.baseline_accuracy,
                    drift_detected=False,
                    drift_amount=0.0,
                    warnings=warnings,
                )

            # Calculate rolling accuracy per window
            acc_t3 = _calc_accuracy([r[0] for r in rows])
            acc_t5 = _calc_accuracy([r[1] for r in rows])
            acc_t10 = _calc_accuracy([r[2] for r in rows])

            # Use T+5 as primary drift metric
            primary_acc = acc_t5 if acc_t5 is not None else acc_t3
            drift_amount = 0.0
            drift_detected = False

            if primary_acc is not None:
                drift_amount = self.config.baseline_accuracy - primary_acc
                if drift_amount >= self.config.drift_threshold:
                    drift_detected = True
                    warnings.append(
                        f"准确率漂移告警: 当前 {primary_acc:.1%} vs 基线 "
                        f"{self.config.baseline_accuracy:.1%}, "
                        f"下降 {drift_amount:.1%}"
                    )

            return DriftReport(
                window_days=window,
                total_predictions=total,
                accuracy_t3=acc_t3,
                accuracy_t5=acc_t5,
                accuracy_t10=acc_t10,
                baseline_accuracy=self.config.baseline_accuracy,
                drift_detected=drift_detected,
                drift_amount=round(drift_amount, 4),
                warnings=warnings,
            )
        finally:
            conn.close()

    def get_accuracy_summary(
        self,
        symbol: str | None = None,
        days: int = 90,
    ) -> dict[str, Any]:
        """Get accuracy summary for display in system prompts."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        conn = sqlite3.connect(str(self._db_path))
        try:
            where = "predicted_at >= ?"
            params: list[Any] = [cutoff]
            if symbol:
                where += " AND symbol = ?"
                params.append(symbol)

            rows = conn.execute(
                f"SELECT correct_t3, correct_t5, correct_t10 "  # noqa: S608
                f"FROM predictions WHERE {where}",
                params,
            ).fetchall()

            total = len(rows)
            return {
                "total_predictions": total,
                "accuracy_t3": _calc_accuracy([r[0] for r in rows]),
                "accuracy_t5": _calc_accuracy([r[1] for r in rows]),
                "accuracy_t10": _calc_accuracy([r[2] for r in rows]),
                "period_days": days,
            }
        finally:
            conn.close()

    def get_predictions(
        self,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[PredictionRecord]:
        """Get recent prediction records."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            where = "1=1"
            params: list[Any] = []
            if symbol:
                where = "symbol = ?"
                params.append(symbol)

            rows = conn.execute(
                f"SELECT * FROM predictions WHERE {where} "  # noqa: S608
                f"ORDER BY predicted_at DESC LIMIT ?",
                [*params, limit],
            ).fetchall()

            return [
                PredictionRecord(
                    prediction_id=r["prediction_id"],
                    symbol=r["symbol"],
                    predicted_at=r["predicted_at"],
                    predicted_direction=r["predicted_direction"],
                    predicted_confidence=r["predicted_confidence"],
                    agent_name=r["agent_name"],
                    context_snapshot=r["context_snapshot"],
                    actual_pct_t3=r["actual_pct_t3"],
                    actual_pct_t5=r["actual_pct_t5"],
                    actual_pct_t10=r["actual_pct_t10"],
                    correct_t3=bool(r["correct_t3"])
                    if r["correct_t3"] is not None
                    else None,
                    correct_t5=bool(r["correct_t5"])
                    if r["correct_t5"] is not None
                    else None,
                    correct_t10=bool(r["correct_t10"])
                    if r["correct_t10"] is not None
                    else None,
                )
                for r in rows
            ]
        finally:
            conn.close()


def _check_direction_correct(direction: str, actual_pct: float) -> bool:
    """Check if predicted direction matches actual price movement."""
    if direction == "bullish":
        return actual_pct > 0
    elif direction == "bearish":
        return actual_pct < 0
    else:  # neutral
        return abs(actual_pct) < 0.02  # within 2% is "correct" for neutral


def _calc_accuracy(values: list[int | None]) -> float | None:
    """Calculate accuracy from a list of 0/1/None correct flags."""
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return round(sum(valid) / len(valid), 4)

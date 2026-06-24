"""Adaptive confidence calibration from decision outcomes.

Phase 5 — FR-ALL001/ALL002: Tracks per-symbol and per-action accuracy,
computes calibration adjustments, and adapts strategy parameters based
on market regime.

The calibrator answers: "How much should I trust my own predictions?"
- Historically overconfident → penalize future confidence
- Historically underconfident → boost future confidence
- Per-sector accuracy tracking → sector-specific adjustments
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.agent_loop.models import DecisionOutcome

logger = logging.getLogger(__name__)


class ConfidenceCalibrator:
    """Learns from past decision outcomes to calibrate future confidence.

    Uses the same ``decisions.db`` as :class:`DecisionLog`, reading
    outcome data to compute calibration factors.
    """

    def __init__(
        self,
        db_path: str = "data/decisions.db",
        config: dict[str, Any] | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        cfg = config or {}
        self._lookback_days = cfg.get("calibration_lookback_days", 60)
        self._min_samples = cfg.get("min_samples_for_calibration", 5)
        self._max_boost = cfg.get("max_confidence_boost", 0.15)
        self._max_penalty = cfg.get("max_confidence_penalty", 0.20)
        self._regime_adjustments: dict[str, dict[str, float]] = cfg.get(
            "regime_adjustments", _DEFAULT_REGIME_ADJUSTMENTS
        )

    def calibrate(
        self,
        raw_confidence: float,
        symbol: str,
        action: str,
        sector: str = "",
        regime: str = "unknown",
    ) -> float:
        """Apply calibration to raw confidence score.

        Adjustments applied in order:
        1. Historical accuracy-based adjustment (per-action)
        2. Per-sector accuracy adjustment
        3. Regime-based adjustment
        """
        adjustment = 0.0

        # 1. Action-level calibration
        action_adj = self._action_calibration(action)
        adjustment += action_adj

        # 2. Sector-level calibration
        if sector:
            sector_adj = self._sector_calibration(sector)
            adjustment += sector_adj

        # 3. Regime adjustment
        regime_adj = self._regime_adjustment(regime, action)
        adjustment += regime_adj

        # Clamp total adjustment
        adjustment = max(-self._max_penalty, min(self._max_boost, adjustment))

        calibrated = max(0.0, min(1.0, raw_confidence + adjustment))

        if abs(adjustment) > 0.01:
            logger.debug(
                "Calibration %s %s: %.2f → %.2f (action=%.3f sector=%.3f regime=%.3f)",
                action,
                symbol,
                raw_confidence,
                calibrated,
                action_adj,
                sector_adj if sector else 0.0,
                regime_adj,
            )

        return calibrated

    def update_from_outcomes(self, outcomes: list[DecisionOutcome]) -> None:
        """Ingest completed outcomes and refresh internal accuracy caches.

        For each outcome with a ``direction_correct`` value, update
        per-action and per-sector accuracy counters in the decisions DB
        so that subsequent ``calibrate()`` calls reflect the latest data.

        This is the bridge between OutcomeTracker (which evaluates T+N
        prices) and the calibrator (which adjusts future confidence).
        """
        if not outcomes:
            return

        conn = self._connect()
        if not conn:
            logger.debug("No decisions DB — skipping outcome update")
            return

        try:
            updated = 0
            for outcome in outcomes:
                if outcome.direction_correct is None:
                    continue

                # Upsert outcome data into decisions table
                conn.execute(
                    """
                    UPDATE decisions
                    SET t1_price = COALESCE(t1_price, ?),
                        t3_price = COALESCE(t3_price, ?),
                        t5_price = COALESCE(t5_price, ?),
                        t1_return_pct = COALESCE(t1_return_pct, ?),
                        t3_return_pct = COALESCE(t3_return_pct, ?),
                        t5_return_pct = COALESCE(t5_return_pct, ?),
                        direction_correct = COALESCE(direction_correct, ?)
                    WHERE proposal_id = ?
                    """,
                    (
                        outcome.t1_price,
                        outcome.t3_price,
                        outcome.t5_price,
                        outcome.t1_return_pct,
                        outcome.t3_return_pct,
                        outcome.t5_return_pct,
                        1 if outcome.direction_correct else 0,
                        outcome.proposal_id,
                    ),
                )
                updated += conn.total_changes

            conn.commit()
            if updated > 0:
                logger.info(
                    "Calibrator updated %d decisions from %d outcomes",
                    updated,
                    len(outcomes),
                )
        except Exception as exc:
            logger.warning("Failed to update calibrator from outcomes: %s", exc)
        finally:
            conn.close()

    def get_calibration_report(self) -> dict[str, Any]:
        """Generate a full calibration report for dashboard display."""
        conn = self._connect()
        if not conn:
            return {"status": "no_data"}

        try:
            cutoff = (
                datetime.now(UTC) - timedelta(days=self._lookback_days)
            ).isoformat()

            # Per-action accuracy
            action_stats = self._query_action_stats(conn, cutoff)

            # Per-sector accuracy (requires symbol→sector mapping)
            overall = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN direction_correct = 1 THEN 1 ELSE 0 END) AS correct,
                    SUM(CASE WHEN direction_correct IS NOT NULL THEN 1 ELSE 0 END)
                        AS evaluated,
                    AVG(t1_return_pct) AS avg_t1,
                    AVG(t3_return_pct) AS avg_t3,
                    AVG(t5_return_pct) AS avg_t5
                FROM decisions WHERE decided_at >= ?
                """,
                (cutoff,),
            ).fetchone()

            total = overall["total"] or 0
            evaluated = overall["evaluated"] or 0
            correct = overall["correct"] or 0

            return {
                "status": "ok",
                "lookback_days": self._lookback_days,
                "total_decisions": total,
                "evaluated_decisions": evaluated,
                "overall_accuracy": (correct / evaluated) if evaluated > 0 else None,
                "avg_returns": {
                    "t1": overall["avg_t1"],
                    "t3": overall["avg_t3"],
                    "t5": overall["avg_t5"],
                },
                "by_action": action_stats,
                "calibration_active": evaluated >= self._min_samples,
            }
        finally:
            conn.close()

    def get_regime_params(self, regime: str) -> dict[str, float]:
        """Get strategy parameter adjustments for current market regime.

        FR-ALL002: Auto-adjust position sizes, stop-loss distances, and
        style preferences based on detected regime.
        """
        return _REGIME_STRATEGY_PARAMS.get(regime, _REGIME_STRATEGY_PARAMS["unknown"])

    # ------------------------------------------------------------------
    # Internal calibration methods
    # ------------------------------------------------------------------

    def _action_calibration(self, action: str) -> float:
        """Compute confidence adjustment based on historical action accuracy."""
        conn = self._connect()
        if not conn:
            return 0.0

        try:
            cutoff = (
                datetime.now(UTC) - timedelta(days=self._lookback_days)
            ).isoformat()

            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN direction_correct = 1 THEN 1 ELSE 0 END) AS correct,
                    SUM(CASE WHEN direction_correct IS NOT NULL THEN 1 ELSE 0 END)
                        AS evaluated
                FROM decisions
                WHERE action = ? AND decided_at >= ?
                """,
                (action, cutoff),
            ).fetchone()

            evaluated = row["evaluated"] or 0
            if evaluated < self._min_samples:
                return 0.0

            accuracy = (row["correct"] or 0) / evaluated

            # If accuracy > 60%, we're good → small boost
            # If accuracy < 40%, we're bad → penalize
            # Linear mapping: 50% → 0, 70% → +max_boost, 30% → -max_penalty
            if accuracy >= 0.5:
                return min(self._max_boost, (accuracy - 0.5) * self._max_boost / 0.2)
            else:
                return max(
                    -self._max_penalty, (accuracy - 0.5) * self._max_penalty / 0.2
                )

        finally:
            conn.close()

    def _sector_calibration(self, sector: str) -> float:
        """Compute confidence adjustment based on sector-level accuracy."""
        # Sector tracking would require joining decisions with thesis/symbol metadata.
        # For now, return 0 — will be enhanced when we add sector to decisions table.
        return 0.0

    def _regime_adjustment(self, regime: str, action: str) -> float:
        """Apply regime-based confidence adjustment."""
        adjustments = self._regime_adjustments.get(regime, {})
        return adjustments.get(action, adjustments.get("default", 0.0))

    def _query_action_stats(
        self, conn: sqlite3.Connection, cutoff: str
    ) -> dict[str, dict[str, Any]]:
        """Query per-action accuracy stats."""
        rows = conn.execute(
            """
            SELECT
                action,
                COUNT(*) AS total,
                SUM(CASE WHEN direction_correct = 1 THEN 1 ELSE 0 END) AS correct,
                SUM(CASE WHEN direction_correct IS NOT NULL THEN 1 ELSE 0 END)
                    AS evaluated,
                AVG(t1_return_pct) AS avg_t1,
                AVG(t3_return_pct) AS avg_t3
            FROM decisions
            WHERE decided_at >= ?
            GROUP BY action
            """,
            (cutoff,),
        ).fetchall()

        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            evaluated = row["evaluated"] or 0
            result[row["action"]] = {
                "total": row["total"],
                "evaluated": evaluated,
                "accuracy": (row["correct"] / evaluated) if evaluated > 0 else None,
                "avg_t1_return": row["avg_t1"],
                "avg_t3_return": row["avg_t3"],
            }
        return result

    def _connect(self) -> sqlite3.Connection | None:
        """Connect to decisions DB. Returns None if DB doesn't exist."""
        if not self._db_path.exists():
            return None
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn


# -- Default regime adjustments --
# Penalize buys in bear markets, boost in bull markets
_DEFAULT_REGIME_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "bull": {"buy": 0.05, "add": 0.05, "sell": -0.05, "default": 0.0},
    "bear": {"buy": -0.10, "add": -0.10, "sell": 0.05, "reduce": 0.05, "default": 0.0},
    "high_volatility": {"buy": -0.08, "add": -0.08, "default": -0.03},
    "low_volatility": {"buy": 0.03, "default": 0.0},
    "unknown": {"default": 0.0},
}

# -- Regime-specific strategy parameter multipliers --
# Applied to position_size, stop_loss_distance, take_profit_distance
_REGIME_STRATEGY_PARAMS: dict[str, dict[str, float]] = {
    "bull": {
        "position_size_factor": 1.2,  # Larger positions in bull
        "stop_loss_factor": 0.8,  # Tighter stops (trending up)
        "take_profit_factor": 1.3,  # Let winners run
        "max_position_pct": 0.35,  # Allow slightly larger positions
    },
    "bear": {
        "position_size_factor": 0.6,  # Much smaller positions
        "stop_loss_factor": 0.7,  # Tighter stops (protect capital)
        "take_profit_factor": 0.8,  # Take profits quickly
        "max_position_pct": 0.20,  # Conservative position limits
    },
    "high_volatility": {
        "position_size_factor": 0.5,  # Smallest positions
        "stop_loss_factor": 1.5,  # Wider stops (avoid whipsaw)
        "take_profit_factor": 1.2,  # Wider targets
        "max_position_pct": 0.20,
    },
    "low_volatility": {
        "position_size_factor": 1.0,
        "stop_loss_factor": 1.0,
        "take_profit_factor": 1.0,
        "max_position_pct": 0.30,
    },
    "unknown": {
        "position_size_factor": 0.8,  # Conservative when uncertain
        "stop_loss_factor": 1.0,
        "take_profit_factor": 1.0,
        "max_position_pct": 0.25,
    },
}

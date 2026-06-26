"""Outcome Tracker — tracks T+1/T+3/T+5 outcomes for every signal.

This is the core feedback loop that enables the system to learn from its
decisions. Every signal and proposal is recorded, then checked at T+1, T+3,
and T+5 to determine if the predicted direction was correct.

Results feed back into:
- BayesianBeliefEngine likelihood table calibration
- ConfidenceCalibrator accuracy computation
- Missed opportunity detection
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.agent_loop.models import (
    AggregatedSignal,
    DecisionOutcome,
    TradeProposal,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/outcome_tracker.db")


@dataclass
class MissedOpportunity:
    """A stock that moved significantly without any system signal."""

    symbol: str
    name: str
    date: str
    daily_return_pct: float
    had_data: bool  # Did we have data that could have triggered?
    preventable: bool  # Could the system have caught it?
    reason: str  # Why did we miss it?

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "date": self.date,
            "daily_return_pct": self.daily_return_pct,
            "had_data": self.had_data,
            "preventable": self.preventable,
            "reason": self.reason,
        }


@dataclass
class SourceAccuracy:
    """Accuracy metrics for a signal source."""

    source: str
    total_signals: int
    direction_correct: int
    accuracy: float
    avg_return_correct: float  # avg return when direction correct
    avg_return_incorrect: float  # avg return when direction incorrect
    lookback_days: int


class OutcomeTracker:
    """Tracks signal outcomes for calibration and learning.

    Schema:
    - signals: every signal generated (with source, confidence, direction)
    - outcomes: T+1/3/5 price lookups for each signal
    - missed: stocks that moved >5% without a signal
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._calendar: Any = None

    def _add_trading_days(self, start: datetime, n: int):
        """Return the date ``n`` *trading* days after ``start``.

        T+1/T+3/T+5 are trading-session horizons, not calendar days — a T+1
        lookup after a Friday signal must land on the next session (Monday),
        not Saturday. Falls back to calendar days if the calendar is unavailable.
        """
        try:
            if self._calendar is None:
                from src.data.trading_calendar import TradingCalendar

                self._calendar = TradingCalendar()
            d = start.date()
            for _ in range(n):
                d = self._calendar.next_trading_day(d)
            return d
        except Exception:
            return (start + timedelta(days=n)).date()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tracked_signals (
                    signal_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    direction TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    urgency TEXT DEFAULT 'normal',
                    reason TEXT DEFAULT '',
                    entry_price REAL,
                    proposal_id TEXT,
                    proposal_action TEXT,
                    proposal_confidence REAL,
                    sector TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    -- Outcome fields (filled later)
                    t1_price REAL,
                    t3_price REAL,
                    t5_price REAL,
                    t1_return_pct REAL,
                    t3_return_pct REAL,
                    t5_return_pct REAL,
                    direction_correct INTEGER,  -- 0/1/NULL
                    evaluated_at TEXT,
                    status TEXT DEFAULT 'pending'  -- pending/partial/complete
                );

                CREATE TABLE IF NOT EXISTS missed_opportunities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    date TEXT NOT NULL,
                    daily_return_pct REAL NOT NULL,
                    had_data INTEGER DEFAULT 0,
                    preventable INTEGER DEFAULT 0,
                    reason TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tracked_status
                    ON tracked_signals(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_tracked_source
                    ON tracked_signals(source, direction_correct);
                CREATE INDEX IF NOT EXISTS idx_tracked_symbol
                    ON tracked_signals(symbol, created_at);
                CREATE INDEX IF NOT EXISTS idx_missed_date
                    ON missed_opportunities(date);
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ------------------------------------------------------------------
    # Record signals and proposals
    # ------------------------------------------------------------------

    async def record_signal(
        self, signal: AggregatedSignal, proposal: TradeProposal | None = None
    ) -> None:
        """Record a generated signal for later outcome evaluation."""
        entry_price = None
        if proposal:
            entry_price = proposal.price_target or proposal.stop_loss
        if not entry_price and signal.metadata:
            entry_price = signal.metadata.get(
                "entry_price",
                signal.metadata.get("price", signal.metadata.get("close")),
            )

        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO tracked_signals
                    (signal_id, symbol, name, direction, source, confidence,
                     urgency, reason, entry_price, proposal_id, proposal_action,
                     proposal_confidence, sector, created_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                    (
                        signal.signal_id,
                        signal.symbol,
                        signal.name,
                        signal.direction.value,
                        signal.source,
                        signal.confidence,
                        signal.urgency.value,
                        signal.reason[:500],
                        entry_price,
                        proposal.proposal_id if proposal else None,
                        proposal.action if proposal else None,
                        proposal.confidence if proposal else None,
                        "",
                        datetime.now(UTC).isoformat(),
                    ),
                )
            logger.debug(
                "Recorded signal %s for %s", signal.signal_id[:8], signal.symbol
            )
        except Exception as exc:
            logger.warning("Failed to record signal: %s", exc)

    def track_decision(
        self,
        symbol: str,
        action: str,
        confidence: float,
        entry_price: float | None = None,
        source: str = "heartbeat_agent",
        name: str = "",
        sector: str = "",
    ) -> None:
        """Record a trading decision for T+1/3/5 outcome tracking.

        Lightweight entry point for DecisionHandler — does not require
        AggregatedSignal or TradeProposal objects.

        Args:
            symbol: 6-digit stock code.
            action: buy/sell/add/reduce.
            confidence: Decision confidence (0-1).
            entry_price: Price at decision time.
            source: Decision source (default: heartbeat_agent).
            name: Stock name.
            sector: Sector name.
        """
        if not symbol or action not in ("buy", "sell", "add", "reduce"):
            return

        import uuid

        signal_id = str(uuid.uuid4())
        direction = action  # buy/add = bullish, sell/reduce = bearish

        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO tracked_signals
                    (signal_id, symbol, name, direction, source, confidence,
                     urgency, reason, entry_price, proposal_id, proposal_action,
                     proposal_confidence, sector, created_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'normal', '', ?, ?, ?, ?, ?, ?, 'pending')""",
                    (
                        signal_id,
                        symbol,
                        name,
                        direction,
                        source,
                        confidence,
                        entry_price,
                        signal_id,
                        action,
                        confidence,
                        sector,
                        datetime.now(UTC).isoformat(),
                    ),
                )
            logger.info(
                "OutcomeTracker: tracking %s %s @ %.2f (conf=%.2f)",
                action,
                symbol,
                entry_price or 0,
                confidence,
            )
        except Exception as exc:
            logger.warning("Failed to track decision: %s", exc)

    # ------------------------------------------------------------------
    # Evaluate pending outcomes
    # ------------------------------------------------------------------

    async def evaluate_pending(
        self, price_fetcher: Any = None
    ) -> list[DecisionOutcome]:
        """Check T+1/T+3/T+5 outcomes for pending signals.

        Args:
            price_fetcher: Callable that accepts (symbol, date) and returns price.
                If None, skips evaluation (caller should provide).
        """
        outcomes: list[DecisionOutcome] = []
        now = datetime.now(UTC)

        with self._conn() as conn:
            rows = conn.execute(
                """SELECT signal_id, symbol, name, direction, source,
                          confidence, entry_price, created_at, status,
                          t1_price, t3_price, t5_price
                   FROM tracked_signals
                   WHERE status IN ('pending', 'partial')
                   AND created_at < ?
                   ORDER BY created_at ASC
                   LIMIT 100""",
                ((now - timedelta(days=1)).isoformat(),),
            ).fetchall()

        if not rows or not price_fetcher:
            return outcomes

        for row in rows:
            (
                signal_id,
                symbol,
                name,
                direction,
                source,
                confidence,
                entry_price,
                created_at_str,
                status,
                t1_price,
                t3_price,
                t5_price,
            ) = row

            if not entry_price:
                continue

            created_at = datetime.fromisoformat(created_at_str)
            today = now.date()

            # Trading-day horizons (T+N = N trading sessions, not calendar days)
            t1_date = self._add_trading_days(created_at, 1)
            t3_date = self._add_trading_days(created_at, 3)
            t5_date = self._add_trading_days(created_at, 5)

            updates: dict[str, Any] = {}
            new_status = status

            # T+1 evaluation
            if t1_price is None and t1_date <= today:
                try:
                    price = await price_fetcher(symbol, t1_date.strftime("%Y-%m-%d"))
                    if price:
                        t1_return = (price - entry_price) / entry_price
                        updates["t1_price"] = price
                        updates["t1_return_pct"] = round(t1_return * 100, 2)
                        new_status = "partial"
                except Exception:
                    pass

            # T+3 evaluation
            if t3_price is None and t3_date <= today:
                try:
                    price = await price_fetcher(symbol, t3_date.strftime("%Y-%m-%d"))
                    if price:
                        t3_return = (price - entry_price) / entry_price
                        updates["t3_price"] = price
                        updates["t3_return_pct"] = round(t3_return * 100, 2)
                        new_status = "partial"
                except Exception:
                    pass

            # T+5 evaluation (final)
            if t5_price is None and t5_date <= today:
                try:
                    price = await price_fetcher(symbol, t5_date.strftime("%Y-%m-%d"))
                    if price:
                        t5_return = (price - entry_price) / entry_price
                        updates["t5_price"] = price
                        updates["t5_return_pct"] = round(t5_return * 100, 2)

                        # Determine direction correctness
                        is_buy = direction in ("buy", "add")
                        direction_correct = (
                            (t5_return > 0) if is_buy else (t5_return < 0)
                        )
                        updates["direction_correct"] = 1 if direction_correct else 0
                        updates["evaluated_at"] = now.isoformat()
                        new_status = "complete"

                        outcomes.append(
                            DecisionOutcome(
                                proposal_id=signal_id,
                                symbol=symbol,
                                action=direction,
                                decided_at=created_at,
                                decided_price=entry_price,
                                t1_price=updates.get("t1_price", t1_price),
                                t3_price=updates.get("t3_price", t3_price),
                                t5_price=price,
                                t5_return_pct=round(t5_return * 100, 2),
                                direction_correct=direction_correct,
                            )
                        )
                except Exception:
                    pass

            if updates:
                updates["status"] = new_status
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                values = list(updates.values()) + [signal_id]
                try:
                    with self._conn() as conn:
                        conn.execute(
                            f"UPDATE tracked_signals SET {set_clause} WHERE signal_id = ?",
                            values,
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to update outcome for %s: %s", signal_id[:8], exc
                    )

        logger.info(
            "Evaluated %d pending signals, %d completed",
            len(rows),
            len(outcomes),
        )
        return outcomes

    # ------------------------------------------------------------------
    # Accuracy by source
    # ------------------------------------------------------------------

    def get_accuracy_by_source(
        self, source: str | None = None, lookback_days: int = 60
    ) -> list[SourceAccuracy]:
        """Get historical accuracy for signal sources."""
        cutoff = (datetime.now(UTC) - timedelta(days=lookback_days)).isoformat()
        results: list[SourceAccuracy] = []

        with self._conn() as conn:
            query = """
                SELECT source,
                       COUNT(*) as total,
                       SUM(CASE WHEN direction_correct = 1 THEN 1 ELSE 0 END) as correct,
                       AVG(CASE WHEN direction_correct = 1 THEN t5_return_pct ELSE NULL END) as avg_correct,
                       AVG(CASE WHEN direction_correct = 0 THEN t5_return_pct ELSE NULL END) as avg_incorrect
                FROM tracked_signals
                WHERE status = 'complete'
                AND created_at > ?
            """
            params: list[Any] = [cutoff]

            if source:
                query += " AND source = ?"
                params.append(source)

            query += " GROUP BY source ORDER BY total DESC"

            for row in conn.execute(query, params).fetchall():
                src, total, correct, avg_correct, avg_incorrect = row
                results.append(
                    SourceAccuracy(
                        source=src,
                        total_signals=total,
                        direction_correct=correct,
                        accuracy=correct / total if total > 0 else 0.0,
                        avg_return_correct=avg_correct or 0.0,
                        avg_return_incorrect=avg_incorrect or 0.0,
                        lookback_days=lookback_days,
                    )
                )

        return results

    def get_rolling_accuracy_summary(self, lookback_days: int = 30) -> str:
        """Return a formatted summary of signal source accuracy with trend.

        Compares last 7 days vs previous 7 days to detect degradation.
        Designed for injection into agent context.
        """
        recent = self.get_accuracy_by_source(lookback_days=7)
        older = self.get_accuracy_by_source(lookback_days=lookback_days)
        older_map = {sa.source: sa.accuracy for sa in older}

        if not recent and not older:
            return ""

        lines = []
        for sa in recent or older:
            if sa.total_signals < 3:
                continue
            old_acc = older_map.get(sa.source)
            trend = ""
            if old_acc is not None and sa.accuracy < old_acc - 0.15:
                trend = " ⚠️衰减"
            elif old_acc is not None and sa.accuracy > old_acc + 0.10:
                trend = " ↑改善"
            lines.append(
                f"- {sa.source}: {sa.accuracy:.0%} "
                f"({sa.direction_correct}/{sa.total_signals}){trend}"
            )

        if not lines:
            return ""
        return "## 信号源准确率\n" + "\n".join(lines)

    def get_chain_accuracy(self, lookback_days: int = 60) -> dict[str, float]:
        """Get accuracy for impact_chain signal sources (C7).

        Returns dict mapping chain source to accuracy (0.0-1.0).
        Used to calibrate CausalChainConstructor confidence.

        Example: {"impact_chain:monetary_policy": 0.7, "impact_chain:geopolitical": 0.4}
        """
        all_accuracy = self.get_accuracy_by_source(lookback_days=lookback_days)
        return {
            sa.source: sa.accuracy
            for sa in all_accuracy
            if sa.source.startswith("impact_chain:") and sa.total_signals >= 3
        }

    # ------------------------------------------------------------------
    # Missed opportunities
    # ------------------------------------------------------------------

    async def get_missed_opportunities(self, date: str) -> list[MissedOpportunity]:
        """Get missed opportunities for a given date."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT symbol, name, date, daily_return_pct, had_data,
                          preventable, reason
                   FROM missed_opportunities
                   WHERE date = ?
                   ORDER BY ABS(daily_return_pct) DESC""",
                (date,),
            ).fetchall()

        return [
            MissedOpportunity(
                symbol=r[0],
                name=r[1],
                date=r[2],
                daily_return_pct=r[3],
                had_data=bool(r[4]),
                preventable=bool(r[5]),
                reason=r[6],
            )
            for r in rows
        ]

    async def record_missed_opportunity(self, missed: MissedOpportunity) -> None:
        """Record a missed opportunity for learning."""
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO missed_opportunities
                    (symbol, name, date, daily_return_pct, had_data,
                     preventable, reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        missed.symbol,
                        missed.name,
                        missed.date,
                        missed.daily_return_pct,
                        int(missed.had_data),
                        int(missed.preventable),
                        missed.reason,
                        datetime.now(UTC).isoformat(),
                    ),
                )
        except Exception as exc:
            logger.warning("Failed to record missed opportunity: %s", exc)

    # ------------------------------------------------------------------
    # Calibration data for Bayesian engine
    # ------------------------------------------------------------------

    def get_calibration_data(
        self, lookback_days: int = 90, min_samples: int = 10
    ) -> dict[str, tuple[float, float]]:
        """Get empirical likelihoods for Bayesian calibration.

        Returns dict mapping ``"{source}/{confidence_bucket}"`` to
        ``(P(bullish reading | true bull), P(bullish reading | true bear))``.

        These are genuine **likelihoods** P(evidence | state), estimated as
        conditional frequencies — NOT the source's hit-rate. The realized state
        is reconstructed per signal from its predicted direction and whether the
        prediction was correct:

            realized bull = (predicted up AND correct) OR (predicted down AND wrong)

        so ``P(bullish reading | bull) = #(predicted up & realized bull) / #(realized bull)``
        and likewise for bear. They are Laplace-smoothed and do **not** sum to 1
        (the previous ``p_bear = 1 - p_bull`` was a posterior-style identity that
        does not hold for likelihoods). The log-likelihood-ratio the engine uses
        is ``log(p_bull / p_bear)``, positive only when a source reads bullish
        more often in true bull states than in true bear states.

        Only returns buckets with >= min_samples completed outcomes.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=lookback_days)).isoformat()
        calibration: dict[str, tuple[float, float]] = {}

        with self._conn() as conn:
            rows = conn.execute(
                """SELECT source,
                          CASE
                            WHEN confidence >= 0.75 THEN 'strong'
                            WHEN confidence >= 0.55 THEN 'moderate'
                            ELSE 'weak'
                          END as bucket,
                          COUNT(*) as total,
                          -- realized bull = up-call correct OR down-call wrong
                          SUM(CASE WHEN (direction IN ('buy', 'add')
                                         AND direction_correct = 1)
                                     OR (direction IN ('sell', 'reduce')
                                         AND direction_correct = 0)
                                   THEN 1 ELSE 0 END) as n_bull,
                          -- bullish reading that landed in a true bull state
                          SUM(CASE WHEN direction IN ('buy', 'add')
                                    AND direction_correct = 1
                                   THEN 1 ELSE 0 END) as bull_in_bull,
                          -- bullish reading that landed in a true bear state
                          SUM(CASE WHEN direction IN ('buy', 'add')
                                    AND direction_correct = 0
                                   THEN 1 ELSE 0 END) as bull_in_bear
                   FROM tracked_signals
                   WHERE status = 'complete'
                   AND direction_correct IS NOT NULL
                   AND created_at > ?
                   GROUP BY source, bucket
                   HAVING total >= ?""",
                (cutoff, min_samples),
            ).fetchall()

        for source, bucket, total, n_bull, bull_in_bull, bull_in_bear in rows:
            n_bear = total - n_bull
            # Laplace-smoothed conditional frequencies → proper likelihoods.
            p_given_bull = (bull_in_bull + 1) / (n_bull + 2)
            p_given_bear = (bull_in_bear + 1) / (n_bear + 2)
            # Clamp to keep the LLR finite/stable.
            p_given_bull = max(0.05, min(0.95, p_given_bull))
            p_given_bear = max(0.05, min(0.95, p_given_bear))
            calibration[f"{source}/{bucket}"] = (p_given_bull, p_given_bear)

        logger.info(
            "Calibration data: %d buckets with >= %d samples",
            len(calibration),
            min_samples,
        )
        return calibration

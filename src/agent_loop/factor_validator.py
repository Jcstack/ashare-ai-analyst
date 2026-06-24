"""Factor Validator — A/B tests screener factors against actual returns.

Periodically validates that screening factors still predict future returns.
Identifies decayed factors, redundant pairs, and ranks predictive power.
Results feed into screener weight tuning and system health monitoring.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/factor_validator.db")


@dataclass
class FactorReport:
    """Validation report for a single screening factor."""

    factor_name: str
    information_coefficient: float  # IC: rank correlation with future return
    hit_rate: float  # % of times factor direction was correct
    avg_return_top: float  # avg return of top-quintile stocks
    avg_return_bottom: float  # avg return of bottom-quintile stocks
    spread: float  # top - bottom
    sample_count: int
    is_significant: bool  # |IC| > 0.03 and sample_count >= 30
    decay_detected: bool  # IC was significant but now isn't

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_name": self.factor_name,
            "information_coefficient": round(self.information_coefficient, 4),
            "hit_rate": round(self.hit_rate, 4),
            "avg_return_top": round(self.avg_return_top, 4),
            "avg_return_bottom": round(self.avg_return_bottom, 4),
            "spread": round(self.spread, 4),
            "sample_count": self.sample_count,
            "is_significant": self.is_significant,
            "decay_detected": self.decay_detected,
        }


def _spearman_rank_corr(xs: list[float], ys: list[float]) -> float:
    """Compute Spearman rank correlation between two lists.

    Uses the standard rank-difference formula. Returns 0.0 on degenerate input.
    """
    n = len(xs)
    if n < 3:
        return 0.0

    def _rank(vals: list[float]) -> list[float]:
        indexed = sorted(enumerate(vals), key=lambda t: t[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and indexed[j + 1][1] == indexed[j][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    rx = _rank(xs)
    ry = _rank(ys)

    d_sq = sum((a - b) ** 2 for a, b in zip(rx, ry))
    denom = n * (n * n - 1)
    if denom == 0:
        return 0.0
    return 1.0 - (6.0 * d_sq / denom)


class FactorValidator:
    """Validates that screening factors predict returns.

    Periodically runs factor validation to identify:
    - Factors that have decayed (were useful, now aren't)
    - Factors that are redundant (highly correlated with each other)
    - Relative predictive power ranking
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS factor_scores (
                    date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    factor_name TEXT NOT NULL,
                    score REAL NOT NULL,
                    PRIMARY KEY (date, symbol, factor_name)
                );

                CREATE TABLE IF NOT EXISTS factor_returns (
                    date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    return_t5 REAL NOT NULL,
                    PRIMARY KEY (date, symbol)
                );

                CREATE INDEX IF NOT EXISTS idx_factor_scores_factor
                    ON factor_scores(factor_name, date);
                CREATE INDEX IF NOT EXISTS idx_factor_returns_date
                    ON factor_returns(date);
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ------------------------------------------------------------------
    # Record data
    # ------------------------------------------------------------------

    async def record_factor_scores(
        self, date: str, scores: list[dict[str, Any]]
    ) -> None:
        """Record factor scores for stocks on a given date.

        Args:
            date: Screening date (YYYY-MM-DD).
            scores: List of {symbol, factor_name, score} dicts.
        """
        if not scores:
            return
        try:
            with self._conn() as conn:
                conn.executemany(
                    """INSERT OR REPLACE INTO factor_scores
                    (date, symbol, factor_name, score)
                    VALUES (?, ?, ?, ?)""",
                    [(date, s["symbol"], s["factor_name"], s["score"]) for s in scores],
                )
            logger.debug("Recorded %d factor scores for %s", len(scores), date)
        except Exception as exc:
            logger.warning("Failed to record factor scores: %s", exc)

    async def record_returns(self, date: str, returns: list[dict[str, Any]]) -> None:
        """Record actual T+5 returns for stocks.

        Args:
            date: The date the factor scores were recorded (not the return date).
            returns: List of {symbol, return_pct} dicts.
        """
        if not returns:
            return
        try:
            with self._conn() as conn:
                conn.executemany(
                    """INSERT OR REPLACE INTO factor_returns
                    (date, symbol, return_t5)
                    VALUES (?, ?, ?)""",
                    [(date, r["symbol"], r["return_pct"]) for r in returns],
                )
            logger.debug("Recorded %d returns for %s", len(returns), date)
        except Exception as exc:
            logger.warning("Failed to record returns: %s", exc)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    async def validate_factor(
        self, factor_name: str, lookback_days: int = 90
    ) -> FactorReport:
        """Check if a factor correlates with future returns.

        Computes Information Coefficient (rank correlation of factor score
        with T+5 return) and hit rate.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT fs.score, fr.return_t5
                   FROM factor_scores fs
                   JOIN factor_returns fr
                     ON fs.date = fr.date AND fs.symbol = fr.symbol
                   WHERE fs.factor_name = ?
                     AND fs.date >= date('now', ?)
                   ORDER BY fs.score DESC""",
                (factor_name, f"-{lookback_days} days"),
            ).fetchall()

        if not rows:
            return FactorReport(
                factor_name=factor_name,
                information_coefficient=0.0,
                hit_rate=0.0,
                avg_return_top=0.0,
                avg_return_bottom=0.0,
                spread=0.0,
                sample_count=0,
                is_significant=False,
                decay_detected=False,
            )

        scores = [r[0] for r in rows]
        returns = [r[1] for r in rows]
        n = len(rows)

        # Information Coefficient (Spearman rank correlation)
        ic = _spearman_rank_corr(scores, returns)

        # Hit rate: % where score sign matches return sign
        hits = sum(
            1
            for s, r in zip(scores, returns)
            if (s > 0 and r > 0) or (s < 0 and r < 0) or (s == 0 and r == 0)
        )
        hit_rate = hits / n if n > 0 else 0.0

        # Quintile analysis
        quintile_size = max(1, n // 5)
        # rows already sorted by score DESC
        top_returns = [r[1] for r in rows[:quintile_size]]
        bottom_returns = [r[1] for r in rows[-quintile_size:]]

        avg_top = sum(top_returns) / len(top_returns) if top_returns else 0.0
        avg_bottom = (
            sum(bottom_returns) / len(bottom_returns) if bottom_returns else 0.0
        )
        spread = avg_top - avg_bottom

        is_significant = abs(ic) > 0.03 and n >= 30

        # Decay detection: check if IC in recent 30 days < threshold
        # while full-period IC was significant
        decay_detected = False
        if is_significant and lookback_days > 30:
            recent_report = await self._compute_ic_for_period(factor_name, 30)
            if recent_report is not None and abs(recent_report) <= 0.03:
                decay_detected = True

        return FactorReport(
            factor_name=factor_name,
            information_coefficient=ic,
            hit_rate=hit_rate,
            avg_return_top=avg_top,
            avg_return_bottom=avg_bottom,
            spread=spread,
            sample_count=n,
            is_significant=is_significant,
            decay_detected=decay_detected,
        )

    async def _compute_ic_for_period(self, factor_name: str, days: int) -> float | None:
        """Compute IC for a recent sub-period."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT fs.score, fr.return_t5
                   FROM factor_scores fs
                   JOIN factor_returns fr
                     ON fs.date = fr.date AND fs.symbol = fr.symbol
                   WHERE fs.factor_name = ?
                     AND fs.date >= date('now', ?)""",
                (factor_name, f"-{days} days"),
            ).fetchall()

        if len(rows) < 10:
            return None

        scores = [r[0] for r in rows]
        returns = [r[1] for r in rows]
        return _spearman_rank_corr(scores, returns)

    async def rank_factors(self, lookback_days: int = 90) -> list[FactorReport]:
        """Rank all factors by predictive power (|IC| descending)."""
        with self._conn() as conn:
            factor_names = [
                r[0]
                for r in conn.execute(
                    """SELECT DISTINCT factor_name FROM factor_scores
                       WHERE date >= date('now', ?)""",
                    (f"-{lookback_days} days",),
                ).fetchall()
            ]

        if not factor_names:
            return []

        reports = []
        for name in factor_names:
            report = await self.validate_factor(name, lookback_days)
            reports.append(report)

        reports.sort(key=lambda r: abs(r.information_coefficient), reverse=True)
        return reports

    async def detect_redundancy(
        self, lookback_days: int = 90
    ) -> list[tuple[str, str, float]]:
        """Find pairs of factors with |correlation| > 0.7.

        Returns: [(factor_a, factor_b, correlation), ...]
        """
        with self._conn() as conn:
            factor_names = [
                r[0]
                for r in conn.execute(
                    """SELECT DISTINCT factor_name FROM factor_scores
                       WHERE date >= date('now', ?)""",
                    (f"-{lookback_days} days",),
                ).fetchall()
            ]

        if len(factor_names) < 2:
            return []

        # Build per-factor score vectors keyed by (date, symbol)
        factor_vectors: dict[str, dict[tuple[str, str], float]] = {}
        with self._conn() as conn:
            for fname in factor_names:
                rows = conn.execute(
                    """SELECT date, symbol, score FROM factor_scores
                       WHERE factor_name = ?
                         AND date >= date('now', ?)""",
                    (fname, f"-{lookback_days} days"),
                ).fetchall()
                factor_vectors[fname] = {(r[0], r[1]): r[2] for r in rows}

        redundant: list[tuple[str, str, float]] = []
        names = sorted(factor_vectors.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                fa, fb = names[i], names[j]
                common_keys = set(factor_vectors[fa]) & set(factor_vectors[fb])
                if len(common_keys) < 20:
                    continue
                xs = [factor_vectors[fa][k] for k in common_keys]
                ys = [factor_vectors[fb][k] for k in common_keys]
                corr = _spearman_rank_corr(xs, ys)
                if abs(corr) > 0.7:
                    redundant.append((fa, fb, round(corr, 4)))

        redundant.sort(key=lambda t: abs(t[2]), reverse=True)
        return redundant

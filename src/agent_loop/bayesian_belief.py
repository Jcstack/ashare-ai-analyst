"""Bayesian Belief Engine for trading decisions.

Implements strict Bayesian inference replacing heuristic confidence scoring:

1. **Prior P(H)** — sector base rate × regime adjustment × quant factor conditional
2. **Likelihood P(E|H)** — signal-specific calibration tables
3. **Posterior P(H|E)** — sequential log-odds update via Bayes' rule

All trading decisions flow through this engine so that confidence is a
mathematically grounded posterior probability, not an ad-hoc scalar.

Math:
    log_odds(P) = ln(P / (1-P))
    P(H|E) ∝ P(E|H) × P(H)
    In log-odds: Ω(H|E) = Ω(H) + ln(P(E|H_bull) / P(E|H_bear))
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BayesianPrior:
    """Prior probability distribution over bullish/bearish hypotheses."""

    p_bullish: float  # P(H=bullish)
    p_bearish: float  # P(H=bearish) = 1 - p_bullish
    components: dict[str, float] = field(default_factory=dict)
    # Tracks which sources contributed to the prior


@dataclass
class BayesianPosterior:
    """Posterior probability after Bayesian update with evidence."""

    p_bullish: float  # P(H=bullish | E1, E2, ..., En)
    p_bearish: float  # P(H=bearish | E1, E2, ..., En)
    prior: BayesianPrior
    evidence_count: int
    log_odds: float  # Raw log-odds for debugging
    likelihood_contributions: list[dict[str, Any]] = field(default_factory=list)
    # Per-signal: {source, llr, p_e_bull, p_e_bear}


@dataclass
class SignalEvidence:
    """A piece of evidence to update beliefs with."""

    source: str  # Signal type: recommendation, capital_flow, technical, etc.
    direction: str  # buy, sell, hold, add
    strength: float  # Original confidence/strength (0-1)
    symbol: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Math utilities
# ---------------------------------------------------------------------------


def _logit(p: float) -> float:
    """Convert probability to log-odds. Clamps to avoid ±inf."""
    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    """Convert log-odds back to probability."""
    if x > 20:
        return 1.0 - 1e-9
    if x < -20:
        return 1e-9
    return 1.0 / (1.0 + math.exp(-x))


def _log_odds_pool(
    probabilities: list[float], weights: list[float] | None = None
) -> float:
    """Combine multiple probability estimates via log-odds pooling.

    This is the principled way to combine independent prior estimates:
    convert to log-odds, take weighted average, convert back.

    If no weights, uses equal weighting.
    """
    if not probabilities:
        return 0.5

    if weights is None:
        weights = [1.0] * len(probabilities)

    total_weight = sum(weights)
    if total_weight == 0:
        return 0.5

    weighted_logit = (
        sum(w * _logit(p) for p, w in zip(probabilities, weights)) / total_weight
    )

    return _sigmoid(weighted_logit)


# ---------------------------------------------------------------------------
# Default likelihood calibration tables
# ---------------------------------------------------------------------------
# Format: {signal_type: {strength_bucket: (P(E|bull), P(E|bear))}}
#
# These are expert-assigned defaults. The engine can be configured with
# empirically-learned tables via CalibrationStore.
#
# Interpretation: P(E|bull) = probability of observing this signal strength
# given the stock IS actually bullish. High P(E|bull) with low P(E|bear)
# means the signal is strong evidence FOR bullish hypothesis.
#
# Likelihood Ratio (LR) = P(E|bull) / P(E|bear):
#   LR > 1  → evidence supports bullish
#   LR < 1  → evidence supports bearish
#   LR = 1  → uninformative signal

_DEFAULT_LIKELIHOOD_TABLES: dict[str, dict[str, tuple[float, float]]] = {
    # --- Recommendation signals ---
    "recommendation": {
        "strong_buy": (0.72, 0.18),  # LR=4.0 — strong bullish evidence
        "buy": (0.62, 0.28),  # LR=2.2
        "watch": (0.50, 0.42),  # LR=1.2 — weak evidence
        "sell": (0.20, 0.70),  # LR=0.29 — bearish evidence
    },
    # --- Capital flow signals ---
    "capital_flow": {
        "large_inflow": (0.73, 0.17),  # LR=4.3
        "moderate_inflow": (0.60, 0.32),  # LR=1.9
        "neutral": (0.47, 0.47),  # LR=1.0 — uninformative
        "moderate_outflow": (0.32, 0.60),  # LR=0.53
        "large_outflow": (0.17, 0.73),  # LR=0.23
    },
    # --- Technical pattern signals ---
    "technical": {
        "strong_bullish": (0.67, 0.23),  # LR=2.9
        "bullish": (0.58, 0.33),  # LR=1.8
        "neutral": (0.46, 0.46),  # LR=1.0
        "bearish": (0.33, 0.58),  # LR=0.57
        "strong_bearish": (0.23, 0.67),  # LR=0.34
    },
    # --- Sentiment cycle phase ---
    "sentiment": {
        "freezing": (0.48, 0.42),  # LR=1.1 — slight bullish (bottoming)
        "ignition": (0.68, 0.22),  # LR=3.1 — strong bullish
        "acceleration": (0.62, 0.30),  # LR=2.1
        "climax": (0.35, 0.58),  # LR=0.60 — bearish (reversal risk)
        "ebb": (0.28, 0.62),  # LR=0.45 — bearish
    },
    # --- Rotation signals ---
    "rotation": {
        "favorable": (0.63, 0.28),  # LR=2.25
        "neutral": (0.47, 0.47),  # LR=1.0
        "unfavorable": (0.28, 0.63),  # LR=0.44
    },
    # --- Black swan / risk alerts ---
    "black_swan": {
        "alert": (0.15, 0.78),  # LR=0.19 — strong bearish
        "elevated": (0.30, 0.60),  # LR=0.50
        "normal": (0.48, 0.48),  # LR=1.0
    },
    # --- Stop-loss / thesis invalidation ---
    "stop_loss": {
        "triggered": (0.08, 0.88),  # LR=0.09 — very strong bearish
    },
    "thesis_invalidation": {
        "invalidated": (0.12, 0.80),  # LR=0.15 — strong bearish
    },
    # --- Intraday pattern signals ---
    "intraday_pattern": {
        "bullish_strong": (0.65, 0.25),  # LR=2.6
        "bullish": (0.56, 0.35),  # LR=1.6
        "bearish": (0.35, 0.56),  # LR=0.63
        "bearish_strong": (0.25, 0.65),  # LR=0.38
    },
    # --- VPIN toxicity ---
    "vpin": {
        "low_toxicity": (0.55, 0.40),  # LR=1.4 — mildly bullish
        "normal": (0.47, 0.47),  # LR=1.0
        "high_toxicity": (0.30, 0.65),  # LR=0.46 — bearish
        "extreme_toxicity": (0.18, 0.75),  # LR=0.24
    },
    # --- Reflexivity loop ---
    "reflexivity": {
        "strengthening": (0.66, 0.24),  # LR=2.75
        "exhausting": (0.38, 0.55),  # LR=0.69
        "breaking": (0.22, 0.70),  # LR=0.31
    },
    # --- Multi-timeframe alignment ---
    "mtf_alignment": {
        "strong_aligned": (0.68, 0.22),  # LR=3.1
        "partial_aligned": (0.55, 0.38),  # LR=1.4
        "conflicting": (0.40, 0.52),  # LR=0.77
        "strong_opposed": (0.25, 0.68),  # LR=0.37
    },
    # --- Global intelligence signals (v39.0) ---
    "global_intelligence": {
        "strong_positive": (0.65, 0.25),  # LR=2.6
        "positive": (0.55, 0.35),  # LR=1.6
        "neutral": (0.47, 0.47),  # LR=1.0
        "negative": (0.35, 0.55),  # LR=0.64
        "strong_negative": (0.25, 0.65),  # LR=0.38
    },
    # --- Leader detection (龙头识别) ---
    "leader_detection": {
        "strong_leader": (0.70, 0.20),  # LR=3.5
        "medium_leader": (0.58, 0.32),  # LR=1.8
        "weak_leader": (0.48, 0.45),  # LR=1.1
    },
}

# Regime prior adjustments (base rate for "random stock is bullish")
_REGIME_PRIORS: dict[str, float] = {
    # HMM regime states
    "bull": 0.58,  # Bull market: slightly above 50%
    "bear": 0.38,  # Bear market: below 50%
    "volatile": 0.44,  # High vol: slightly bearish
    "quiet": 0.52,  # Low vol: slightly bullish
    # A-share sentiment cycle phases (游资 framework)
    "freezing": 0.35,  # 冰点: very few limit-ups, low activity → bearish
    "ignition": 0.58,  # 启动: momentum building → bullish
    "acceleration": 0.65,  # 加速: strong trend, many limit-ups → strongly bullish
    "climax": 0.45,  # 高潮: exhaustion imminent → slightly bearish
    "ebb": 0.32,  # 退潮: trend breaking → bearish
    # Default
    "unknown": 0.50,  # No info: maximum entropy
}

# A-share sector historical base rates (approximate annualized win rates)
# These represent P(positive 5-day return | sector) from historical data
_SECTOR_BASE_RATES: dict[str, float] = {
    "bank": 0.49,  # 银行 — low beta, mean-reverting
    "insurance": 0.48,
    "securities": 0.46,  # 券商 — high beta, momentum-driven
    "real_estate": 0.44,  # 房地产 — policy-sensitive
    "consumer_staples": 0.52,  # 消费 — defensive
    "consumer_discretionary": 0.50,
    "healthcare": 0.51,  # 医药 — growth sector
    "technology": 0.48,  # 科技 — high vol
    "semiconductor": 0.47,
    "new_energy": 0.47,  # 新能源 — policy-driven, high vol
    "materials": 0.49,  # 材料
    "industrials": 0.50,
    "utilities": 0.51,  # 公用事业 — defensive
    "telecom": 0.50,
    "military": 0.47,  # 军工 — event-driven
    "auto": 0.49,
    "agriculture": 0.48,
    "media": 0.46,
    "default": 0.50,  # Unknown sector → maximum entropy
}


# ---------------------------------------------------------------------------
# Calibration Store (likelihood table management)
# ---------------------------------------------------------------------------


class CalibrationStore:
    """Manages likelihood calibration tables.

    Starts with expert defaults and can be updated empirically from
    decision outcome tracking (via OutcomeTracker).

    Empirical data is blended with expert defaults using Bayesian shrinkage:
    ``alpha = min(sample_count / 100, 1.0)`` so that full empirical weight
    is reached after 100 samples per bucket.
    """

    def __init__(
        self,
        custom_tables: dict[str, dict[str, tuple[float, float]]] | None = None,
    ) -> None:
        self._tables = dict(_DEFAULT_LIKELIHOOD_TABLES)
        if custom_tables:
            for signal_type, table in custom_tables.items():
                self._tables[signal_type] = table
        # Empirically calibrated overrides (populated via update_from_empirical)
        self._calibrated_table: dict[str, tuple[float, float]] = {}

    def update_from_empirical(
        self,
        calibration_data: dict[str, tuple[float, float]],
        sample_counts: dict[str, int] | None = None,
    ) -> None:
        """Blend empirical calibration data with expert defaults.

        Uses Bayesian shrinkage: ``alpha = min(sample_count / 100, 1.0)``
        so that the empirical estimate fully replaces the expert prior
        only after 100 samples.

        Args:
            calibration_data: Mapping ``"{source}/{bucket}"`` to
                ``(P(signal|bull), P(signal|bear))`` from OutcomeTracker.
            sample_counts: Optional per-key sample counts.  When provided
                the shrinkage ``alpha`` is computed from these; otherwise
                ``alpha = 1.0`` (full empirical weight).
        """
        sample_counts = sample_counts or {}

        for key, (emp_bull, emp_bear) in calibration_data.items():
            parts = key.split("/", 1)
            if len(parts) != 2:
                continue
            source, bucket = parts

            # Look up expert default
            expert_table = self._tables.get(source)
            if expert_table is not None:
                expert_entry = expert_table.get(bucket)
            else:
                expert_entry = None

            expert_bull = expert_entry[0] if expert_entry else 0.50
            expert_bear = expert_entry[1] if expert_entry else 0.50

            # Bayesian shrinkage: alpha ramps from 0→1 over 100 samples
            count = sample_counts.get(key, 100)
            alpha = min(count / 100.0, 1.0)

            blended_bull = alpha * emp_bull + (1 - alpha) * expert_bull
            blended_bear = alpha * emp_bear + (1 - alpha) * expert_bear

            self._calibrated_table[key] = (blended_bull, blended_bear)

        logger.info(
            "Calibration updated: %d empirical buckets blended",
            len(calibration_data),
        )

    # ------------------------------------------------------------------
    # SQLite-backed empirical likelihood tables
    # ------------------------------------------------------------------

    def update_likelihood_tables(
        self,
        outcomes: list[dict[str, Any]],
        db_path: str = "data/calibration.db",
        min_samples: int = 30,
        decay_lambda_days: float = 30.0,
    ) -> int:
        """Compute empirical P(signal|bull) and P(signal|bear) from outcomes.

        For each signal type with >= ``min_samples`` completed outcomes,
        computes time-weighted empirical likelihoods using exponential
        decay (lambda = ``decay_lambda_days``).  Expert defaults are
        retained as fallback when samples < ``min_samples``.

        Stores results in SQLite ``data/calibration.db``.

        Args:
            outcomes: List of dicts, each with keys:
                ``source``, ``bucket``, ``direction_correct`` (bool),
                ``created_at`` (ISO string or datetime).
            db_path: Path to calibration database.
            min_samples: Minimum sample count per bucket before
                empirical values replace expert defaults.
            decay_lambda_days: Half-life parameter for exponential
                weighting (recent outcomes count more).

        Returns:
            Number of buckets updated.
        """
        if not outcomes:
            return 0

        db = Path(db_path)
        db.parent.mkdir(parents=True, exist_ok=True)

        # Group outcomes by (source, bucket)
        buckets: dict[str, list[tuple[float, bool]]] = {}
        now = datetime.now(UTC)

        for o in outcomes:
            source = o.get("source", "unknown")
            bucket = o.get("bucket", "unknown")
            correct = o.get("direction_correct")
            if correct is None:
                continue

            created = o.get("created_at")
            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created)
                except (ValueError, TypeError):
                    created = now
            elif not isinstance(created, datetime):
                created = now

            age_days = max((now - created).total_seconds() / 86400.0, 0.0)
            weight = math.exp(-age_days / decay_lambda_days)

            key = f"{source}/{bucket}"
            buckets.setdefault(key, []).append((weight, bool(correct)))

        updated = 0
        empirical_data: dict[str, tuple[float, float]] = {}
        sample_counts: dict[str, int] = {}

        for key, entries in buckets.items():
            if len(entries) < min_samples:
                continue

            total_weight = sum(w for w, _ in entries)
            if total_weight < 1e-9:
                continue

            p_correct = sum(w for w, c in entries if c) / total_weight
            # P(signal|bull) = fraction of correct signals (weighted)
            p_given_bull = max(0.10, min(0.90, p_correct))
            p_given_bear = max(0.10, min(0.90, 1.0 - p_correct))

            empirical_data[key] = (p_given_bull, p_given_bear)
            sample_counts[key] = len(entries)
            updated += 1

        # Blend with expert defaults and store in memory
        if empirical_data:
            self.update_from_empirical(empirical_data, sample_counts)

        # Persist to SQLite
        if updated > 0:
            self._save_empirical_tables(db_path, empirical_data, sample_counts)

        logger.info(
            "Empirical likelihood update: %d buckets updated from %d outcomes",
            updated,
            len(outcomes),
        )
        return updated

    def load_empirical_tables(self, db_path: str = "data/calibration.db") -> int:
        """Load empirically calibrated tables from SQLite on startup.

        Returns number of buckets loaded.
        """
        db = Path(db_path)
        if not db.exists():
            return 0

        try:
            conn = sqlite3.connect(str(db))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT key, p_bull, p_bear, sample_count FROM likelihood_tables"
            ).fetchall()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to load empirical tables: %s", exc)
            return 0

        if not rows:
            return 0

        empirical: dict[str, tuple[float, float]] = {}
        counts: dict[str, int] = {}
        for row in rows:
            empirical[row["key"]] = (row["p_bull"], row["p_bear"])
            counts[row["key"]] = row["sample_count"]

        self.update_from_empirical(empirical, counts)
        logger.info("Loaded %d empirical likelihood buckets from DB", len(rows))
        return len(rows)

    @staticmethod
    def _save_empirical_tables(
        db_path: str,
        data: dict[str, tuple[float, float]],
        counts: dict[str, int],
    ) -> None:
        """Persist empirical tables to SQLite."""
        db = Path(db_path)
        db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS likelihood_tables (
                key TEXT PRIMARY KEY,
                p_bull REAL NOT NULL,
                p_bear REAL NOT NULL,
                sample_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        now = datetime.now(UTC).isoformat()
        for key, (p_bull, p_bear) in data.items():
            conn.execute(
                """INSERT OR REPLACE INTO likelihood_tables
                   (key, p_bull, p_bear, sample_count, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, p_bull, p_bear, counts.get(key, 0), now),
            )
        conn.commit()
        conn.close()

    def get_likelihood(
        self, signal_type: str, strength_bucket: str, hypothesis: str = "bullish"
    ) -> float:
        """Look up P(E|H) from calibration table.

        Checks empirically calibrated overrides first, then falls back
        to expert defaults.

        Args:
            signal_type: E.g. "recommendation", "capital_flow", "technical"
            strength_bucket: E.g. "strong_buy", "large_inflow"
            hypothesis: "bullish" or "bearish"

        Returns:
            P(E|H) — probability of observing this signal given hypothesis.
        """
        # Check empirically calibrated table first
        calibrated_key = f"{signal_type}/{strength_bucket}"
        calibrated_entry = self._calibrated_table.get(calibrated_key)
        if calibrated_entry is not None:
            p_bull, p_bear = calibrated_entry
            return p_bull if hypothesis == "bullish" else p_bear

        # Fall back to expert defaults
        table = self._tables.get(signal_type)
        if table is None:
            # Unknown signal type → uninformative (LR=1)
            return 0.50

        entry = table.get(strength_bucket)
        if entry is None:
            # Unknown bucket → uninformative
            return 0.50

        p_bull, p_bear = entry
        return p_bull if hypothesis == "bullish" else p_bear

    def get_likelihood_ratio(self, signal_type: str, strength_bucket: str) -> float:
        """Compute likelihood ratio LR = P(E|bull) / P(E|bear).

        LR > 1 → evidence favors bullish
        LR < 1 → evidence favors bearish
        LR = 1 → uninformative
        """
        p_bull = self.get_likelihood(signal_type, strength_bucket, "bullish")
        p_bear = self.get_likelihood(signal_type, strength_bucket, "bearish")
        if p_bear < 1e-6:
            return 10.0  # Cap to avoid division by zero
        return p_bull / p_bear


# ---------------------------------------------------------------------------
# Signal → Evidence mapping
# ---------------------------------------------------------------------------


def _map_signal_to_evidence(signal: Any) -> SignalEvidence:
    """Convert an aggregated trading signal to Bayesian evidence.

    Maps the signal's source and confidence to the appropriate
    likelihood table key and strength bucket.
    """
    # Handle dict-like signals
    if isinstance(signal, dict):
        source = signal.get("source", "unknown")
        direction = signal.get("direction", "buy")
        confidence = float(signal.get("confidence", 0.5))
        symbol = signal.get("symbol", "")
    else:
        source = getattr(signal, "source", "unknown")
        direction = getattr(signal, "direction", "buy")
        if hasattr(direction, "value"):
            direction = direction.value
        confidence = float(getattr(signal, "confidence", 0.5))
        symbol = getattr(signal, "symbol", "")

    # Map source to likelihood table key
    source_map = {
        "recommendation": "recommendation",
        "rec": "recommendation",
        "technical": "technical",
        "signal": "technical",
        "rotation": "rotation",
        "black_swan": "black_swan",
        "stop_loss": "stop_loss",
        "thesis_invalidation": "thesis_invalidation",
        "capital_flow": "capital_flow",
        "intraday": "intraday_pattern",
        "intraday_pattern": "intraday_pattern",
        "vpin": "vpin",
        "reflexivity": "reflexivity",
        "mtf": "mtf_alignment",
        "multi_timeframe": "mtf_alignment",
        "sentiment": "sentiment",
        "global_intelligence": "global_intelligence",
        "leader_detection": "leader_detection",
    }
    table_key = source_map.get(source, source)

    # Map confidence to strength bucket based on signal type
    strength_bucket = _confidence_to_bucket(table_key, direction, confidence)

    return SignalEvidence(
        source=table_key,
        direction=direction,
        strength=confidence,
        symbol=symbol,
        metadata={"original_source": source, "bucket": strength_bucket},
    )


def _confidence_to_bucket(signal_type: str, direction: str, confidence: float) -> str:
    """Map a continuous confidence value to a discrete strength bucket."""
    is_bearish = direction in ("sell", "reduce", "avoid")

    if signal_type == "recommendation":
        if is_bearish:
            return "sell"
        if confidence >= 0.75:
            return "strong_buy"
        if confidence >= 0.55:
            return "buy"
        return "watch"

    if signal_type == "capital_flow":
        if confidence >= 0.75:
            return "large_outflow" if is_bearish else "large_inflow"
        if confidence >= 0.55:
            return "moderate_outflow" if is_bearish else "moderate_inflow"
        return "neutral"

    if signal_type == "technical":
        if confidence >= 0.75:
            return "strong_bearish" if is_bearish else "strong_bullish"
        if confidence >= 0.50:
            return "bearish" if is_bearish else "bullish"
        return "neutral"

    if signal_type == "sentiment":
        # Sentiment source usually carries phase name in metadata
        return "neutral"  # Overridden by explicit phase mapping

    if signal_type == "stop_loss":
        return "triggered"

    if signal_type == "thesis_invalidation":
        return "invalidated"

    if signal_type == "black_swan":
        if confidence >= 0.70:
            return "alert"
        if confidence >= 0.40:
            return "elevated"
        return "normal"

    if signal_type == "vpin":
        if confidence >= 0.80:
            return "extreme_toxicity"
        if confidence >= 0.60:
            return "high_toxicity"
        if confidence >= 0.40:
            return "normal"
        return "low_toxicity"

    if signal_type == "reflexivity":
        if confidence >= 0.65:
            return "strengthening" if not is_bearish else "breaking"
        if confidence >= 0.40:
            return "exhausting"
        return "strengthening" if not is_bearish else "breaking"

    if signal_type in ("mtf_alignment", "multi_timeframe"):
        if confidence >= 0.75:
            return "strong_opposed" if is_bearish else "strong_aligned"
        if confidence >= 0.50:
            return "conflicting" if is_bearish else "partial_aligned"
        return "conflicting"

    if signal_type == "intraday_pattern":
        if confidence >= 0.65:
            return "bearish_strong" if is_bearish else "bullish_strong"
        return "bearish" if is_bearish else "bullish"

    if signal_type == "global_intelligence":
        if confidence >= 0.75:
            return "strong_negative" if is_bearish else "strong_positive"
        if confidence >= 0.55:
            return "negative" if is_bearish else "positive"
        return "neutral"

    if signal_type == "leader_detection":
        if confidence >= 0.80:
            return "strong_leader"
        if confidence >= 0.65:
            return "medium_leader"
        return "weak_leader"

    # Fallback: generic technical-style bucketing
    if confidence >= 0.70:
        return "strong_bearish" if is_bearish else "strong_bullish"
    if confidence >= 0.45:
        return "bearish" if is_bearish else "bullish"
    return "neutral"


# ---------------------------------------------------------------------------
# Bayesian Belief Engine
# ---------------------------------------------------------------------------


class BayesianBeliefEngine:
    """Core engine for Bayesian inference in trading decisions.

    Replaces heuristic confidence scoring with mathematically grounded
    posterior probabilities via sequential Bayesian updating.

    Usage::

        engine = BayesianBeliefEngine()
        prior = engine.compute_prior(symbol="600519", sector="consumer_staples",
                                     regime="bull", quant_p_up=0.58)
        evidence = [SignalEvidence(source="recommendation", direction="buy", strength=0.7),
                    SignalEvidence(source="capital_flow", direction="buy", strength=0.8)]
        posterior = engine.update_posterior(prior, evidence)
        # posterior.p_bullish → 0.78 (vs prior 0.55)
    """

    def __init__(
        self,
        calibration_store: CalibrationStore | None = None,
        sector_base_rates: dict[str, float] | None = None,
        regime_priors: dict[str, float] | None = None,
    ) -> None:
        self._calibration = calibration_store or CalibrationStore()
        self._sector_rates = sector_base_rates or _SECTOR_BASE_RATES
        self._regime_priors = regime_priors or _REGIME_PRIORS

    # ------------------------------------------------------------------
    # Step 1: Prior P(H)
    # ------------------------------------------------------------------

    def compute_prior(
        self,
        symbol: str = "",
        sector: str = "default",
        regime: str = "unknown",
        quant_p_up: float | None = None,
        volatility_pct: float | None = None,
        # Portfolio context (v50.0 §4.3)
        portfolio_sector_weight: float | None = None,
        portfolio_position_exists: bool = False,
        portfolio_correlation: float | None = None,
    ) -> BayesianPrior:
        """Compute prior P(bullish) from base rates.

        Args:
            symbol: Stock symbol (for logging).
            sector: Sector key (matches _SECTOR_BASE_RATES).
            regime: Market regime from regime detector.
            quant_p_up: P(up) from BayesianIndicatorAnalyzer (if available).
            volatility_pct: Current annualized volatility percentile [0-100].
            portfolio_sector_weight: Current sector allocation as fraction of
                total portfolio value (0.0–1.0).  When > 0.15, applies a
                diversification penalty to the prior.
            portfolio_position_exists: True if the portfolio already holds
                this symbol.  Applies a mild bearish prior for new buys.
            portfolio_correlation: Correlation of this symbol to existing
                holdings (0.0–1.0).  When > 0.5, applies a diversification
                penalty.

        Returns:
            BayesianPrior with combined prior probability.
        """
        components: dict[str, float] = {}
        probs: list[float] = []
        weights: list[float] = []

        # 1. Sector base rate (historical win rate)
        sector_rate = self._sector_rates.get(sector, self._sector_rates["default"])
        components["sector_base_rate"] = sector_rate
        probs.append(sector_rate)
        weights.append(1.0)

        # 2. Regime adjustment
        regime_prior = self._regime_priors.get(regime, 0.50)
        components["regime"] = regime_prior
        probs.append(regime_prior)
        weights.append(1.2)  # Regime gets slightly more weight

        # 3. Quantitative factor conditional probability
        if quant_p_up is not None:
            components["quant_p_up"] = quant_p_up
            probs.append(quant_p_up)
            weights.append(1.5)  # Quant signals are most informative prior

        # 4. Volatility adjustment (high vol → slightly lower prior)
        if volatility_pct is not None:
            # Map volatility percentile to prior adjustment:
            # 90th pct → 0.44, 50th pct → 0.50, 10th pct → 0.53
            vol_adj = 0.50 - (volatility_pct - 50) * 0.001
            vol_adj = max(0.40, min(0.55, vol_adj))
            components["volatility_adj"] = vol_adj
            probs.append(vol_adj)
            weights.append(0.5)  # Low weight — volatility is weak prior

        # 5. Portfolio sector concentration penalty
        # If already heavily allocated to this sector, reduce prior for new buys
        # (diversification pressure)
        if portfolio_sector_weight is not None and portfolio_sector_weight > 0.15:
            # Penalty ramps from 0.50 at 15% to 0.42 at 40%
            concentration_penalty = 0.50 - (portfolio_sector_weight - 0.15) * 0.32
            concentration_penalty = max(0.38, min(0.50, concentration_penalty))
            components["sector_concentration"] = concentration_penalty
            probs.append(concentration_penalty)
            weights.append(0.8)

        # 6. Position overlap adjustment
        # Already holding this stock → mild bearish prior for new buy
        # (avoid doubling down without strong conviction)
        if portfolio_position_exists:
            components["position_overlap"] = 0.45
            probs.append(0.45)
            weights.append(0.4)

        # 7. Portfolio correlation penalty
        # High correlation to existing holdings → diversification penalty
        if portfolio_correlation is not None and portfolio_correlation > 0.5:
            corr_penalty = 0.50 - (portfolio_correlation - 0.5) * 0.16
            corr_penalty = max(0.42, min(0.50, corr_penalty))
            components["correlation_penalty"] = corr_penalty
            probs.append(corr_penalty)
            weights.append(0.6)

        # Combine via log-odds pooling
        combined = _log_odds_pool(probs, weights)

        # Clamp to [0.25, 0.75] — prior should not be too extreme
        combined = max(0.25, min(0.75, combined))

        prior = BayesianPrior(
            p_bullish=combined,
            p_bearish=1 - combined,
            components=components,
        )

        logger.debug(
            "PRIOR %s: P(bull)=%.3f [sector=%.3f regime=%.3f quant=%s vol=%s"
            " sect_wt=%s pos_exists=%s corr=%s]",
            symbol,
            combined,
            sector_rate,
            regime_prior,
            f"{quant_p_up:.3f}" if quant_p_up is not None else "N/A",
            f"{volatility_pct:.0f}pct" if volatility_pct is not None else "N/A",
            f"{portfolio_sector_weight:.2f}"
            if portfolio_sector_weight is not None
            else "N/A",
            portfolio_position_exists,
            f"{portfolio_correlation:.2f}"
            if portfolio_correlation is not None
            else "N/A",
        )

        return prior

    # ------------------------------------------------------------------
    # Step 2: Likelihood P(E|H)
    # ------------------------------------------------------------------

    def compute_likelihood(self, evidence: SignalEvidence) -> tuple[float, float]:
        """Compute likelihood pair (P(E|bull), P(E|bear)) for one signal.

        Args:
            evidence: A single piece of evidence.

        Returns:
            (p_e_given_bull, p_e_given_bear) tuple.
        """
        bucket = evidence.metadata.get("bucket")
        if bucket is None:
            bucket = _confidence_to_bucket(
                evidence.source, evidence.direction, evidence.strength
            )

        p_bull = self._calibration.get_likelihood(evidence.source, bucket, "bullish")
        p_bear = self._calibration.get_likelihood(evidence.source, bucket, "bearish")

        return p_bull, p_bear

    # ------------------------------------------------------------------
    # Step 3: Posterior P(H|E) via sequential update
    # ------------------------------------------------------------------

    def update_posterior(
        self,
        prior: BayesianPrior,
        signals: list[Any],
        symbol: str = "",
    ) -> BayesianPosterior:
        """Sequential Bayesian update: P(H|E1,...,En) ∝ P(H) × ∏ P(Ei|H).

        Uses log-odds representation for numerical stability:
            Ω(H|E) = Ω(H) + Σ ln(P(Ei|bull) / P(Ei|bear))

        Args:
            prior: The prior belief.
            signals: List of signals (TradingSignal objects or dicts).
            symbol: Stock symbol for logging.

        Returns:
            BayesianPosterior with updated probability.
        """
        log_odds = _logit(prior.p_bullish)
        contributions: list[dict[str, Any]] = []

        for signal in signals:
            evidence = _map_signal_to_evidence(signal)

            # Skip signals for different symbols if symbol is specified
            if symbol and evidence.symbol and evidence.symbol != symbol:
                continue

            p_bull, p_bear = self.compute_likelihood(evidence)

            # Compute log-likelihood ratio
            if p_bear > 1e-6 and p_bull > 1e-6:
                llr = math.log(p_bull / p_bear)
            elif p_bull > p_bear:
                llr = 3.0  # Strong bullish evidence (capped)
            else:
                llr = -3.0  # Strong bearish evidence (capped)

            # Cap individual LLR to prevent single signal domination
            # Max LLR ±2.5 ≈ single signal can shift probability by ~12x
            llr = max(-2.5, min(2.5, llr))

            log_odds += llr

            bucket = evidence.metadata.get("bucket", "?")
            contributions.append(
                {
                    "source": evidence.source,
                    "direction": evidence.direction,
                    "strength": evidence.strength,
                    "bucket": bucket,
                    "p_e_bull": round(p_bull, 3),
                    "p_e_bear": round(p_bear, 3),
                    "llr": round(llr, 3),
                    "lr": round(math.exp(llr), 2),
                }
            )

        posterior_bull = _sigmoid(log_odds)

        posterior = BayesianPosterior(
            p_bullish=posterior_bull,
            p_bearish=1 - posterior_bull,
            prior=prior,
            evidence_count=len(contributions),
            log_odds=log_odds,
            likelihood_contributions=contributions,
        )

        if contributions:
            logger.info(
                "POSTERIOR %s: P(bull)=%.3f (prior=%.3f, %d signals, log_odds=%.2f)",
                symbol,
                posterior_bull,
                prior.p_bullish,
                len(contributions),
                log_odds,
            )
            for c in contributions:
                logger.debug(
                    "  Evidence: %s/%s [%s] → LR=%.2f (P(E|bull)=%.3f, P(E|bear)=%.3f)",
                    c["source"],
                    c["direction"],
                    c["bucket"],
                    c["lr"],
                    c["p_e_bull"],
                    c["p_e_bear"],
                )

        return posterior

    # ------------------------------------------------------------------
    # Convenience: full pipeline in one call
    # ------------------------------------------------------------------

    def infer(
        self,
        symbol: str,
        signals: list[Any],
        sector: str = "default",
        regime: str = "unknown",
        quant_p_up: float | None = None,
        volatility_pct: float | None = None,
        # Portfolio context (v50.0 §4.3)
        portfolio_sector_weight: float | None = None,
        portfolio_position_exists: bool = False,
        portfolio_correlation: float | None = None,
    ) -> BayesianPosterior:
        """Run full Bayesian inference: prior → likelihood → posterior.

        This is the main entry point for the trading decision pipeline.

        Args:
            symbol: Stock symbol.
            signals: All relevant signals for this symbol.
            sector: Sector classification.
            regime: Market regime.
            quant_p_up: P(up) from quantitative analysis.
            volatility_pct: Volatility percentile.
            portfolio_sector_weight: Current sector allocation fraction.
            portfolio_position_exists: Whether portfolio already holds symbol.
            portfolio_correlation: Correlation to existing holdings.

        Returns:
            BayesianPosterior with the final probability.
        """
        prior = self.compute_prior(
            symbol=symbol,
            sector=sector,
            regime=regime,
            quant_p_up=quant_p_up,
            volatility_pct=volatility_pct,
            portfolio_sector_weight=portfolio_sector_weight,
            portfolio_position_exists=portfolio_position_exists,
            portfolio_correlation=portfolio_correlation,
        )
        return self.update_posterior(prior, signals, symbol=symbol)

    # ------------------------------------------------------------------
    # Posterior → trading decision helpers
    # ------------------------------------------------------------------

    @staticmethod
    def posterior_to_confidence(
        posterior: BayesianPosterior, direction: str = "buy"
    ) -> float:
        """Convert posterior to a confidence score compatible with existing pipeline.

        For buy signals: confidence = P(bullish)
        For sell signals: confidence = P(bearish)
        """
        if direction in ("buy", "add"):
            return posterior.p_bullish
        if direction in ("sell", "reduce"):
            return posterior.p_bearish
        return 0.5  # hold → neutral

    @staticmethod
    def posterior_to_kelly_win_rate(
        posterior: BayesianPosterior, direction: str = "buy"
    ) -> float:
        """Extract win rate for Kelly criterion from posterior.

        This replaces the pattern of using raw confidence as win_rate.
        The posterior IS the win rate (probability of correct direction).
        """
        return BayesianBeliefEngine.posterior_to_confidence(posterior, direction)

    @staticmethod
    def format_posterior_summary(posterior: BayesianPosterior) -> str:
        """Format posterior for human-readable logging or message display."""
        lines = [
            f"贝叶斯推断结果: P(看多)={posterior.p_bullish:.1%}, P(看空)={posterior.p_bearish:.1%}",
            f"先验: P(看多)={posterior.prior.p_bullish:.1%}",
        ]

        prior_parts = []
        for k, v in posterior.prior.components.items():
            label = {
                "sector_base_rate": "行业基础胜率",
                "regime": "市场环境",
                "quant_p_up": "量化因子",
                "volatility_adj": "波动率调整",
                "sector_concentration": "行业集中度惩罚",
                "position_overlap": "持仓重叠惩罚",
                "correlation_penalty": "相关性惩罚",
            }.get(k, k)
            prior_parts.append(f"{label}={v:.1%}")
        if prior_parts:
            lines.append(f"  先验构成: {', '.join(prior_parts)}")

        if posterior.likelihood_contributions:
            lines.append(f"证据 ({posterior.evidence_count} 条):")
            for c in posterior.likelihood_contributions:
                direction_cn = "看多" if c["direction"] in ("buy", "add") else "看空"
                lr = c["lr"]
                if lr > 1.5:
                    strength = "强支持看多"
                elif lr > 1.1:
                    strength = "弱支持看多"
                elif lr > 0.9:
                    strength = "中性"
                elif lr > 0.67:
                    strength = "弱支持看空"
                else:
                    strength = "强支持看空"
                lines.append(
                    f"  [{c['source']}] {direction_cn} (LR={lr:.2f} {strength})"
                )

        return "\n".join(lines)

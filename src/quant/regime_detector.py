"""Market regime detection using Hidden Markov Model with volatility fallback.

Primary: 3-state Gaussian HMM learns hidden states (bull/bear/consolidation)
from daily returns + rolling volatility features via hmmlearn.

Fallback: Volatility percentile thresholds when hmmlearn is not installed
or data is insufficient.

Part of v15.0 Quant Core layer, enhanced in v50.0 (PRD SS5.6).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("quant.regime_detector")

TRADING_DAYS_PER_YEAR = 252

# HMM state labels ordered by mean-return ranking
_HMM_LABELS: dict[str, str] = {
    "bull": "bull",
    "bear": "bear",
    "consolidation": "consolidation",
}


@dataclass
class RegimeState:
    """Current regime classification for a single observation.

    Attributes:
        date: ISO date string.
        regime_id: Numeric regime identifier (0, 1, 2).
        regime_label: Human-readable label from config.
        volatility: Annualized rolling volatility at this point.
        percentile: Percentile rank of current volatility vs lookback.
        hmm_state: HMM-derived label (bull/bear/consolidation).
        hmm_probability: Probability of the current HMM state.
        switch_probability: 1 - P(stay in current state).
    """

    date: str = ""
    regime_id: int = 0
    regime_label: str = ""
    volatility: float = 0.0
    percentile: float = 0.0
    hmm_state: str = ""
    hmm_probability: float = 0.0
    switch_probability: float = 0.0


@dataclass
class TransitionMatrix:
    """Empirical regime transition probabilities.

    Attributes:
        matrix: 3x3 matrix where matrix[i][j] = P(next=j | current=i).
        regime_labels: Labels for each regime id.
    """

    matrix: list[list[float]] = field(default_factory=list)
    regime_labels: dict[int, str] = field(default_factory=dict)


@dataclass
class RegimeReport:
    """Full regime detection report.

    Attributes:
        current_regime: Most recent regime state.
        regime_history: Full time series of regime states.
        transition_matrix: Empirical transition probabilities.
        regime_distribution: Fraction of time spent in each regime.
        avg_duration: Average consecutive days in each regime.
        summary: Human-readable summary.
        method: Detection method used ("hmm" or "volatility_percentile").
    """

    current_regime: RegimeState = field(default_factory=RegimeState)
    regime_history: list[RegimeState] = field(default_factory=list)
    transition_matrix: TransitionMatrix = field(default_factory=TransitionMatrix)
    regime_distribution: dict[str, float] = field(default_factory=dict)
    avg_duration: dict[str, float] = field(default_factory=dict)
    summary: str = ""
    method: str = ""


class RegimeDetector:
    """Market regime detection with HMM primary and volatility fallback.

    Uses a 3-state Gaussian HMM (from hmmlearn) trained on [daily_return,
    rolling_volatility] features. Falls back to volatility percentile
    thresholds when hmmlearn is unavailable or fitting fails.

    Usage::

        detector = RegimeDetector()
        report = detector.detect(daily_returns=returns_series, dates=date_list)
        print(report.current_regime.hmm_state)
    """

    def __init__(self) -> None:
        cfg = load_config("quant").get("regime_detection", {})
        self.n_regimes = cfg.get("n_regimes", 3)
        self.vol_window = cfg.get("volatility_window_days", 20)
        self.lookback = cfg.get("lookback_days", 252)
        self.min_obs = cfg.get("min_observations", 60)
        self._hmm_n_iter = cfg.get("hmm_n_iter", 100)
        self.regime_labels: dict[int, str] = {
            int(k): v
            for k, v in cfg.get(
                "regime_labels",
                {0: "low_volatility", 1: "medium_volatility", 2: "high_volatility"},
            ).items()
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        daily_returns: list[float] | pd.Series,
        dates: list[str] | None = None,
    ) -> RegimeReport:
        """Run regime detection — HMM first, volatility percentile fallback.

        Args:
            daily_returns: Daily percentage returns (decimals).
            dates: ISO date strings aligned with daily_returns.

        Returns:
            RegimeReport with current regime, history, and transitions.
        """
        returns = (
            daily_returns
            if isinstance(daily_returns, pd.Series)
            else pd.Series(daily_returns, dtype=float)
        )
        n = len(returns)

        if n < self.min_obs:
            return RegimeReport(
                summary=f"Insufficient data: {n} days < {self.min_obs} required",
            )

        # Try HMM first when we have enough data
        if n >= self.min_obs:
            try:
                return self.detect_hmm(returns, dates)
            except Exception as exc:
                logger.debug(
                    "HMM detection failed, falling back to volatility: %s", exc
                )

        return self._detect_volatility(returns, dates)

    # ------------------------------------------------------------------
    # HMM-based detection (primary)
    # ------------------------------------------------------------------

    def detect_hmm(
        self,
        daily_returns: list[float] | pd.Series,
        dates: list[str] | None = None,
    ) -> RegimeReport:
        """Run 3-state Gaussian HMM regime detection.

        Fits a GaussianHMM on [daily_return, rolling_volatility] features.
        Maps learned states to bull/bear/consolidation by mean return.

        Args:
            daily_returns: Daily percentage returns (decimals).
            dates: ISO date strings aligned with daily_returns.

        Returns:
            RegimeReport with HMM-derived states.

        Raises:
            ImportError: If hmmlearn is not installed.
            ValueError: If data is insufficient or HMM fitting fails.
        """
        try:
            from hmmlearn.hmm import GaussianHMM
        except ImportError:
            raise ImportError(
                "hmmlearn is required for HMM regime detection. "
                "Install with: pip install hmmlearn>=0.3.0"
            )

        returns = (
            daily_returns
            if isinstance(daily_returns, pd.Series)
            else pd.Series(daily_returns, dtype=float)
        )
        n = len(returns)

        if n < self.min_obs:
            raise ValueError(f"Insufficient data: {n} days < {self.min_obs} required")

        # --- Feature preparation ---
        rolling_vol = returns.rolling(window=self.vol_window).std() * np.sqrt(
            TRADING_DAYS_PER_YEAR
        )

        # Align returns and volatility (drop NaN from rolling window warmup)
        valid_mask = rolling_vol.notna()
        aligned_returns = returns[valid_mask].values
        aligned_vol = rolling_vol[valid_mask].values
        valid_indices = np.where(valid_mask)[0]

        if len(aligned_returns) < self.min_obs:
            raise ValueError(
                f"Insufficient aligned data: {len(aligned_returns)} < {self.min_obs}"
            )

        # Stack 2D observation matrix: [return, volatility]
        observations = np.column_stack([aligned_returns, aligned_vol])

        # --- Fit HMM ---
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = GaussianHMM(
                n_components=self.n_regimes,
                covariance_type="full",
                n_iter=self._hmm_n_iter,
                random_state=42,
            )
            model.fit(observations)

        # --- State mapping: order by mean return ---
        # model.means_ is (n_components, n_features); col 0 = return
        mean_returns = model.means_[:, 0]
        sorted_indices = np.argsort(mean_returns)  # ascending: bear, consol, bull

        # Map: lowest mean → bear, middle → consolidation, highest → bull
        hmm_to_label: dict[int, str] = {}
        hmm_to_semantic_id: dict[int, int] = {}
        for rank, hmm_idx in enumerate(sorted_indices):
            if rank == 0:
                hmm_to_label[hmm_idx] = "bear"
                hmm_to_semantic_id[hmm_idx] = 0
            elif rank == self.n_regimes - 1:
                hmm_to_label[hmm_idx] = "bull"
                hmm_to_semantic_id[hmm_idx] = 2
            else:
                hmm_to_label[hmm_idx] = "consolidation"
                hmm_to_semantic_id[hmm_idx] = 1

        # --- Predict state sequence and probabilities ---
        hidden_states = model.predict(observations)
        state_probs = model.predict_proba(observations)

        # --- Extract HMM transition matrix ---
        hmm_transmat = model.transmat_

        # Reorder transition matrix to semantic order (bear=0, consol=1, bull=2)
        semantic_labels = {0: "bear", 1: "consolidation", 2: "bull"}
        reordered_transmat: list[list[float]] = []
        for from_semantic in range(self.n_regimes):
            row: list[float] = []
            # Find which HMM index maps to this semantic id
            from_hmm = _semantic_to_hmm(from_semantic, hmm_to_semantic_id)
            for to_semantic in range(self.n_regimes):
                to_hmm = _semantic_to_hmm(to_semantic, hmm_to_semantic_id)
                if from_hmm is not None and to_hmm is not None:
                    row.append(float(hmm_transmat[from_hmm, to_hmm]))
                else:
                    row.append(0.0)
            reordered_transmat.append(row)

        tm = TransitionMatrix(
            matrix=reordered_transmat,
            regime_labels=semantic_labels,
        )

        # --- Build regime history ---
        history: list[RegimeState] = []
        mapped_ids = np.array([hmm_to_semantic_id[s] for s in hidden_states])

        for i, (hmm_state, orig_idx) in enumerate(zip(hidden_states, valid_indices)):
            date_str = (
                dates[orig_idx] if dates and orig_idx < len(dates) else str(orig_idx)
            )
            label = hmm_to_label[hmm_state]
            semantic_id = hmm_to_semantic_id[hmm_state]
            prob = float(state_probs[i, hmm_state])
            vol = float(aligned_vol[i])

            # Switch probability = 1 - P(stay in current state)
            stay_prob = float(hmm_transmat[hmm_state, hmm_state])
            switch_prob = 1.0 - stay_prob

            history.append(
                RegimeState(
                    date=date_str,
                    regime_id=semantic_id,
                    regime_label=label,
                    volatility=vol,
                    percentile=_percentile_rank(pd.Series(aligned_vol[: i + 1]), vol),
                    hmm_state=label,
                    hmm_probability=prob,
                    switch_probability=switch_prob,
                )
            )

        # Current regime
        current = history[-1] if history else RegimeState()

        # Distribution and average duration (using semantic ids)
        distribution = _regime_distribution(mapped_ids, self.n_regimes, semantic_labels)
        avg_dur = _avg_regime_duration(mapped_ids, self.n_regimes, semantic_labels)

        # Summary
        summary_parts = [
            f"Current: {current.hmm_state} (P={current.hmm_probability:.0%})",
            f"Switch P={current.switch_probability:.0%}",
            f"Distribution: {', '.join(f'{k}={v:.0%}' for k, v in distribution.items())}",
        ]

        return RegimeReport(
            current_regime=current,
            regime_history=history,
            transition_matrix=tm,
            regime_distribution=distribution,
            avg_duration=avg_dur,
            summary=" | ".join(summary_parts),
            method="hmm",
        )

    # ------------------------------------------------------------------
    # Volatility-percentile detection (fallback)
    # ------------------------------------------------------------------

    def _detect_volatility(
        self,
        daily_returns: list[float] | pd.Series,
        dates: list[str] | None = None,
    ) -> RegimeReport:
        """Run regime detection using volatility percentile thresholds.

        This is the original detection method, retained as fallback when
        hmmlearn is not installed or HMM fitting fails.

        Args:
            daily_returns: Daily percentage returns (decimals).
            dates: ISO date strings aligned with daily_returns.

        Returns:
            RegimeReport with volatility-based regimes.
        """
        returns = (
            daily_returns
            if isinstance(daily_returns, pd.Series)
            else pd.Series(daily_returns, dtype=float)
        )
        n = len(returns)

        if n < self.min_obs:
            return RegimeReport(
                summary=f"Insufficient data: {n} days < {self.min_obs} required",
            )

        # Compute annualized rolling volatility
        rolling_vol = returns.rolling(window=self.vol_window).std() * np.sqrt(
            TRADING_DAYS_PER_YEAR
        )
        rolling_vol = rolling_vol.dropna()

        if len(rolling_vol) < self.min_obs:
            return RegimeReport(
                summary=f"Insufficient volatility data: {len(rolling_vol)} < {self.min_obs}",
            )

        # Classify regimes via percentile thresholds
        regime_ids = _classify_regimes(rolling_vol)

        # Build regime history
        vol_offset = n - len(rolling_vol)
        history: list[RegimeState] = []
        for i, (vol, rid) in enumerate(zip(rolling_vol, regime_ids)):
            date_idx = vol_offset + i
            date_str = (
                dates[date_idx] if dates and date_idx < len(dates) else str(date_idx)
            )
            percentile = _percentile_rank(rolling_vol.iloc[: i + 1], vol)
            history.append(
                RegimeState(
                    date=date_str,
                    regime_id=int(rid),
                    regime_label=self.regime_labels.get(int(rid), f"regime_{rid}"),
                    volatility=float(vol),
                    percentile=float(percentile),
                )
            )

        # Current regime
        current = history[-1] if history else RegimeState()

        # Transition matrix
        transition = _compute_transition_matrix(regime_ids, self.n_regimes)
        tm = TransitionMatrix(
            matrix=transition,
            regime_labels=self.regime_labels,
        )

        # Distribution and average duration
        distribution = _regime_distribution(
            regime_ids, self.n_regimes, self.regime_labels
        )
        avg_dur = _avg_regime_duration(regime_ids, self.n_regimes, self.regime_labels)

        # Summary
        summary_parts = [
            f"Current: {current.regime_label} (vol={current.volatility:.1%})",
            f"Distribution: {', '.join(f'{k}={v:.0%}' for k, v in distribution.items())}",
        ]

        return RegimeReport(
            current_regime=current,
            regime_history=history,
            transition_matrix=tm,
            regime_distribution=distribution,
            avg_duration=avg_dur,
            summary=" | ".join(summary_parts),
            method="volatility_percentile",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _semantic_to_hmm(semantic_id: int, mapping: dict[int, int]) -> int | None:
    """Find HMM index that maps to a given semantic id."""
    for hmm_idx, sem_id in mapping.items():
        if sem_id == semantic_id:
            return hmm_idx
    return None


def _classify_regimes(vol_series: pd.Series) -> np.ndarray:
    """Classify volatility into 3 regimes using tercile thresholds."""
    p33 = np.percentile(vol_series, 33.3)
    p67 = np.percentile(vol_series, 66.7)

    regimes = np.zeros(len(vol_series), dtype=int)
    regimes[vol_series.values > p67] = 2  # high volatility
    regimes[(vol_series.values > p33) & (vol_series.values <= p67)] = 1  # medium
    # regime 0 = low volatility (default)
    return regimes


def _percentile_rank(series: pd.Series, value: float) -> float:
    """Compute percentile rank of a value within a series."""
    if len(series) == 0:
        return 0.0
    return float((series <= value).sum() / len(series))


def _compute_transition_matrix(
    regime_ids: np.ndarray, n_regimes: int
) -> list[list[float]]:
    """Compute empirical transition probability matrix."""
    counts = np.zeros((n_regimes, n_regimes), dtype=float)
    for i in range(len(regime_ids) - 1):
        counts[regime_ids[i], regime_ids[i + 1]] += 1

    # Normalize rows
    matrix: list[list[float]] = []
    for row in counts:
        row_sum = row.sum()
        if row_sum > 0:
            matrix.append([float(v / row_sum) for v in row])
        else:
            matrix.append([0.0] * n_regimes)
    return matrix


def _regime_distribution(
    regime_ids: np.ndarray,
    n_regimes: int,
    labels: dict[int, str],
) -> dict[str, float]:
    """Fraction of time spent in each regime."""
    total = len(regime_ids)
    if total == 0:
        return {}
    result: dict[str, float] = {}
    for rid in range(n_regimes):
        label = labels.get(rid, f"regime_{rid}")
        result[label] = float((regime_ids == rid).sum() / total)
    return result


def _avg_regime_duration(
    regime_ids: np.ndarray,
    n_regimes: int,
    labels: dict[int, str],
) -> dict[str, float]:
    """Average consecutive days spent in each regime."""
    if len(regime_ids) == 0:
        return {}

    durations: dict[int, list[int]] = {i: [] for i in range(n_regimes)}
    current_regime = regime_ids[0]
    current_count = 1

    for i in range(1, len(regime_ids)):
        if regime_ids[i] == current_regime:
            current_count += 1
        else:
            durations[current_regime].append(current_count)
            current_regime = regime_ids[i]
            current_count = 1
    durations[current_regime].append(current_count)

    result: dict[str, float] = {}
    for rid in range(n_regimes):
        label = labels.get(rid, f"regime_{rid}")
        if durations[rid]:
            result[label] = float(np.mean(durations[rid]))
        else:
            result[label] = 0.0
    return result

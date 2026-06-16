"""Market regime detection using volatility-based Hidden Markov Model.

Identifies market states (low/medium/high volatility) from rolling
volatility series. Uses a simplified HMM approach that doesn't require
scipy — fits regimes via rolling percentile thresholds.

Part of v15.0 Quant Core layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("quant.regime_detector")

TRADING_DAYS_PER_YEAR = 252


@dataclass
class RegimeState:
    """Current regime classification for a single observation.

    Attributes:
        date: ISO date string.
        regime_id: Numeric regime identifier (0, 1, 2).
        regime_label: Human-readable label from config.
        volatility: Annualized rolling volatility at this point.
        percentile: Percentile rank of current volatility vs lookback.
    """

    date: str = ""
    regime_id: int = 0
    regime_label: str = ""
    volatility: float = 0.0
    percentile: float = 0.0


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
    """

    current_regime: RegimeState = field(default_factory=RegimeState)
    regime_history: list[RegimeState] = field(default_factory=list)
    transition_matrix: TransitionMatrix = field(default_factory=TransitionMatrix)
    regime_distribution: dict[str, float] = field(default_factory=dict)
    avg_duration: dict[str, float] = field(default_factory=dict)
    summary: str = ""


class RegimeDetector:
    """Volatility-based market regime detection.

    Uses rolling volatility percentiles to classify market into
    3 regimes: low, medium, and high volatility.

    Usage::

        detector = RegimeDetector()
        report = detector.detect(daily_returns=returns_series, dates=date_list)
        print(report.current_regime.regime_label)
    """

    def __init__(self) -> None:
        cfg = load_config("quant").get("regime_detection", {})
        self.n_regimes = cfg.get("n_regimes", 3)
        self.vol_window = cfg.get("volatility_window_days", 20)
        self.lookback = cfg.get("lookback_days", 252)
        self.min_obs = cfg.get("min_observations", 60)
        self.regime_labels: dict[int, str] = {
            int(k): v
            for k, v in cfg.get(
                "regime_labels",
                {0: "low_volatility", 1: "medium_volatility", 2: "high_volatility"},
            ).items()
        }

    def detect(
        self,
        daily_returns: list[float] | pd.Series,
        dates: list[str] | None = None,
    ) -> RegimeReport:
        """Run regime detection on a return series.

        Args:
            daily_returns: Daily percentage returns (decimals).
            dates: ISO date strings aligned with daily_returns.

        Returns:
            RegimeReport with current regime, history, and transitions.
        """
        returns = (
            daily_returns
            if isinstance(daily_returns, pd.Series)
            else pd.Series(daily_returns)
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
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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

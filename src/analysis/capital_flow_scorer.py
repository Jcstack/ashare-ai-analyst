"""Capital flow environment scoring engine.

Computes a composite score [-100, +100] from 4 macro capital channels:
northbound, southbound, margin balance change, and ETF net flow.

Per PRD v26.0 FR-CF002: Capital flow environment composite score.
"""

from __future__ import annotations

import math
from typing import Any

from src.data.macro_flow_fetcher import MacroFlowFetcher, MacroFlowSnapshot
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("analysis.capital_flow_scorer")


def _safe_mean(vals: list[float]) -> float:
    """Mean that avoids Python 3.13 statistics.mean issues with numpy floats."""
    return sum(vals) / len(vals) if vals else 0.0


def _safe_stdev(vals: list[float]) -> float:
    """Stdev that avoids Python 3.13 statistics.stdev bug with constant lists."""
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    ss = sum((x - mean) ** 2 for x in vals)
    return math.sqrt(ss / (n - 1))


def _normalise(value: float, mean: float, std: float) -> float:
    """Normalise a value to [-100, +100] based on z-score.

    Clamps the result to the [-100, +100] range.
    """
    if std <= 0:
        return 0.0
    z = (value - mean) / std
    # Sigmoid-like clamping: z of +-2 maps to roughly +-100
    score = max(-100.0, min(100.0, z * 50.0))
    return round(score, 1)


class CapitalFlowScorer:
    """Computes macro capital environment score from 4 channels.

    Weights are configurable via config/capital_flow.yaml.
    """

    def __init__(self, fetcher: MacroFlowFetcher | None = None) -> None:
        try:
            self._config: dict[str, Any] = load_config("capital_flow")
        except Exception:
            self._config = {}
        self._weights = self._config.get("capital_flow", {}).get("macro_weights", {})
        self._fetcher = fetcher

    @property
    def weights(self) -> dict[str, float]:
        return {
            "northbound": self._weights.get("northbound", 0.35),
            "margin": self._weights.get("margin", 0.25),
            "southbound": self._weights.get("southbound", 0.20),
            "etf": self._weights.get("etf", 0.20),
        }

    def score_snapshot(
        self,
        snapshot: MacroFlowSnapshot,
        history: list[MacroFlowSnapshot] | None = None,
    ) -> tuple[float, str]:
        """Score a single MacroFlowSnapshot.

        Args:
            snapshot: The current day's macro flow data.
            history: Historical snapshots for computing mean/std.
                If None and a fetcher is available, fetches automatically.

        Returns:
            Tuple of (score [-100, +100], signal: bullish/bearish/neutral).
        """
        if history is None and self._fetcher is not None:
            history = self._fetcher.get_macro_history(days=30)

        if not history or len(history) < 3:
            # Insufficient history — use simple sign-based scoring
            return self._simple_score(snapshot)

        w = self.weights

        # Compute per-channel normalised scores
        # Convert to native float — numpy float64 breaks statistics.stdev() in Python 3.13
        nb_vals = [float(s.northbound_net) for s in history]
        sb_vals = [float(s.southbound_net) for s in history]
        mg_vals = [float(s.margin_balance_change) for s in history]
        etf_vals = [float(s.etf_net_flow) for s in history]

        nb_score = _normalise(
            float(snapshot.northbound_net),
            _safe_mean(nb_vals),
            _safe_stdev(nb_vals) if len(nb_vals) >= 2 else 1.0,
        )
        # Southbound: positive = money leaving A-share → negative signal
        sb_score = -_normalise(
            float(snapshot.southbound_net),
            _safe_mean(sb_vals),
            _safe_stdev(sb_vals) if len(sb_vals) >= 2 else 1.0,
        )
        mg_score = _normalise(
            float(snapshot.margin_balance_change),
            _safe_mean(mg_vals),
            _safe_stdev(mg_vals) if len(mg_vals) >= 2 else 1.0,
        )
        etf_score = _normalise(
            float(snapshot.etf_net_flow),
            _safe_mean(etf_vals),
            _safe_stdev(etf_vals) if len(etf_vals) >= 2 else 1.0,
        )

        composite = (
            nb_score * w["northbound"]
            + sb_score * w["southbound"]
            + mg_score * w["margin"]
            + etf_score * w["etf"]
        )
        composite = max(-100.0, min(100.0, round(composite, 1)))

        signal = "neutral"
        if composite >= 20:
            signal = "bullish"
        elif composite <= -20:
            signal = "bearish"

        return composite, signal

    def _simple_score(self, snapshot: MacroFlowSnapshot) -> tuple[float, str]:
        """Fallback scoring when no history is available."""
        score = 0.0
        if snapshot.northbound_net > 0:
            score += 25
        elif snapshot.northbound_net < 0:
            score -= 25

        if snapshot.margin_balance_change > 0:
            score += 15
        elif snapshot.margin_balance_change < 0:
            score -= 15

        if snapshot.etf_net_flow > 0:
            score += 10
        elif snapshot.etf_net_flow < 0:
            score -= 10

        # Southbound positive = A-share money out → bearish
        if snapshot.southbound_net > 0:
            score -= 10
        elif snapshot.southbound_net < 0:
            score += 10

        score = max(-100.0, min(100.0, score))
        signal = "neutral"
        if score >= 20:
            signal = "bullish"
        elif score <= -20:
            signal = "bearish"
        return round(score, 1), signal

    def score_and_update(self, snapshot: MacroFlowSnapshot) -> MacroFlowSnapshot:
        """Score the snapshot and update its fields in-place.

        Returns the same snapshot with environment_score and signal set.
        """
        score, signal = self.score_snapshot(snapshot)
        snapshot.environment_score = score
        snapshot.signal = signal
        return snapshot

"""Composite confidence scoring for MarketSignal instances.

Computes a weighted 5-factor confidence score (0–100) with volatility
regime adjustment.  Designed to be dependency-injected so the scorer
degrades gracefully when upstream components are unavailable.

Part of v20.0 Market Intelligence Phase 2.

Factors & weights (from PRD v20.0):
    0.25 × source_reliability       — DataHealthTracker
    0.25 × multi_source_confirmation — signal.sources count
    0.15 × data_freshness            — signal.data_freshness_ms
    0.20 × historical_accuracy       — SignalStore
    0.15 × signal_strength            — signal.confidence_score
    ×  volatility_adjustment (0.7–1.0) from RegimeDetector
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.data.health_tracker import DataHealthTracker
    from src.market_intelligence.signal_store import SignalStore
    from src.quant.regime_detector import RegimeDetector

from src.web.schemas.market_signal import MarketSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Factor weights
W_SOURCE_RELIABILITY = 0.25
W_MULTI_SOURCE = 0.25
W_DATA_FRESHNESS = 0.15
W_HISTORICAL_ACCURACY = 0.20
W_SIGNAL_STRENGTH = 0.15

# Freshness half-life in milliseconds (5 minutes)
_FRESHNESS_HALFLIFE_MS = 300_000

# Default value when a factor cannot be computed
_DEFAULT_FACTOR = 50.0

# Volatility adjustment mapping: regime_label -> multiplier
_VOLATILITY_MULTIPLIERS: dict[str, float] = {
    "high": 0.7,
    "high_volatility": 0.7,
    "medium": 0.85,
    "medium_volatility": 0.85,
    "low": 1.0,
    "low_volatility": 1.0,
}

_DEFAULT_VOLATILITY_ADJUSTMENT = 1.0


# ---------------------------------------------------------------------------
# ConfidenceScorer
# ---------------------------------------------------------------------------


class ConfidenceScorer:
    """Compute composite confidence score for :class:`MarketSignal` instances.

    Constructor accepts optional dependency-injected components.  When a
    component is ``None``, the corresponding factor falls back to a safe
    default (50/100) so the scorer always produces a usable result.

    Args:
        health_tracker: :class:`DataHealthTracker` for source reliability.
        signal_store: :class:`SignalStore` for historical accuracy lookup.
        regime_detector: :class:`RegimeDetector` for volatility adjustment.
    """

    def __init__(
        self,
        health_tracker: DataHealthTracker | None = None,
        signal_store: SignalStore | None = None,
        regime_detector: RegimeDetector | None = None,
    ) -> None:
        self._health_tracker = health_tracker
        self._signal_store = signal_store
        self._regime_detector = regime_detector

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(
        self,
        signal: MarketSignal,
        context: dict[str, Any] | None = None,
    ) -> float:
        """Compute composite confidence score (0–100) for a signal.

        Args:
            signal: The MarketSignal to evaluate.
            context: Optional dict; may include ``"daily_returns"`` for
                volatility regime detection.

        Returns:
            Composite score clamped to 0–100.
        """
        factors = self._compute_factors(signal, context)

        composite = (
            W_SOURCE_RELIABILITY * factors["source_reliability"]
            + W_MULTI_SOURCE * factors["multi_source_confirmation"]
            + W_DATA_FRESHNESS * factors["data_freshness"]
            + W_HISTORICAL_ACCURACY * factors["historical_accuracy"]
            + W_SIGNAL_STRENGTH * factors["signal_strength"]
        ) * factors["volatility_adjustment"]

        return _clamp(composite, 0.0, 100.0)

    def score_breakdown(
        self,
        signal: MarketSignal,
        context: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """Return individual factor scores and final composite for audit.

        Useful for debugging and dashboard display.

        Returns:
            Dict with keys: ``source_reliability``,
            ``multi_source_confirmation``, ``data_freshness``,
            ``historical_accuracy``, ``signal_strength``,
            ``volatility_adjustment``, ``composite``.
        """
        factors = self._compute_factors(signal, context)
        composite = self.score(signal, context)
        return {**factors, "composite": composite}

    # ------------------------------------------------------------------
    # Factor computation (private)
    # ------------------------------------------------------------------

    def _compute_factors(
        self,
        signal: MarketSignal,
        context: dict[str, Any] | None,
    ) -> dict[str, float]:
        """Compute all 5 factors + volatility adjustment."""
        return {
            "source_reliability": self._source_reliability(signal),
            "multi_source_confirmation": self._multi_source_confirmation(signal),
            "data_freshness": self._data_freshness(signal),
            "historical_accuracy": self._historical_accuracy(signal),
            "signal_strength": self._signal_strength(signal),
            "volatility_adjustment": self._volatility_adjustment(context),
        }

    def _source_reliability(self, signal: MarketSignal) -> float:
        """Factor 1: source reliability from DataHealthTracker (0–100)."""
        if self._health_tracker is None:
            return _DEFAULT_FACTOR
        try:
            health = self._health_tracker.get_health(signal.producer)
            success_rate = health.get("success_rate")
            if success_rate is None:
                return _DEFAULT_FACTOR
            return float(success_rate) * 100.0
        except Exception:
            logger.warning(
                "Failed to get health for producer '%s', using default",
                signal.producer,
                exc_info=True,
            )
            return _DEFAULT_FACTOR

    @staticmethod
    def _multi_source_confirmation(signal: MarketSignal) -> float:
        """Factor 2: multi-source confirmation (0, 50, or 100)."""
        n = len(signal.sources)
        if n == 0:
            return 0.0
        if n == 1:
            return 50.0
        return 100.0

    @staticmethod
    def _data_freshness(signal: MarketSignal) -> float:
        """Factor 3: data freshness via exponential decay (0–100).

        Formula: ``100 * exp(-data_freshness_ms / halflife_ms)``
        Halflife = 300 000 ms (5 minutes).
        """
        freshness_ms = signal.data_freshness_ms
        if freshness_ms <= 0:
            return 100.0
        return 100.0 * math.exp(-freshness_ms / _FRESHNESS_HALFLIFE_MS)

    def _historical_accuracy(self, signal: MarketSignal) -> float:
        """Factor 4: historical T+3 accuracy from SignalStore (0–100)."""
        if self._signal_store is None:
            return _DEFAULT_FACTOR
        try:
            result = self._signal_store.get_signal_accuracy(
                signal.signal_type.value,
                window_days=30,
            )
            if result.get("insufficient_data"):
                return _DEFAULT_FACTOR
            accuracy_t3 = result.get("accuracy_t3")
            if accuracy_t3 is None:
                return _DEFAULT_FACTOR
            return float(accuracy_t3) * 100.0
        except Exception:
            logger.warning(
                "Failed to get accuracy for signal type '%s', using default",
                signal.signal_type.value,
                exc_info=True,
            )
            return _DEFAULT_FACTOR

    @staticmethod
    def _signal_strength(signal: MarketSignal) -> float:
        """Factor 5: raw signal confidence clamped to 0–100."""
        return _clamp(float(signal.confidence_score), 0.0, 100.0)

    def _volatility_adjustment(
        self,
        context: dict[str, Any] | None,
    ) -> float:
        """Volatility regime multiplier (0.7–1.0)."""
        if self._regime_detector is None:
            return _DEFAULT_VOLATILITY_ADJUSTMENT
        if context is None or "daily_returns" not in context:
            return _DEFAULT_VOLATILITY_ADJUSTMENT
        try:
            report = self._regime_detector.detect(context["daily_returns"])
            label = report.current_regime.regime_label.lower()
            # Match against known labels (handles both "high" and
            # "high_volatility" style labels from config)
            for key, multiplier in _VOLATILITY_MULTIPLIERS.items():
                if key in label:
                    return multiplier
            logger.warning(
                "Unknown regime label '%s', using default adjustment",
                label,
            )
            return _DEFAULT_VOLATILITY_ADJUSTMENT
        except Exception:
            logger.warning(
                "Regime detection failed, using default volatility adjustment",
                exc_info=True,
            )
            return _DEFAULT_VOLATILITY_ADJUSTMENT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))

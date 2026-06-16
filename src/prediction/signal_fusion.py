"""Bayesian signal fusion engine — fuses multi-source signals into unified confidence.

Migrated from ``scripts/data_aggregator.py`` and enhanced for service-layer use.

Sources:
- sentinel: Gemini sentiment score (from InfoStore / sentinel output)
- actuary: Qlib quantitative prediction
- technical: Bayesian indicator P(up) via BayesianIndicatorAnalyzer
- macro: MacroRadarService macro-level signals

Weights are loaded from ``config/research.yaml`` → ``bayesian_fusion`` section.
When a source is unavailable the remaining weights are re-normalized to sum to 1.0.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SignalFusionEngine:
    """Fuses multi-source signals using configurable Bayesian weights.

    Args:
        qlib_adapter: Optional QlibAdapter instance for quantitative predictions.
        bayesian_analyzer_factory: Optional callable returning a BayesianIndicatorAnalyzer.
        config: ``research.yaml`` config dict. Loads automatically if None.
    """

    def __init__(
        self,
        qlib_adapter: Any | None = None,
        bayesian_analyzer_factory: Any | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        if config is None:
            try:
                from src.utils.config import load_config

                config = load_config("research")
            except Exception:
                config = {}

        self._config = config
        self._fusion_cfg = config.get("bayesian_fusion", {})
        self._constraint_cfg = config.get("ashare_constraints", {})
        self._weights: dict[str, float] = self._fusion_cfg.get(
            "weights",
            {"sentinel": 0.25, "actuary": 0.35, "technical": 0.40},
        )
        self._thresholds = self._fusion_cfg.get("thresholds", {})
        self._labels = self._fusion_cfg.get("labels", {})

        self._qlib = qlib_adapter
        self._bayesian_factory = bayesian_analyzer_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fuse(
        self,
        symbol: str,
        sources: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Fuse all available signals for *symbol* into a unified result.

        If *sources* is provided it is used directly; otherwise the engine
        attempts to gather sentinel/actuary/technical data automatically.

        Returns:
            Dict with ``symbol``, ``sources``, ``fusion`` (confidence + signal),
            and ``constraints`` keys.
        """
        if sources is None:
            sources = {}

        available_weights: dict[str, float] = {}

        # --- Sentinel ---
        if "sentinel" in sources:
            src = sources["sentinel"]
            if src.get("score") is not None and not src.get("fallback_used", True):
                damping = self._constraint_cfg.get("sentiment_damping", 0.8)
                raw = src["score"]
                src["score"] = round(0.5 + (raw - 0.5) * damping, 4)
                available_weights["sentinel"] = self._weights.get("sentinel", 0.25)

        # --- Actuary (Qlib) ---
        if "actuary" not in sources:
            qlib_signal = self.get_qlib_signal(symbol)
            if qlib_signal and qlib_signal.get("available"):
                sources["actuary"] = qlib_signal
        if sources.get("actuary", {}).get("available"):
            available_weights["actuary"] = self._weights.get("actuary", 0.35)

        # --- Technical (Bayesian indicators) ---
        if "technical" not in sources:
            sources["technical"] = self._get_technical_signal(symbol)
        if sources.get("technical", {}).get("available"):
            available_weights["technical"] = self._weights.get("technical", 0.40)

        # --- Fusion ---
        fusion = self._compute_fusion(sources, available_weights)

        # --- A-share constraints ---
        constraints = self._check_constraints(symbol)

        return {
            "symbol": symbol,
            "sources": sources,
            "fusion": fusion,
            "constraints": constraints,
        }

    def get_qlib_signal(self, symbol: str) -> dict[str, Any] | None:
        """Return Qlib prediction signal for *symbol*, or None."""
        if self._qlib is None:
            return None
        try:
            if not self._qlib.is_available():
                return None
            preds = self._qlib.predict([symbol])
            result = preds.get(symbol)
            if result and result.get("score") is not None:
                return {
                    "score": round(result["score"], 4),
                    "ic": result.get("ic"),
                    "available": True,
                }
            return {"score": None, "ic": None, "available": False}
        except Exception as exc:
            logger.warning("Qlib signal for %s failed: %s", symbol, exc)
            return None

    def get_alpha_factors(self, symbol: str) -> dict[str, float] | None:
        """Return Qlib alpha factor values for *symbol*, or None."""
        if self._qlib is None:
            return None
        try:
            if not self._qlib.is_available():
                return None
            return self._qlib.get_alpha_factors(symbol)
        except Exception as exc:
            logger.warning("Qlib alpha factors for %s failed: %s", symbol, exc)
            return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_technical_signal(self, symbol: str) -> dict[str, Any]:
        """Compute Bayesian indicator signal for *symbol*."""
        try:
            if self._bayesian_factory is not None:
                analyzer = self._bayesian_factory()
            else:
                from src.analysis.bayesian_indicators import BayesianIndicatorAnalyzer

                analyzer = BayesianIndicatorAnalyzer()

            from src.analysis.indicators import TechnicalIndicators
            from src.data.fetcher import StockDataFetcher

            df = StockDataFetcher().fetch_daily_ohlcv(symbol)
            if df is None or df.empty:
                return {"p_up": 0.5, "composite_signal": "neutral", "available": False}

            df = TechnicalIndicators().add_all(df)
            result = analyzer.analyze(df)
            composite = result.get("composite", {})

            p_up = composite.get("bullish_count", 0) / max(
                composite.get("total_indicators", 1), 1
            )

            return {
                "p_up": round(p_up, 4),
                "composite_signal": composite.get("overall_signal", "neutral"),
                "available": True,
                "indicator_count": composite.get("total_indicators", 0),
            }
        except Exception as exc:
            logger.warning("Technical signal failed for %s: %s", symbol, exc)
            return {"p_up": 0.5, "composite_signal": "neutral", "available": False}

    def _compute_fusion(
        self,
        sources: dict[str, dict[str, Any]],
        available_weights: dict[str, float],
    ) -> dict[str, Any]:
        """Compute weighted-average fusion score with re-normalization."""
        if not available_weights:
            return {
                "confidence": 0.5,
                "signal": self._labels.get("neutral", "中性"),
                "weights_used": {},
            }

        total = sum(available_weights.values())
        normalized = (
            {k: v / total for k, v in available_weights.items()} if total > 0 else {}
        )

        weighted_sum = 0.0
        for source_name, weight in normalized.items():
            src = sources.get(source_name, {})
            score = src.get("score") if source_name != "technical" else src.get("p_up")
            if score is not None:
                weighted_sum += weight * score

        confidence = round(weighted_sum, 4)
        signal = self._confidence_to_signal(confidence)

        return {
            "confidence": confidence,
            "signal": signal,
            "weights_used": {k: round(v, 4) for k, v in normalized.items()},
        }

    def _confidence_to_signal(self, confidence: float) -> str:
        """Map confidence score to a human-readable signal label."""
        t = self._thresholds
        if confidence >= t.get("strong_buy", 0.75):
            return self._labels.get("strong_buy", "强烈看多")
        if confidence >= t.get("buy", 0.60):
            return self._labels.get("buy", "看多")
        if confidence >= t.get("neutral_high", 0.55):
            return self._labels.get("neutral", "中性")
        if confidence >= t.get("neutral_low", 0.45):
            return self._labels.get("neutral", "中性")
        if confidence >= t.get("sell", 0.40):
            return self._labels.get("sell", "看空")
        return self._labels.get("strong_sell", "强烈看空")

    def _check_constraints(self, symbol: str) -> dict[str, Any]:
        """Return A-share trading constraints for *symbol*."""
        if symbol.startswith("3") or symbol.startswith("68"):
            limit = self._constraint_cfg.get("chinext_star_limit", 0.20)
            board = "ChiNext/STAR"
        else:
            limit = self._constraint_cfg.get("main_board_limit", 0.10)
            board = "Main"

        return {
            "board": board,
            "limit_pct": limit,
            "t_plus_1": self._constraint_cfg.get("t_plus_1", True),
            "sentiment_damping": self._constraint_cfg.get("sentiment_damping", 0.8),
        }

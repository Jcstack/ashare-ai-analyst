"""Strategy signal aggregation and Bayesian analysis integration for AI input.

Collects multi-strategy consensus and Bayesian conditional probabilities
to provide quantitative context for AI analysis prompts. This bridges the
gap between the quantitative strategy engine and the LLM analysis layer.
"""

from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

logger = get_logger("web.strategy_context_service")

_STRATEGY_NAMES: dict[str, str] = {
    "trend_following": "趋势跟踪",
    "mean_reversion": "均值回归",
    "momentum": "动量策略",
}


class StrategyContextService:
    """Generates multi-strategy consensus and Bayesian context for AI analysis."""

    def __init__(self, signal_service=None, stock_service=None) -> None:
        self._signal_service = signal_service
        self._stock_service = stock_service

    def get_strategy_context(self, symbol: str) -> dict[str, Any]:
        """Get aggregated multi-strategy signals for a stock.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict with 'signals' (per-strategy) and 'consensus' (aggregate).
        """
        try:
            if self._signal_service is not None:
                svc = self._signal_service
            else:
                from src.web.services.paper_trade_signal_service import (
                    PaperTradeSignalService,
                )

                svc = PaperTradeSignalService()
            raw_signals = svc.get_latest_signals(symbol)
        except Exception as exc:
            logger.warning("Strategy signals unavailable for %s: %s", symbol, exc)
            return {}

        if not raw_signals:
            return {}

        signals: dict[str, dict[str, Any]] = {}
        for sig in raw_signals:
            key = sig.get("strategy_key", "")
            direction = sig.get("signal", "hold")
            strength = sig.get("strength", 0.0)
            reason = sig.get("reason", "")
            signals[key] = {
                "name": sig.get("strategy_name", _STRATEGY_NAMES.get(key, key)),
                "direction": direction,
                "strength": strength,
                "reason": reason,
            }

        consensus = self._compute_consensus(signals)

        return {
            "signals": signals,
            "consensus": consensus,
        }

    def get_bayesian_context(self, symbol: str) -> dict[str, Any]:
        """Get Bayesian conditional probability analysis for a stock.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict with 'indicators' (per-indicator probabilities) and
            'composite' (aggregate signal).
        """
        try:
            from src.analysis.bayesian_indicators import BayesianIndicatorAnalyzer

            if self._stock_service is not None:
                stock_svc = self._stock_service
            else:
                from src.web.services.stock_service import StockService

                stock_svc = StockService()
            df = stock_svc.get_stock_with_indicators(symbol)
            if df is None or df.empty:
                return {}

            analyzer = BayesianIndicatorAnalyzer()
            result = analyzer.analyze(df)
        except Exception as exc:
            logger.warning("Bayesian analysis unavailable for %s: %s", symbol, exc)
            return {}

        if not result:
            return {}

        # Reshape for prompt consumption
        indicators: dict[str, dict[str, Any]] = {}
        for ind in result.get("indicators", []):
            key = ind.get("indicator", "")
            probs = ind.get("probabilities", {})
            indicators[key] = {
                "current": ind.get("current_value", 0),
                "bin": ind.get("bin_label", ""),
                "p_up": probs.get("up", 0),
                "p_down": probs.get("down", 0),
                "samples": ind.get("sample_count", 0),
                "interpretation": ind.get("interpretation", ""),
                "data_sufficient": ind.get("data_sufficient", False),
            }

        composite = result.get("composite", {})
        composite_out = {
            "signal": composite.get("signal", ""),
            "confidence": 0.0,
            "data_sufficient": bool(indicators),
        }
        # Derive confidence from composite bullish/bearish ratio
        total = (
            composite.get("bullish_count", 0)
            + composite.get("bearish_count", 0)
            + composite.get("neutral_count", 0)
        )
        if total > 0:
            dominant = max(
                composite.get("bullish_count", 0),
                composite.get("bearish_count", 0),
                composite.get("neutral_count", 0),
            )
            composite_out["confidence"] = dominant / total

        return {
            "indicators": indicators,
            "composite": composite_out,
        }

    @staticmethod
    def _compute_consensus(signals: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Compute multi-strategy consensus from individual signals."""
        bullish = 0
        bearish = 0
        neutral = 0

        for sig in signals.values():
            direction = sig.get("direction", "hold")
            if direction == "buy":
                bullish += 1
            elif direction == "sell":
                bearish += 1
            else:
                neutral += 1

        if bullish >= 2 and bearish == 0:
            agreement = "strong_bullish"
        elif bearish >= 2 and bullish == 0:
            agreement = "strong_bearish"
        elif bullish > 0 and bearish > 0:
            agreement = "divergent"
        else:
            agreement = "mixed"

        # Generate Chinese description
        parts = []
        if bullish:
            parts.append(f"{bullish}个策略看多")
        if bearish:
            parts.append(f"{bearish}个策略看空")
        if neutral:
            parts.append(f"{neutral}个策略观望")

        note = "、".join(parts) if parts else "无策略信号"

        if agreement == "divergent":
            note += "，策略信号存在分歧，需谨慎判断"
        elif agreement == "strong_bullish":
            note += "，多策略一致看多"
        elif agreement == "strong_bearish":
            note += "，多策略一致看空"

        return {
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "agreement": agreement,
            "note": note,
        }

"""Risk Overlay Engine for the v20.0 Market Intelligence pipeline.

Enriches MarketSignal with portfolio-aware risk classification by
combining regime detection, circuit breaker state, VaR, and optional
macro regime data.  The engine never generates trading instructions —
it only annotates signals with risk context.

Part of v20.0 Market Intelligence Phase 2.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from src.web.schemas.market_signal import RiskContext, RiskLevel

if TYPE_CHECKING:
    from src.market_intelligence.macro_classifier import MacroRegimeClassifier
    from src.quant.regime_detector import RegimeDetector
    from src.risk.circuit_breaker import CircuitBreaker
    from src.risk.var_calculator import VaRCalculator
    from src.web.schemas.market_signal import MarketSignal

logger = logging.getLogger(__name__)


class RiskOverlayEngine:
    """Annotate a MarketSignal with risk level and risk context.

    Combines four risk subsystems:
    - **RegimeDetector** — volatility regime (low / medium / high)
    - **CircuitBreaker** — portfolio P&L halt logic
    - **VaRCalculator** — Value-at-Risk (1-day, 95%)
    - **MacroRegimeClassifier** (optional) — macro backdrop

    Usage::

        engine = RiskOverlayEngine(regime_detector, circuit_breaker, var_calculator)
        enriched = engine.evaluate(signal, portfolio_context)
        if engine.should_block(enriched):
            ...  # suppress low-confidence signal under extreme risk
    """

    def __init__(
        self,
        regime_detector: RegimeDetector,
        circuit_breaker: CircuitBreaker,
        var_calculator: VaRCalculator,
        macro_classifier: MacroRegimeClassifier | None = None,
    ) -> None:
        self._regime_detector = regime_detector
        self._circuit_breaker = circuit_breaker
        self._var_calculator = var_calculator
        self._macro_classifier = macro_classifier

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        signal: MarketSignal,
        portfolio_context: dict,
    ) -> MarketSignal:
        """Fill ``risk_level`` and ``risk_context`` on *signal* and return it.

        Args:
            signal: Incoming MarketSignal (mutated in-place).
            portfolio_context: Dict with keys:
                - ``daily_returns`` (list[float])
                - ``daily_pnl_pct`` (float)
                - ``weekly_pnl_pct`` (float)
                - ``portfolio_value`` (float)
                - ``position_weights`` (dict[str, float])
        """
        volatility_regime = "medium"
        circuit_breaker_state = "NORMAL"
        var_1d_95: float | None = None
        concentration_risk: float | None = None
        macro_regime = "neutral"
        watch_items: list[str] = []

        # 1. Regime detection
        try:
            daily_returns = portfolio_context.get("daily_returns", [])
            if daily_returns is not None and len(daily_returns) > 0:
                report = self._regime_detector.detect(daily_returns)
                if report.current_regime and report.current_regime.regime_label:
                    label = report.current_regime.regime_label
                    volatility_regime = _normalize_regime_label(label)
        except Exception:
            logger.warning("RegimeDetector failed; defaulting to medium", exc_info=True)

        # 2. Circuit breaker
        try:
            daily_pnl = portfolio_context.get("daily_pnl_pct", 0.0)
            weekly_pnl = portfolio_context.get("weekly_pnl_pct", 0.0)
            breaker_status = self._circuit_breaker.check(daily_pnl, weekly_pnl)
            circuit_breaker_state = breaker_status.state.value.upper()
            if not breaker_status.can_trade:
                watch_items.append(
                    f"熔断触发: {breaker_status.trigger_reason or circuit_breaker_state}"
                )
        except Exception:
            logger.warning("CircuitBreaker failed; defaulting to NORMAL", exc_info=True)

        # 3. VaR
        try:
            daily_returns_list = portfolio_context.get("daily_returns", [])
            portfolio_value = portfolio_context.get("portfolio_value", 0.0)
            if daily_returns_list and portfolio_value > 0:
                returns_arr = np.asarray(daily_returns_list, dtype=float)
                var_result = self._var_calculator.historical_var(
                    returns=returns_arr,
                    portfolio_value=portfolio_value,
                    confidence_level=0.95,
                    holding_period=1,
                )
                var_1d_95 = var_result.var_pct
        except Exception:
            logger.warning("VaRCalculator failed; VaR unavailable", exc_info=True)

        # 4. Concentration risk
        try:
            position_weights = portfolio_context.get("position_weights", {})
            if position_weights:
                concentration_risk = max(position_weights.values())
        except Exception:
            logger.warning("Concentration risk calculation failed", exc_info=True)

        # 5. Macro regime (optional)
        if self._macro_classifier is not None:
            try:
                macro_result = self._macro_classifier.classify()
                macro_regime = macro_result.get("macro_regime", "neutral")
            except Exception:
                logger.warning(
                    "MacroRegimeClassifier failed; defaulting to neutral",
                    exc_info=True,
                )

        # 6. Determine risk level
        risk_level = _determine_risk_level(
            circuit_breaker_state=circuit_breaker_state,
            var_1d_95=var_1d_95,
            volatility_regime=volatility_regime,
            concentration_risk=concentration_risk,
        )

        # 7. Build explanation
        explanation = _build_explanation(
            risk_level=risk_level,
            volatility_regime=volatility_regime,
            circuit_breaker_state=circuit_breaker_state,
            var_1d_95=var_1d_95,
            concentration_risk=concentration_risk,
            macro_regime=macro_regime,
        )

        # 8. Attach to signal
        signal.risk_level = risk_level
        signal.risk_context = RiskContext(
            volatility_regime=volatility_regime,
            circuit_breaker_state=circuit_breaker_state,
            var_1d_95=var_1d_95,
            concentration_risk=concentration_risk,
            macro_regime=macro_regime,
            explanation=explanation,
            watch_items=watch_items,
        )

        return signal

    def should_block(self, signal: MarketSignal) -> bool:
        """Return True if the signal should be suppressed.

        Blocks when risk is EXTREME *and* the signal confidence is below 40.
        """
        return signal.risk_level == RiskLevel.EXTREME and signal.confidence_score < 40


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_regime_label(label: str) -> str:
    """Map RegimeDetector labels to the canonical low/medium/high vocabulary."""
    lower = label.lower()
    if "low" in lower:
        return "low"
    if "high" in lower:
        return "high"
    return "medium"


def _determine_risk_level(
    *,
    circuit_breaker_state: str,
    var_1d_95: float | None,
    volatility_regime: str,
    concentration_risk: float | None,
) -> RiskLevel:
    """Apply the PRD risk-level decision rules.

    Priority order (highest first):
    - EXTREME: breaker != NORMAL OR var > 8% OR (high vol AND concentration > 0.7)
    - ELEVATED: var > 5% OR high vol
    - MODERATE: var > 3% OR medium vol
    - LOW: otherwise
    """
    var = var_1d_95 if var_1d_95 is not None else 0.0
    conc = concentration_risk if concentration_risk is not None else 0.0

    # EXTREME
    if circuit_breaker_state != "NORMAL":
        return RiskLevel.EXTREME
    if var > 0.08:
        return RiskLevel.EXTREME
    if volatility_regime == "high" and conc > 0.7:
        return RiskLevel.EXTREME

    # ELEVATED
    if var > 0.05:
        return RiskLevel.ELEVATED
    if volatility_regime == "high":
        return RiskLevel.ELEVATED

    # MODERATE
    if var > 0.03:
        return RiskLevel.MODERATE
    if volatility_regime == "medium":
        return RiskLevel.MODERATE

    return RiskLevel.LOW


def _build_explanation(
    *,
    risk_level: RiskLevel,
    volatility_regime: str,
    circuit_breaker_state: str,
    var_1d_95: float | None,
    concentration_risk: float | None,
    macro_regime: str,
) -> str:
    """Build a Chinese-language explanation string for the risk assessment."""
    parts: list[str] = []

    level_cn = {
        RiskLevel.LOW: "低",
        RiskLevel.MODERATE: "中等",
        RiskLevel.ELEVATED: "偏高",
        RiskLevel.EXTREME: "极端",
    }
    parts.append(f"综合风险等级: {level_cn.get(risk_level, str(risk_level.value))}")

    vol_cn = {"low": "低波动", "medium": "中波动", "high": "高波动"}
    parts.append(f"波动率状态: {vol_cn.get(volatility_regime, volatility_regime)}")

    if circuit_breaker_state != "NORMAL":
        parts.append(f"熔断状态: {circuit_breaker_state}")

    if var_1d_95 is not None:
        parts.append(f"1日95%VaR: {var_1d_95:.2%}")

    if concentration_risk is not None:
        parts.append(f"集中度: {concentration_risk:.1%}")

    macro_cn = {"risk_on": "风险偏好", "risk_off": "风险规避", "neutral": "中性"}
    parts.append(f"宏观环境: {macro_cn.get(macro_regime, macro_regime)}")

    return "；".join(parts)

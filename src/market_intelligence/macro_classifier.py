"""Macro Regime Classifier for the v20.0 Market Intelligence pipeline.

Determines the prevailing macro backdrop (risk_on / risk_off / neutral)
by examining VIX level and the US Treasury yield curve.  This classification
feeds into the RiskOverlayEngine as an optional enrichment signal.

Part of v20.0 Market Intelligence Phase 2.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.global_market import GlobalMarketFetcher

logger = logging.getLogger(__name__)

# Thresholds
_VIX_RISK_OFF_THRESHOLD = 25.0


class MacroRegimeClassifier:
    """Classify the macro regime from VIX and yield-curve data.

    Usage::

        classifier = MacroRegimeClassifier(global_market_fetcher)
        result = classifier.classify()
        print(result["macro_regime"])  # "risk_on" | "risk_off" | "neutral"
    """

    def __init__(
        self,
        global_market_fetcher: GlobalMarketFetcher | None = None,
    ) -> None:
        self._fetcher = global_market_fetcher

    def classify(self) -> dict:
        """Return a macro regime classification dict.

        Returns:
            Dict with keys:
                - ``macro_regime``: ``"risk_on"`` | ``"risk_off"`` | ``"neutral"``
                - ``vix_level``: Current VIX value or ``None``
                - ``yield_spread``: 10Y minus 2Y spread or ``None``
                - ``explanation``: Chinese-language explanation string
        """
        vix_level: float | None = None
        yield_spread: float | None = None
        risk_off_signals: list[str] = []
        risk_on_signals: list[str] = []

        # 1. VIX
        vix_level = self._fetch_vix()
        if vix_level is not None:
            if vix_level > _VIX_RISK_OFF_THRESHOLD:
                risk_off_signals.append(
                    f"VIX={vix_level:.1f} 超过阈值 {_VIX_RISK_OFF_THRESHOLD}"
                )
            else:
                risk_on_signals.append(f"VIX={vix_level:.1f} 处于正常水平")

        # 2. Yield curve
        yield_spread = self._fetch_yield_spread()
        if yield_spread is not None:
            if yield_spread < 0:
                risk_off_signals.append(f"收益率曲线倒挂 (利差={yield_spread:.2f}%)")
            else:
                risk_on_signals.append(f"收益率曲线正常 (利差={yield_spread:.2f}%)")

        # 3. Decision
        if risk_off_signals:
            macro_regime = "risk_off"
            explanation = "宏观环境偏向风险规避: " + "; ".join(risk_off_signals)
        elif risk_on_signals:
            macro_regime = "risk_on"
            explanation = "宏观环境偏向风险偏好: " + "; ".join(risk_on_signals)
        else:
            macro_regime = "neutral"
            explanation = "宏观数据不足，默认中性判断"

        return {
            "macro_regime": macro_regime,
            "vix_level": vix_level,
            "yield_spread": yield_spread,
            "explanation": explanation,
        }

    # ------------------------------------------------------------------
    # Data fetching helpers
    # ------------------------------------------------------------------

    def _fetch_vix(self) -> float | None:
        """Fetch VIX level via GlobalMarketFetcher."""
        if self._fetcher is None:
            return None
        try:
            raw = self._fetcher._fetch_tickers(["^VIX"])
            vix_data = raw.get("^VIX", {})
            price = vix_data.get("price")
            return float(price) if price is not None else None
        except Exception:
            logger.warning("Failed to fetch VIX data", exc_info=True)
            return None

    def _fetch_yield_spread(self) -> float | None:
        """Fetch US 10Y-2Y yield spread via GlobalMarketFetcher.fetch_bond_yields."""
        if self._fetcher is None:
            return None
        try:
            yields = self._fetcher.fetch_bond_yields()
            us_10y = yields.get("US_10Y")
            us_2y = yields.get("US_2Y")
            if us_10y is not None and us_2y is not None:
                return round(us_10y - us_2y, 4)
            return None
        except Exception:
            logger.warning("Failed to fetch bond yield data", exc_info=True)
            return None

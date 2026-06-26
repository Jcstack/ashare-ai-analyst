"""Qlib alpha factor computation — custom factor library for stock screening.

FR-QL001: a hand-written set of ~20 alpha factors expressed in the Qlib DSL,
computed via the QlibAdapter (remote/subprocess/in-process). This is *inspired
by* Qlib's Alpha158 factor categories but is NOT Qlib's Alpha158 dataset handler
— it does not instantiate or reproduce the full 158-factor set.

Factor categories:
- Momentum: 5d, 10d, 20d, 60d price momentum
- Reversal: mean reversion signals (overreaction detection)
- Volatility: historical volatility at multiple windows
- Liquidity: turnover ratio / Amihud illiquidity proxy
- Quality: ROE stability proxy via price-earnings consistency

All factors are normalized to comparable ranges for scoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AlphaFactors:
    """Container for computed alpha factors for a single stock."""

    symbol: str
    factors: dict[str, float] = field(default_factory=dict)
    available: bool = False

    @property
    def momentum_score(self) -> float:
        """Aggregate momentum score (average of momentum + roc factors, 0-1)."""
        keys = [
            k for k in self.factors if k.startswith("momentum_") or k.startswith("roc_")
        ]
        if not keys:
            return 0.5
        return sum(self.factors[k] for k in keys) / len(keys)

    @property
    def reversal_score(self) -> float:
        """Aggregate reversal/mean-reversion score."""
        keys = [
            k
            for k in self.factors
            if k.startswith("mean_reversion_") or k == "high_low_ratio_20d"
        ]
        if not keys:
            return 0.5
        return sum(self.factors[k] for k in keys) / len(keys)

    @property
    def volatility_score(self) -> float:
        """Aggregate volatility (lower is better for screening)."""
        keys = [
            k for k in self.factors if k.startswith("volatility_") or k == "atr_14d"
        ]
        if not keys:
            return 0.5
        raw = sum(self.factors[k] for k in keys) / len(keys)
        return max(0.0, min(1.0, 1.0 - raw))  # invert: low vol = high score

    @property
    def liquidity_score(self) -> float:
        """Liquidity score from turnover, volume MA ratio, OBV, VWAP."""
        keys = [
            k
            for k in self.factors
            if k
            in (
                "turnover_ratio",
                "volume_ma_ratio_5_20",
                "obv_slope",
                "vwap_deviation",
            )
        ]
        if not keys:
            return 0.5
        return max(0.0, min(1.0, sum(self.factors[k] for k in keys) / len(keys)))

    @property
    def price_pattern_score(self) -> float:
        """Price pattern score from MA deviations."""
        keys = [k for k in self.factors if k.startswith("price_to_ma")]
        if not keys:
            return 0.5
        return sum(self.factors[k] for k in keys) / len(keys)

    @property
    def quality_score(self) -> float:
        """Quality/strength score from RSI, shadow ratio, and derived quality."""
        keys = [
            k
            for k in self.factors
            if k in ("rsi_14", "upper_shadow_ratio", "quality_score")
        ]
        if not keys:
            return 0.5
        return sum(self.factors[k] for k in keys) / len(keys)

    @property
    def composite_score(self) -> float:
        """Weighted composite of all factor dimensions."""
        if not self.available:
            return 0.5
        weights = {
            "momentum": 0.25,
            "reversal": 0.10,
            "volatility": 0.15,
            "liquidity": 0.15,
            "price_pattern": 0.15,
            "quality": 0.20,
        }
        scores = {
            "momentum": self.momentum_score,
            "reversal": self.reversal_score,
            "volatility": self.volatility_score,
            "liquidity": self.liquidity_score,
            "price_pattern": self.price_pattern_score,
            "quality": self.quality_score,
        }
        return round(
            sum(weights[k] * scores[k] for k in weights),
            4,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "factors": self.factors,
            "available": self.available,
            "momentum_score": round(self.momentum_score, 4),
            "reversal_score": round(self.reversal_score, 4),
            "volatility_score": round(self.volatility_score, 4),
            "liquidity_score": round(self.liquidity_score, 4),
            "price_pattern_score": round(self.price_pattern_score, 4),
            "quality_score": round(self.quality_score, 4),
            "composite_score": self.composite_score,
        }


class QlibAlphaEngine:
    """Enhanced alpha factor computation using QlibAdapter.

    Uses the existing QlibAdapter (remote/subprocess/in-process) to compute
    alpha factors, then enriches them with derived scores.
    """

    def __init__(self, qlib_adapter: Any | None = None) -> None:
        self._qlib = qlib_adapter

    def compute_factors(self, symbol: str) -> AlphaFactors:
        """Compute all alpha factors for a single stock."""
        result = AlphaFactors(symbol=symbol)

        if self._qlib is None:
            return result

        try:
            if not self._qlib.is_available():
                return result

            raw = self._qlib.get_alpha_factors(symbol)
            if not raw:
                return result

            result.factors = self._normalize_factors(raw)
            result.available = True

        except Exception as exc:
            logger.warning("Alpha factor computation failed for %s: %s", symbol, exc)

        return result

    def compute_batch(self, symbols: list[str]) -> dict[str, AlphaFactors]:
        """Compute factors for multiple symbols."""
        return {s: self.compute_factors(s) for s in symbols}

    def _normalize_factors(self, raw: dict[str, float]) -> dict[str, float]:
        """Normalize raw Qlib factors to [0, 1] range using sigmoid."""
        import math

        normalized: dict[str, float] = {}
        for name, val in raw.items():
            if name.startswith("momentum_") or name.startswith("roc_"):
                # Momentum/ROC: center at 0, scale by 10
                normalized[name] = round(1.0 / (1.0 + math.exp(-val * 10)), 4)
            elif name.startswith("mean_reversion_"):
                # Mean reversion: positive = below MA (buy signal), sigmoid
                normalized[name] = round(1.0 / (1.0 + math.exp(-val * 10)), 4)
            elif name == "high_low_ratio_20d":
                # Range ratio: higher = more volatile, sigmoid centered at 0.03
                normalized[name] = round(1.0 / (1.0 + math.exp(-(val - 0.03) * 30)), 4)
            elif name.startswith("volatility_") or name == "atr_14d":
                # Volatility: raw is coefficient of variation, keep in [0, 1]
                normalized[name] = round(max(0.0, min(1.0, val)), 4)
            elif name in ("turnover_ratio", "volume_ma_ratio_5_20"):
                # Turnover/volume ratios: sigmoid centered at 1.0
                normalized[name] = round(1.0 / (1.0 + math.exp(-(val - 1.0))), 4)
            elif name == "obv_slope":
                # OBV slope: [-1, 1] range, sigmoid
                normalized[name] = round(1.0 / (1.0 + math.exp(-val * 3)), 4)
            elif name == "vwap_deviation":
                # VWAP deviation: center at 0
                normalized[name] = round(1.0 / (1.0 + math.exp(-val * 10)), 4)
            elif name.startswith("price_to_ma"):
                # Price relative to MA: center at 0
                normalized[name] = round(1.0 / (1.0 + math.exp(-val * 10)), 4)
            elif name == "rsi_14":
                # RSI: already 0-100, normalize to 0-1
                normalized[name] = round(max(0.0, min(1.0, val / 100.0)), 4)
            elif name == "upper_shadow_ratio":
                # Upper shadow: 0-1 range, invert (less shadow = better)
                normalized[name] = round(max(0.0, min(1.0, 1.0 - val)), 4)
            else:
                normalized[name] = round(max(0.0, min(1.0, val)), 4)

        # Derive quality score from stability of momentum
        m5 = normalized.get("momentum_5d", 0.5)
        m20 = normalized.get("momentum_20d", 0.5)
        quality = 1.0 - abs(m5 - m20)  # consistent momentum = higher quality
        normalized["quality_score"] = round(max(0.0, min(1.0, quality)), 4)

        return normalized

"""Qlib Alpha factor computation — enhanced factor library for stock screening.

FR-QL001: Wraps Qlib-style Alpha158 factor categories into a computation
engine that works via the QlibAdapter (remote/subprocess/in-process).

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
        """Aggregate momentum score (average of momentum factors, 0-1)."""
        keys = [k for k in self.factors if k.startswith("momentum_")]
        if not keys:
            return 0.5
        return sum(self.factors[k] for k in keys) / len(keys)

    @property
    def volatility_score(self) -> float:
        """Aggregate volatility (lower is better for screening)."""
        keys = [k for k in self.factors if k.startswith("volatility_")]
        if not keys:
            return 0.5
        raw = sum(self.factors[k] for k in keys) / len(keys)
        return max(0.0, min(1.0, 1.0 - raw))  # invert: low vol = high score

    @property
    def liquidity_score(self) -> float:
        """Liquidity score (higher is better)."""
        tr = self.factors.get("turnover_ratio")
        if tr is None:
            return 0.5
        return max(0.0, min(1.0, tr))

    @property
    def composite_score(self) -> float:
        """Weighted composite of all factor dimensions."""
        if not self.available:
            return 0.5
        weights = {
            "momentum": 0.35,
            "volatility": 0.25,
            "liquidity": 0.20,
            "quality": 0.20,
        }
        scores = {
            "momentum": self.momentum_score,
            "volatility": self.volatility_score,
            "liquidity": self.liquidity_score,
            "quality": self.factors.get("quality_score", 0.5),
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
            "volatility_score": round(self.volatility_score, 4),
            "liquidity_score": round(self.liquidity_score, 4),
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
            if name.startswith("momentum_"):
                # Momentum: center at 0, scale by 10
                normalized[name] = round(1.0 / (1.0 + math.exp(-val * 10)), 4)
            elif name.startswith("volatility_"):
                # Volatility: raw is coefficient of variation, keep in [0, 1]
                normalized[name] = round(max(0.0, min(1.0, val)), 4)
            elif name == "turnover_ratio":
                # Turnover: sigmoid centered at 1.0
                normalized[name] = round(1.0 / (1.0 + math.exp(-(val - 1.0))), 4)
            elif name == "price_to_ma20":
                # Price relative to MA: center at 0
                normalized[name] = round(1.0 / (1.0 + math.exp(-val * 10)), 4)
            else:
                normalized[name] = round(max(0.0, min(1.0, val)), 4)

        # Derive quality score from stability of momentum
        m5 = normalized.get("momentum_5d", 0.5)
        m20 = normalized.get("momentum_20d", 0.5)
        quality = 1.0 - abs(m5 - m20)  # consistent momentum = higher quality
        normalized["quality_score"] = round(max(0.0, min(1.0, quality)), 4)

        return normalized

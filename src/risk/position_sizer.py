"""Dynamic position sizing engine.

Part of v17.0 Institutional Risk Engine.

Implements:
- Kelly criterion (fractional, with conservative scaling)
- Volatility scaling (target vol vs realized vol)
- A-share constraints: 100-share lots, 30% max single position
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SizingResult:
    """Result of a position sizing calculation."""

    symbol: str
    recommended_weight: float  # Fraction of portfolio (0-1)
    recommended_shares: int  # Rounded to 100-share lots
    recommended_amount: float  # Currency amount
    kelly_raw: float  # Raw Kelly fraction (before scaling)
    kelly_scaled: float  # Scaled Kelly fraction
    vol_adjustment: float  # Volatility scaling factor
    capped: bool  # Whether max_single_weight cap was applied
    lot_adjusted: bool  # Whether 100-share rounding changed the amount
    warnings: list[str] = field(default_factory=list)


@dataclass
class PositionSizingConfig:
    """Configuration for position sizing."""

    max_single_weight: float = 0.30
    min_lot_size: int = 100
    kelly_fraction: float = 0.25
    target_volatility: float = 0.15
    max_leverage: float = 1.0


class PositionSizer:
    """Calculates optimal position sizes using Kelly + vol-scaling."""

    def __init__(self, config: PositionSizingConfig | None = None):
        self.config = config or PositionSizingConfig()

    def kelly_criterion(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
    ) -> float:
        """Calculate raw Kelly fraction.

        f* = (p * b - q) / b

        Where:
            p = probability of winning
            q = probability of losing (1 - p)
            b = ratio of average win to average loss
        """
        if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0

        p = win_rate
        q = 1 - p
        b = abs(avg_win / avg_loss)

        if b <= 0:
            return 0.0

        kelly = (p * b - q) / b
        return max(kelly, 0.0)

    def volatility_scale(
        self,
        realized_vol: float,
        target_vol: float | None = None,
    ) -> float:
        """Calculate volatility scaling factor.

        Scales position size inversely proportional to realized volatility
        relative to target volatility.
        """
        target = target_vol or self.config.target_volatility

        if realized_vol <= 0:
            return 1.0

        # Scale = target_vol / realized_vol, capped at 2.0
        scale = target / realized_vol
        return min(scale, 2.0)

    def conviction_multiplier(
        self,
        rr_ratio: float = 0.0,
        confidence: float = 0.5,
    ) -> float:
        """Dynamic Kelly multiplier based on R/R ratio and confidence.

        High R/R (>3) × high confidence (>0.8) → up to 2x Kelly.
        Low R/R or low confidence → 0.5-1.0x.

        Args:
            rr_ratio: Reward/risk ratio (target upside / stop-loss downside).
            confidence: Decision confidence (0-1).

        Returns:
            Multiplier (0.5 to 2.0) to apply to Kelly fraction.
        """
        if rr_ratio <= 0 or confidence <= 0:
            return 0.5

        # Base: (rr / 2.0) * (conf / 0.7), capped at 2.0
        raw = (rr_ratio / 2.0) * (confidence / 0.7)
        return max(0.5, min(2.0, round(raw, 2)))

    def calculate_size(
        self,
        symbol: str,
        portfolio_value: float,
        current_price: float,
        win_rate: float = 0.5,
        avg_win: float = 0.05,
        avg_loss: float = 0.03,
        realized_vol: float | None = None,
        returns: np.ndarray | None = None,
        rr_ratio: float = 0.0,
        current_confidence: float = 0.5,
    ) -> SizingResult:
        """Calculate recommended position size for a stock.

        Args:
            symbol: Stock code.
            portfolio_value: Total portfolio value.
            current_price: Current stock price.
            win_rate: Estimated probability of positive return.
            avg_win: Average winning return (e.g., 0.05 = 5%).
            avg_loss: Average losing return magnitude (positive, e.g., 0.03 = 3%).
            realized_vol: Annualized realized volatility. If None, computed from returns.
            returns: Daily returns array for volatility computation.
            rr_ratio: Current decision's reward/risk ratio.
            current_confidence: Current decision's confidence (0-1).
        """
        warnings: list[str] = []

        # 1. Kelly criterion
        kelly_raw = self.kelly_criterion(win_rate, avg_win, avg_loss)

        # Scale Kelly by conservative fraction × conviction multiplier
        conv_mult = self.conviction_multiplier(rr_ratio, current_confidence)
        kelly_scaled = kelly_raw * self.config.kelly_fraction * conv_mult
        if conv_mult != 1.0:
            warnings.append(
                f"信念乘数 {conv_mult:.1f}x (R/R={rr_ratio:.1f}, 信心={current_confidence:.0%})"
            )

        # 2. Volatility scaling
        if realized_vol is None and returns is not None:
            returns_clean = np.asarray(returns, dtype=float)
            returns_clean = returns_clean[np.isfinite(returns_clean)]
            if len(returns_clean) > 5:
                realized_vol = float(np.std(returns_clean, ddof=1) * np.sqrt(252))
            else:
                realized_vol = self.config.target_volatility
                warnings.append("收益率样本不足，使用目标波动率")

        if realized_vol is None:
            realized_vol = self.config.target_volatility

        vol_adj = self.volatility_scale(realized_vol)

        # 3. Combine: weight = kelly_scaled * vol_adjustment
        weight = kelly_scaled * vol_adj

        # 4. Cap at max_single_weight
        capped = False
        if weight > self.config.max_single_weight:
            weight = self.config.max_single_weight
            capped = True

        # Cap at max_leverage
        weight = min(weight, self.config.max_leverage)

        # 5. Calculate amount and shares
        amount = portfolio_value * weight

        # Round to 100-share lots
        lot_adjusted = False
        if current_price > 0:
            shares_raw = amount / current_price
            shares = (
                int(shares_raw // self.config.min_lot_size) * self.config.min_lot_size
            )
            if shares != math.floor(shares_raw):
                lot_adjusted = True
            # Recalculate amount after lot rounding
            actual_amount = shares * current_price
        else:
            shares = 0
            actual_amount = 0
            warnings.append("股价无效")

        if kelly_raw <= 0:
            warnings.append("Kelly 公式建议不配置该股票（期望收益为负）")

        return SizingResult(
            symbol=symbol,
            recommended_weight=round(weight, 4),
            recommended_shares=shares,
            recommended_amount=round(actual_amount, 2),
            kelly_raw=round(kelly_raw, 4),
            kelly_scaled=round(kelly_scaled, 4),
            vol_adjustment=round(vol_adj, 4),
            capped=capped,
            lot_adjusted=lot_adjusted,
            warnings=warnings,
        )

    def validate_portfolio_weights(
        self,
        weights: dict[str, float],
    ) -> list[str]:
        """Validate a set of portfolio weights against constraints.

        Returns list of warning messages. Empty = valid.
        """
        warnings = []
        total = sum(weights.values())

        if total > self.config.max_leverage:
            warnings.append(
                f"总仓位 {total:.1%} 超过最大杠杆 {self.config.max_leverage:.1%}"
            )

        for symbol, w in weights.items():
            if w > self.config.max_single_weight:
                warnings.append(
                    f"{symbol} 仓位 {w:.1%} 超过单仓上限 {self.config.max_single_weight:.1%}"
                )
            if w < 0:
                warnings.append(f"{symbol} 仓位为负 ({w:.1%})，不支持做空")

        return warnings

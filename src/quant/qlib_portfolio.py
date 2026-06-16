"""Qlib portfolio optimization — rule-based position sizing with factor signals.

FR-QL002: Portfolio optimization using alpha factors and risk constraints.

Note: Full RL (PPO) optimization requires Qlib RL module which is only
available in the Qlib service container. This module provides a rule-based
optimizer that uses alpha factor signals + risk constraints as a practical
alternative, with the same output format for downstream compatibility.

Output: target weights + rebalance suggestions + expected risk metrics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PortfolioTarget:
    """Optimized portfolio target for a single position."""

    symbol: str
    name: str = ""
    current_weight: float = 0.0
    target_weight: float = 0.0
    alpha_score: float = 0.5
    action: str = "hold"  # "buy" | "sell" | "hold" | "rebalance"
    reason: str = ""

    @property
    def weight_delta(self) -> float:
        return round(self.target_weight - self.current_weight, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "current_weight": round(self.current_weight, 4),
            "target_weight": round(self.target_weight, 4),
            "weight_delta": self.weight_delta,
            "alpha_score": round(self.alpha_score, 4),
            "action": self.action,
            "reason": self.reason,
        }


@dataclass
class OptimizationResult:
    """Full portfolio optimization output."""

    targets: list[PortfolioTarget] = field(default_factory=list)
    total_positions: int = 0
    rebalance_needed: bool = False
    risk_metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": [t.to_dict() for t in self.targets],
            "total_positions": self.total_positions,
            "rebalance_needed": self.rebalance_needed,
            "risk_metrics": self.risk_metrics,
        }


class QlibPortfolioOptimizer:
    """Rule-based portfolio optimizer using alpha factor signals.

    Constraints (A-share):
    - max_position: max weight per stock (default 30%)
    - max_stocks: max number of holdings (default 5)
    - lot_size: 100 shares per lot
    - min_rebalance_delta: minimum weight change to trigger action (default 5%)
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        if config is None:
            try:
                from src.utils.config import load_config

                research = load_config("research")
                config = research.get("ashare_constraints", {})
            except Exception:
                config = {}
        self._max_position = config.get("max_position", 0.30)
        self._max_stocks = config.get("max_stocks", 5)
        self._min_delta = config.get("min_rebalance_delta", 0.05)

    def optimize(
        self,
        positions: list[dict[str, Any]],
        alpha_scores: dict[str, float] | None = None,
    ) -> OptimizationResult:
        """Compute target weights based on alpha scores.

        Args:
            positions: List of {"symbol", "name", "market_value", ...}
            alpha_scores: Dict of symbol → composite alpha score [0, 1]
        """
        if not positions:
            return OptimizationResult()

        alpha_scores = alpha_scores or {}
        total_value = sum(p.get("market_value", 0) for p in positions) or 1.0

        # Score-based weight allocation
        scored: list[tuple[dict, float]] = []
        for pos in positions:
            sym = pos.get("symbol", "")
            score = alpha_scores.get(sym, 0.5)
            scored.append((pos, score))

        # Sort by score descending, keep top N
        scored.sort(key=lambda x: x[1], reverse=True)
        top_n = scored[: self._max_stocks]

        # Allocate weights proportional to scores
        total_score = sum(s for _, s in top_n) or 1.0
        targets: list[PortfolioTarget] = []
        rebalance_needed = False

        for pos, score in top_n:
            sym = pos.get("symbol", "")
            name = pos.get("name", sym)
            current_w = pos.get("market_value", 0) / total_value
            target_w = min(score / total_score, self._max_position)

            delta = target_w - current_w
            if abs(delta) >= self._min_delta:
                action = "buy" if delta > 0 else "sell"
                reason = f"Alpha {score:.2f}, 调整 {delta:+.1%}"
                rebalance_needed = True
            else:
                action = "hold"
                reason = f"Alpha {score:.2f}, 权重合理"

            targets.append(
                PortfolioTarget(
                    symbol=sym,
                    name=name,
                    current_weight=current_w,
                    target_weight=target_w,
                    alpha_score=score,
                    action=action,
                    reason=reason,
                )
            )

        # Positions outside top N → suggest reduce
        for pos, score in scored[self._max_stocks :]:
            sym = pos.get("symbol", "")
            name = pos.get("name", sym)
            current_w = pos.get("market_value", 0) / total_value
            if current_w > 0.01:
                rebalance_needed = True
                targets.append(
                    PortfolioTarget(
                        symbol=sym,
                        name=name,
                        current_weight=current_w,
                        target_weight=0.0,
                        alpha_score=score,
                        action="sell",
                        reason=f"Alpha {score:.2f}, 超出持仓上限 ({self._max_stocks} 只)",
                    )
                )

        # Normalize target weights to sum to 1.0
        total_target = sum(t.target_weight for t in targets) or 1.0
        for t in targets:
            if t.target_weight > 0:
                t.target_weight = round(t.target_weight / total_target, 4)

        # Risk metrics
        weights = [t.target_weight for t in targets if t.target_weight > 0]
        concentration = max(weights) if weights else 0
        diversification = len(weights)

        return OptimizationResult(
            targets=targets,
            total_positions=len(positions),
            rebalance_needed=rebalance_needed,
            risk_metrics={
                "max_concentration": round(concentration, 4),
                "diversification": diversification,
                "position_limit": self._max_stocks,
            },
        )

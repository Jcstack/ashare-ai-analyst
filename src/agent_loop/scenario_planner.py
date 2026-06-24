"""Scenario planner — best/base/worst case analysis for trading decisions.

Generates structured scenarios for every trade proposal using deterministic
rules (no LLM call). LLM-based deep scenario planning is handled separately
by the debate engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Scenario:
    """A single scenario (best / base / worst)."""

    name: str  # "乐观" / "基准" / "悲观"
    probability: float  # 0.0-1.0, all three must sum to 1.0
    description: str  # What happens in this scenario
    trigger: str  # What would trigger this scenario
    target_price: float | None = None
    time_horizon_days: int | None = None


# Regime → (best_prob, base_prob, worst_prob)
_REGIME_PROBABILITIES: dict[str, tuple[float, float, float]] = {
    "bull": (0.40, 0.40, 0.20),
    "bear": (0.15, 0.35, 0.50),
    "unknown": (0.25, 0.50, 0.25),
}


class ScenarioPlanner:
    """Generates best/base/worst case scenarios for trading decisions.

    Uses structured analysis (not LLM) for speed. LLM-based scenario
    planning is done in the debate engine for deeper analysis.
    """

    def plan(
        self,
        symbol: str,
        direction: str,  # "buy" or "sell"
        current_price: float,
        stop_loss: float | None = None,
        target_price: float | None = None,
        atr: float | None = None,
        sector: str = "",
        regime: str = "unknown",
    ) -> list[Scenario]:
        """Generate 3 scenarios (best/base/worst) for a trade.

        Args:
            stop_loss: Stop-loss as percentage (e.g. -3.0 means -3%).
            target_price: Take-profit as percentage (e.g. 6.0 means +6%).

        Rules:
        - Best case: target_price or current + 2*ATR
        - Base case: current +/- 0.5*ATR (range-bound)
        - Worst case: stop_loss or current - 2*ATR
        - Probabilities: regime-dependent
        """
        if current_price <= 0:
            logger.warning("Invalid current_price=%.2f for %s", current_price, symbol)
            return []

        effective_atr = atr if atr and atr > 0 else current_price * 0.02

        # Convert percentage-based stop/target to absolute prices
        stop_loss_price: float | None = None
        if stop_loss is not None:
            stop_loss_price = current_price * (1 + stop_loss / 100.0)
        target_abs: float | None = None
        if target_price is not None:
            target_abs = current_price * (1 + target_price / 100.0)
        probs = _REGIME_PROBABILITIES.get(regime, _REGIME_PROBABILITIES["unknown"])

        sector_label = f"（{sector}板块）" if sector else ""
        is_buy = direction.lower() in ("buy", "add")

        # Best case
        best_target = target_abs if target_abs else current_price + 2 * effective_atr
        best_return_pct = (best_target - current_price) / current_price * 100
        if is_buy:
            best_desc = (
                f"股价上涨至{best_target:.2f}元{sector_label}，"
                f"涨幅约{best_return_pct:.1f}%，板块整体走强带动"
            )
            best_trigger = "利好消息或板块轮动，主力资金持续流入"
        else:
            best_desc = f"及时卖出避免进一步下跌，资金转入更优标的{sector_label}"
            best_trigger = "止损信号确认，资金快速撤离"

        best = Scenario(
            name="乐观",
            probability=probs[0],
            description=best_desc,
            trigger=best_trigger,
            target_price=round(best_target, 2),
            time_horizon_days=5,
        )

        # Base case
        base_high = current_price + 0.5 * effective_atr
        base_low = current_price - 0.5 * effective_atr
        base_return_pct = 0.5 * effective_atr / current_price * 100
        if is_buy:
            base_desc = (
                f"股价在{base_low:.2f}-{base_high:.2f}元区间震荡{sector_label}，"
                f"波动约±{base_return_pct:.1f}%，等待方向选择"
            )
            base_trigger = "市场整体横盘，板块无明显催化剂"
        else:
            base_desc = f"股价小幅波动，卖出后短期无明显方向{sector_label}"
            base_trigger = "成交量萎缩，多空平衡"

        base = Scenario(
            name="基准",
            probability=probs[1],
            description=base_desc,
            trigger=base_trigger,
            target_price=round(current_price, 2),
            time_horizon_days=5,
        )

        # Worst case
        worst_target = (
            stop_loss_price if stop_loss_price else current_price - 2 * effective_atr
        )
        worst_return_pct = (worst_target - current_price) / current_price * 100
        if is_buy:
            worst_desc = (
                f"股价跌至{worst_target:.2f}元{sector_label}，"
                f"跌幅约{abs(worst_return_pct):.1f}%，触发止损"
            )
            worst_trigger = "利空消息、大盘系统性下跌或主力出货"
        else:
            worst_desc = (
                f"卖出后股价反弹上涨{abs(worst_return_pct):.1f}%，"
                f"错失反弹机会{sector_label}"
            )
            worst_trigger = "利好突发，市场情绪快速反转"

        worst = Scenario(
            name="悲观",
            probability=probs[2],
            description=worst_desc,
            trigger=worst_trigger,
            target_price=round(worst_target, 2),
            time_horizon_days=5,
        )

        return [best, base, worst]

    def format_for_proposal(self, scenarios: list[Scenario]) -> dict[str, str]:
        """Format scenarios for TradeProposal fields.

        Returns dict with keys: scenario_best, scenario_base, scenario_worst.
        """
        result: dict[str, str] = {
            "scenario_best": "",
            "scenario_base": "",
            "scenario_worst": "",
        }

        name_to_key = {
            "乐观": "scenario_best",
            "基准": "scenario_base",
            "悲观": "scenario_worst",
        }

        for s in scenarios:
            key = name_to_key.get(s.name)
            if key:
                price_str = f"目标{s.target_price:.2f}元" if s.target_price else ""
                result[key] = (
                    f"[{s.probability:.0%}概率] {s.description} "
                    f"{price_str}（触发: {s.trigger}）"
                )

        return result

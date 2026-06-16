"""A-Share native trading constraints — T+1 settlement, price limits, lot sizing.

Phase 6 — FR-ASC001/ASC002/ASC003: The agent THINKS in A-share terms,
not just validates after the fact. These constraints are first-class
inputs to the decision pipeline, not afterthought checks.

Key constraints modeled:
- T+1 settlement: bought today → cannot sell until tomorrow
- Price limits: main board ±10%, ChiNext/STAR ±20%
- Lot size: 100-share lots (main board), 200-share minimum (ChiNext/STAR buy)
- Liquidity: can I exit within N days given average volume?
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AShareRiskAssessment:
    """Result of A-share constraint analysis for a proposed trade."""

    # T+1 overnight risk
    overnight_max_loss_pct: float  # Max loss if limit-down tomorrow
    overnight_max_loss_amount: float
    gap_risk_score: float  # 0-1, higher = more gap risk

    # Price limit context
    board_type: str  # "main", "chinext", "star", "bse"
    price_limit_pct: float  # 10 or 20
    distance_to_upper_limit_pct: float
    distance_to_lower_limit_pct: float
    near_limit_warning: bool

    # Liquidity
    days_to_exit: float  # Estimated days to fully exit position
    liquidity_adequate: bool

    # Lot sizing
    shares_rounded: int  # Rounded to valid lot size
    min_order_value_met: bool

    # Overall
    constraint_violations: list[str]
    risk_warnings: list[str]
    tradeable: bool  # False if any hard constraint violated

    def to_dict(self) -> dict[str, Any]:
        return {
            "overnight_max_loss_pct": round(self.overnight_max_loss_pct, 4),
            "overnight_max_loss_amount": round(self.overnight_max_loss_amount, 2),
            "gap_risk_score": round(self.gap_risk_score, 3),
            "board_type": self.board_type,
            "price_limit_pct": self.price_limit_pct,
            "distance_to_upper_limit_pct": round(self.distance_to_upper_limit_pct, 4),
            "distance_to_lower_limit_pct": round(self.distance_to_lower_limit_pct, 4),
            "near_limit_warning": self.near_limit_warning,
            "days_to_exit": round(self.days_to_exit, 1),
            "liquidity_adequate": self.liquidity_adequate,
            "shares_rounded": self.shares_rounded,
            "constraint_violations": self.constraint_violations,
            "risk_warnings": self.risk_warnings,
            "tradeable": self.tradeable,
        }


class AShareConstraintChecker:
    """First-class A-share trading constraint engine.

    The agent calls this BEFORE making any trade decision to understand
    the full constraint landscape. Not just validation — intelligence.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._min_order_value = cfg.get("min_order_value", 1000.0)
        self._max_days_to_exit = cfg.get("max_days_to_exit", 3.0)
        self._near_limit_threshold = cfg.get("near_limit_threshold_pct", 0.08)
        self._overnight_risk_budget = cfg.get("overnight_risk_budget_pct", 0.05)

    def assess_trade(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        portfolio_value: float,
        market_data: dict[str, Any] | None = None,
    ) -> AShareRiskAssessment:
        """Full A-share constraint assessment for a proposed trade.

        Args:
            symbol: Stock code (e.g., "600519", "300750", "688981").
            action: "buy", "sell", "add", "reduce".
            shares: Proposed number of shares.
            price: Current/target price.
            portfolio_value: Total portfolio value for risk budgeting.
            market_data: Optional dict with keys like ``avg_volume``,
                ``daily_change_pct``, ``prev_close``, ``upper_limit``,
                ``lower_limit``.
        """
        mkt = market_data or {}
        board = self._detect_board_type(symbol)
        limit_pct = _PRICE_LIMITS[board]

        # Round shares to valid lot
        shares_rounded = self._round_to_lot(shares, board, action)

        violations: list[str] = []
        warnings: list[str] = []

        # -- T+1 overnight risk (FR-ASC001) --
        position_value = shares_rounded * price
        overnight_max_loss_pct = limit_pct / 100.0  # Limit-down = max overnight loss
        overnight_max_loss = position_value * overnight_max_loss_pct

        # Gap risk: higher if stock moved significantly today
        daily_change = abs(mkt.get("daily_change_pct", 0))
        gap_risk = min(1.0, daily_change / (limit_pct / 100.0))

        # Penalize if near daily limit (momentum exhaustion)
        if daily_change > self._near_limit_threshold:
            gap_risk = min(1.0, gap_risk * 1.5)

        # Check overnight risk budget
        if portfolio_value > 0:
            overnight_risk_of_portfolio = overnight_max_loss / portfolio_value
            if overnight_risk_of_portfolio > self._overnight_risk_budget:
                warnings.append(
                    f"隔夜风险{overnight_risk_of_portfolio:.1%}超过预算"
                    f"{self._overnight_risk_budget:.1%}"
                )

        # -- Price limit awareness (FR-ASC002) --
        prev_close = mkt.get("prev_close", price)
        upper_limit = mkt.get("upper_limit", prev_close * (1 + limit_pct / 100))
        lower_limit = mkt.get("lower_limit", prev_close * (1 - limit_pct / 100))

        dist_upper = (upper_limit - price) / price if price > 0 else 0
        dist_lower = (price - lower_limit) / price if price > 0 else 0

        near_limit = False
        if action in ("buy", "add") and dist_upper < 0.02:
            near_limit = True
            warnings.append(
                f"距涨停仅{dist_upper:.1%}，追高风险大"
            )
        if action in ("sell", "reduce") and dist_lower < 0.02:
            near_limit = True
            warnings.append(
                f"距跌停仅{dist_lower:.1%}，可能无法卖出"
            )

        # Confidence penalty when near limit
        if daily_change > limit_pct / 100 * 0.8:
            warnings.append(
                f"今日涨跌幅{daily_change:.1%}接近涨跌停，动能耗尽风险"
            )

        # -- Liquidity check (FR-ASC003) --
        avg_volume = mkt.get("avg_volume", 0)
        if avg_volume > 0:
            # Assume we can trade up to 5% of daily volume without impact
            daily_tradeable = avg_volume * 0.05
            days_to_exit = shares_rounded / daily_tradeable if daily_tradeable > 0 else 99
        else:
            days_to_exit = 0.0  # Unknown volume → skip check

        liquidity_ok = days_to_exit <= self._max_days_to_exit
        if not liquidity_ok and avg_volume > 0:
            warnings.append(
                f"流动性不足: 预计{days_to_exit:.1f}天才能完全退出"
            )

        # -- Lot size validation --
        if shares_rounded == 0 and action in ("buy", "add"):
            violations.append("股数不足一手(100股)")

        # Min order value
        order_value = shares_rounded * price
        min_value_ok = order_value >= self._min_order_value or action in ("sell", "reduce")
        if not min_value_ok:
            violations.append(
                f"订单金额¥{order_value:.0f}低于最低要求¥{self._min_order_value:.0f}"
            )

        tradeable = len(violations) == 0

        return AShareRiskAssessment(
            overnight_max_loss_pct=overnight_max_loss_pct,
            overnight_max_loss_amount=overnight_max_loss,
            gap_risk_score=gap_risk,
            board_type=board,
            price_limit_pct=limit_pct,
            distance_to_upper_limit_pct=dist_upper,
            distance_to_lower_limit_pct=dist_lower,
            near_limit_warning=near_limit,
            days_to_exit=days_to_exit,
            liquidity_adequate=liquidity_ok,
            shares_rounded=shares_rounded,
            min_order_value_met=min_value_ok,
            constraint_violations=violations,
            risk_warnings=warnings,
            tradeable=tradeable,
        )

    def check_t1_sellable(
        self, symbol: str, positions: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Check how many shares of *symbol* are sellable today (T+1 rule).

        Returns:
            (sellable_shares, locked_shares) — locked = bought today.
        """
        held = next(
            (p for p in positions if p.get("symbol") == symbol), None
        )
        if not held:
            return 0, 0

        total_shares = held.get("shares", 0)
        # Shares bought today are locked (T+1)
        today_bought = held.get("today_bought", 0)
        sellable = max(0, total_shares - today_bought)

        return sellable, today_bought

    def adjust_shares_for_liquidity(
        self,
        shares: int,
        symbol: str,
        avg_volume: float,
        max_days: float = 2.0,
    ) -> int:
        """Reduce share count to ensure exit within *max_days*.

        Conservative: assumes 5% of daily volume is our max participation.
        """
        if avg_volume <= 0:
            return shares

        max_shares = int(avg_volume * 0.05 * max_days)
        board = self._detect_board_type(symbol)
        adjusted = min(shares, max_shares)
        return self._round_to_lot(adjusted, board, "buy")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_board_type(symbol: str) -> str:
        """Detect board type from stock code prefix.

        - 60xxxx, 00xxxx → main board (SSE/SZSE), ±10%
        - 30xxxx → ChiNext (创业板), ±20%
        - 68xxxx → STAR Market (科创板), ±20%
        - 8xxxxx, 4xxxxx → BSE (北交所), ±30%
        """
        if symbol.startswith("68"):
            return "star"
        if symbol.startswith("30"):
            return "chinext"
        if symbol.startswith(("8", "4")):
            return "bse"
        return "main"

    @staticmethod
    def _round_to_lot(shares: int, board: str, action: str) -> int:
        """Round shares to valid A-share lot size.

        Main board / ChiNext / STAR: 100-share lots.
        Sell: can sell odd lots (< 100) if that's all you hold.
        """
        if action in ("sell", "reduce"):
            # Selling can use odd lots — no rounding needed
            return shares

        # Buy/add: must be 100-share multiples
        return (shares // 100) * 100


# Price limit percentages by board type
_PRICE_LIMITS: dict[str, float] = {
    "main": 10.0,
    "chinext": 20.0,
    "star": 20.0,
    "bse": 30.0,
}

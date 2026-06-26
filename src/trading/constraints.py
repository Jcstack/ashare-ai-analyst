"""Trading Constraints Engine — enforces A-share rules across the entire pipeline.

Per PRD v34.0 FR-PA004: Full-pipeline constraint enforcement for:
- Exchange restrictions (main board only, no ChiNext/STAR/BSE)
- T+1 settlement rules
- Ultra-short-term trading constraints
- Lot size and commission rules
- Chase-buy penalties
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from src.utils.ashare_constants import (
    CHINEXT_PREFIXES,
    COMMISSION_RATE,
    LOT_SIZE,
    STAMP_DUTY_RATE,
    STAR_PREFIXES,
)
from src.utils.config import load_config

logger = logging.getLogger(__name__)

# A-share exchange prefixes (CHINEXT/STAR from the canonical constants module)
BSE_PREFIXES = ("8",)  # 北交所
MAIN_BOARD_SH = ("600", "601", "603", "605")  # 沪市主板
MAIN_BOARD_SZ = ("000", "001", "002", "003")  # 深市主板


@dataclass
class ConstraintViolation:
    """A single constraint violation."""

    rule: str  # e.g. "exchange_blocked", "chase_buy", "low_liquidity"
    severity: str  # "block" | "warn" | "info"
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConstraintCheckResult:
    """Result of checking a stock against all trading constraints."""

    symbol: str
    name: str
    passed: bool
    violations: list[ConstraintViolation] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(v.severity == "block" for v in self.violations)

    @property
    def warnings(self) -> list[ConstraintViolation]:
        return [v for v in self.violations if v.severity == "warn"]


class TradingConstraintsEngine:
    """Centralized trading constraint enforcement for A-share market.

    Used by: recommendation screener, rotation engine, agent outputs,
    portfolio suggestions — any component that produces trade recommendations.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or self._load_config()
        self._allowed_boards = self._config.get("allowed_boards", ["main"])
        self._max_hold_days = self._config.get("max_hold_days", 3)
        self._max_single_position_pct = self._config.get(
            "max_single_position_pct", 30.0
        )
        self._max_chase_pct = self._config.get("max_intraday_chase_pct", 5.0)
        self._min_daily_turnover_wan = self._config.get("min_daily_turnover_wan", 5000)
        self._lot_size = self._config.get("lot_size", LOT_SIZE)
        self._commission_rate = self._config.get("commission_rate", COMMISSION_RATE)
        self._stamp_duty_rate = self._config.get("stamp_duty_rate", STAMP_DUTY_RATE)
        self._min_commission = self._config.get("min_commission", 5.0)
        logger.info("TradingConstraintsEngine initialized")

    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            cfg = load_config("trading_constraints")
            return cfg
        except FileNotFoundError:
            logger.warning("config/trading_constraints.yaml not found; using defaults")
            return {}

    # ------------------------------------------------------------------
    # Exchange / board checks
    # ------------------------------------------------------------------

    def get_board(self, symbol: str) -> str:
        """Determine which board a stock belongs to based on its code prefix."""
        code = symbol.split(".")[0]  # strip exchange suffix if present
        if code.startswith(CHINEXT_PREFIXES):
            return "chinext"
        if code.startswith(STAR_PREFIXES):
            return "star"
        if code.startswith(BSE_PREFIXES) and len(code) == 6:
            return "bse"
        if code.startswith(MAIN_BOARD_SH) or code.startswith(MAIN_BOARD_SZ):
            return "main"
        return "unknown"

    def is_board_allowed(self, symbol: str) -> bool:
        """Check if a stock's board is in the allowed list."""
        return self.get_board(symbol) in self._allowed_boards

    # ------------------------------------------------------------------
    # Full constraint check
    # ------------------------------------------------------------------

    def check(
        self,
        symbol: str,
        name: str = "",
        *,
        current_price: float | None = None,
        open_price: float | None = None,
        prev_close: float | None = None,
        daily_turnover_wan: float | None = None,
        intraday_change_pct: float | None = None,
        is_st: bool = False,
        is_halted: bool = False,
        hold_days: int | None = None,
        position_pct: float | None = None,
    ) -> ConstraintCheckResult:
        """Run all constraint checks on a stock.

        Args:
            symbol: Stock code (e.g. "002155")
            name: Stock name for display
            current_price: Current/latest price
            open_price: Today's open price
            prev_close: Previous close price
            daily_turnover_wan: Average daily turnover in 万元
            intraday_change_pct: Today's price change %
            is_st: Whether the stock is ST
            is_halted: Whether the stock is halted
            hold_days: Days held (for existing positions)
            position_pct: Current position weight %

        Returns:
            ConstraintCheckResult with pass/fail and violations.
        """
        violations: list[ConstraintViolation] = []

        # 1. Exchange restriction
        board = self.get_board(symbol)
        if board not in self._allowed_boards:
            board_names = {
                "chinext": "创业板",
                "star": "科创板",
                "bse": "北交所",
                "unknown": "未知板块",
            }
            violations.append(
                ConstraintViolation(
                    rule="exchange_blocked",
                    severity="block",
                    message=f"{name or symbol} 属于{board_names.get(board, board)}，无交易权限",
                    details={"board": board, "symbol": symbol},
                )
            )

        # 2. ST / halted
        if is_st:
            violations.append(
                ConstraintViolation(
                    rule="st_stock",
                    severity="block",
                    message=f"{name or symbol} 为ST股票，风险过高",
                )
            )
        if is_halted:
            violations.append(
                ConstraintViolation(
                    rule="halted",
                    severity="block",
                    message=f"{name or symbol} 已停牌",
                )
            )

        # 3. Chase-buy penalty (intraday already up > threshold)
        if (
            intraday_change_pct is not None
            and intraday_change_pct > self._max_chase_pct
        ):
            violations.append(
                ConstraintViolation(
                    rule="chase_buy",
                    severity="warn",
                    message=(
                        f"{name or symbol} 今日已涨{intraday_change_pct:.1f}%，"
                        f"超过追涨阈值{self._max_chase_pct}%，追高风险大"
                    ),
                    details={
                        "change_pct": intraday_change_pct,
                        "threshold": self._max_chase_pct,
                    },
                )
            )

        # 4. Liquidity check
        if (
            daily_turnover_wan is not None
            and daily_turnover_wan < self._min_daily_turnover_wan
        ):
            violations.append(
                ConstraintViolation(
                    rule="low_liquidity",
                    severity="warn",
                    message=(
                        f"{name or symbol} 日均成交额{daily_turnover_wan:.0f}万，"
                        f"低于门槛{self._min_daily_turnover_wan:.0f}万"
                    ),
                    details={
                        "turnover_wan": daily_turnover_wan,
                        "threshold": self._min_daily_turnover_wan,
                    },
                )
            )

        # 5. Position concentration
        if position_pct is not None and position_pct > self._max_single_position_pct:
            violations.append(
                ConstraintViolation(
                    rule="concentration",
                    severity="warn",
                    message=(
                        f"{name or symbol} 仓位占比{position_pct:.1f}%，"
                        f"超过单票上限{self._max_single_position_pct:.1f}%"
                    ),
                    details={
                        "position_pct": position_pct,
                        "max_pct": self._max_single_position_pct,
                    },
                )
            )

        # 6. Holding period warning (for existing positions)
        if hold_days is not None and hold_days > self._max_hold_days:
            violations.append(
                ConstraintViolation(
                    rule="hold_too_long",
                    severity="warn",
                    message=(
                        f"{name or symbol} 已持有{hold_days}天，"
                        f"超过超短线目标{self._max_hold_days}天"
                    ),
                    details={
                        "hold_days": hold_days,
                        "max_days": self._max_hold_days,
                    },
                )
            )

        passed = not any(v.severity == "block" for v in violations)
        return ConstraintCheckResult(
            symbol=symbol, name=name, passed=passed, violations=violations
        )

    def filter_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        symbol_key: str = "symbol",
        name_key: str = "name",
    ) -> tuple[list[dict[str, Any]], list[ConstraintCheckResult]]:
        """Filter a list of candidate stocks, returning (passed, rejected).

        Each candidate dict should have at least symbol_key.
        Additional fields used if present: board, is_st, daily_turnover,
        intraday_change_pct.
        """
        passed: list[dict[str, Any]] = []
        rejected: list[ConstraintCheckResult] = []

        for c in candidates:
            result = self.check(
                symbol=c.get(symbol_key, ""),
                name=c.get(name_key, ""),
                intraday_change_pct=c.get("intraday_change_pct"),
                daily_turnover_wan=c.get("daily_turnover_wan"),
                is_st=c.get("is_st", False),
                is_halted=c.get("is_halted", False),
            )
            if result.passed:
                # Attach warnings to the candidate
                if result.warnings:
                    c["constraint_warnings"] = [w.message for w in result.warnings]
                passed.append(c)
            else:
                rejected.append(result)

        logger.info(
            "Constraint filter: %d passed, %d rejected out of %d candidates",
            len(passed),
            len(rejected),
            len(candidates),
        )
        return passed, rejected

    # ------------------------------------------------------------------
    # T+1 helpers
    # ------------------------------------------------------------------

    def can_sell_today(self, buy_date: str | date) -> bool:
        """Check if a position bought on buy_date can be sold today (T+1)."""
        if isinstance(buy_date, str):
            buy_date = datetime.strptime(buy_date, "%Y-%m-%d").date()
        return date.today() > buy_date

    def overnight_risk_note(self) -> str:
        """Return standard T+1 overnight risk warning."""
        return (
            "A股T+1规则: 买入当天不可卖出，必须承受至少1个隔夜风险。"
            "请确认隔夜持仓风险在可接受范围内。"
        )

    # ------------------------------------------------------------------
    # Cost calculation
    # ------------------------------------------------------------------

    def calc_trade_cost(
        self,
        price: float,
        shares: int,
        side: str = "buy",
    ) -> dict[str, float]:
        """Calculate trade costs for a given order.

        Args:
            price: Trade price per share
            shares: Number of shares
            side: "buy" or "sell"

        Returns:
            Dict with commission, stamp_duty (sell only), total_cost, net_amount.
        """
        amount = price * shares
        commission = max(amount * self._commission_rate, self._min_commission)
        stamp_duty = amount * self._stamp_duty_rate if side == "sell" else 0.0
        total_cost = commission + stamp_duty

        return {
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "stamp_duty": round(stamp_duty, 2),
            "total_cost": round(total_cost, 2),
            "net_amount": round(
                amount - total_cost if side == "sell" else amount + total_cost,
                2,
            ),
        }

    def round_to_lot(self, shares: int) -> int:
        """Round shares down to nearest lot size (100 for A-shares)."""
        return (shares // self._lot_size) * self._lot_size

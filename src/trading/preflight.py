"""Preflight risk checks — aggregated pre-order validation.

Combines all existing risk modules into a single gate that runs
before any order reaches the broker. Each check is independent;
the overall result fails if *any* check fails.

No new risk logic — this module is pure aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("trading.preflight")


@dataclass
class PreflightResult:
    """Outcome of all pre-order checks."""

    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        """One-line summary for logging."""
        failed = [c["name"] for c in self.checks if not c["passed"]]
        if not failed:
            return "All preflight checks passed"
        return f"Preflight BLOCKED: {', '.join(failed)}"


class PreflightRiskCheck:
    """Aggregated pre-execution validation.

    Combines: kill switch, trading hours, circuit breaker, available
    cash, trading constraints, T+1 sellability (when ``buy_date`` is
    supplied), order amount limit.

    Args:
        kill_switch: :class:`KillSwitch` instance.
        broker: :class:`BrokerInterface` for balance queries.
        max_order_amount: Single order CNY cap (from broker.yaml).
    """

    def __init__(
        self,
        kill_switch: Any,
        broker: Any,
        max_order_amount: float = 100_000,
    ) -> None:
        self._kill_switch = kill_switch
        self._broker = broker
        self._max_order_amount = max_order_amount

    def check(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        buy_date: str | date | None = None,
    ) -> PreflightResult:
        """Run all preflight checks.

        Args:
            symbol: Stock code (e.g. "600498").
            action: "buy", "sell", "add", or "reduce".
            shares: Number of shares.
            price: Proposed order price.
            buy_date: Date the position being sold/reduced was opened. When
                supplied for a "sell"/"reduce" action, T+1 settlement is
                enforced (a position bought today cannot be sold today). When
                omitted, the T+1 check passes (caller must supply it to bind).

        Returns:
            :class:`PreflightResult` with per-check details.
        """
        checks: list[dict[str, Any]] = []

        checks.append(self._check_kill_switch())
        checks.append(self._check_trading_hours())
        checks.append(self._check_circuit_breaker())

        if action in ("buy", "add"):
            checks.append(self._check_available_cash(shares, price))

        if action in ("sell", "reduce"):
            checks.append(self._check_t1_sellability(buy_date))

        checks.append(self._check_constraints(symbol))
        checks.append(self._check_lot_size(shares))
        checks.append(self._check_order_amount(shares, price))

        passed = all(c["passed"] for c in checks)
        result = PreflightResult(passed=passed, checks=checks)
        if not passed:
            logger.warning(
                "Preflight BLOCKED %s %s %d@%.2f: %s",
                action,
                symbol,
                shares,
                price,
                result.summary(),
            )
        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_kill_switch(self) -> dict[str, Any]:
        active = self._kill_switch.is_active()
        return {
            "name": "kill_switch",
            "passed": not active,
            "reason": "Kill switch is active" if active else "",
        }

    def _check_trading_hours(self) -> dict[str, Any]:
        try:
            from src.utils.market_hours import get_market_session

            session = get_market_session()
            is_trading = session.get("is_trading", False)
            return {
                "name": "trading_hours",
                "passed": is_trading,
                "reason": (
                    ""
                    if is_trading
                    else f"Market not in session: {session.get('label', 'unknown')}"
                ),
            }
        except Exception as exc:
            return {
                "name": "trading_hours",
                "passed": False,
                "reason": f"Cannot determine market hours: {exc}",
            }

    def _check_circuit_breaker(self) -> dict[str, Any]:
        try:
            from src.risk.circuit_breaker import CircuitBreaker

            breaker = CircuitBreaker()
            # is_halted() loads the persisted state from Redis and honors any
            # active cooldown — a fresh instance's in-memory state is always
            # NORMAL, so this load is what makes the gate actually enforce halts.
            if breaker.is_halted():
                return {
                    "name": "circuit_breaker",
                    "passed": False,
                    "reason": f"Circuit breaker in {breaker.state.value} state",
                }
            return {"name": "circuit_breaker", "passed": True, "reason": ""}
        except Exception as exc:
            # If circuit breaker unavailable, allow (don't block on import failure)
            logger.debug("Circuit breaker check skipped: %s", exc)
            return {"name": "circuit_breaker", "passed": True, "reason": ""}

    def _check_t1_sellability(self, buy_date: str | date | None) -> dict[str, Any]:
        """T+1 settlement: a position bought today cannot be sold today.

        Enforced only when ``buy_date`` is known; without it the check passes
        (the caller is responsible for supplying ``buy_date`` to make T+1 bind).
        """
        if buy_date is None:
            return {"name": "t1_sellability", "passed": True, "reason": ""}
        try:
            from src.trading.constraints import TradingConstraintsEngine

            engine = TradingConstraintsEngine()
            if not engine.can_sell_today(buy_date):
                return {
                    "name": "t1_sellability",
                    "passed": False,
                    "reason": (
                        f"T+1 settlement: position opened {buy_date} "
                        "cannot be sold today"
                    ),
                }
            return {"name": "t1_sellability", "passed": True, "reason": ""}
        except Exception as exc:
            logger.debug("T+1 sellability check skipped: %s", exc)
            return {"name": "t1_sellability", "passed": True, "reason": ""}

    def _check_available_cash(self, shares: int, price: float) -> dict[str, Any]:
        order_amount = shares * price
        try:
            balance = self._broker.get_balance()
            if balance.available_cash >= order_amount:
                return {"name": "available_cash", "passed": True, "reason": ""}
            return {
                "name": "available_cash",
                "passed": False,
                "reason": (
                    f"Insufficient cash: need {order_amount:.0f}, "
                    f"available {balance.available_cash:.0f}"
                ),
            }
        except Exception as exc:
            return {
                "name": "available_cash",
                "passed": False,
                "reason": f"Cannot query balance: {exc}",
            }

    def _check_constraints(self, symbol: str) -> dict[str, Any]:
        try:
            from src.trading.constraints import TradingConstraintsEngine

            engine = TradingConstraintsEngine()
            if not engine.is_board_allowed(symbol):
                board = engine.get_board(symbol)
                return {
                    "name": "board_restriction",
                    "passed": False,
                    "reason": f"Board '{board}' not allowed (main board only)",
                }
            return {"name": "board_restriction", "passed": True, "reason": ""}
        except Exception as exc:
            logger.debug("Constraint check skipped: %s", exc)
            return {"name": "board_restriction", "passed": True, "reason": ""}

    def _check_lot_size(self, shares: int) -> dict[str, Any]:
        if shares > 0 and shares % 100 == 0:
            return {"name": "lot_size", "passed": True, "reason": ""}
        return {
            "name": "lot_size",
            "passed": False,
            "reason": f"Shares {shares} not a positive multiple of 100",
        }

    def _check_order_amount(self, shares: int, price: float) -> dict[str, Any]:
        amount = shares * price
        if amount <= self._max_order_amount:
            return {"name": "order_amount", "passed": True, "reason": ""}
        return {
            "name": "order_amount",
            "passed": False,
            "reason": (
                f"Order amount {amount:.0f} exceeds limit {self._max_order_amount:.0f}"
            ),
        }

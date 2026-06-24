"""Stop-loss enforcer — monitors positions against thesis stop prices.

Runs during the fast-scan cycle (every 5 minutes). When a position
breaches its stop-loss, generates a sell proposal routed through
the ExecutionBridge.

In ``auto`` mode the sell order executes immediately.
In ``confirm`` mode a high-priority notification is pushed.
"""

from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

logger = get_logger("trading.stop_loss_enforcer")


class StopLossEnforcer:
    """Checks positions against thesis stop-loss levels.

    Args:
        execution_bridge: :class:`ExecutionBridge` for routing sell proposals.
        portfolio_service: Service with ``get_portfolio()`` method.
        thesis_store: :class:`ThesisStore` for stop-loss percentages.
    """

    def __init__(
        self,
        execution_bridge: Any,
        portfolio_service: Any,
        thesis_store: Any | None = None,
    ) -> None:
        self._bridge = execution_bridge
        self._portfolio = portfolio_service
        self._thesis_store = thesis_store

    def check_and_enforce(self) -> list[dict[str, Any]]:
        """Check all positions against stop-loss levels.

        Returns a list of result dicts for each enforced stop-loss.
        """
        if not self._bridge:
            return []

        positions = self._get_positions()
        if not positions:
            return []

        results: list[dict[str, Any]] = []
        for pos in positions:
            symbol = pos.get("symbol", "")
            current_price = pos.get("current_price", 0.0)
            cost_price = pos.get("cost_price", pos.get("costPrice", 0.0))
            shares = int(pos.get("shares", 0))

            if not symbol or current_price <= 0 or cost_price <= 0 or shares <= 0:
                continue

            stop_price = self._get_stop_price(symbol, cost_price)
            if stop_price is None:
                continue

            if current_price <= stop_price:
                result = self._enforce_stop_loss(
                    symbol=symbol,
                    stock_name=pos.get("name", pos.get("stock_name", "")),
                    shares=shares,
                    current_price=current_price,
                    stop_price=stop_price,
                    cost_price=cost_price,
                )
                results.append(result)

        if results:
            logger.warning(
                "Stop-loss enforced for %d positions: %s",
                len(results),
                ", ".join(r["symbol"] for r in results),
            )
        return results

    def _get_positions(self) -> list[dict[str, Any]]:
        """Get current portfolio positions."""
        try:
            data = self._portfolio.get_portfolio()
            return data.get("positions", []) if isinstance(data, dict) else []
        except Exception as exc:
            logger.warning("Cannot load portfolio for stop-loss check: %s", exc)
            return []

    def _get_stop_price(self, symbol: str, cost_price: float) -> float | None:
        """Compute stop-loss price from thesis or default."""
        stop_loss_pct = 0.05  # default 5%

        if self._thesis_store:
            try:
                thesis = self._thesis_store.get_by_symbol(symbol)
                if thesis and thesis.stop_loss_pct:
                    stop_loss_pct = thesis.stop_loss_pct
            except Exception:
                pass

        return cost_price * (1.0 - stop_loss_pct)

    def _enforce_stop_loss(
        self,
        symbol: str,
        stock_name: str,
        shares: int,
        current_price: float,
        stop_price: float,
        cost_price: float,
    ) -> dict[str, Any]:
        """Generate and submit a sell proposal through the execution bridge."""
        # Round shares to lot size
        sell_shares = (shares // 100) * 100
        if sell_shares <= 0:
            return {
                "symbol": symbol,
                "status": "skipped",
                "reason": "Shares below minimum lot",
            }

        loss_pct = (current_price - cost_price) / cost_price * 100
        reasoning = (
            f"止损触发: 当前价{current_price:.2f} <= 止损价{stop_price:.2f} "
            f"(成本{cost_price:.2f}, 亏损{loss_pct:.1f}%)"
        )

        logger.warning(
            "STOP-LOSS TRIGGERED: %s %s — sell %d @ %.2f (%s)",
            symbol,
            stock_name,
            sell_shares,
            current_price,
            reasoning,
        )

        result = self._bridge.process_proposal(
            symbol=symbol,
            action="sell",
            shares=sell_shares,
            price=current_price,
            stock_name=stock_name,
            reasoning=reasoning,
            confidence=0.99,
        )
        return {
            "symbol": symbol,
            "stock_name": stock_name,
            "shares": sell_shares,
            "current_price": current_price,
            "stop_price": stop_price,
            "loss_pct": loss_pct,
            "status": result.status,
            "gate_request_id": result.gate_request_id,
        }

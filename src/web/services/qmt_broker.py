"""QMT broker — real trading via xttrader SDK.

Implements BrokerInterface using XtQuant's xttrader module for
live order submission, position queries, and balance checks.

Gracefully unavailable when XtQuant is not installed.
"""

from __future__ import annotations

import os
from typing import Any

from src.utils.logger import get_logger
from src.web.services.broker_interface import (
    Balance,
    BrokerInterface,
    OrderStatus,
    Position,
)

try:
    from xtquant import xttrader, xtconstant

    _HAS_XTTRADER = True
except ImportError:
    xttrader = None  # type: ignore[assignment]
    xtconstant = None  # type: ignore[assignment]
    _HAS_XTTRADER = False

logger = get_logger("web.qmt_broker")


class QmtBroker(BrokerInterface):
    """Live broker using QMT's xttrader SDK.

    Reads account_id and safety limits from config/broker.yaml.
    All trades require ConfirmationGate verification.

    Args:
        config: Broker configuration dict (from config/broker.yaml).
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        if not _HAS_XTTRADER:
            raise RuntimeError(
                "QmtBroker requires xtquant package. "
                "Install it in your QMT environment."
            )

        cfg = config or {}
        qmt_cfg = cfg.get("qmt", {})
        # Env vars take precedence over YAML (sensitive credentials)
        self._account_id: str = os.environ.get("QMT_ACCOUNT_ID") or qmt_cfg.get(
            "account_id", ""
        )
        self._mini_qmt_path: str = os.environ.get("QMT_MINI_QMT_PATH") or qmt_cfg.get(
            "mini_qmt_path", ""
        )
        self._max_order_amount: float = qmt_cfg.get("max_order_amount", 100000)
        self._allowed_actions: list[str] = qmt_cfg.get(
            "allowed_actions", ["buy", "sell"]
        )
        self._trader = None
        self._connected = False

        if not self._account_id:
            raise ValueError(
                "QmtBroker requires account ID. "
                "Set QMT_ACCOUNT_ID env var or qmt.account_id in config/broker.yaml"
            )

    def _ensure_connected(self) -> None:
        """Lazily connect to xttrader."""
        if self._connected and self._trader is not None:
            return

        self._trader = xttrader.XtQuantTrader(self._mini_qmt_path, self._account_id)
        self._trader.start()
        connect_result = self._trader.connect()
        if connect_result != 0:
            raise ConnectionError(
                f"QMT xttrader connect failed (code={connect_result})"
            )
        self._connected = True
        logger.info("QMT xttrader connected for account %s", self._account_id)

    def get_positions(self) -> list[Position]:
        """Get current positions from QMT account."""
        self._ensure_connected()
        try:
            raw_positions = self._trader.query_stock_positions(self._account_id)
            positions: list[Position] = []
            for p in raw_positions:
                symbol = (
                    p.stock_code.split(".")[0] if "." in p.stock_code else p.stock_code
                )
                market_value = p.market_value if hasattr(p, "market_value") else 0.0
                cost_price = p.open_price if hasattr(p, "open_price") else 0.0
                current_price = p.market_price if hasattr(p, "market_price") else 0.0
                shares = p.volume if hasattr(p, "volume") else 0
                pnl = market_value - (cost_price * shares) if cost_price > 0 else 0.0
                pnl_pct = (
                    (pnl / (cost_price * shares) * 100)
                    if cost_price * shares > 0
                    else 0.0
                )

                positions.append(
                    Position(
                        symbol=symbol,
                        stock_name=getattr(p, "stock_name", ""),
                        shares=shares,
                        cost_price=cost_price,
                        current_price=current_price,
                        market_value=market_value,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                    )
                )
            return positions
        except Exception as exc:
            logger.error("QMT get_positions failed: %s", exc)
            return []

    def get_balance(self) -> Balance:
        """Get account balance from QMT."""
        self._ensure_connected()
        try:
            account = self._trader.query_stock_asset(self._account_id)
            return Balance(
                total_assets=getattr(account, "total_asset", 0.0),
                available_cash=getattr(account, "cash", 0.0),
                market_value=getattr(account, "market_value", 0.0),
                utilization_rate=(
                    getattr(account, "market_value", 0.0)
                    / getattr(account, "total_asset", 1.0)
                    if getattr(account, "total_asset", 0.0) > 0
                    else 0.0
                ),
            )
        except Exception as exc:
            logger.error("QMT get_balance failed: %s", exc)
            return Balance()

    def get_order_status(self, order_id: str) -> OrderStatus:
        """Get status of a previously submitted QMT order."""
        self._ensure_connected()
        try:
            orders = self._trader.query_stock_orders(self._account_id)
            for o in orders:
                if str(getattr(o, "order_id", "")) == order_id:
                    status_map = {
                        0: "pending",
                        1: "pending",
                        2: "partial",
                        3: "filled",
                        4: "cancelled",
                        5: "rejected",
                    }
                    return OrderStatus(
                        order_id=order_id,
                        symbol=o.stock_code.split(".")[0],
                        action="buy" if getattr(o, "order_type", 0) == 23 else "sell",
                        shares=getattr(o, "order_volume", 0),
                        price=getattr(o, "price", 0.0),
                        status=status_map.get(
                            getattr(o, "order_status", -1), "unknown"
                        ),
                        message=getattr(o, "status_msg", ""),
                    )
            return OrderStatus(
                order_id=order_id,
                symbol="",
                action="",
                shares=0,
                price=0.0,
                status="not_found",
            )
        except Exception as exc:
            logger.error("QMT get_order_status failed: %s", exc)
            return OrderStatus(
                order_id=order_id,
                symbol="",
                action="",
                shares=0,
                price=0.0,
                status="error",
                message=str(exc),
            )

    def submit_order(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        gate_request_id: str = "",
    ) -> OrderStatus:
        """Submit a live order via QMT xttrader.

        Safety checks:
        - Action must be in allowed_actions
        - Order amount must not exceed max_order_amount
        - Shares must be positive and in lots of 100
        """
        # Safety validation
        if action not in self._allowed_actions:
            return OrderStatus(
                order_id="",
                symbol=symbol,
                action=action,
                shares=shares,
                price=price,
                status="rejected",
                message=f"Action '{action}' not allowed. Allowed: {self._allowed_actions}",
            )

        order_amount = shares * price
        if order_amount > self._max_order_amount:
            return OrderStatus(
                order_id="",
                symbol=symbol,
                action=action,
                shares=shares,
                price=price,
                status="rejected",
                message=(
                    f"Order amount {order_amount:.0f} exceeds limit "
                    f"{self._max_order_amount:.0f}"
                ),
            )

        if shares <= 0 or shares % 100 != 0:
            return OrderStatus(
                order_id="",
                symbol=symbol,
                action=action,
                shares=shares,
                price=price,
                status="rejected",
                message="Shares must be positive and in lots of 100",
            )

        self._ensure_connected()

        try:
            from src.data.qmt_adapter import QmtDataAdapter

            xt_code = QmtDataAdapter.to_xt_code(symbol)

            if action == "buy":
                order_type = xtconstant.STOCK_BUY
            else:
                order_type = xtconstant.STOCK_SELL

            order_id = self._trader.order_stock(
                self._account_id,
                xt_code,
                order_type,
                shares,
                xtconstant.FIX_PRICE,
                price,
            )

            logger.info(
                "QMT order submitted: %s %s %d @ %.2f (id=%s, gate=%s)",
                action,
                symbol,
                shares,
                price,
                order_id,
                gate_request_id,
            )

            return OrderStatus(
                order_id=str(order_id),
                symbol=symbol,
                action=action,
                shares=shares,
                price=price,
                status="pending",
                message="QMT 实盘委托已提交",
            )
        except Exception as exc:
            logger.error("QMT submit_order failed: %s", exc)
            return OrderStatus(
                order_id="",
                symbol=symbol,
                action=action,
                shares=shares,
                price=price,
                status="rejected",
                message=f"QMT 下单失败: {exc}",
            )

    @property
    def mode(self) -> str:
        return "qmt"

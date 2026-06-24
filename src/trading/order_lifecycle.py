"""Order lifecycle manager — polls broker for fill/rejection status.

After an order is submitted (gate stage EXECUTED), this manager
periodically checks the broker for status updates and reconciles:

- **Filled**: gate → VERIFIED, record trade + fill in DB.
- **Rejected/Cancelled**: gate → REJECTED, notify user.
- **Partial**: update fill_shares incrementally.
"""

from __future__ import annotations

import json
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("trading.order_lifecycle")


class OrderLifecycleManager:
    """Polls pending broker orders and reconciles with internal state.

    Args:
        broker: :class:`BrokerInterface` for order status queries.
        gate: :class:`ConfirmationGate` for state transitions.
        trade_service: :class:`TradeService` for recording fills.
        action_queue: :class:`ActionQueueService` for updating actions.
    """

    def __init__(
        self,
        broker: Any,
        gate: Any,
        trade_service: Any,
        action_queue: Any | None = None,
    ) -> None:
        self._broker = broker
        self._gate = gate
        self._trade_service = trade_service
        self._action_queue = action_queue

    def poll_pending_orders(self) -> list[dict[str, Any]]:
        """Check all EXECUTED gate requests for broker status updates.

        Returns a list of result dicts, one per polled order.
        """
        executed_requests = self._gate.get_pending_requests(stage="EXECUTED")
        if not executed_requests:
            return []

        results: list[dict[str, Any]] = []
        for req in executed_requests:
            meta = json.loads(req.metadata) if req.metadata else {}
            broker_order_id = meta.get("broker_order_id")
            if not broker_order_id:
                continue

            # Skip dry-run orders
            if broker_order_id == "dry-run":
                continue

            result = self._poll_single_order(req, broker_order_id, meta)
            results.append(result)

        if results:
            logger.info(
                "Polled %d pending orders: %s",
                len(results),
                ", ".join(f"{r['request_id']}={r['new_status']}" for r in results),
            )
        return results

    def _poll_single_order(
        self,
        gate_req: Any,
        broker_order_id: str,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        """Poll a single order and handle the result."""
        try:
            status = self._broker.get_order_status(broker_order_id)
        except Exception as exc:
            logger.warning(
                "Failed to poll order %s for gate %s: %s",
                broker_order_id,
                gate_req.request_id,
                exc,
            )
            return {
                "request_id": gate_req.request_id,
                "broker_order_id": broker_order_id,
                "new_status": "poll_error",
                "error": str(exc),
            }

        if status.status == "filled":
            self._handle_fill(gate_req, status, meta)
            return {
                "request_id": gate_req.request_id,
                "broker_order_id": broker_order_id,
                "new_status": "filled",
                "fill_price": status.price,
                "fill_shares": status.shares,
            }

        if status.status in ("rejected", "cancelled"):
            self._handle_rejection(gate_req, status)
            return {
                "request_id": gate_req.request_id,
                "broker_order_id": broker_order_id,
                "new_status": status.status,
                "message": status.message,
            }

        # Still pending / partial — no action needed yet
        return {
            "request_id": gate_req.request_id,
            "broker_order_id": broker_order_id,
            "new_status": status.status,
        }

    def _handle_fill(
        self,
        gate_req: Any,
        order_status: Any,
        meta: dict[str, Any],
    ) -> None:
        """Process a filled order: verify gate, record trade, update action queue."""
        request_id = gate_req.request_id
        logger.info(
            "Order FILLED: gate=%s symbol=%s %d @ %.2f",
            request_id,
            gate_req.symbol,
            order_status.shares,
            order_status.price,
        )

        # 1. Transition gate → VERIFIED
        self._gate.mark_verified(
            request_id,
            actual_price=order_status.price,
            notes=f"Filled {order_status.shares} shares @ {order_status.price}",
        )

        # 2. Record trade in trade_service (triggers capital settlement + portfolio sync)
        try:
            self._trade_service.execute_trade(
                symbol=gate_req.symbol,
                stock_name=meta.get("stock_name", ""),
                action=gate_req.trade_type,
                shares=order_status.shares,
                price=order_status.price,
                reasoning=meta.get("reasoning", ""),
                gate_request_id=request_id,
            )
        except Exception as exc:
            logger.error("Failed to record trade for gate=%s: %s", request_id, exc)

        # 3. Update action queue if linked
        action_id = meta.get("action_id")
        if action_id and self._action_queue:
            try:
                self._action_queue.record_fill(
                    action_id, order_status.price, order_status.shares
                )
            except Exception as exc:
                logger.warning(
                    "Failed to record fill in action_queue for %s: %s",
                    action_id,
                    exc,
                )

    def _handle_rejection(self, gate_req: Any, order_status: Any) -> None:
        """Process a rejected/cancelled order."""
        logger.warning(
            "Order %s: gate=%s symbol=%s — %s",
            order_status.status.upper(),
            gate_req.request_id,
            gate_req.symbol,
            order_status.message,
        )
        self._gate.reject(
            gate_req.request_id,
            actor="broker",
            reason=f"{order_status.status}: {order_status.message}",
        )

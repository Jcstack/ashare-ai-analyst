"""Broker health monitor — periodic QMT connectivity check.

Calls ``broker.get_balance()`` as a heartbeat. After *max_failures*
consecutive failures, auto-activates the kill switch and pushes
a Discord alert.
"""

from __future__ import annotations

import time
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("trading.broker_health")


class BrokerHealthMonitor:
    """Periodic health checker for the broker connection.

    Args:
        broker: Any :class:`BrokerInterface` implementation.
        kill_switch: :class:`KillSwitch` to engage on repeated failures.
        redis_client: Redis client for persisting health state.
        max_failures: Consecutive failures before auto-engaging kill switch.
    """

    REDIS_KEY = "trading:broker_health"

    def __init__(
        self,
        broker: Any,
        kill_switch: Any,
        redis_client: Any | None = None,
        max_failures: int = 3,
    ) -> None:
        self._broker = broker
        self._kill_switch = kill_switch
        self._redis = redis_client
        self._max_failures = max_failures
        self._consecutive_failures = 0

    def check(self) -> dict[str, Any]:
        """Run a health check by calling ``broker.get_balance()``.

        Returns a status dict with ``healthy``, ``balance``, ``error``,
        ``consecutive_failures``, and ``checked_at`` fields.
        """
        checked_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            balance = self._broker.get_balance()
            self._consecutive_failures = 0
            status = {
                "healthy": True,
                "total_assets": balance.total_assets,
                "available_cash": balance.available_cash,
                "consecutive_failures": 0,
                "checked_at": checked_at,
            }
            logger.debug(
                "Broker health OK — assets=%.2f cash=%.2f",
                balance.total_assets,
                balance.available_cash,
            )
        except Exception as exc:
            self._consecutive_failures += 1
            status = {
                "healthy": False,
                "error": str(exc),
                "consecutive_failures": self._consecutive_failures,
                "checked_at": checked_at,
            }
            logger.warning(
                "Broker health FAIL (%d/%d): %s",
                self._consecutive_failures,
                self._max_failures,
                exc,
            )
            if self._consecutive_failures >= self._max_failures:
                self._trigger_kill_switch()

        self._persist_status(status)
        return status

    def get_last_status(self) -> dict[str, Any] | None:
        """Read the most recent health check result from Redis."""
        if not self._redis:
            return None
        try:
            import json

            raw = self._redis.get(self.REDIS_KEY)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def _trigger_kill_switch(self) -> None:
        """Engage the kill switch after repeated broker failures."""
        reason = (
            f"Broker unreachable for {self._consecutive_failures} "
            f"consecutive health checks"
        )
        logger.error("AUTO KILL SWITCH: %s", reason)
        self._kill_switch.activate(reason=reason, activated_by="broker_health")

    def _persist_status(self, status: dict[str, Any]) -> None:
        """Write health status to Redis for dashboard visibility."""
        if not self._redis:
            return
        try:
            import json

            self._redis.set(self.REDIS_KEY, json.dumps(status), ex=600)
        except Exception:
            pass

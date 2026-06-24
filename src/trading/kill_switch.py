"""Kill switch — Redis-backed emergency trading halt.

When activated, all order submissions are blocked at every entry point
(ExecutionBridge, tool registry, Celery tasks). Stays active until
explicitly deactivated.

Fail-open when Redis is unavailable (simulation-safe).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("trading.kill_switch")

_REDIS_KEY = "trading:kill_switch"
_REASON_KEY = "trading:kill_switch:reason"
_ACTIVATED_AT_KEY = "trading:kill_switch:activated_at"
_ACTIVATED_BY_KEY = "trading:kill_switch:activated_by"


@dataclass
class KillSwitchStatus:
    """Current state of the kill switch."""

    active: bool
    reason: str = ""
    activated_at: str = ""
    activated_by: str = ""


class KillSwitch:
    """Redis-backed emergency halt for all trading activity.

    Args:
        redis_client: Redis client (from ``get_redis()``). If *None*,
            the switch is always inactive (fail-open for simulation).
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    def is_active(self) -> bool:
        """Return *True* if trading is halted."""
        if self._redis is None:
            return False
        try:
            return self._redis.get(_REDIS_KEY) == "1"
        except Exception:
            logger.warning("Redis unavailable for kill switch check — fail-open")
            return False

    def activate(self, reason: str = "", activated_by: str = "system") -> None:
        """Engage the kill switch. All orders will be blocked."""
        if self._redis is None:
            logger.warning("Cannot activate kill switch — no Redis connection")
            return
        try:
            pipe = self._redis.pipeline()
            pipe.set(_REDIS_KEY, "1")
            pipe.set(_REASON_KEY, reason)
            pipe.set(_ACTIVATED_AT_KEY, time.strftime("%Y-%m-%dT%H:%M:%S"))
            pipe.set(_ACTIVATED_BY_KEY, activated_by)
            pipe.execute()
            logger.warning(
                "KILL SWITCH ACTIVATED by=%s reason=%s", activated_by, reason
            )
        except Exception:
            logger.error("Failed to activate kill switch", exc_info=True)

    def deactivate(self) -> None:
        """Disengage the kill switch. Trading resumes."""
        if self._redis is None:
            return
        try:
            self._redis.delete(
                _REDIS_KEY, _REASON_KEY, _ACTIVATED_AT_KEY, _ACTIVATED_BY_KEY
            )
            logger.info("Kill switch deactivated")
        except Exception:
            logger.error("Failed to deactivate kill switch", exc_info=True)

    def status(self) -> KillSwitchStatus:
        """Return the current kill switch state."""
        if self._redis is None:
            return KillSwitchStatus(active=False)
        try:
            active = self._redis.get(_REDIS_KEY) == "1"
            return KillSwitchStatus(
                active=active,
                reason=self._redis.get(_REASON_KEY) or "",
                activated_at=self._redis.get(_ACTIVATED_AT_KEY) or "",
                activated_by=self._redis.get(_ACTIVATED_BY_KEY) or "",
            )
        except Exception:
            return KillSwitchStatus(active=False)

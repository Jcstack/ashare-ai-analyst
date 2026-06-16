"""Simple circuit breaker for external API calls.

Implements the circuit breaker pattern per data reliability audit
recommendation #5. Prevents cascading failures when an external
service is consistently failing.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Service is down, requests fail fast without calling
- HALF_OPEN: After cooldown, allow one probe request
"""

from __future__ import annotations

import time
from typing import Any, Callable

from src.utils.logger import get_logger

logger = get_logger("data.circuit_breaker")


class CircuitBreakerOpen(Exception):
    """Raised when a request is rejected because the circuit is open."""

    def __init__(self, name: str, remaining_seconds: float) -> None:
        self.name = name
        self.remaining_seconds = remaining_seconds
        super().__init__(
            f"Circuit breaker '{name}' is OPEN "
            f"(retry in {remaining_seconds:.0f}s)"
        )


class CircuitBreaker:
    """Lightweight circuit breaker for external API calls.

    Args:
        name: Identifier for logging.
        failure_threshold: Consecutive failures before opening circuit.
        recovery_timeout: Seconds to wait before allowing a probe request.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._state = "closed"

    @property
    def state(self) -> str:
        if self._state == "open":
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                return "half_open"
        return self._state

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute function through the circuit breaker.

        Raises:
            CircuitBreakerOpen: If the circuit is open.
        """
        current_state = self.state

        if current_state == "open":
            remaining = self.recovery_timeout - (
                time.monotonic() - self._last_failure_time
            )
            raise CircuitBreakerOpen(self.name, remaining)

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise exc

    def _on_success(self) -> None:
        if self._state != "closed":
            logger.info(
                "Circuit breaker '%s': %s → CLOSED (service recovered)",
                self.name,
                self._state,
            )
        self._failure_count = 0
        self._state = "closed"

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._failure_count >= self.failure_threshold:
            if self._state != "open":
                logger.warning(
                    "Circuit breaker '%s': OPEN after %d consecutive failures "
                    "(cooldown %.0fs)",
                    self.name,
                    self._failure_count,
                    self.recovery_timeout,
                )
            self._state = "open"

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        self._failure_count = 0
        self._state = "closed"

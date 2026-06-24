"""Price spike detector using Welford temporal baselines.

Monitors real-time quotes for >3-sigma price moves relative to
same-time-of-day baselines. Publishes events to the event bus.

Per PRD v50.0 §9.5: real-time anomaly detection layer.
"""

from __future__ import annotations

import time
from typing import Any

from src.data.welford_baseline import WelfordBaseline
from src.utils.logger import get_logger

logger = get_logger("data.price_spike_detector")

# Default z-score threshold for spike detection
DEFAULT_Z_THRESHOLD = 3.0

# Cooldown period: do not re-alert the same symbol within this many seconds
DEFAULT_COOLDOWN_SECONDS = 15 * 60  # 15 minutes


class PriceSpikeDetector:
    """Detect price spikes using Welford z-score baselines.

    Monitors price changes (returns) and fires events when the absolute
    return exceeds ``z_threshold`` standard deviations from the temporal
    baseline for that day-of-week and time-slot.

    Args:
        event_bus: EventBus instance for publishing detections.
        redis_client: Redis client for Welford persistence and cooldown tracking.
        z_threshold: Minimum absolute z-score to trigger a spike event.
        cooldown_seconds: Seconds to suppress repeated alerts for the same symbol.
        stream: Event bus stream to publish to.
    """

    def __init__(
        self,
        event_bus: Any | None = None,
        redis_client: Any | None = None,
        z_threshold: float = DEFAULT_Z_THRESHOLD,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
        stream: str = "events:market",
    ) -> None:
        self._bus = event_bus
        self._redis = redis_client
        self._z_threshold = z_threshold
        self._cooldown_seconds = cooldown_seconds
        self._stream = stream

        # Welford baselines keyed by symbol
        self._baselines: dict[str, WelfordBaseline] = {}

        # In-memory cooldown tracker: symbol -> last alert timestamp
        self._cooldowns: dict[str, float] = {}

        # Last known price per symbol (for computing returns)
        self._last_prices: dict[str, float] = {}

    def _get_baseline(self, symbol: str) -> WelfordBaseline:
        """Get or create the Welford baseline for a symbol."""
        if symbol not in self._baselines:
            self._baselines[symbol] = WelfordBaseline(
                symbol=symbol,
                metric="price_return",
                redis_client=self._redis,
                redis_prefix="welford",
            )
        return self._baselines[symbol]

    def _is_in_cooldown(self, symbol: str) -> bool:
        """Check whether a symbol is still in cooldown."""
        last_alert = self._cooldowns.get(symbol)
        if last_alert is None:
            return False
        return (time.time() - last_alert) < self._cooldown_seconds

    def _set_cooldown(self, symbol: str) -> None:
        """Mark a symbol as alerted (start cooldown)."""
        self._cooldowns[symbol] = time.time()

    def check(
        self,
        symbol: str,
        price: float,
        prev_close: float,
        day_of_week: int,
        hour: int,
        minute: int,
    ) -> dict[str, Any] | None:
        """Check a real-time quote for price spike.

        Updates the Welford baseline and checks for anomalies.

        Args:
            symbol: Stock symbol (e.g. "000001").
            price: Current price.
            prev_close: Previous close price (for return calculation).
            day_of_week: 0=Monday .. 4=Friday.
            hour: Current hour (24h).
            minute: Current minute.

        Returns:
            Event dict if spike detected, None otherwise.
        """
        if prev_close <= 0 or price <= 0:
            return None

        # Compute return as percentage change
        price_return = (price - prev_close) / prev_close * 100.0

        baseline = self._get_baseline(symbol)

        # Compute z-score before updating (to compare against historical baseline)
        z = baseline.z_score(day_of_week, hour, minute, price_return)

        # Always update baseline with new observation
        baseline.update(day_of_week, hour, minute, price_return)

        if z is None:
            return None

        if abs(z) < self._z_threshold:
            return None

        if self._is_in_cooldown(symbol):
            logger.debug("Spike for %s suppressed (cooldown), z=%.2f", symbol, z)
            return None

        self._set_cooldown(symbol)

        event_data = {
            "symbol": symbol,
            "price": price,
            "prev_close": prev_close,
            "return_pct": round(price_return, 4),
            "z_score": round(z, 2),
            "direction": "up" if z > 0 else "down",
            "day_of_week": day_of_week,
            "hour": hour,
            "minute": minute,
        }

        logger.info(
            "Price spike detected: %s z=%.2f return=%.2f%%",
            symbol,
            z,
            price_return,
        )

        # Publish to event bus if available (legacy path)
        if self._bus is not None:
            try:
                import asyncio

                publish_data = {"event_type": "price_spike", **event_data}
                coro = self._bus.publish(self._stream, publish_data)
                if asyncio.iscoroutine(coro):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(coro)
                    except RuntimeError:
                        asyncio.run(coro)
            except Exception as exc:
                logger.warning("Event bus publish failed (non-critical): %s", exc)

        # Publish to Redis Streams event bus (v50.0)
        try:
            from src.event_bus.producers import publish_price_spike

            publish_price_spike(
                symbol=symbol,
                name=symbol,
                z_score=round(z, 2),
                price=price,
                change_pct=round(price_return, 4),
            )
        except Exception:
            pass  # Never break the caller

        return event_data

    def check_batch(
        self,
        quotes: list[dict[str, Any]],
        day_of_week: int,
        hour: int,
        minute: int,
    ) -> list[dict[str, Any]]:
        """Check a batch of quotes for price spikes.

        Args:
            quotes: List of dicts with keys: symbol, price, prev_close.
            day_of_week: 0=Monday .. 4=Friday.
            hour: Current hour.
            minute: Current minute.

        Returns:
            List of spike event dicts (may be empty).
        """
        spikes = []
        for q in quotes:
            symbol = q.get("symbol", "")
            price = q.get("price", 0)
            prev_close = q.get("prev_close", 0)
            if not symbol or not price or not prev_close:
                continue
            result = self.check(symbol, price, prev_close, day_of_week, hour, minute)
            if result is not None:
                spikes.append(result)
        return spikes

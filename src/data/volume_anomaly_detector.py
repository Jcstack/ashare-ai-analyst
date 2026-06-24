"""Volume anomaly detector using Welford temporal baselines.

Monitors minute-bar volumes for >2-sigma anomalies relative to
same-time-of-day baselines. Distinguishes between abnormally high
and abnormally low volume.

Per PRD v50.0 §9.5: real-time anomaly detection layer.
"""

from __future__ import annotations

import time
from typing import Any

from src.data.welford_baseline import WelfordBaseline
from src.utils.logger import get_logger

logger = get_logger("data.volume_anomaly_detector")

# Default z-score threshold for volume anomaly
DEFAULT_Z_THRESHOLD = 2.0

# Cooldown period: do not re-alert the same symbol within this many seconds
DEFAULT_COOLDOWN_SECONDS = 15 * 60  # 15 minutes


class VolumeAnomalyDetector:
    """Detect volume anomalies using Welford z-score baselines.

    Monitors minute-bar volume against historical same-time-of-day baselines.
    Fires events when volume deviates by more than ``z_threshold`` standard
    deviations. Distinguishes between abnormally high and low volume.

    Args:
        event_bus: EventBus instance for publishing detections.
        redis_client: Redis client for Welford persistence.
        z_threshold: Minimum absolute z-score to trigger an anomaly event.
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

    def _get_baseline(self, symbol: str) -> WelfordBaseline:
        """Get or create the Welford baseline for a symbol."""
        if symbol not in self._baselines:
            self._baselines[symbol] = WelfordBaseline(
                symbol=symbol,
                metric="volume",
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
        volume: float,
        day_of_week: int,
        hour: int,
        minute: int,
    ) -> dict[str, Any] | None:
        """Check a minute-bar volume for anomaly.

        Updates the Welford baseline and checks for deviations.

        Args:
            symbol: Stock symbol (e.g. "000001").
            volume: Volume for the minute bar.
            day_of_week: 0=Monday .. 4=Friday.
            hour: Current hour (24h).
            minute: Current minute.

        Returns:
            Event dict if anomaly detected, None otherwise.
        """
        if volume < 0:
            return None

        baseline = self._get_baseline(symbol)

        # Compute z-score before updating (compare against historical)
        z = baseline.z_score(day_of_week, hour, minute, volume)

        # Always update baseline
        baseline.update(day_of_week, hour, minute, volume)

        if z is None:
            return None

        if abs(z) < self._z_threshold:
            return None

        if self._is_in_cooldown(symbol):
            logger.debug(
                "Volume anomaly for %s suppressed (cooldown), z=%.2f",
                symbol,
                z,
            )
            return None

        self._set_cooldown(symbol)

        # Classify the anomaly
        if z > 0:
            anomaly_type = "high_volume"
        else:
            anomaly_type = "low_volume"

        event_data = {
            "symbol": symbol,
            "volume": volume,
            "z_score": round(z, 2),
            "anomaly_type": anomaly_type,
            "day_of_week": day_of_week,
            "hour": hour,
            "minute": minute,
        }

        logger.info(
            "Volume anomaly detected: %s type=%s z=%.2f vol=%.0f",
            symbol,
            anomaly_type,
            z,
            volume,
        )

        # Publish to event bus if available (legacy path)
        if self._bus is not None:
            self._bus.publish(self._stream, "volume_anomaly", event_data)

        # Publish to Redis Streams event bus (v50.0)
        try:
            from src.event_bus.producers import publish_volume_anomaly

            publish_volume_anomaly(
                symbol=symbol,
                name=symbol,
                z_score=round(z, 2),
                volume=int(volume),
            )
        except Exception:
            pass  # Never break the caller

        return event_data

    def check_batch(
        self,
        bars: list[dict[str, Any]],
        day_of_week: int,
        hour: int,
        minute: int,
    ) -> list[dict[str, Any]]:
        """Check a batch of minute bars for volume anomalies.

        Args:
            bars: List of dicts with keys: symbol, volume.
            day_of_week: 0=Monday .. 4=Friday.
            hour: Current hour.
            minute: Current minute.

        Returns:
            List of anomaly event dicts (may be empty).
        """
        anomalies = []
        for bar in bars:
            symbol = bar.get("symbol", "")
            volume = bar.get("volume", 0)
            if not symbol:
                continue
            result = self.check(symbol, volume, day_of_week, hour, minute)
            if result is not None:
                anomalies.append(result)
        return anomalies

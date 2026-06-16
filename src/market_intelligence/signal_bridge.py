"""Redis pub/sub bridge for cross-process MarketSignal transport.

Celery workers produce signals in separate processes — this bridge
serializes MarketSignal to JSON and publishes to Redis pub/sub so
the FastAPI process can consume and inject into the in-process SignalBus.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

CHANNEL = "signals:cross_process"


class SignalBridge:
    """Redis pub/sub bridge for cross-process signal transport."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    def publish(self, signal_dict: dict[str, Any]) -> bool:
        """Publish a serialized signal dict to Redis pub/sub.

        Called from Celery worker context.

        Args:
            signal_dict: Signal data as a JSON-serializable dict.

        Returns:
            True if published successfully, False otherwise.
        """
        if self._redis is None:
            logger.debug("SignalBridge: no Redis client, skipping publish")
            return False

        try:
            payload = json.dumps(signal_dict, ensure_ascii=False, default=str)
            self._redis.publish(CHANNEL, payload)
            logger.debug("SignalBridge: published signal to %s", CHANNEL)
            return True
        except Exception:
            logger.warning("SignalBridge: publish failed", exc_info=True)
            return False

    def publish_from_report(self, report: dict[str, Any]) -> bool:
        """Convenience: convert an intel report dict and publish.

        Args:
            report: IntelReport dict with symbol, signal, confidence, etc.

        Returns:
            True if published successfully.
        """
        signal_dict = {
            "source": "intel_report",
            "symbol": report.get("symbol", ""),
            "signal": report.get("signal", "neutral"),
            "confidence": report.get("confidence", 0.5),
            "summary": report.get("summary", ""),
            "action": report.get("action", "hold"),
        }
        return self.publish(signal_dict)

    def publish_from_recommendation(self, rec: dict[str, Any]) -> bool:
        """Convenience: convert a recommendation dict and publish.

        Args:
            rec: Recommendation dict with symbol, action, confidence, etc.

        Returns:
            True if published successfully.
        """
        signal_dict = {
            "source": "recommendation",
            "symbol": rec.get("symbol", ""),
            "action": rec.get("action", "watch"),
            "confidence": rec.get("confidence", 0.5),
            "style": rec.get("style", ""),
            "reason": rec.get("reason", ""),
        }
        return self.publish(signal_dict)

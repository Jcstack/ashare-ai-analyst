"""Event bus producer helpers — thin wrappers for publishing typed events.

Each function handles lazy EventBus initialization and graceful degradation
when Redis is unavailable (log warning, never crash the caller).

Per PRD v50.0 §17.3: all inter-module communication flows through
typed event streams.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("event_bus.producers")


@lru_cache(maxsize=1)
def _get_bus():
    """Lazily create a singleton EventBus instance.

    Returns None if Redis is unavailable at init time.
    """
    try:
        from src.event_bus.bus import EventBus

        return EventBus()
    except Exception as exc:
        logger.warning("EventBus initialization failed (will retry next call): %s", exc)
        # Clear cache so next call retries
        _get_bus.cache_clear()
        return None


def _safe_publish(stream: str, event_type: str, data: dict[str, Any]) -> None:
    """Publish an event, swallowing all errors."""
    bus = _get_bus()
    if bus is None:
        return
    try:
        bus.publish(stream, event_type, data)
    except Exception as exc:
        logger.warning("Event bus publish failed (%s/%s): %s", stream, event_type, exc)


# ------------------------------------------------------------------
# events:market
# ------------------------------------------------------------------


def publish_price_spike(
    symbol: str,
    name: str,
    z_score: float,
    price: float,
    change_pct: float,
) -> None:
    """Publish a price spike detection to events:market."""
    _safe_publish(
        "events:market",
        "price_spike",
        {
            "symbol": symbol,
            "name": name,
            "z_score": z_score,
            "price": price,
            "change_pct": change_pct,
            "ts": time.time(),
        },
    )


def publish_volume_anomaly(
    symbol: str,
    name: str,
    z_score: float,
    volume: int,
) -> None:
    """Publish a volume anomaly detection to events:market."""
    _safe_publish(
        "events:market",
        "volume_anomaly",
        {
            "symbol": symbol,
            "name": name,
            "z_score": z_score,
            "volume": volume,
            "ts": time.time(),
        },
    )


# ------------------------------------------------------------------
# events:news
# ------------------------------------------------------------------


def publish_intel_event(
    event_type: str,
    title: str,
    severity: float,
    sectors: list[str],
    data: dict[str, Any],
) -> None:
    """Publish an intelligence pipeline output to events:news."""
    _safe_publish(
        "events:news",
        event_type,
        {
            "title": title,
            "severity": severity,
            "sectors": sectors,
            "ts": time.time(),
            **data,
        },
    )


# ------------------------------------------------------------------
# events:regime
# ------------------------------------------------------------------


def publish_regime_change(
    phase: str,
    phase_cn: str,
    confidence: float,
    prev_phase: str,
) -> None:
    """Publish a sentiment/regime phase change to events:regime."""
    _safe_publish(
        "events:regime",
        "sentiment_phase_change",
        {
            "phase": phase,
            "phase_cn": phase_cn,
            "confidence": confidence,
            "prev_phase": prev_phase,
            "ts": time.time(),
        },
    )


# ------------------------------------------------------------------
# events:signal
# ------------------------------------------------------------------


def publish_signal_detected(
    symbol: str,
    direction: str,
    source: str,
    confidence: float,
    reason: str,
) -> None:
    """Publish a new signal detection to events:signal."""
    _safe_publish(
        "events:signal",
        "signal_detected",
        {
            "symbol": symbol,
            "direction": direction,
            "source": source,
            "confidence": confidence,
            "reason": reason,
            "ts": time.time(),
        },
    )


# ------------------------------------------------------------------
# events:thesis
# ------------------------------------------------------------------


def publish_thesis_change(
    thesis_id: str,
    symbol: str,
    status: str,
    confidence: float,
) -> None:
    """Publish a thesis state change to events:thesis."""
    _safe_publish(
        "events:thesis",
        "thesis_state_change",
        {
            "thesis_id": thesis_id,
            "symbol": symbol,
            "status": status,
            "confidence": confidence,
            "ts": time.time(),
        },
    )


# ------------------------------------------------------------------
# events:risk
# ------------------------------------------------------------------


def publish_risk_alert(
    alert_type: str,
    symbol: str,
    severity: float,
    message: str,
) -> None:
    """Publish a risk limit breach to events:risk."""
    _safe_publish(
        "events:risk",
        alert_type,
        {
            "symbol": symbol,
            "severity": severity,
            "message": message,
            "ts": time.time(),
        },
    )

"""Unified signal event bus for the v20.0 Market Intelligence system.

All signal producers (signal_library, alert_engine, system_alert_engine)
publish ``MarketSignal`` instances through the bus.  All registered consumers
receive every signal via a fan-out pattern.

Adapter classes convert upstream domain types into the canonical
``MarketSignal`` envelope before publishing.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from src.web.schemas.market_signal import (
    MarketPhase,
    MarketSignal,
    RiskLevel,
    SignalType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal name -> SignalType mapping used by SignalLibraryAdapter
# ---------------------------------------------------------------------------

_SIGNAL_NAME_MAP: dict[str, SignalType] = {
    "ma_cross": SignalType.S1_TREND,
    "rsi_extreme": SignalType.S2_MOMENTUM_SHIFT,
    "bollinger_squeeze": SignalType.S5_VOLATILITY,
    "volume_breakout": SignalType.S4_ANOMALY,
    "macd_divergence": SignalType.S2_MOMENTUM_SHIFT,
}

# ---------------------------------------------------------------------------
# Core event bus
# ---------------------------------------------------------------------------


class SignalBus:
    """Unified signal event bus -- all signal producers publish here, all consumers subscribe."""

    def __init__(self, maxsize: int = 1000) -> None:
        self._queue: asyncio.Queue[MarketSignal] = asyncio.Queue(maxsize=maxsize)
        self._consumers: dict[str, Callable[[MarketSignal], Awaitable[None]]] = {}
        self._producers: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._running = False

        # Stats
        self._published_count = 0
        self._consumed_count = 0
        self._dropped_count = 0

    # -- Producer / consumer registration -----------------------------------

    def register_producer(self, name: str) -> None:
        """Register a signal producer by name."""
        self._producers.add(name)
        logger.info("Producer registered: %s", name)

    def register_consumer(
        self,
        name: str,
        callback: Callable[[MarketSignal], Awaitable[None]],
    ) -> None:
        """Register a consumer that will receive every signal via fan-out."""
        self._consumers[name] = callback
        logger.info("Consumer registered: %s", name)

    # -- Publish ------------------------------------------------------------

    def publish(self, signal: MarketSignal) -> None:
        """Non-blocking publish.  If the queue is full, drop the oldest signal and log a warning."""
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._dropped_count += 1
                logger.warning(
                    "Signal bus queue full -- dropped oldest signal (total dropped: %d)",
                    self._dropped_count,
                )
            except asyncio.QueueEmpty:
                pass  # pragma: no cover — race condition guard

        try:
            self._queue.put_nowait(signal)
            self._published_count += 1
        except asyncio.QueueFull:
            # Should not happen after draining above, but guard defensively.
            self._dropped_count += 1
            logger.error("Signal bus: failed to enqueue signal after drain")

    # -- Lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Start the background consumer loop that fans out signals."""
        if self._running:
            logger.warning("SignalBus already running")
            return
        self._running = True
        self._task = asyncio.ensure_future(self._consume_loop())
        logger.info("SignalBus started")

    async def stop(self) -> None:
        """Gracefully shut down the consumer loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("SignalBus stopped")

    # -- Stats --------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return operational statistics."""
        return {
            "published_count": self._published_count,
            "consumed_count": self._consumed_count,
            "dropped_count": self._dropped_count,
            "producer_names": sorted(self._producers),
            "consumer_names": sorted(self._consumers.keys()),
            "queue_size": self._queue.qsize(),
        }

    # -- Internal -----------------------------------------------------------

    async def _consume_loop(self) -> None:
        """Background loop: dequeue signals and fan-out to all consumers."""
        while self._running:
            try:
                signal = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            for consumer_name, callback in self._consumers.items():
                try:
                    await callback(signal)
                    self._consumed_count += 1
                except Exception:
                    logger.exception(
                        "Consumer '%s' failed processing signal %s",
                        consumer_name,
                        signal.signal_id,
                    )


# ---------------------------------------------------------------------------
# Adapters — convert upstream domain types into MarketSignal
# ---------------------------------------------------------------------------


class SignalLibraryAdapter:
    """Convert ``SignalResult`` (from ``src.quant.signal_library``) to ``MarketSignal``."""

    @staticmethod
    def convert(
        signal_result: object,
        symbol: str,
        phase: MarketPhase = MarketPhase.CLOSED,
    ) -> MarketSignal:
        """Build a ``MarketSignal`` from a quant ``SignalResult``.

        Args:
            signal_result: A ``SignalResult`` dataclass instance.
            symbol: Stock code (e.g. ``"600519"``).
            phase: Current market phase.

        Returns:
            A fully-populated ``MarketSignal`` envelope.
        """
        # Dynamically access dataclass attributes so we don't need a hard
        # import of SignalResult (keeps the dependency one-directional).
        signal_name: str = getattr(signal_result, "signal_name", "")
        strength: float = getattr(signal_result, "strength", 0.0)
        description: str = getattr(signal_result, "description", "")
        direction: str = getattr(signal_result, "direction", "neutral")

        signal_type = _SIGNAL_NAME_MAP.get(signal_name, SignalType.S4_ANOMALY)
        confidence = strength * 100.0

        # Build short summary (max 50 chars)
        summary_short = f"{signal_name}|{direction}"
        if len(summary_short) > 50:
            summary_short = summary_short[:50]

        return MarketSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=signal_type,
            timestamp=datetime.now(timezone.utc),
            assets=[symbol],
            phase=phase,
            confidence_score=confidence,
            risk_level=RiskLevel.LOW,
            sources=[],
            producer="signal_library",
            summary_short=summary_short,
            summary_detailed=description or None,
        )


class AlertEngineAdapter:
    """Convert an alert dict (from ``src.analysis.alerts.AlertEngine``) to ``MarketSignal``."""

    _SEVERITY_CONFIDENCE: dict[str, float] = {
        "critical": 85.0,
        "warning": 65.0,
        "info": 45.0,
    }

    @staticmethod
    def convert(
        alert: dict,
        phase: MarketPhase = MarketPhase.CLOSED,
    ) -> MarketSignal:
        """Build a ``MarketSignal`` from a stock-level alert dict.

        Expected alert keys: id, symbol, name, alert_type, severity, title,
        description, value, threshold, timestamp.

        Args:
            alert: Alert dictionary from ``AlertEngine.check_alerts()``.
            phase: Current market phase.

        Returns:
            A fully-populated ``MarketSignal`` envelope.
        """
        severity: str = alert.get("severity", "info")
        confidence = AlertEngineAdapter._SEVERITY_CONFIDENCE.get(severity, 45.0)
        symbol: str = alert.get("symbol", "")
        title: str = alert.get("title", "")
        description: str = alert.get("description", "")

        summary_short = title[:50] if title else "stock alert"

        return MarketSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=SignalType.STOCK_ALERT,
            timestamp=datetime.now(timezone.utc),
            assets=[symbol] if symbol else [],
            phase=phase,
            confidence_score=confidence,
            risk_level=RiskLevel.LOW,
            sources=[],
            producer="alert_engine",
            summary_short=summary_short,
            summary_detailed=description or None,
        )


class IntelReportAdapter:
    """Convert an IntelReport dict into a ``MarketSignal``."""

    @staticmethod
    def convert(
        report: dict,
        phase: MarketPhase = MarketPhase.CLOSED,
    ) -> MarketSignal:
        """Build a ``MarketSignal`` from an intel analysis report.

        Args:
            report: Report dict with signal, confidence, symbol, factors, summary.
            phase: Current market phase.

        Returns:
            A fully-populated ``MarketSignal`` envelope.
        """
        signal_map = {
            "bullish": SignalType.S7_POLICY_DRIVEN,
            "bearish": SignalType.S7_POLICY_DRIVEN,
            "neutral": SignalType.S7_POLICY_DRIVEN,
        }
        report_signal = report.get("signal", "neutral")
        signal_type = signal_map.get(report_signal, SignalType.STOCK_ALERT)

        confidence = report.get("confidence", 0.5)
        symbol = report.get("symbol", "")
        summary = report.get("summary", "")[:50]

        return MarketSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=signal_type,
            timestamp=datetime.now(timezone.utc),
            assets=[symbol] if symbol and symbol != "MACRO" else [],
            phase=phase,
            confidence_score=confidence * 100.0,
            risk_level=RiskLevel.LOW,
            sources=[],
            producer="intel_report",
            summary_short=summary,
            summary_detailed=report.get("intel_summary") or None,
        )


class RecommendationAdapter:
    """Convert a Recommendation dict into a ``MarketSignal``."""

    @staticmethod
    def convert(
        rec: dict,
        phase: MarketPhase = MarketPhase.CLOSED,
    ) -> MarketSignal:
        """Build a ``MarketSignal`` from a recommendation record.

        Args:
            rec: Recommendation dict with action, confidence, symbol, style.
            phase: Current market phase.

        Returns:
            A fully-populated ``MarketSignal`` envelope.
        """
        action = rec.get("action", "watch")
        confidence = rec.get("confidence", 0.5)
        symbol = rec.get("symbol", "")
        style = rec.get("style", "")

        summary = f"{action}|{symbol}|{style}"[:50]

        return MarketSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=SignalType.S1_TREND,
            timestamp=datetime.now(timezone.utc),
            assets=[symbol] if symbol else [],
            phase=phase,
            confidence_score=confidence * 100.0,
            risk_level=RiskLevel.LOW,
            sources=[],
            producer="recommendation",
            summary_short=summary,
            summary_detailed=rec.get("reason") or None,
        )


class SystemAlertEngineAdapter:
    """Convert an ``Alert`` dataclass (from ``src.intelligence.alert_engine``) to ``MarketSignal``."""

    _SEVERITY_CONFIDENCE: dict[str, float] = {
        "critical": 90.0,
        "warning": 70.0,
        "info": 50.0,
    }

    @staticmethod
    def convert(
        alert: object,
        phase: MarketPhase = MarketPhase.CLOSED,
    ) -> MarketSignal:
        """Build a ``MarketSignal`` from a system-level ``Alert`` dataclass.

        The ``Alert`` dataclass has: alert_id, rule_name, severity
        (info/warning/critical), title, description, symbol (optional),
        data (dict), timestamp.

        Args:
            alert: An ``Alert`` dataclass instance from the intelligence layer.
            phase: Current market phase.

        Returns:
            A fully-populated ``MarketSignal`` envelope.
        """
        severity: str = getattr(alert, "severity", "info")
        confidence = SystemAlertEngineAdapter._SEVERITY_CONFIDENCE.get(severity, 50.0)
        symbol: str | None = getattr(alert, "symbol", None)
        title: str = getattr(alert, "title", "")
        description: str = getattr(alert, "description", "")

        summary_short = title[:50] if title else "system alert"

        return MarketSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=SignalType.SYSTEM_ALERT,
            timestamp=datetime.now(timezone.utc),
            assets=[symbol] if symbol else [],
            phase=phase,
            confidence_score=confidence,
            risk_level=RiskLevel.LOW,
            sources=[],
            producer="system_alert_engine",
            summary_short=summary_short,
            summary_detailed=description or None,
        )

"""Tests for SignalBus and signal adapter classes.

Part of v20.0 Market Intelligence Phase 1.
"""

from __future__ import annotations

import asyncio
import types

import pytest

from src.market_intelligence.signal_bus import (
    AlertEngineAdapter,
    SignalBus,
    SignalLibraryAdapter,
    SystemAlertEngineAdapter,
)
from src.web.schemas.market_signal import (
    MarketSignal,
    MarketPhase,
    SignalType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(*, signal_type: SignalType = SignalType.S1_TREND) -> MarketSignal:
    """Build a minimal MarketSignal for testing."""
    from datetime import datetime, timezone

    return MarketSignal(
        signal_type=signal_type,
        timestamp=datetime.now(timezone.utc),
        assets=["600519"],
        phase=MarketPhase.CLOSED,
        confidence_score=50.0,
        sources=[],
        producer="test",
        summary_short="test signal",
    )


# ---------------------------------------------------------------------------
# SignalBus core tests
# ---------------------------------------------------------------------------


class TestSignalBus:
    """Tests for the SignalBus publish/consume fan-out."""

    @pytest.mark.anyio
    async def test_publish_and_consume(self):
        """Register a consumer, publish a signal, verify it receives it."""
        bus = SignalBus()
        received: list[MarketSignal] = []
        done = asyncio.Event()

        async def consumer(signal: MarketSignal) -> None:
            received.append(signal)
            done.set()

        bus.register_consumer("c1", consumer)
        bus.start()

        signal = _make_signal()
        bus.publish(signal)

        try:
            await asyncio.wait_for(done.wait(), timeout=3.0)
        finally:
            await bus.stop()

        assert len(received) == 1
        assert received[0].signal_id == signal.signal_id

    @pytest.mark.anyio
    async def test_multiple_consumers(self):
        """Register 2 consumers, publish 1 signal, both should receive it."""
        bus = SignalBus()
        received_a: list[MarketSignal] = []
        received_b: list[MarketSignal] = []
        done = asyncio.Event()

        async def consumer_a(signal: MarketSignal) -> None:
            received_a.append(signal)

        async def consumer_b(signal: MarketSignal) -> None:
            received_b.append(signal)
            done.set()

        bus.register_consumer("a", consumer_a)
        bus.register_consumer("b", consumer_b)
        bus.start()

        signal = _make_signal()
        bus.publish(signal)

        try:
            await asyncio.wait_for(done.wait(), timeout=3.0)
        finally:
            await bus.stop()

        assert len(received_a) == 1
        assert len(received_b) == 1
        assert received_a[0].signal_id == signal.signal_id
        assert received_b[0].signal_id == signal.signal_id

    def test_queue_overflow_drops_oldest(self):
        """Create bus with maxsize=2, publish 3 signals, verify dropped_count == 1."""
        bus = SignalBus(maxsize=2)

        bus.publish(_make_signal())
        bus.publish(_make_signal())
        bus.publish(_make_signal())

        stats = bus.get_stats()
        assert stats["dropped_count"] == 1
        assert stats["published_count"] == 3

    def test_get_stats(self):
        """Verify stats dict has correct keys and counts."""
        bus = SignalBus()
        bus.register_producer("prod1")
        bus.register_consumer("cons1", lambda s: None)

        bus.publish(_make_signal())

        stats = bus.get_stats()
        assert set(stats.keys()) == {
            "published_count",
            "consumed_count",
            "dropped_count",
            "producer_names",
            "consumer_names",
            "queue_size",
        }
        assert stats["published_count"] == 1
        assert stats["consumed_count"] == 0
        assert stats["dropped_count"] == 0
        assert stats["producer_names"] == ["prod1"]
        assert stats["consumer_names"] == ["cons1"]
        assert stats["queue_size"] == 1


# ---------------------------------------------------------------------------
# Adapter tests
# ---------------------------------------------------------------------------


class TestSignalLibraryAdapter:
    """Tests for SignalLibraryAdapter.convert()."""

    def test_signal_library_adapter(self):
        """Convert a mock SignalResult and verify fields."""
        signal_result = types.SimpleNamespace(
            signal_name="ma_cross",
            strength=0.75,
            description="test",
            direction="bullish",
        )
        result = SignalLibraryAdapter.convert(signal_result, symbol="600519")

        assert result.signal_type == SignalType.S1_TREND
        assert result.confidence_score == 75.0
        assert result.producer == "signal_library"
        assert result.assets == ["600519"]
        assert "ma_cross" in result.summary_short
        assert "bullish" in result.summary_short


class TestAlertEngineAdapter:
    """Tests for AlertEngineAdapter.convert()."""

    def test_alert_engine_adapter(self):
        """Convert an alert dict and verify fields."""
        alert = {
            "id": "alert-1",
            "symbol": "600519",
            "name": "贵州茅台",
            "alert_type": "price_drop",
            "severity": "critical",
            "title": "Test Alert",
            "description": "desc",
            "value": 1.0,
            "threshold": 0.5,
            "timestamp": "2025-01-01T00:00:00Z",
        }
        result = AlertEngineAdapter.convert(alert)

        assert result.signal_type == SignalType.STOCK_ALERT
        assert result.confidence_score == 85.0
        assert result.producer == "alert_engine"
        assert result.assets == ["600519"]
        assert result.summary_short == "Test Alert"


class TestSystemAlertEngineAdapter:
    """Tests for SystemAlertEngineAdapter.convert()."""

    def test_system_alert_engine_adapter(self):
        """Convert a mock Alert object and verify fields."""
        alert = types.SimpleNamespace(
            alert_id="a1",
            rule_name="test",
            severity="warning",
            title="System Alert",
            description="desc",
            symbol="600519",
            data={},
            timestamp="2025-01-01T00:00:00Z",
        )
        result = SystemAlertEngineAdapter.convert(alert)

        assert result.signal_type == SignalType.SYSTEM_ALERT
        assert result.confidence_score == 70.0
        assert result.producer == "system_alert_engine"
        assert result.assets == ["600519"]
        assert result.summary_short == "System Alert"

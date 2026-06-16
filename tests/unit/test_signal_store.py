"""Tests for SignalStore — SQLite-backed signal persistence + accuracy tracking.

Part of v20.0 Market Intelligence Phase 1.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.market_intelligence.signal_store import SignalStore
from src.web.schemas.market_signal import (
    MarketPhase,
    MarketSignal,
    RiskLevel,
    SignalType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    *,
    signal_type: SignalType = SignalType.S1_TREND,
    assets: list[str] | None = None,
    summary_short: str = "test signal",
    confidence_score: float = 60.0,
    timestamp: datetime | None = None,
    signal_id: str | None = None,
) -> MarketSignal:
    """Build a MarketSignal for testing."""
    return MarketSignal(
        signal_id=signal_id or str(uuid.uuid4()),
        signal_type=signal_type,
        timestamp=timestamp or datetime.now(timezone.utc),
        assets=assets or ["600519"],
        phase=MarketPhase.CLOSED,
        confidence_score=confidence_score,
        risk_level=RiskLevel.LOW,
        sources=[],
        producer="test",
        summary_short=summary_short,
    )


@pytest.fixture
def store(tmp_path):
    """Create a SignalStore backed by a temporary database."""
    db_path = str(tmp_path / "test_signals.db")
    return SignalStore(db_path=db_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSignalStore:
    """Tests for SignalStore CRUD operations."""

    def test_store_and_retrieve(self, store: SignalStore):
        """Store a signal, retrieve by ID, verify fields match."""
        signal = _make_signal(
            signal_type=SignalType.S1_TREND,
            summary_short="bullish trend",
            confidence_score=72.0,
        )
        store.store(signal)

        row = store.get_signal(signal.signal_id)
        assert row is not None
        assert row["signal_id"] == signal.signal_id
        assert row["signal_type"] == "S1_TREND"
        assert row["confidence_score"] == 72.0
        assert row["summary_short"] == "bullish trend"
        assert row["producer"] == "test"

    def test_get_signals_with_filters(self, store: SignalStore):
        """Store 3 signals with different types/assets, query with type filter."""
        store.store(_make_signal(signal_type=SignalType.S1_TREND, assets=["600519"]))
        store.store(_make_signal(signal_type=SignalType.STOCK_ALERT, assets=["000001"]))
        store.store(_make_signal(signal_type=SignalType.S1_TREND, assets=["000858"]))

        results = store.get_signals(signal_type="S1_TREND")
        assert len(results) == 2
        for r in results:
            assert r["signal_type"] == "S1_TREND"

    def test_duplicate_signal_ignored(self, store: SignalStore):
        """Store same signal twice, verify no error (INSERT OR IGNORE)."""
        signal = _make_signal()
        store.store(signal)
        store.store(signal)  # Should not raise

        row = store.get_signal(signal.signal_id)
        assert row is not None

    def test_backfill_outcome_bullish_correct(self, store: SignalStore):
        """Signal with 'bullish' summary + positive actual_pct => correct_t3 == 1."""
        signal = _make_signal(summary_short="bullish trend signal")
        store.store(signal)

        ok = store.backfill_outcome(signal.signal_id, window=3, actual_pct_change=0.05)
        assert ok is True

        # Read outcome from DB
        conn = store._connect()
        try:
            row = conn.execute(
                "SELECT correct_t3, actual_change_t3 FROM signal_outcomes WHERE signal_id = ?",
                (signal.signal_id,),
            ).fetchone()
            assert row is not None
            assert row["correct_t3"] == 1
            assert row["actual_change_t3"] == 0.05
        finally:
            conn.close()

    def test_backfill_outcome_bearish_wrong(self, store: SignalStore):
        """Signal with 'bearish' summary + positive actual_pct => correct_t3 == 0."""
        signal = _make_signal(summary_short="bearish momentum")
        store.store(signal)

        ok = store.backfill_outcome(signal.signal_id, window=3, actual_pct_change=0.03)
        assert ok is True

        conn = store._connect()
        try:
            row = conn.execute(
                "SELECT correct_t3 FROM signal_outcomes WHERE signal_id = ?",
                (signal.signal_id,),
            ).fetchone()
            assert row is not None
            assert row["correct_t3"] == 0
        finally:
            conn.close()

    def test_get_signal_accuracy_insufficient_data(self, store: SignalStore):
        """With < 20 signals, accuracy should return insufficient_data: True."""
        # Store 5 signals with outcomes (well below 20 threshold)
        for i in range(5):
            sig = _make_signal(summary_short="bullish test")
            store.store(sig)
            store.backfill_outcome(sig.signal_id, window=3, actual_pct_change=0.01)

        result = store.get_signal_accuracy()
        assert result["insufficient_data"] is True
        assert result["accuracy_t3"] == 0.5  # default fallback
        assert result["sample_count"] < 20

    def test_cleanup_old_signals(self, store: SignalStore):
        """Store a signal with old timestamp, run cleanup(days=1), verify deleted."""
        old_ts = datetime.now(timezone.utc) - timedelta(days=10)
        signal = _make_signal(timestamp=old_ts)
        store.store(signal)

        # Verify it exists first
        assert store.get_signal(signal.signal_id) is not None

        deleted = store.cleanup(days=1)
        assert deleted == 1
        assert store.get_signal(signal.signal_id) is None

    def test_get_pending_backfills(self, store: SignalStore):
        """Store a directional signal with old timestamp, verify it appears in pending backfills."""
        old_ts = datetime.now(timezone.utc) - timedelta(days=7)
        signal = _make_signal(
            signal_type=SignalType.S1_TREND,
            summary_short="bullish signal",
            timestamp=old_ts,
        )
        store.store(signal)

        pending = store.get_pending_backfills(window=3)
        assert len(pending) >= 1
        signal_ids = [p["signal_id"] for p in pending]
        assert signal.signal_id in signal_ids

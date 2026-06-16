"""Tests for DeliveryTracker — v23.0 Phase 3 delivery tracking."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src.intelligence_hub.delivery_tracker import DeliveryTracker


@pytest.fixture()
def tracker(tmp_path):
    """Create a DeliveryTracker backed by a temp database."""
    db = tmp_path / "test_delivery.db"
    return DeliveryTracker(db_path=str(db))


# ------------------------------------------------------------------
# TestTrackEvent
# ------------------------------------------------------------------


class TestTrackEvent:
    """Tests for single and batch event tracking."""

    def test_track_single_event(self, tracker: DeliveryTracker):
        tracker.track("item-1", "clicked")
        stats = tracker.get_item_stats("item-1")
        assert stats["clicked"] == 1
        assert stats["displayed"] == 0
        assert stats["analyzed"] == 0

    def test_track_multiple_event_types(self, tracker: DeliveryTracker):
        tracker.track("item-1", "displayed")
        tracker.track("item-1", "clicked")
        tracker.track("item-1", "analyzed")
        stats = tracker.get_item_stats("item-1")
        assert stats["displayed"] == 1
        assert stats["clicked"] == 1
        assert stats["analyzed"] == 1

    def test_track_batch(self, tracker: DeliveryTracker):
        ids = ["item-a", "item-b", "item-c"]
        count = tracker.track_batch(ids, "displayed")
        assert count == 3
        for iid in ids:
            stats = tracker.get_item_stats(iid)
            assert stats["displayed"] == 1

    def test_track_batch_empty(self, tracker: DeliveryTracker):
        count = tracker.track_batch([], "displayed")
        assert count == 0

    def test_track_unknown_event_type_accepted(self, tracker: DeliveryTracker):
        """Non-standard event types are silently accepted (no validation)."""
        tracker.track("item-x", "shared")
        # Should not raise; stats won't include it in standard keys
        stats = tracker.get_item_stats("item-x")
        assert stats["displayed"] == 0


# ------------------------------------------------------------------
# TestGetItemStats
# ------------------------------------------------------------------


class TestGetItemStats:
    """Tests for per-item statistics."""

    def test_stats_for_tracked_item(self, tracker: DeliveryTracker):
        tracker.track("item-1", "displayed")
        tracker.track("item-1", "displayed")
        tracker.track("item-1", "clicked")
        stats = tracker.get_item_stats("item-1")
        assert stats == {"displayed": 2, "clicked": 1, "analyzed": 0}

    def test_stats_for_untracked_item_returns_zeros(self, tracker: DeliveryTracker):
        stats = tracker.get_item_stats("nonexistent")
        assert stats == {"displayed": 0, "clicked": 0, "analyzed": 0}


# ------------------------------------------------------------------
# TestGetStats
# ------------------------------------------------------------------


class TestGetStats:
    """Tests for aggregate delivery statistics."""

    def test_aggregate_stats(self, tracker: DeliveryTracker):
        tracker.track_batch(["a", "b", "c"], "displayed")
        tracker.track("a", "clicked")
        tracker.track("a", "analyzed")
        stats = tracker.get_stats(days=7)
        assert stats["total_displayed"] == 3
        assert stats["total_clicked"] == 1
        assert stats["total_analyzed"] == 1
        assert stats["unique_items_displayed"] == 3

    def test_click_through_rate_calculation(self, tracker: DeliveryTracker):
        tracker.track_batch(["a", "b", "c", "d"], "displayed")
        tracker.track("a", "clicked")
        tracker.track("b", "clicked")
        stats = tracker.get_stats(days=7)
        # 2 clicks / 4 displays = 0.5
        assert stats["click_through_rate"] == 0.5

    def test_empty_db_stats(self, tracker: DeliveryTracker):
        stats = tracker.get_stats(days=7)
        assert stats["total_displayed"] == 0
        assert stats["total_clicked"] == 0
        assert stats["total_analyzed"] == 0
        assert stats["click_through_rate"] == 0.0
        assert stats["unique_items_displayed"] == 0


# ------------------------------------------------------------------
# TestGetPopularItems
# ------------------------------------------------------------------


class TestGetPopularItems:
    """Tests for most-clicked items query."""

    def test_ordering_by_clicks(self, tracker: DeliveryTracker):
        # item-b has more clicks than item-a
        tracker.track("item-a", "clicked")
        tracker.track("item-b", "clicked")
        tracker.track("item-b", "clicked")
        tracker.track("item-a", "displayed")
        tracker.track("item-b", "displayed")
        popular = tracker.get_popular_items(limit=10, days=7)
        assert len(popular) == 2
        assert popular[0]["item_id"] == "item-b"
        assert popular[0]["click_count"] == 2
        assert popular[1]["item_id"] == "item-a"
        assert popular[1]["click_count"] == 1

    def test_limit_respected(self, tracker: DeliveryTracker):
        for i in range(5):
            tracker.track(f"item-{i}", "clicked")
        popular = tracker.get_popular_items(limit=3, days=7)
        assert len(popular) == 3

    def test_empty_db_popular(self, tracker: DeliveryTracker):
        popular = tracker.get_popular_items(limit=10, days=7)
        assert popular == []


# ------------------------------------------------------------------
# TestCleanup
# ------------------------------------------------------------------


class TestCleanup:
    """Tests for event cleanup/retention."""

    def test_removes_old_events(self, tracker: DeliveryTracker):
        # Insert an event with a timestamp 60 days ago
        conn = sqlite3.connect(str(tracker._db_path))
        old_ts = (datetime.now(UTC) - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO delivery_events (item_id, event_type, timestamp) VALUES (?, ?, ?)",
            ("old-item", "displayed", old_ts),
        )
        conn.commit()
        conn.close()

        # Also add a recent event
        tracker.track("recent-item", "displayed")

        deleted = tracker.cleanup(days=30)
        assert deleted == 1

        # Recent item still exists
        stats = tracker.get_item_stats("recent-item")
        assert stats["displayed"] == 1

        # Old item is gone
        stats = tracker.get_item_stats("old-item")
        assert stats["displayed"] == 0

    def test_preserves_recent_events(self, tracker: DeliveryTracker):
        tracker.track("item-1", "clicked")
        tracker.track("item-2", "displayed")
        deleted = tracker.cleanup(days=30)
        assert deleted == 0
        # Both items still present
        assert tracker.get_item_stats("item-1")["clicked"] == 1
        assert tracker.get_item_stats("item-2")["displayed"] == 1

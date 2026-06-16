"""Tests for src.market_intelligence.latency_tracker — LatencyTracker."""

from src.market_intelligence.latency_tracker import LatencyTracker


class TestLatencyTracker:
    def test_record_and_percentiles(self):
        """Record 100 measurements, verify P50/P95/P99 are sensible."""
        tracker = LatencyTracker()
        # Record values 1.0 through 100.0
        for i in range(1, 101):
            tracker.record(float(i))

        stats = tracker.get_percentiles()
        assert stats["count"] == 100
        # P50 should be around 50 (median of 1..100)
        assert 45.0 <= stats["p50"] <= 55.0
        # P95 should be around 95
        assert 90.0 <= stats["p95"] <= 100.0
        # P99 should be around 99
        assert 95.0 <= stats["p99"] <= 100.0
        # Mean of 1..100 is 50.5
        assert 49.0 <= stats["mean"] <= 52.0

    def test_source_latency(self):
        """Record with source names, verify per-source stats."""
        tracker = LatencyTracker()
        # Record some measurements for two different sources
        for i in range(1, 51):
            tracker.record(float(i), source="akshare")
        for i in range(50, 101):
            tracker.record(float(i), source="llm")

        source_stats = tracker.get_source_latency()
        assert "akshare" in source_stats
        assert "llm" in source_stats
        assert source_stats["akshare"]["count"] == 50
        assert source_stats["llm"]["count"] == 51
        # akshare mean should be ~25.5, llm mean should be ~75
        assert 20.0 <= source_stats["akshare"]["mean"] <= 30.0
        assert 70.0 <= source_stats["llm"]["mean"] <= 80.0

    def test_reset(self):
        """Record, reset, verify empty."""
        tracker = LatencyTracker()
        for i in range(20):
            tracker.record(float(i), source="test_source")

        # Verify data exists before reset
        assert tracker.get_percentiles()["count"] == 20
        assert "test_source" in tracker.get_source_latency()

        # Reset and verify empty
        tracker.reset()
        stats = tracker.get_percentiles()
        assert stats["count"] == 0
        assert stats["p50"] == 0.0
        assert stats["p95"] == 0.0
        assert stats["p99"] == 0.0
        assert stats["mean"] == 0.0
        assert tracker.get_source_latency() == {}

    def test_max_window(self):
        """Record more than 10000, verify oldest dropped."""
        tracker = LatencyTracker()
        # Record 10500 measurements: first 500 are very large (99999.0),
        # remaining 10000 are small (1.0)
        for _ in range(500):
            tracker.record(99999.0)
        for _ in range(10_000):
            tracker.record(1.0)

        stats = tracker.get_percentiles()
        # Window should be capped at 10000
        assert stats["count"] == 10_000
        # All values in the window should be 1.0 (the large ones were dropped)
        assert stats["p50"] == 1.0
        assert stats["p95"] == 1.0
        assert stats["p99"] == 1.0
        assert stats["mean"] == 1.0

    def test_empty_percentiles(self):
        """No records, verify returns zeros/defaults."""
        tracker = LatencyTracker()
        stats = tracker.get_percentiles()
        assert stats["p50"] == 0.0
        assert stats["p95"] == 0.0
        assert stats["p99"] == 0.0
        assert stats["count"] == 0
        assert stats["mean"] == 0.0

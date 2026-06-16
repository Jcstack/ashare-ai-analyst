"""Tests for src.data.health_tracker — DataHealthTracker."""

from src.data.health_tracker import DataHealthTracker, SourceHealth


class TestSourceHealth:
    def test_default_status_healthy(self):
        h = SourceHealth(name="test")
        assert h.status == "healthy"
        assert h.success_rate == 1.0

    def test_success_rate_calculation(self):
        h = SourceHealth(name="test", total_calls=10, success_count=8, failure_count=2)
        assert h.success_rate == 0.8

    def test_to_dict(self):
        h = SourceHealth(name="sina", total_calls=5, success_count=5)
        d = h.to_dict()
        assert d["name"] == "sina"
        assert d["status"] == "healthy"
        assert d["success_rate"] == 1.0


class TestDataHealthTracker:
    def test_initial_sources(self):
        tracker = DataHealthTracker()
        health = tracker.get_all_health()
        assert health["overall_status"] == "healthy"
        assert "sina" in health["sources"]
        assert "eastmoney" in health["sources"]

    def test_record_success(self):
        tracker = DataHealthTracker()
        tracker.record_success("sina", latency_ms=150.0)
        h = tracker.get_health("sina")
        assert h["total_calls"] == 1
        assert h["success_rate"] == 1.0
        assert h["avg_latency_ms"] == 150.0

    def test_record_failure(self):
        tracker = DataHealthTracker()
        tracker.record_failure("eastmoney", error="timeout")
        h = tracker.get_health("eastmoney")
        assert h["failure_count"] == 1
        assert h["last_error"] == "timeout"

    def test_unknown_source_auto_created(self):
        tracker = DataHealthTracker()
        tracker.record_success("new_source")
        h = tracker.get_health("new_source")
        assert h["total_calls"] == 1

    def test_degraded_sources(self):
        tracker = DataHealthTracker()
        tracker.record_failure("sina", error="err")
        degraded = tracker.get_degraded_sources()
        assert "sina" in degraded

    def test_overall_status_degrades(self):
        tracker = DataHealthTracker()
        tracker.record_failure("sina")
        health = tracker.get_all_health()
        assert health["overall_status"] == "degraded"

"""Tests for SourceRegistry — layer/weight/health tracking."""

from __future__ import annotations

import pytest

from src.intelligence_hub.source_registry import SourceMeta, SourceRegistry


def _make_config(*overrides: dict) -> list[dict]:
    base = {
        "source_id": "test_src",
        "layer": "L3",
        "base_weight": 0.75,
        "compliance_level": "MEDIUM",
        "domain_tags": ["global", "macro"],
    }
    if overrides:
        return [{**base, **o} for o in overrides]
    return [base]


class TestSourceMeta:
    def test_effective_weight_ok(self) -> None:
        m = SourceMeta("s1", "L1", 0.9, "HIGH")
        assert m.effective_weight == 0.9

    def test_effective_weight_warn(self) -> None:
        m = SourceMeta("s1", "L1", 0.9, "HIGH", status="WARN")
        assert m.effective_weight == pytest.approx(0.45)

    def test_effective_weight_down(self) -> None:
        m = SourceMeta("s1", "L1", 0.9, "HIGH", status="DOWN")
        assert m.effective_weight == 0.0

    def test_to_dict(self) -> None:
        m = SourceMeta("s1", "L2", 0.8, "HIGH", domain_tags=["us"])
        d = m.to_dict()
        assert d["source_id"] == "s1"
        assert d["layer"] == "L2"
        assert d["effective_weight"] == 0.8
        assert d["status"] == "OK"


class TestSourceRegistry:
    def test_init_from_config(self) -> None:
        reg = SourceRegistry(_make_config())
        assert reg.get("test_src") is not None
        assert reg.get("nonexistent") is None

    def test_skips_empty_source_id(self) -> None:
        reg = SourceRegistry([{"layer": "L1", "base_weight": 1.0}])
        assert reg.get_all_health() == []

    def test_record_success_resets_failures(self) -> None:
        reg = SourceRegistry(_make_config())
        reg.record_failure("test_src")
        reg.record_failure("test_src")
        reg.record_failure("test_src")
        assert reg.get("test_src").status == "WARN"

        reg.record_success("test_src", latency_ms=100.0)
        meta = reg.get("test_src")
        assert meta.status == "OK"
        assert meta.consecutive_failures == 0

    def test_record_success_tracks_latency(self) -> None:
        reg = SourceRegistry(_make_config())
        reg.record_success("test_src", latency_ms=100.0)
        reg.record_success("test_src", latency_ms=200.0)
        meta = reg.get("test_src")
        assert meta.avg_latency_ms == pytest.approx(150.0)

    def test_record_failure_warn_threshold(self) -> None:
        reg = SourceRegistry(_make_config(), warn_after=3, down_after=8)
        for _ in range(3):
            reg.record_failure("test_src")
        assert reg.get("test_src").status == "WARN"

    def test_record_failure_down_threshold(self) -> None:
        reg = SourceRegistry(_make_config(), warn_after=3, down_after=5)
        for _ in range(5):
            reg.record_failure("test_src")
        assert reg.get("test_src").status == "DOWN"
        assert reg.get("test_src").effective_weight == 0.0

    def test_record_failure_unknown_source_noop(self) -> None:
        reg = SourceRegistry(_make_config())
        reg.record_failure("unknown_source")  # should not raise

    def test_record_success_unknown_source_noop(self) -> None:
        reg = SourceRegistry(_make_config())
        reg.record_success("unknown_source", latency_ms=50.0)  # should not raise

    def test_get_all_health(self) -> None:
        cfg = _make_config(
            {"source_id": "a", "layer": "L1", "base_weight": 1.0},
            {"source_id": "b", "layer": "L5", "base_weight": 0.3},
        )
        reg = SourceRegistry(cfg)
        health = reg.get_all_health()
        assert len(health) == 2
        ids = {h["source_id"] for h in health}
        assert ids == {"a", "b"}

    def test_warn_to_ok_recovery(self) -> None:
        reg = SourceRegistry(_make_config(), warn_after=2)
        reg.record_failure("test_src")
        reg.record_failure("test_src")
        assert reg.get("test_src").status == "WARN"
        reg.record_success("test_src")
        assert reg.get("test_src").status == "OK"

    def test_latency_window_limit(self) -> None:
        reg = SourceRegistry(_make_config())
        for i in range(25):
            reg.record_success("test_src", latency_ms=float(i))
        meta = reg.get("test_src")
        # Should keep only last 20 samples (5..24)
        assert len(meta._latency_samples) == 20

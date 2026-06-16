"""Tests for the v14.0 LineageService — data snapshots and operation tracking.

Validates that:
- Snapshots are persisted with correct hash and metadata
- Operations are recorded with input/output refs
- Lineage graphs are built from thread operations
- Cleanup removes old records
- Edge cases (missing data, empty threads) are handled
"""

import pytest

from src.web.services.lineage_service import LineageService


@pytest.fixture()
def lineage_svc(tmp_path):
    """Create a LineageService backed by a temp database."""
    db = tmp_path / "test_lineage.db"
    return LineageService(db_path=db)


# ---------------------------------------------------------------------------
# Snapshot creation
# ---------------------------------------------------------------------------


class TestSnapshotCreation:
    def test_creates_snapshot_with_hash(self, lineage_svc):
        snap = lineage_svc.snapshot_data(
            source="akshare",
            payload={"close": 100.5, "volume": 10000},
            symbol="600519",
        )
        assert snap.id
        assert snap.source == "akshare"
        assert snap.symbol == "600519"
        assert snap.content_hash  # non-empty SHA-256
        assert len(snap.content_hash) == 64  # SHA-256 hex length

    def test_snapshot_deterministic_hash(self, lineage_svc):
        payload = {"close": 100.5, "volume": 10000}
        snap1 = lineage_svc.snapshot_data(source="test", payload=payload)
        snap2 = lineage_svc.snapshot_data(source="test", payload=payload)
        assert snap1.content_hash == snap2.content_hash

    def test_snapshot_different_payload_different_hash(self, lineage_svc):
        snap1 = lineage_svc.snapshot_data(source="test", payload={"a": 1})
        snap2 = lineage_svc.snapshot_data(source="test", payload={"a": 2})
        assert snap1.content_hash != snap2.content_hash

    def test_snapshot_has_unique_ids(self, lineage_svc):
        snap1 = lineage_svc.snapshot_data(source="test", payload={"x": 1})
        snap2 = lineage_svc.snapshot_data(source="test", payload={"x": 2})
        assert snap1.id != snap2.id

    def test_snapshot_records_size(self, lineage_svc):
        payload = {"data": "hello world"}
        snap = lineage_svc.snapshot_data(source="test", payload=payload)
        assert snap.payload_size_bytes > 0

    def test_snapshot_with_ttl(self, lineage_svc):
        snap = lineage_svc.snapshot_data(
            source="redis_cache",
            payload={"cached": True},
            ttl_seconds=300,
        )
        assert snap.ttl_seconds == 300

    def test_snapshot_default_source_type(self, lineage_svc):
        snap = lineage_svc.snapshot_data(source="test", payload={})
        assert snap.source_type == "market_data"

    def test_snapshot_custom_source_type(self, lineage_svc):
        snap = lineage_svc.snapshot_data(
            source="test",
            payload={},
            source_type="llm",
        )
        assert snap.source_type == "llm"

    def test_snapshot_complex_payload(self, lineage_svc):
        payload = {
            "records": [{"date": "2026-02-14", "close": 1800.5}],
            "metadata": {"source": "akshare", "count": 1},
        }
        snap = lineage_svc.snapshot_data(source="test", payload=payload)
        assert snap.payload_summary  # non-empty summary


# ---------------------------------------------------------------------------
# Snapshot retrieval
# ---------------------------------------------------------------------------


class TestSnapshotRetrieval:
    def test_get_snapshot_by_id(self, lineage_svc):
        snap = lineage_svc.snapshot_data(source="test", payload={"val": 42})
        retrieved = lineage_svc.get_snapshot(snap.id)
        assert retrieved is not None
        assert retrieved.id == snap.id
        assert retrieved.source == "test"
        assert retrieved.content_hash == snap.content_hash

    def test_get_snapshot_not_found(self, lineage_svc):
        result = lineage_svc.get_snapshot("nonexistent-id")
        assert result is None

    def test_get_snapshot_payload(self, lineage_svc):
        payload = {"close": 100.5, "indicators": {"rsi": 45}}
        snap = lineage_svc.snapshot_data(source="test", payload=payload)
        retrieved_payload = lineage_svc.get_snapshot_payload(snap.id)
        assert retrieved_payload == payload

    def test_get_snapshot_payload_not_found(self, lineage_svc):
        result = lineage_svc.get_snapshot_payload("nonexistent-id")
        assert result is None


# ---------------------------------------------------------------------------
# Operation recording
# ---------------------------------------------------------------------------


class TestOperationRecording:
    def test_record_basic_operation(self, lineage_svc):
        node = lineage_svc.record_operation(
            "get_realtime_quote",
            operation_type="tool_call",
            agent_name="master",
            thread_id="thread-1",
        )
        assert node.id
        assert node.operation == "get_realtime_quote"
        assert node.operation_type == "tool_call"
        assert node.agent_name == "master"

    def test_record_operation_with_snapshots(self, lineage_svc):
        input_snap = lineage_svc.snapshot_data(source="input", payload={"q": "600519"})
        output_snap = lineage_svc.snapshot_data(
            source="output", payload={"price": 1800}
        )

        node = lineage_svc.record_operation(
            "get_realtime_quote",
            input_snapshot_ids=[input_snap.id],
            output_snapshot_id=output_snap.id,
            thread_id="thread-1",
        )
        assert node.input_snapshot_ids == [input_snap.id]
        assert node.output_snapshot_id == output_snap.id

    def test_record_operation_with_metadata(self, lineage_svc):
        node = lineage_svc.record_operation(
            "analyze_stock",
            metadata={"symbol": "600519", "message_id": "msg-1"},
            thread_id="thread-1",
        )
        assert node.metadata["symbol"] == "600519"

    def test_record_operation_with_duration(self, lineage_svc):
        node = lineage_svc.record_operation(
            "get_concept_heat",
            duration_ms=123.45,
            thread_id="thread-1",
        )
        assert node.duration_ms == pytest.approx(123.45)

    def test_record_multiple_input_snapshots(self, lineage_svc):
        snap1 = lineage_svc.snapshot_data(source="a", payload={"x": 1})
        snap2 = lineage_svc.snapshot_data(source="b", payload={"y": 2})

        node = lineage_svc.record_operation(
            "merge_data",
            input_snapshot_ids=[snap1.id, snap2.id],
            thread_id="thread-1",
        )
        assert len(node.input_snapshot_ids) == 2


# ---------------------------------------------------------------------------
# Lineage graph
# ---------------------------------------------------------------------------


class TestLineageGraph:
    def test_get_lineage_empty_thread(self, lineage_svc):
        graph = lineage_svc.get_lineage("nonexistent-thread")
        assert graph.thread_id == "nonexistent-thread"
        assert graph.nodes == []
        assert graph.snapshots == []

    def test_get_lineage_single_operation(self, lineage_svc):
        output_snap = lineage_svc.snapshot_data(source="test", payload={"result": "ok"})
        lineage_svc.record_operation(
            "tool_call_1",
            output_snapshot_id=output_snap.id,
            thread_id="thread-A",
        )

        graph = lineage_svc.get_lineage("thread-A")
        assert len(graph.nodes) == 1
        assert len(graph.snapshots) == 1
        assert graph.root_node_id == graph.leaf_node_id

    def test_get_lineage_chain(self, lineage_svc):
        snap1 = lineage_svc.snapshot_data(source="a", payload={"step": 1})
        lineage_svc.record_operation(
            "step_1",
            output_snapshot_id=snap1.id,
            thread_id="thread-B",
        )

        snap2 = lineage_svc.snapshot_data(source="b", payload={"step": 2})
        lineage_svc.record_operation(
            "step_2",
            input_snapshot_ids=[snap1.id],
            output_snapshot_id=snap2.id,
            thread_id="thread-B",
        )

        graph = lineage_svc.get_lineage("thread-B")
        assert len(graph.nodes) == 2
        assert graph.root_node_id != graph.leaf_node_id

    def test_get_lineage_collects_all_snapshots(self, lineage_svc):
        snaps = []
        for i in range(3):
            s = lineage_svc.snapshot_data(source="test", payload={"i": i})
            snaps.append(s)

        lineage_svc.record_operation(
            "merge",
            input_snapshot_ids=[snaps[0].id, snaps[1].id],
            output_snapshot_id=snaps[2].id,
            thread_id="thread-C",
        )

        graph = lineage_svc.get_lineage("thread-C")
        snapshot_ids = {s.id for s in graph.snapshots}
        assert all(s.id in snapshot_ids for s in snaps)


# ---------------------------------------------------------------------------
# Counts and cleanup
# ---------------------------------------------------------------------------


class TestCountsAndCleanup:
    def test_count_snapshots(self, lineage_svc):
        assert lineage_svc.count_snapshots() == 0
        lineage_svc.snapshot_data(source="a", payload={"x": 1})
        lineage_svc.snapshot_data(source="b", payload={"y": 2})
        assert lineage_svc.count_snapshots() == 2

    def test_count_nodes(self, lineage_svc):
        assert lineage_svc.count_nodes() == 0
        lineage_svc.record_operation("op1", thread_id="t1")
        lineage_svc.record_operation("op2", thread_id="t1")
        assert lineage_svc.count_nodes() == 2

    def test_cleanup_no_old_records(self, lineage_svc):
        lineage_svc.snapshot_data(source="test", payload={"fresh": True})
        lineage_svc.record_operation("op", thread_id="t1")
        deleted = lineage_svc.cleanup_old_records(max_age_days=30)
        assert deleted == 0
        assert lineage_svc.count_snapshots() == 1
        assert lineage_svc.count_nodes() == 1

    def test_cleanup_old_records(self, lineage_svc):
        """Records created now are recent, so cleanup with max_age_days=0 should clear them."""
        lineage_svc.snapshot_data(source="test", payload={"old": True})
        lineage_svc.record_operation("old_op", thread_id="t1")
        # max_age_days=0 means everything is "old"
        deleted = lineage_svc.cleanup_old_records(max_age_days=0)
        assert deleted >= 2
        assert lineage_svc.count_snapshots() == 0
        assert lineage_svc.count_nodes() == 0


# ---------------------------------------------------------------------------
# DataSnapshot model methods
# ---------------------------------------------------------------------------


class TestDataSnapshotModel:
    def test_compute_hash_dict(self):
        from src.web.schemas.lineage import DataSnapshot

        h = DataSnapshot.compute_hash({"key": "value"})
        assert len(h) == 64  # SHA-256

    def test_compute_hash_list(self):
        from src.web.schemas.lineage import DataSnapshot

        h = DataSnapshot.compute_hash([1, 2, 3])
        assert len(h) == 64

    def test_compute_hash_string(self):
        from src.web.schemas.lineage import DataSnapshot

        h = DataSnapshot.compute_hash("plain text")
        assert len(h) == 64

    def test_summarize_dict_payload(self):
        from src.web.schemas.lineage import DataSnapshot

        summary = DataSnapshot.summarize_payload({"close": 100, "volume": 5000})
        assert "close" in summary
        assert "volume" in summary

    def test_summarize_list_payload(self):
        from src.web.schemas.lineage import DataSnapshot

        summary = DataSnapshot.summarize_payload([1, 2, 3, 4, 5])
        assert "1" in summary and "5" in summary

    def test_summarize_string_payload(self):
        from src.web.schemas.lineage import DataSnapshot

        summary = DataSnapshot.summarize_payload("short text")
        assert "short text" in summary

"""Tests for ImmutableAuditLog — hash-chain tamper-proof audit logging.

Part of v19.0 Production Hardening.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from src.audit.immutable_log import (
    AuditConfig,
    ImmutableAuditLog,
    _GENESIS_HASH,
    _compute_hash,
)


@pytest.fixture
def audit_log(tmp_path):
    """Create an audit log with a temp DB."""
    config = AuditConfig(db_path=str(tmp_path / "test_audit.db"))
    return ImmutableAuditLog(config=config)


class TestComputeHash:
    """Tests for the hash computation function."""

    def test_deterministic(self):
        h1 = _compute_hash("abc", {"key": "value"})
        h2 = _compute_hash("abc", {"key": "value"})
        assert h1 == h2

    def test_different_prev_hash(self):
        h1 = _compute_hash("aaa", {"key": "value"})
        h2 = _compute_hash("bbb", {"key": "value"})
        assert h1 != h2

    def test_different_payload(self):
        h1 = _compute_hash("abc", {"key": "a"})
        h2 = _compute_hash("abc", {"key": "b"})
        assert h1 != h2

    def test_sha256_length(self):
        h = _compute_hash("prev", {"data": 42})
        assert len(h) == 64

    def test_sorted_keys(self):
        """Payload key order should not matter."""
        h1 = _compute_hash("x", {"a": 1, "b": 2})
        h2 = _compute_hash("x", {"b": 2, "a": 1})
        assert h1 == h2

    def test_manual_verification(self):
        prev = "0" * 64
        payload = {"event": "test"}
        payload_str = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, default=str
        )
        expected = hashlib.sha256(f"{prev}{payload_str}".encode("utf-8")).hexdigest()
        assert _compute_hash(prev, payload) == expected


class TestImmutableAuditLog:
    """Tests for the main audit log class."""

    def test_db_creation(self, audit_log):
        """DB and tables should be created on init."""
        assert audit_log._db_path.exists()

    def test_log_entry(self, audit_log):
        entry = audit_log.log("trade_executed", {"symbol": "600519"}, actor="user")
        assert entry.entry_id != ""
        assert entry.event_type == "trade_executed"
        assert entry.actor == "user"
        assert entry.payload == {"symbol": "600519"}
        assert entry.prev_hash == _GENESIS_HASH
        assert entry.entry_hash != ""

    def test_hash_chain(self, audit_log):
        """Each entry's prev_hash should match the previous entry's hash."""
        e1 = audit_log.log("event_a", {"n": 1})
        e2 = audit_log.log("event_b", {"n": 2})
        e3 = audit_log.log("event_c", {"n": 3})

        assert e1.prev_hash == _GENESIS_HASH
        assert e2.prev_hash == e1.entry_hash
        assert e3.prev_hash == e2.entry_hash

    def test_verify_integrity_empty(self, audit_log):
        report = audit_log.verify_integrity()
        assert report.valid is True
        assert report.total_entries == 0

    def test_verify_integrity_valid(self, audit_log):
        for i in range(5):
            audit_log.log("test", {"i": i})
        report = audit_log.verify_integrity()
        assert report.valid is True
        assert report.total_entries == 5
        assert report.verified_entries == 5

    def test_verify_integrity_tampered_hash(self, audit_log):
        """Tampering with an entry_hash should be detected."""
        audit_log.log("test", {"i": 1})
        audit_log.log("test", {"i": 2})

        # Tamper with the first entry's hash
        conn = sqlite3.connect(str(audit_log._db_path))
        conn.execute("UPDATE audit_log SET entry_hash = 'tampered' WHERE rowid = 1")
        conn.commit()
        conn.close()

        report = audit_log.verify_integrity()
        assert report.valid is False
        assert report.verified_entries == 0
        assert "哈希篡改" in report.error_message

    def test_verify_integrity_broken_chain(self, audit_log):
        """Tampering with prev_hash should be detected."""
        audit_log.log("test", {"i": 1})
        audit_log.log("test", {"i": 2})

        conn = sqlite3.connect(str(audit_log._db_path))
        conn.execute("UPDATE audit_log SET prev_hash = 'broken' WHERE rowid = 2")
        conn.commit()
        conn.close()

        report = audit_log.verify_integrity()
        assert report.valid is False
        assert "链断裂" in report.error_message

    def test_get_entry(self, audit_log):
        entry = audit_log.log("test_event", {"data": "hello"})
        retrieved = audit_log.get_entry(entry.entry_id)
        assert retrieved is not None
        assert retrieved.entry_id == entry.entry_id
        assert retrieved.event_type == "test_event"
        assert retrieved.payload == {"data": "hello"}

    def test_get_entry_not_found(self, audit_log):
        assert audit_log.get_entry("nonexistent") is None

    def test_get_entries_filter_by_event_type(self, audit_log):
        audit_log.log("type_a", {"n": 1})
        audit_log.log("type_b", {"n": 2})
        audit_log.log("type_a", {"n": 3})

        results = audit_log.get_entries(event_type="type_a")
        assert len(results) == 2
        assert all(e.event_type == "type_a" for e in results)

    def test_get_entries_filter_by_actor(self, audit_log):
        audit_log.log("ev", actor="user")
        audit_log.log("ev", actor="system")
        audit_log.log("ev", actor="user")

        results = audit_log.get_entries(actor="user")
        assert len(results) == 2

    def test_get_entries_limit(self, audit_log):
        for i in range(10):
            audit_log.log("test", {"i": i})
        results = audit_log.get_entries(limit=3)
        assert len(results) == 3

    def test_count(self, audit_log):
        assert audit_log.count() == 0
        audit_log.log("a", {})
        audit_log.log("b", {})
        audit_log.log("a", {})
        assert audit_log.count() == 3
        assert audit_log.count(event_type="a") == 2
        assert audit_log.count(event_type="b") == 1

    def test_capture_events_filter(self, tmp_path):
        """When capture_events is set, only those event types are recorded."""
        config = AuditConfig(
            db_path=str(tmp_path / "filter_audit.db"),
            capture_events=["trade_executed", "tool_called"],
        )
        log = ImmutableAuditLog(config=config)

        e1 = log.log("trade_executed", {"symbol": "600519"})
        e2 = log.log("ignored_event", {"data": "skip"})
        e3 = log.log("tool_called", {"tool": "get_quote"})

        assert e1.entry_id != ""  # Logged
        assert e2.entry_id == ""  # Filtered out
        assert e3.entry_id != ""  # Logged
        assert log.count() == 2

    def test_chinese_payload(self, audit_log):
        """Chinese characters in payload should be preserved."""
        entry = audit_log.log("test", {"消息": "茅台分析完成"})
        retrieved = audit_log.get_entry(entry.entry_id)
        assert retrieved.payload["消息"] == "茅台分析完成"

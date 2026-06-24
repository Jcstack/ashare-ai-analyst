"""Unit tests for ActionQueueService.

Tests CRUD operations, status transitions, expiry logic, and priority sorting.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.web.services.action_queue_service import ActionItem, ActionQueueService


@pytest.fixture()
def svc(tmp_path: Path) -> ActionQueueService:
    """Return an ActionQueueService backed by a temp database."""
    return ActionQueueService(db_path=tmp_path / "test.db")


# ------------------------------------------------------------------
# Creation
# ------------------------------------------------------------------


class TestCreateAction:
    def test_create_returns_action_item(self, svc: ActionQueueService):
        item = svc.create_action(
            symbol="600519",
            action="buy",
            urgency="today",
            confidence=0.75,
            execution_plan={"target_price": 1800, "stop_loss": 1750},
            thesis_id="thesis-001",
            session="late_session",
        )
        assert isinstance(item, ActionItem)
        assert item.symbol == "600519"
        assert item.action == "buy"
        assert item.urgency == "today"
        assert item.confidence == 0.75
        assert item.status == "pending"
        assert item.thesis_id == "thesis-001"
        assert item.session == "late_session"
        assert item.execution_plan == {"target_price": 1800, "stop_loss": 1750}
        assert item.confirmed_at is None
        assert item.executed_at is None

    def test_create_generates_unique_id(self, svc: ActionQueueService):
        a = svc.create_action("600519", "buy", "today", 0.7, {})
        b = svc.create_action("600519", "buy", "today", 0.7, {})
        assert a.id != b.id

    def test_create_defaults(self, svc: ActionQueueService):
        item = svc.create_action("000001", "sell", "immediate", 0.9, {})
        assert item.thesis_id is None
        assert item.session is None
        assert item.fill_price is None
        assert item.fill_shares is None


# ------------------------------------------------------------------
# Retrieval
# ------------------------------------------------------------------


class TestGetAction:
    def test_get_existing(self, svc: ActionQueueService):
        created = svc.create_action("600519", "buy", "today", 0.7, {})
        fetched = svc.get_action(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.symbol == "600519"

    def test_get_nonexistent_returns_none(self, svc: ActionQueueService):
        assert svc.get_action("nonexistent-id") is None


# ------------------------------------------------------------------
# List and sorting
# ------------------------------------------------------------------


class TestListActions:
    def test_list_pending_sorted_by_urgency_and_confidence(
        self, svc: ActionQueueService
    ):
        # Create actions with varying urgency and confidence
        svc.create_action("A", "buy", "observe", 0.9, {})
        svc.create_action("B", "buy", "immediate", 0.5, {})
        svc.create_action("C", "buy", "today", 0.8, {})
        svc.create_action("D", "buy", "immediate", 0.9, {})

        pending = svc.list_pending()
        symbols = [a.symbol for a in pending]
        # immediate first (D higher confidence, then B), then today (C), then observe (A)
        assert symbols == ["D", "B", "C", "A"]

    def test_list_all_actions(self, svc: ActionQueueService):
        svc.create_action("A", "buy", "today", 0.7, {})
        svc.create_action("B", "sell", "today", 0.8, {})
        all_actions = svc.list_actions()
        assert len(all_actions) == 2

    def test_list_filtered_by_status(self, svc: ActionQueueService):
        a = svc.create_action("A", "buy", "today", 0.7, {})
        svc.create_action("B", "sell", "today", 0.8, {})
        svc.confirm_action(a.id)

        confirmed = svc.list_actions(status="confirmed")
        assert len(confirmed) == 1
        assert confirmed[0].symbol == "A"

        pending = svc.list_actions(status="pending")
        assert len(pending) == 1
        assert pending[0].symbol == "B"


# ------------------------------------------------------------------
# Status transitions
# ------------------------------------------------------------------


class TestStatusTransitions:
    def test_pending_to_confirmed(self, svc: ActionQueueService):
        item = svc.create_action("600519", "buy", "today", 0.7, {})
        confirmed = svc.confirm_action(item.id)
        assert confirmed is not None
        assert confirmed.status == "confirmed"
        assert confirmed.confirmed_at is not None

    def test_confirmed_to_executed(self, svc: ActionQueueService):
        item = svc.create_action("600519", "buy", "today", 0.7, {})
        svc.confirm_action(item.id)
        executed = svc.record_fill(item.id, fill_price=1800.50, fill_shares=100)
        assert executed is not None
        assert executed.status == "executed"
        assert executed.fill_price == 1800.50
        assert executed.fill_shares == 100
        assert executed.executed_at is not None

    def test_pending_to_rejected(self, svc: ActionQueueService):
        item = svc.create_action("600519", "buy", "today", 0.7, {})
        rejected = svc.reject_action(item.id)
        assert rejected is not None
        assert rejected.status == "rejected"

    def test_confirmed_to_rejected(self, svc: ActionQueueService):
        item = svc.create_action("600519", "buy", "today", 0.7, {})
        svc.confirm_action(item.id)
        rejected = svc.reject_action(item.id)
        assert rejected is not None
        assert rejected.status == "rejected"

    def test_cannot_confirm_already_executed(self, svc: ActionQueueService):
        item = svc.create_action("600519", "buy", "today", 0.7, {})
        svc.confirm_action(item.id)
        svc.record_fill(item.id, 1800.0, 100)
        # Attempting to confirm an executed item should return it unchanged
        result = svc.confirm_action(item.id)
        assert result is not None
        assert result.status == "executed"

    def test_cannot_fill_pending_action(self, svc: ActionQueueService):
        item = svc.create_action("600519", "buy", "today", 0.7, {})
        # Cannot fill without confirming first
        result = svc.record_fill(item.id, 1800.0, 100)
        assert result is not None
        assert result.status == "pending"
        assert result.fill_price is None

    def test_confirm_nonexistent_returns_none(self, svc: ActionQueueService):
        assert svc.confirm_action("no-such-id") is None

    def test_reject_nonexistent_returns_none(self, svc: ActionQueueService):
        assert svc.reject_action("no-such-id") is None

    def test_fill_nonexistent_returns_none(self, svc: ActionQueueService):
        assert svc.record_fill("no-such-id", 100.0, 10) is None


# ------------------------------------------------------------------
# Expiry
# ------------------------------------------------------------------


class TestExpiry:
    def test_expire_old_actions(self, svc: ActionQueueService):
        # Create an action and manually backdate it
        item = svc.create_action("600519", "buy", "today", 0.7, {})
        old_time = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        with svc._connect() as conn:
            conn.execute(
                "UPDATE action_queue SET created_at = ? WHERE id = ?",
                (old_time, item.id),
            )

        # Also create a fresh action that should NOT be expired
        fresh = svc.create_action("000001", "sell", "today", 0.8, {})

        expired_count = svc.expire_old_actions()
        assert expired_count == 1

        old_item = svc.get_action(item.id)
        assert old_item is not None
        assert old_item.status == "expired"

        fresh_item = svc.get_action(fresh.id)
        assert fresh_item is not None
        assert fresh_item.status == "pending"

    def test_expire_does_not_touch_confirmed(self, svc: ActionQueueService):
        item = svc.create_action("600519", "buy", "today", 0.7, {})
        svc.confirm_action(item.id)
        # Backdate
        old_time = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        with svc._connect() as conn:
            conn.execute(
                "UPDATE action_queue SET created_at = ? WHERE id = ?",
                (old_time, item.id),
            )

        expired_count = svc.expire_old_actions()
        assert expired_count == 0

        result = svc.get_action(item.id)
        assert result is not None
        assert result.status == "confirmed"


# ------------------------------------------------------------------
# Stats
# ------------------------------------------------------------------


class TestStats:
    def test_empty_stats(self, svc: ActionQueueService):
        stats = svc.get_stats()
        assert stats["pending"] == 0
        assert stats["total"] == 0

    def test_stats_reflect_state(self, svc: ActionQueueService):
        a = svc.create_action("A", "buy", "today", 0.7, {})
        svc.create_action("B", "sell", "today", 0.8, {})
        c = svc.create_action("C", "hold", "observe", 0.5, {})

        svc.confirm_action(a.id)
        svc.reject_action(c.id)

        stats = svc.get_stats()
        assert stats["pending"] == 1
        assert stats["confirmed"] == 1
        assert stats["rejected"] == 1
        assert stats["total"] == 3


# ------------------------------------------------------------------
# Serialization
# ------------------------------------------------------------------


class TestSerialization:
    def test_to_dict(self, svc: ActionQueueService):
        item = svc.create_action(
            "600519", "buy", "today", 0.75, {"key": "value"}, thesis_id="t1"
        )
        d = item.to_dict()
        assert isinstance(d, dict)
        assert d["symbol"] == "600519"
        assert d["action"] == "buy"
        assert d["confidence"] == 0.75
        assert d["execution_plan"] == {"key": "value"}
        assert isinstance(d["created_at"], str)  # ISO format string

"""Tests for KillSwitch — Redis-backed emergency trading halt.

Part of v19.0 Production Hardening — Phase 0.1.
"""

from __future__ import annotations

import pytest

from src.trading.kill_switch import (
    KillSwitch,
    KillSwitchStatus,
    _ACTIVATED_AT_KEY,
    _ACTIVATED_BY_KEY,
    _REASON_KEY,
    _REDIS_KEY,
)


# ---------------------------------------------------------------------------
# Fake Redis helpers
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal Redis stub using an in-memory dict."""

    def __init__(self):
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value

    def delete(self, *keys: str) -> None:
        for k in keys:
            self._data.pop(k, None)

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops: list[tuple] = []

    def set(self, key: str, value: str) -> FakePipeline:
        self._ops.append(("set", key, value))
        return self

    def execute(self) -> None:
        for op in self._ops:
            if op[0] == "set":
                self._redis.set(op[1], op[2])
        self._ops.clear()


class BrokenRedis:
    """Redis stub that raises on every operation."""

    def get(self, key: str):
        raise ConnectionError("Redis unavailable")

    def set(self, key: str, value: str, ex: int | None = None):
        raise ConnectionError("Redis unavailable")

    def delete(self, *keys: str):
        raise ConnectionError("Redis unavailable")

    def pipeline(self):
        raise ConnectionError("Redis unavailable")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def ks(fake_redis: FakeRedis) -> KillSwitch:
    return KillSwitch(redis_client=fake_redis)


# ---------------------------------------------------------------------------
# Tests — is_active
# ---------------------------------------------------------------------------


class TestIsActive:
    def test_returns_false_when_redis_is_none(self):
        ks = KillSwitch(redis_client=None)
        assert ks.is_active() is False

    def test_returns_false_when_key_not_set(self, ks: KillSwitch):
        assert ks.is_active() is False

    def test_returns_true_when_key_is_set(self, fake_redis: FakeRedis, ks: KillSwitch):
        fake_redis.set(_REDIS_KEY, "1")
        assert ks.is_active() is True

    def test_returns_false_when_key_is_not_one(
        self, fake_redis: FakeRedis, ks: KillSwitch
    ):
        fake_redis.set(_REDIS_KEY, "0")
        assert ks.is_active() is False

    def test_fail_open_on_redis_exception(self):
        """Redis errors should fail-open (return False, not crash)."""
        ks = KillSwitch(redis_client=BrokenRedis())
        assert ks.is_active() is False


# ---------------------------------------------------------------------------
# Tests — activate
# ---------------------------------------------------------------------------


class TestActivate:
    def test_sets_key_reason_timestamp_and_actor(self, fake_redis: FakeRedis):
        ks = KillSwitch(redis_client=fake_redis)
        ks.activate(reason="market crash", activated_by="operator")

        assert fake_redis.get(_REDIS_KEY) == "1"
        assert fake_redis.get(_REASON_KEY) == "market crash"
        assert fake_redis.get(_ACTIVATED_BY_KEY) == "operator"
        # Timestamp should be an ISO-ish string
        ts = fake_redis.get(_ACTIVATED_AT_KEY)
        assert ts is not None
        assert "T" in ts

    def test_activate_with_default_actor(self, fake_redis: FakeRedis):
        ks = KillSwitch(redis_client=fake_redis)
        ks.activate(reason="test")
        assert fake_redis.get(_ACTIVATED_BY_KEY) == "system"

    def test_activate_noop_when_no_redis(self):
        ks = KillSwitch(redis_client=None)
        # Should not raise
        ks.activate(reason="no redis")

    def test_activate_handles_redis_error(self):
        ks = KillSwitch(redis_client=BrokenRedis())
        # Should not raise — logs error internally
        ks.activate(reason="broken")


# ---------------------------------------------------------------------------
# Tests — deactivate
# ---------------------------------------------------------------------------


class TestDeactivate:
    def test_removes_all_keys(self, fake_redis: FakeRedis):
        ks = KillSwitch(redis_client=fake_redis)
        ks.activate(reason="test", activated_by="op")
        assert ks.is_active() is True

        ks.deactivate()
        assert ks.is_active() is False
        assert fake_redis.get(_REDIS_KEY) is None
        assert fake_redis.get(_REASON_KEY) is None
        assert fake_redis.get(_ACTIVATED_AT_KEY) is None
        assert fake_redis.get(_ACTIVATED_BY_KEY) is None

    def test_deactivate_noop_when_no_redis(self):
        ks = KillSwitch(redis_client=None)
        ks.deactivate()  # Should not raise

    def test_deactivate_handles_redis_error(self):
        ks = KillSwitch(redis_client=BrokenRedis())
        ks.deactivate()  # Should not raise


# ---------------------------------------------------------------------------
# Tests — status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_returns_inactive_when_no_redis(self):
        ks = KillSwitch(redis_client=None)
        st = ks.status()
        assert isinstance(st, KillSwitchStatus)
        assert st.active is False
        assert st.reason == ""

    def test_returns_active_status_with_details(self, fake_redis: FakeRedis):
        ks = KillSwitch(redis_client=fake_redis)
        ks.activate(reason="testing", activated_by="admin")

        st = ks.status()
        assert st.active is True
        assert st.reason == "testing"
        assert st.activated_by == "admin"
        assert st.activated_at != ""

    def test_returns_inactive_status_when_not_set(self, fake_redis: FakeRedis):
        ks = KillSwitch(redis_client=fake_redis)
        st = ks.status()
        assert st.active is False
        assert st.reason == ""
        assert st.activated_by == ""

    def test_returns_inactive_on_redis_exception(self):
        ks = KillSwitch(redis_client=BrokenRedis())
        st = ks.status()
        assert st.active is False

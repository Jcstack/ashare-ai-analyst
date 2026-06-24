"""Tests for BrokerHealthMonitor — periodic QMT connectivity check.

Part of v19.0 Production Hardening — Phase 0.2.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import MagicMock

from src.trading.broker_health import BrokerHealthMonitor
from src.web.services.broker_interface import Balance


# ---------------------------------------------------------------------------
# Fake Redis
# ---------------------------------------------------------------------------


class FakeRedis:
    def __init__(self):
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value

    def delete(self, *keys: str) -> None:
        for k in keys:
            self._data.pop(k, None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_broker() -> MagicMock:
    broker = MagicMock()
    broker.get_balance.return_value = Balance(
        available_cash=100_000, total_assets=200_000
    )
    return broker


@pytest.fixture
def mock_kill_switch() -> MagicMock:
    return MagicMock()


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def monitor(
    mock_broker: MagicMock,
    mock_kill_switch: MagicMock,
    fake_redis: FakeRedis,
) -> BrokerHealthMonitor:
    return BrokerHealthMonitor(
        broker=mock_broker,
        kill_switch=mock_kill_switch,
        redis_client=fake_redis,
        max_failures=3,
    )


# ---------------------------------------------------------------------------
# Tests — healthy check resets failure count
# ---------------------------------------------------------------------------


class TestHealthyCheck:
    def test_healthy_check_returns_healthy(self, monitor: BrokerHealthMonitor):
        result = monitor.check()
        assert result["healthy"] is True
        assert result["consecutive_failures"] == 0
        assert result["total_assets"] == 200_000
        assert result["available_cash"] == 100_000

    def test_healthy_check_resets_failure_count(
        self,
        mock_broker: MagicMock,
        monitor: BrokerHealthMonitor,
    ):
        # Simulate 2 failures first
        mock_broker.get_balance.side_effect = ConnectionError("down")
        monitor.check()
        monitor.check()
        assert monitor._consecutive_failures == 2

        # Recover — success should reset counter
        mock_broker.get_balance.side_effect = None
        mock_broker.get_balance.return_value = Balance(
            available_cash=50_000, total_assets=100_000
        )
        result = monitor.check()
        assert result["healthy"] is True
        assert result["consecutive_failures"] == 0
        assert monitor._consecutive_failures == 0


# ---------------------------------------------------------------------------
# Tests — consecutive failures trigger kill switch
# ---------------------------------------------------------------------------


class TestKillSwitchTrigger:
    def test_three_failures_triggers_kill_switch(
        self,
        mock_broker: MagicMock,
        mock_kill_switch: MagicMock,
        monitor: BrokerHealthMonitor,
    ):
        mock_broker.get_balance.side_effect = ConnectionError("down")

        # First two failures should NOT trigger
        monitor.check()
        monitor.check()
        mock_kill_switch.activate.assert_not_called()

        # Third failure should trigger
        monitor.check()
        mock_kill_switch.activate.assert_called_once()
        call_kwargs = mock_kill_switch.activate.call_args
        assert "3" in call_kwargs.kwargs.get("reason", call_kwargs[1].get("reason", ""))
        assert (
            call_kwargs.kwargs.get(
                "activated_by", call_kwargs[1].get("activated_by", "")
            )
            == "broker_health"
        )

    def test_failure_count_tracked_correctly(
        self,
        mock_broker: MagicMock,
        monitor: BrokerHealthMonitor,
    ):
        mock_broker.get_balance.side_effect = RuntimeError("timeout")

        for i in range(1, 4):
            result = monitor.check()
            assert result["healthy"] is False
            assert result["consecutive_failures"] == i

    def test_two_failures_does_not_trigger(
        self,
        mock_broker: MagicMock,
        mock_kill_switch: MagicMock,
        monitor: BrokerHealthMonitor,
    ):
        mock_broker.get_balance.side_effect = ConnectionError("down")
        monitor.check()
        monitor.check()
        mock_kill_switch.activate.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — status persistence to Redis
# ---------------------------------------------------------------------------


class TestStatusPersistence:
    def test_healthy_status_persisted(
        self, fake_redis: FakeRedis, monitor: BrokerHealthMonitor
    ):
        monitor.check()
        raw = fake_redis.get(BrokerHealthMonitor.REDIS_KEY)
        assert raw is not None
        data = json.loads(raw)
        assert data["healthy"] is True
        assert "checked_at" in data

    def test_unhealthy_status_persisted(
        self,
        mock_broker: MagicMock,
        fake_redis: FakeRedis,
        monitor: BrokerHealthMonitor,
    ):
        mock_broker.get_balance.side_effect = RuntimeError("fail")
        monitor.check()
        raw = fake_redis.get(BrokerHealthMonitor.REDIS_KEY)
        data = json.loads(raw)
        assert data["healthy"] is False
        assert "error" in data

    def test_no_redis_does_not_crash(
        self,
        mock_broker: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        monitor = BrokerHealthMonitor(
            broker=mock_broker,
            kill_switch=mock_kill_switch,
            redis_client=None,
        )
        result = monitor.check()
        assert result["healthy"] is True


# ---------------------------------------------------------------------------
# Tests — get_last_status
# ---------------------------------------------------------------------------


class TestGetLastStatus:
    def test_reads_from_redis(
        self, fake_redis: FakeRedis, monitor: BrokerHealthMonitor
    ):
        monitor.check()
        status = monitor.get_last_status()
        assert status is not None
        assert status["healthy"] is True

    def test_returns_none_when_no_data(self, monitor: BrokerHealthMonitor):
        # No check performed yet
        status = monitor.get_last_status()
        assert status is None

    def test_returns_none_when_no_redis(
        self,
        mock_broker: MagicMock,
        mock_kill_switch: MagicMock,
    ):
        monitor = BrokerHealthMonitor(
            broker=mock_broker,
            kill_switch=mock_kill_switch,
            redis_client=None,
        )
        assert monitor.get_last_status() is None

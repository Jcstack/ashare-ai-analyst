"""Tests for the Redis Streams-based event bus."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.event_bus.bus import EventBus, _resolve_redis_url


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_redis():
    """Return a MagicMock pretending to be a redis.Redis client."""
    r = MagicMock()
    r.xadd.return_value = "1678886400000-0"
    r.ping.return_value = True
    return r


@pytest.fixture()
def bus(mock_redis, tmp_path):
    """Return an EventBus with a mock Redis and minimal config."""
    config = {
        "redis_url": "redis://localhost:6379/0",
        "streams": {
            "market": "events:market",
            "news": "events:news",
            "signal": "events:signal",
        },
        "batch_size": 5,
        "block_ms": 1000,
        "max_stream_length": 100,
    }
    with patch("src.event_bus.bus.load_config", return_value=config):
        return EventBus(redis_client=mock_redis)


# ---------------------------------------------------------------------------
# Tests: _resolve_redis_url
# ---------------------------------------------------------------------------


class TestResolveRedisUrl:
    def test_plain_url(self):
        assert (
            _resolve_redis_url({"redis_url": "redis://host:1234/5"})
            == "redis://host:1234/5"
        )

    def test_env_var_with_default(self, monkeypatch):
        monkeypatch.delenv("MY_REDIS", raising=False)
        url = _resolve_redis_url({"redis_url": "${MY_REDIS:-redis://fallback:6379/0}"})
        assert url == "redis://fallback:6379/0"

    def test_env_var_set(self, monkeypatch):
        monkeypatch.setenv("MY_REDIS", "redis://real:6379/2")
        url = _resolve_redis_url({"redis_url": "${MY_REDIS:-redis://fallback:6379/0}"})
        assert url == "redis://real:6379/2"

    def test_missing_key_defaults(self):
        assert _resolve_redis_url({}) == "redis://localhost:6379/0"


# ---------------------------------------------------------------------------
# Tests: EventBus.publish
# ---------------------------------------------------------------------------


class TestPublish:
    def test_publish_calls_xadd(self, bus, mock_redis):
        entry_id = bus.publish("events:market", "price_spike", {"symbol": "000001"})
        assert entry_id == "1678886400000-0"
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "events:market"
        entry = call_args[0][1]
        assert entry["type"] == "price_spike"
        assert json.loads(entry["data"]) == {"symbol": "000001"}

    def test_publish_uses_maxlen(self, bus, mock_redis):
        bus.publish("events:market", "test", {}, maxlen=50)
        call_kwargs = mock_redis.xadd.call_args[1]
        assert call_kwargs["maxlen"] == 50


# ---------------------------------------------------------------------------
# Tests: EventBus.ensure_consumer_group
# ---------------------------------------------------------------------------


class TestConsumerGroup:
    def test_create_new_group(self, bus, mock_redis):
        result = bus.ensure_consumer_group("events:market", "my_group")
        assert result is True
        mock_redis.xgroup_create.assert_called_once_with(
            "events:market",
            "my_group",
            id="0",
            mkstream=True,
        )

    def test_existing_group_returns_false(self, bus, mock_redis):
        import redis as _redis

        mock_redis.xgroup_create.side_effect = _redis.ResponseError("BUSYGROUP")
        result = bus.ensure_consumer_group("events:market", "my_group")
        assert result is False

    def test_other_errors_propagate(self, bus, mock_redis):
        import redis as _redis

        mock_redis.xgroup_create.side_effect = _redis.ResponseError("WRONGTYPE")
        with pytest.raises(_redis.ResponseError, match="WRONGTYPE"):
            bus.ensure_consumer_group("events:market", "my_group")


# ---------------------------------------------------------------------------
# Tests: EventBus.subscribe
# ---------------------------------------------------------------------------


class TestSubscribe:
    def test_subscribe_processes_events(self, bus, mock_redis):
        # Simulate one batch of results then empty (to stop)
        raw_entry = {
            "type": "price_spike",
            "ts": "1678886400.0",
            "data": '{"symbol": "000001"}',
        }
        mock_redis.xreadgroup.side_effect = [
            [("events:market", [("1-0", raw_entry)])],
            [],  # empty batch for second iteration
        ]

        received = []

        def handler(stream, entry_id, data):
            received.append((stream, entry_id, data))

        total = bus.subscribe(
            streams=["events:market"],
            consumer_group="test_group",
            consumer_name="worker-1",
            callback=handler,
            max_iterations=2,
        )

        assert total == 1
        assert len(received) == 1
        assert received[0][0] == "events:market"
        assert received[0][1] == "1-0"
        assert received[0][2]["type"] == "price_spike"
        assert received[0][2]["data"]["symbol"] == "000001"

        # Verify ACK was called
        mock_redis.xack.assert_called_once_with("events:market", "test_group", "1-0")

    def test_subscribe_handles_callback_error(self, bus, mock_redis):
        raw_entry = {
            "type": "test",
            "ts": "1.0",
            "data": "{}",
        }
        mock_redis.xreadgroup.side_effect = [
            [("events:market", [("1-0", raw_entry)])],
        ]

        def bad_handler(stream, entry_id, data):
            raise ValueError("oops")

        total = bus.subscribe(
            streams=["events:market"],
            consumer_group="g",
            consumer_name="w",
            callback=bad_handler,
            max_iterations=1,
        )

        assert total == 0  # failed events are not counted
        mock_redis.xack.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: EventBus.health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_healthy(self, bus, mock_redis):
        mock_redis.xinfo_stream.return_value = {
            "length": 42,
            "first-entry": ("1-0", {}),
            "last-entry": ("2-0", {}),
        }
        result = bus.health_check()
        assert result["healthy"] is True
        assert result["streams"]["market"]["length"] == 42

    def test_unhealthy_connection(self, bus, mock_redis):
        import redis as _redis

        mock_redis.ping.side_effect = _redis.ConnectionError()
        result = bus.health_check()
        assert result["healthy"] is False

    def test_stream_not_created(self, bus, mock_redis):
        import redis as _redis

        mock_redis.xinfo_stream.side_effect = _redis.ResponseError("no such key")
        result = bus.health_check()
        assert result["healthy"] is True
        assert result["streams"]["market"]["status"] == "not_created"


# ---------------------------------------------------------------------------
# Tests: Deserialization
# ---------------------------------------------------------------------------


class TestDeserialize:
    def test_normal(self):
        raw = {"type": "test", "ts": "100.5", "data": '{"a": 1}'}
        result = EventBus._deserialize(raw)
        assert result["type"] == "test"
        assert result["ts"] == 100.5
        assert result["data"] == {"a": 1}

    def test_bad_json(self):
        raw = {"type": "test", "ts": "0", "data": "not json"}
        result = EventBus._deserialize(raw)
        assert result["data"] == {"raw": "not json"}

    def test_missing_fields(self):
        result = EventBus._deserialize({})
        assert result["type"] == "unknown"
        assert result["ts"] == 0.0

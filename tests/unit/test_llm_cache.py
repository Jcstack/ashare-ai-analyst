"""Tests for src.llm.cache.LLMResultCache (L1/L2 two-level cache)."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from src.llm.cache import LLMResultCache, _KEY_PREFIX


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_redis():
    """Return a mock Redis client with get/set/ttl."""
    r = MagicMock()
    r.get.return_value = None
    r.set.return_value = True
    return r


@pytest.fixture()
def cache_no_redis():
    """LLMResultCache with L2 disabled (redis=None)."""
    return LLMResultCache(redis_client=None)


@pytest.fixture()
def cache_with_redis(mock_redis):
    """LLMResultCache with a mock Redis backend."""
    return LLMResultCache(redis_client=mock_redis)


# ── L1-only tests ──────────────────────────────────────────────────────


class TestL1Only:
    def test_miss_returns_none(self, cache_no_redis):
        assert cache_no_redis.get("nonexistent", ttl=60) is None

    def test_set_then_get(self, cache_no_redis):
        data = {"signal": "bullish", "confidence": 0.8}
        cache_no_redis.set("test_key", data, ttl_seconds=300)
        result = cache_no_redis.get("test_key", ttl=300)
        assert result == data

    def test_ttl_expiry(self, cache_no_redis):
        data = {"signal": "bearish"}
        cache_no_redis.set("expire_key", data, ttl_seconds=1)
        # Manually expire L1
        cache_no_redis._l1["expire_key"] = (time.time() - 10, data)
        assert cache_no_redis.get("expire_key", ttl=5) is None

    def test_multiple_keys(self, cache_no_redis):
        cache_no_redis.set("a", {"v": 1}, ttl_seconds=60)
        cache_no_redis.set("b", {"v": 2}, ttl_seconds=60)
        assert cache_no_redis.get("a", ttl=60) == {"v": 1}
        assert cache_no_redis.get("b", ttl=60) == {"v": 2}

    def test_overwrite(self, cache_no_redis):
        cache_no_redis.set("k", {"v": 1}, ttl_seconds=60)
        cache_no_redis.set("k", {"v": 2}, ttl_seconds=60)
        assert cache_no_redis.get("k", ttl=60) == {"v": 2}


# ── L2 (Redis) tests ──────────────────────────────────────────────────


class TestL2Redis:
    def test_set_writes_to_redis(self, cache_with_redis, mock_redis):
        data = {"trend": "up"}
        cache_with_redis.set("my_key", data, ttl_seconds=600)
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == f"{_KEY_PREFIX}my_key"
        payload = json.loads(call_args[0][1])
        assert payload["data"] == data
        assert "_ts" in payload
        assert call_args[1]["ex"] == 600

    def test_get_l1_miss_l2_hit_backfills(self, cache_with_redis, mock_redis):
        data = {"status": "ok", "confidence": 0.9}
        now = time.time()
        payload = json.dumps({"_ts": now, "data": data})
        mock_redis.get.return_value = payload

        result = cache_with_redis.get("key_from_l2", ttl=300)
        assert result == data
        # L1 should now be populated
        assert "key_from_l2" in cache_with_redis._l1
        l1_data = cache_with_redis._l1["key_from_l2"][1]
        assert l1_data == data

    def test_get_l2_expired(self, cache_with_redis, mock_redis):
        old_ts = time.time() - 500
        payload = json.dumps({"_ts": old_ts, "data": {"stale": True}})
        mock_redis.get.return_value = payload

        result = cache_with_redis.get("stale_key", ttl=300)
        assert result is None

    def test_get_l1_hit_skips_l2(self, cache_with_redis, mock_redis):
        data = {"cached": True}
        cache_with_redis._l1["fast_key"] = (time.time(), data)

        result = cache_with_redis.get("fast_key", ttl=300)
        assert result == data
        mock_redis.get.assert_not_called()

    def test_key_prefix_correct(self, cache_with_redis, mock_redis):
        cache_with_redis.set("unified_600123", {"v": 1}, ttl_seconds=1800)
        key_arg = mock_redis.set.call_args[0][0]
        assert key_arg == "llm:result:unified_600123"


# ── Degradation tests (Redis down) ────────────────────────────────────


class TestDegradation:
    def test_redis_get_error_returns_none(self, cache_with_redis, mock_redis):
        mock_redis.get.side_effect = ConnectionError("Redis down")
        assert cache_with_redis.get("fail_key", ttl=300) is None

    def test_redis_set_error_silent(self, cache_with_redis, mock_redis):
        mock_redis.set.side_effect = ConnectionError("Redis down")
        # Should not raise
        cache_with_redis.set("fail_key", {"v": 1}, ttl_seconds=300)
        # L1 should still be written
        assert "fail_key" in cache_with_redis._l1

    def test_redis_none_pure_memory(self, cache_no_redis):
        """redis_client=None → pure in-memory, same as pre-cache behaviour."""
        cache_no_redis.set("k", {"v": 42}, ttl_seconds=600)
        assert cache_no_redis.get("k", ttl=600) == {"v": 42}

    def test_l2_miss_returns_none(self, cache_with_redis, mock_redis):
        mock_redis.get.return_value = None
        assert cache_with_redis.get("miss", ttl=300) is None

    def test_l2_invalid_json(self, cache_with_redis, mock_redis):
        mock_redis.get.return_value = "not valid json{{"
        assert cache_with_redis.get("bad_json", ttl=300) is None

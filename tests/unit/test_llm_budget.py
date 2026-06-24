"""Unit tests for LLMBudgetTracker."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.llm.llm_budget import LLMBudgetTracker


class TestCanCallNoRedis:
    def test_always_allows_without_redis(self):
        tracker = LLMBudgetTracker(redis_client=None, config={})
        assert tracker.can_call("gemini_web") is True
        assert tracker.can_call("google") is True

    def test_allows_with_empty_config(self):
        tracker = LLMBudgetTracker(redis_client=None)
        assert tracker.can_call("gemini_web") is True


class TestDailyExceeded:
    def test_blocks_when_daily_exceeded(self):
        redis = MagicMock()
        redis.get.return_value = b"500"

        tracker = LLMBudgetTracker(
            redis_client=redis,
            config={"daily_limits": {"gemini_web": 500}},
        )
        assert tracker.can_call("gemini_web") is False

    def test_allows_when_under_limit(self):
        redis = MagicMock()
        redis.get.return_value = b"10"

        tracker = LLMBudgetTracker(
            redis_client=redis,
            config={"daily_limits": {"gemini_web": 500}},
        )
        assert tracker.can_call("gemini_web") is True

    def test_allows_unconfigured_provider(self):
        redis = MagicMock()
        redis.get.return_value = None

        tracker = LLMBudgetTracker(
            redis_client=redis,
            config={"daily_limits": {"gemini_web": 500}},
        )
        # "google" has no daily limit configured
        assert tracker.can_call("google") is True


class TestMinuteExceeded:
    def test_blocks_when_minute_exceeded(self):
        redis = MagicMock()
        # Only minute check fires (no daily_limits configured for google)
        redis.get.return_value = b"30"

        tracker = LLMBudgetTracker(
            redis_client=redis,
            config={"per_minute_limits": {"google": 30}},
        )
        assert tracker.can_call("google") is False


class TestModelDailyLimit:
    def test_blocks_when_model_limit_exceeded(self):
        redis = MagicMock()
        # Only model check fires (no daily/minute limits for google)
        redis.get.return_value = b"250"

        tracker = LLMBudgetTracker(
            redis_client=redis,
            config={"model_daily_limits": {"gemini-2.5-pro": 250}},
        )
        assert tracker.can_call("google", model="gemini-2.5-pro") is False

    def test_allows_when_model_under_limit(self):
        redis = MagicMock()
        redis.get.return_value = b"10"

        tracker = LLMBudgetTracker(
            redis_client=redis,
            config={"model_daily_limits": {"gemini-2.5-pro": 250}},
        )
        assert tracker.can_call("google", model="gemini-2.5-pro") is True


class TestRecordIncrements:
    def test_record_call_increments_counters(self):
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe

        tracker = LLMBudgetTracker(redis_client=redis)
        tracker.record_call("gemini_web", model="gemini-2.5-pro")

        # Should have called incr at least for daily + minute + model
        assert pipe.incr.call_count == 3
        assert pipe.expire.call_count == 3
        pipe.execute.assert_called_once()

    def test_record_without_model_has_two_counters(self):
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe

        tracker = LLMBudgetTracker(redis_client=redis)
        tracker.record_call("gemini_web")

        # Daily + minute only (no model)
        assert pipe.incr.call_count == 2
        pipe.execute.assert_called_once()

    def test_record_noop_without_redis(self):
        tracker = LLMBudgetTracker(redis_client=None)
        tracker.record_call("gemini_web")  # should not raise


class TestGetRemaining:
    def test_returns_none_without_redis(self):
        tracker = LLMBudgetTracker(redis_client=None)
        result = tracker.get_remaining("gemini_web")
        assert result == {"daily": None, "per_minute": None}

    def test_returns_remaining_counts(self):
        redis = MagicMock()
        redis.get.side_effect = [b"100", b"5"]

        tracker = LLMBudgetTracker(
            redis_client=redis,
            config={
                "daily_limits": {"gemini_web": 500},
                "per_minute_limits": {"gemini_web": 10},
            },
        )
        result = tracker.get_remaining("gemini_web")
        assert result["daily"] == 400
        assert result["per_minute"] == 5


class TestRedisFailureGraceful:
    def test_can_call_allows_on_redis_error(self):
        redis = MagicMock()
        redis.get.side_effect = ConnectionError("Redis down")

        tracker = LLMBudgetTracker(
            redis_client=redis,
            config={"daily_limits": {"gemini_web": 500}},
        )
        assert tracker.can_call("gemini_web") is True

    def test_record_does_not_raise_on_redis_error(self):
        redis = MagicMock()
        redis.pipeline.side_effect = ConnectionError("Redis down")

        tracker = LLMBudgetTracker(redis_client=redis)
        tracker.record_call("gemini_web")  # should not raise

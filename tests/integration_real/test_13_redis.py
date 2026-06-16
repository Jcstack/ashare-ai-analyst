"""Redis connectivity and performance tests.

All tests require a running Redis instance on localhost:6379.
No mocks — real Redis commands.
"""

from __future__ import annotations

import time

import pytest

from tests.integration_real.conftest import (
    TestResult,
    measure_time,
    requires_redis,
)

pytestmark = [pytest.mark.integration_real, requires_redis]


class TestRedisConnectivity:
    """Verify Redis is reachable and operational."""

    def _get_redis(self):
        """Create a Redis client for localhost:6379."""
        import redis

        return redis.Redis(
            host="localhost", port=6379, socket_timeout=5, decode_responses=True
        )

    def test_ping(self, result_collector):
        """PING Redis and assert PONG response."""
        test_name = "redis_ping"
        try:
            r = self._get_redis()
            with measure_time() as timing:
                result = r.ping()

            assert result is True, f"Redis PING returned {result}"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="stability",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="stability",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_set_get_roundtrip(self, result_collector):
        """SET a key with TTL, GET it back, verify, then DEL."""
        test_name = "redis_set_get_roundtrip"
        test_key = "integration_test:roundtrip"
        test_value = "hello_integration_test_2026"
        try:
            r = self._get_redis()
            with measure_time() as timing:
                r.set(test_key, test_value, ex=10)
                retrieved = r.get(test_key)

            assert retrieved == test_value, (
                f"Value mismatch: expected {test_value!r}, got {retrieved!r}"
            )

            ttl = r.ttl(test_key)
            assert ttl > 0, f"TTL should be positive, got {ttl}"

            r.delete(test_key)
            after_del = r.get(test_key)
            assert after_del is None, "Key still exists after DELETE"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="stability",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"ttl_remaining": ttl},
                )
            )
        except Exception as exc:
            # Clean up on failure
            try:
                self._get_redis().delete(test_key)
            except Exception:
                pass
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="stability",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_pubsub(self, result_collector):
        """Subscribe to a channel, publish a message, receive within 2s."""
        test_name = "redis_pubsub"
        channel = "integration_test:pubsub_channel"
        message = "test_message_pubsub_2026"
        try:
            r = self._get_redis()
            pubsub = r.pubsub()
            pubsub.subscribe(channel)

            # Consume the subscription confirmation message
            pubsub.get_message(timeout=2)  # consume subscription confirmation

            with measure_time() as timing:
                r.publish(channel, message)

                received = None
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    msg = pubsub.get_message(timeout=0.1)
                    if msg and msg["type"] == "message":
                        received = msg["data"]
                        break

            pubsub.unsubscribe(channel)
            pubsub.close()

            assert received == message, f"Expected {message!r}, received {received!r}"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="stability",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="stability",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_info_stats(self, result_collector):
        """Retrieve Redis INFO and record memory / client statistics."""
        test_name = "redis_info_stats"
        try:
            r = self._get_redis()
            with measure_time() as timing:
                info = r.info()

            used_memory = info.get("used_memory_human", "unknown")
            connected_clients = info.get("connected_clients", -1)
            redis_version = info.get("redis_version", "unknown")

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="stability",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "used_memory_human": used_memory,
                        "connected_clients": connected_clients,
                        "redis_version": redis_version,
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="stability",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_latency(self, result_collector):
        """Measure average latency over 10 SET/GET cycles."""
        test_name = "redis_latency_10_cycles"
        latencies: list[float] = []
        base_key = "integration_test:latency"
        try:
            r = self._get_redis()

            for i in range(10):
                key = f"{base_key}:{i}"
                value = f"value_{i}"
                start = time.perf_counter()
                r.set(key, value, ex=5)
                retrieved = r.get(key)
                elapsed_ms = (time.perf_counter() - start) * 1000
                latencies.append(elapsed_ms)
                assert retrieved == value

            # Cleanup
            for i in range(10):
                r.delete(f"{base_key}:{i}")

            avg_ms = sum(latencies) / len(latencies)
            max_ms = max(latencies)
            min_ms = min(latencies)

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="stability",
                    status="pass",
                    latency_ms=avg_ms,
                    details={
                        "avg_ms": round(avg_ms, 2),
                        "min_ms": round(min_ms, 2),
                        "max_ms": round(max_ms, 2),
                        "cycles": 10,
                    },
                )
            )
        except Exception as exc:
            # Cleanup on failure
            try:
                r_cleanup = self._get_redis()
                for i in range(10):
                    r_cleanup.delete(f"{base_key}:{i}")
            except Exception:
                pass
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="stability",
                    status="fail",
                    error=str(exc),
                    details={
                        "latencies_collected": [round(lat, 2) for lat in latencies]
                    },
                )
            )

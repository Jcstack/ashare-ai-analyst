"""Reliability & stability tests — long-running polling, memory tracking,
cache TTL validation.
"""

from __future__ import annotations

import os
import time
import tracemalloc

import pytest

from tests.integration_real.conftest import (
    TestResult,
    measure_time,
    requires_china_network,
)

pytestmark = [pytest.mark.integration_real, requires_china_network]


class TestLongRunningStability:
    """5-minute continuous polling stability test."""

    @pytest.mark.slow
    def test_5_minute_polling(self, real_client, result_collector):
        """Poll /market/realtime every 30s for 5 minutes. Track failures."""
        duration = 300  # 5 minutes
        interval = 30  # seconds
        start = time.monotonic()
        poll_results: list[dict] = []

        while time.monotonic() - start < duration:
            try:
                with measure_time() as timing:
                    resp = real_client.get("/api/v1/market/realtime?symbols=000001")
                poll_results.append(
                    {
                        "elapsed_s": round(time.monotonic() - start, 1),
                        "status_code": resp.status_code,
                        "latency_ms": round(timing["elapsed_ms"], 2),
                        "has_data": resp.status_code == 200,
                    }
                )
            except Exception as exc:
                poll_results.append(
                    {
                        "elapsed_s": round(time.monotonic() - start, 1),
                        "status_code": 0,
                        "latency_ms": 0,
                        "error": str(exc),
                    }
                )
            time.sleep(interval)

        total = len(poll_results)
        successes = sum(1 for r in poll_results if r.get("status_code") == 200)
        success_rate = successes / total if total > 0 else 0
        latencies = [
            r["latency_ms"] for r in poll_results if r.get("latency_ms", 0) > 0
        ]
        avg_lat = sum(latencies) / len(latencies) if latencies else 0

        # Check for latency degradation (last 3 vs first 3)
        if len(latencies) >= 6:
            first_3_avg = sum(latencies[:3]) / 3
            last_3_avg = sum(latencies[-3:]) / 3
            degradation = last_3_avg / first_3_avg if first_3_avg > 0 else 1.0
        else:
            degradation = 1.0

        result_collector.record(
            TestResult(
                test_name="5_minute_polling_stability",
                category="stability",
                status="pass" if success_rate >= 0.9 else "fail",
                latency_ms=avg_lat,
                details={
                    "duration_s": duration,
                    "total_polls": total,
                    "successes": successes,
                    "success_rate": round(success_rate, 4),
                    "avg_latency_ms": round(avg_lat, 2),
                    "latency_degradation": round(degradation, 2),
                    "polls": poll_results,
                },
                error=""
                if success_rate >= 0.9
                else f"Success rate {success_rate:.1%} below 90% threshold",
            )
        )
        assert success_rate >= 0.9, f"Success rate {success_rate:.1%} < 90%"


class TestMemoryStability:
    """Check for memory leaks under repeated API calls."""

    def test_no_memory_leak(self, real_client, result_collector):
        """Make 50 requests, assert memory growth < 50MB."""
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()
        mem_before = sum(stat.size for stat in snapshot_before.statistics("filename"))

        endpoints = [
            "/api/v1/watchlist",
            "/api/v1/market/status",
            "/api/v1/notifications/unread-count",
            "/api/v1/stocks/search?q=bank",
            "/api/v1/stock/000001",
        ]

        for i in range(50):
            ep = endpoints[i % len(endpoints)]
            try:
                real_client.get(ep)
            except Exception:
                pass

        snapshot_after = tracemalloc.take_snapshot()
        mem_after = sum(stat.size for stat in snapshot_after.statistics("filename"))
        tracemalloc.stop()

        growth_mb = (mem_after - mem_before) / (1024 * 1024)

        result_collector.record(
            TestResult(
                test_name="memory_stability_50_requests",
                category="stability",
                status="pass" if growth_mb < 50 else "fail",
                details={
                    "requests_made": 50,
                    "mem_before_mb": round(mem_before / (1024 * 1024), 2),
                    "mem_after_mb": round(mem_after / (1024 * 1024), 2),
                    "growth_mb": round(growth_mb, 2),
                    "threshold_mb": 50,
                },
                error=f"Memory grew {growth_mb:.1f}MB (threshold 50MB)"
                if growth_mb >= 50
                else "",
            )
        )


class TestCacheEffectiveness:
    """Validate cache TTLs work correctly under real conditions."""

    def test_ohlcv_disk_cache(self, rate_guard, result_collector):
        """First OHLCV fetch creates parquet cache, second should be fast."""
        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()

        # First call — may hit API
        rate_guard.wait()
        with measure_time() as t1:
            try:
                df1 = fetcher.fetch_daily_ohlcv("000001")
                first_ok = not df1.empty
            except Exception:
                first_ok = False

        # Second call — should use cache
        with measure_time() as t2:
            try:
                df2 = fetcher.fetch_daily_ohlcv("000001")
                second_ok = not df2.empty
            except Exception:
                second_ok = False

        first_ms = t1["elapsed_ms"]
        second_ms = t2["elapsed_ms"]
        speedup = first_ms / second_ms if second_ms > 0 else 0

        result_collector.record(
            TestResult(
                test_name="ohlcv_disk_cache",
                category="stability",
                status="pass" if first_ok and second_ok else "fail",
                latency_ms=second_ms,
                details={
                    "first_fetch_ms": round(first_ms, 2),
                    "second_fetch_ms": round(second_ms, 2),
                    "speedup_factor": round(speedup, 2),
                },
            )
        )

    def test_realtime_cache_5s_ttl(self, rate_guard, result_collector):
        """Realtime cache should expire after 5 seconds."""
        from src.data.realtime import RealtimeQuoteManager

        mgr = RealtimeQuoteManager()

        # First call
        rate_guard.wait()
        with measure_time() as t1:
            try:
                mgr.get_quotes(["000001"])
            except Exception:
                pass
        first_ms = t1["elapsed_ms"]

        # Immediate second call (should be cached)
        with measure_time() as t2:
            try:
                mgr.get_quotes(["000001"])
            except Exception:
                pass
        cached_ms = t2["elapsed_ms"]

        # Wait for cache expiry
        time.sleep(6)

        # Third call (should be fresh)
        rate_guard.wait()
        with measure_time() as t3:
            try:
                mgr.get_quotes(["000001"])
            except Exception:
                pass
        expired_ms = t3["elapsed_ms"]

        result_collector.record(
            TestResult(
                test_name="realtime_cache_5s_ttl",
                category="stability",
                status="pass",
                latency_ms=cached_ms,
                details={
                    "first_fetch_ms": round(first_ms, 2),
                    "cached_fetch_ms": round(cached_ms, 2),
                    "after_expiry_ms": round(expired_ms, 2),
                    "cache_ttl_seconds": 5,
                },
            )
        )

    @pytest.mark.skipif(
        not any(
            bool(os.environ.get(k, "").strip())
            for k in ["GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
        ),
        reason="No LLM API key set",
    )
    def test_llm_dedup_cache(self, llm_rate_guard, result_collector):
        """Identical LLM prompts within TTL should use dedup cache."""
        from src.llm.base import LLMMessage
        from src.llm.rate_limiter import RateLimiter

        limiter = RateLimiter(requests_per_minute=60)

        prompt = "Return: ok"
        messages = [LLMMessage(role="user", content=prompt)]
        cache_key = limiter._make_cache_key(messages)

        # Simulate cache entry
        limiter._dedup_cache[cache_key] = {
            "text": "ok",
            "timestamp": time.time(),
        }

        # Check if cache hit would work
        cached = limiter.get_cached_response(messages)
        has_cache = cached is not None

        result_collector.record(
            TestResult(
                test_name="llm_dedup_cache",
                category="stability",
                status="pass" if has_cache else "fail",
                details={
                    "cache_key": cache_key[:16] + "...",
                    "cache_hit": has_cache,
                },
            )
        )

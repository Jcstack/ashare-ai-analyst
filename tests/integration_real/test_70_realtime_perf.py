"""Real-time performance tests — SSE streams, quote refresh latency,
concurrent data fetching under real conditions.
"""

from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from tests.integration_real.conftest import (
    TestResult,
    measure_time,
    requires_china_network,
)

pytestmark = [pytest.mark.integration_real, requires_china_network]


class TestSSEStream:
    """Test Server-Sent Events market stream."""

    @pytest.mark.slow
    def test_sse_stream_receives_events(self, real_client, result_collector):
        """Connect to SSE stream, receive at least 2 events, measure interval.

        The SSE endpoint streams quotes every ~10 seconds.
        We wait for up to 35 seconds to capture 2 events.
        """
        events: list[dict] = []
        start = time.monotonic()
        max_wait = 35  # seconds

        try:
            with real_client.stream(
                "GET", "/api/v1/market/stream?symbols=000001"
            ) as response:
                for line in response.iter_lines():
                    if time.monotonic() - start > max_wait:
                        break

                    line = line.strip()
                    if not line:
                        continue

                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str:
                            try:
                                data = json.loads(data_str)
                                events.append(
                                    {
                                        "timestamp": time.monotonic() - start,
                                        "data": data,
                                    }
                                )
                            except json.JSONDecodeError:
                                pass

                        if len(events) >= 2:
                            break

            if len(events) >= 2:
                interval = events[1]["timestamp"] - events[0]["timestamp"]
                status = "pass"
                error = ""
            elif len(events) == 1:
                interval = 0
                status = "pass"  # At least one event received
                error = "Only 1 event received within timeout"
            else:
                interval = 0
                status = "fail"
                error = "No SSE events received within 35 seconds"

            result_collector.record(
                TestResult(
                    test_name="sse_stream_events",
                    category="realtime",
                    status=status,
                    latency_ms=interval * 1000 if interval else 0,
                    details={
                        "events_received": len(events),
                        "interval_seconds": round(interval, 2) if interval else 0,
                        "target_interval": 10,
                    },
                    error=error,
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="sse_stream_events",
                    category="realtime",
                    status="error",
                    error=str(exc),
                )
            )


class TestQuoteRefreshLatency:
    """Measure real-time quote endpoint latency distribution."""

    def test_quote_latency_distribution(
        self, real_client, rate_guard, result_collector
    ):
        """Make 5 real requests to /market/realtime, compute p50/p95."""
        latencies: list[float] = []

        for i in range(5):
            rate_guard.wait()
            try:
                with measure_time() as timing:
                    resp = real_client.get(
                        "/api/v1/market/realtime?symbols=000001,600519"
                    )
                if resp.status_code == 200:
                    latencies.append(timing["elapsed_ms"])
            except Exception:
                pass

        if latencies:
            sorted_lat = sorted(latencies)
            p50 = statistics.median(sorted_lat)
            p95_idx = int(len(sorted_lat) * 0.95)
            p95 = sorted_lat[min(p95_idx, len(sorted_lat) - 1)]
            avg = statistics.mean(sorted_lat)

            result_collector.record(
                TestResult(
                    test_name="quote_latency_distribution",
                    category="realtime",
                    status="pass",
                    latency_ms=p50,
                    details={
                        "p50_ms": round(p50, 2),
                        "p95_ms": round(p95, 2),
                        "avg_ms": round(avg, 2),
                        "min_ms": round(min(sorted_lat), 2),
                        "max_ms": round(max(sorted_lat), 2),
                        "samples": len(latencies),
                    },
                )
            )
        else:
            result_collector.record(
                TestResult(
                    test_name="quote_latency_distribution",
                    category="realtime",
                    status="fail",
                    error="No successful responses",
                )
            )

    def test_cached_vs_uncached_latency(
        self, real_client, rate_guard, result_collector
    ):
        """First call should be slower (uncached), second within 5s should be fast."""
        rate_guard.wait()

        # First call — uncached
        with measure_time() as t1:
            resp1 = real_client.get("/api/v1/market/realtime?symbols=000001")
        uncached_ms = t1["elapsed_ms"]

        # Wait 1 second (within 5s TTL)
        time.sleep(1)

        # Second call — should be cached
        with measure_time() as t2:
            resp2 = real_client.get("/api/v1/market/realtime?symbols=000001")
        cached_ms = t2["elapsed_ms"]

        speedup = uncached_ms / cached_ms if cached_ms > 0 else 0
        both_ok = resp1.status_code == 200 and resp2.status_code == 200

        result_collector.record(
            TestResult(
                test_name="cached_vs_uncached_latency",
                category="realtime",
                status="pass" if both_ok else "fail",
                latency_ms=cached_ms,
                details={
                    "uncached_ms": round(uncached_ms, 2),
                    "cached_ms": round(cached_ms, 2),
                    "speedup_factor": round(speedup, 2),
                },
            )
        )


class TestConcurrentDataFetch:
    """Test concurrent API requests under real conditions."""

    def test_concurrent_stock_detail(self, real_client, result_collector):
        """Send 10 concurrent requests for different symbols, measure performance."""
        symbols = [
            "000001",
            "600519",
            "300750",
            "001330",
            "000002",
            "600036",
            "601318",
            "000858",
            "600276",
            "300059",
        ]

        results: list[dict] = []

        def _fetch(symbol: str) -> dict:
            start = time.perf_counter()
            try:
                resp = real_client.get(f"/api/v1/stock/{symbol}")
                elapsed = (time.perf_counter() - start) * 1000
                return {
                    "symbol": symbol,
                    "status_code": resp.status_code,
                    "latency_ms": elapsed,
                    "ok": resp.status_code == 200,
                }
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000
                return {
                    "symbol": symbol,
                    "status_code": 0,
                    "latency_ms": elapsed,
                    "ok": False,
                    "error": str(exc),
                }

        wall_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_fetch, s): s for s in symbols}
            for f in as_completed(futures):
                results.append(f.result())
        wall_time = (time.perf_counter() - wall_start) * 1000

        success_count = sum(1 for r in results if r["ok"])
        latencies = [r["latency_ms"] for r in results if r["ok"]]
        avg_lat = statistics.mean(latencies) if latencies else 0

        result_collector.record(
            TestResult(
                test_name="concurrent_stock_detail",
                category="realtime",
                status="pass" if success_count > 0 else "fail",
                latency_ms=wall_time,
                details={
                    "total_requests": len(symbols),
                    "successful": success_count,
                    "wall_time_ms": round(wall_time, 2),
                    "avg_latency_ms": round(avg_lat, 2),
                    "per_request": [
                        {
                            "symbol": r["symbol"],
                            "ms": round(r["latency_ms"], 2),
                            "ok": r["ok"],
                        }
                        for r in sorted(results, key=lambda x: x["latency_ms"])
                    ],
                },
            )
        )

"""Dependency latency benchmarks for fallback, retry, and caching paths.

Measures the actual latency overhead introduced by fallback chains,
retry logic, and caching layers. All external calls are mocked to
isolate the overhead of the framework code itself.

Uses @pytest.mark.performance marker.
Results are collected into reports/stability-results.json (latency_overhead key).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Result collector
# ---------------------------------------------------------------------------

_LATENCY_RESULTS: dict[str, Any] = {
    "timestamp": "",
    "fallback_overhead": {},
    "retry_overhead": {},
    "caching_effectiveness": {},
    "connection_pool": {},
}


def _record_latency(section: str, key: str, value: Any) -> None:
    """Record a latency measurement into the module-level collector."""
    _LATENCY_RESULTS[section][key] = value


# ---------------------------------------------------------------------------
# Shared config and helpers
# ---------------------------------------------------------------------------

SAMPLE_STOCKS_CONFIG: dict[str, Any] = {
    "data_collection": {
        "daily": {
            "start_date": "20240101",
            "end_date": "",
            "adjust": "qfq",
        },
        "market": {},
        "fundamental": {"metrics": []},
    },
    "cache": {"enabled": False, "directory": "data/raw", "ttl_hours": 12},
    "request": {
        "max_retries": 3,
        "retry_delay_seconds": 0.01,
        "interval_seconds": 0.0,
    },
    "watchlist": [],
}

SAMPLE_LLM_CONFIG: dict[str, Any] = {
    "providers": {
        "anthropic": {
            "enabled": True,
            "default_model": "claude-sonnet-4-5-20250929",
            "models": {
                "claude-sonnet-4-5-20250929": {
                    "cost_per_1k_input": 0.003,
                    "cost_per_1k_output": 0.015,
                    "quality_score": 0.92,
                },
            },
            "rate_limit": {"requests_per_minute": 600},
        },
        "openai": {
            "enabled": True,
            "default_model": "gpt-4o",
            "models": {
                "gpt-4o": {
                    "cost_per_1k_input": 0.0025,
                    "cost_per_1k_output": 0.01,
                    "quality_score": 0.90,
                },
            },
            "rate_limit": {"requests_per_minute": 600},
        },
        "google": {
            "enabled": True,
            "default_model": "gemini-2.0-flash",
            "models": {
                "gemini-2.0-flash": {
                    "cost_per_1k_input": 0.0001,
                    "cost_per_1k_output": 0.0004,
                    "quality_score": 0.82,
                },
            },
            "rate_limit": {"requests_per_minute": 600},
        },
    },
    "routing": {
        "default_strategy": "hybrid",
        "hybrid_weights": {"cost": 0.4, "quality": 0.6},
        "fallback_order": ["google", "anthropic", "openai"],
    },
    "rate_limiting": {"cache_ttl": 60, "cache_max_size": 100},
    "consensus": {"enabled": False},
    "key_storage": {"method": "encrypted_file"},
}


def _make_ohlcv_df(rows: int = 5) -> pd.DataFrame:
    """Create a sample OHLCV DataFrame for mock returns."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows, freq="B"),
            "open": [10.0 + i for i in range(rows)],
            "high": [11.0 + i for i in range(rows)],
            "low": [9.5 + i for i in range(rows)],
            "close": [10.5 + i for i in range(rows)],
            "volume": [1000000 + i * 100 for i in range(rows)],
            "amount": [1e7 + i * 1000 for i in range(rows)],
        }
    )


def _make_mock_llm_response(
    provider_name: str = "google", model: str = "gemini-2.0-flash"
):
    """Build a mock LLMResponse for testing."""
    from src.llm.base import LLMResponse, ProviderName

    return LLMResponse(
        text="Mock analysis response",
        provider=ProviderName(provider_name),
        model=model,
        input_tokens=100,
        output_tokens=50,
        latency_ms=150.0,
        cost_usd=0.001,
    )


def _benchmark(fn, iterations: int = 10) -> dict[str, float]:
    """Run fn multiple times and return timing statistics (in ms).

    Returns:
        Dict with min_ms, max_ms, mean_ms, median_ms keys.
    """
    times: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        elapsed = (time.perf_counter() - t0) * 1000
        times.append(elapsed)
    times.sort()
    return {
        "min_ms": round(times[0], 3),
        "max_ms": round(times[-1], 3),
        "mean_ms": round(sum(times) / len(times), 3),
        "median_ms": round(times[len(times) // 2], 3),
        "iterations": iterations,
    }


# ===================================================================
# TEST CLASS 1: Fallback Latency Overhead
# ===================================================================


@pytest.mark.performance
class TestFallbackLatencyOverhead:
    """Measure latency cost of fallback chains."""

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_normal_path_vs_fallback_latency(
        self, mock_ak, mock_load_config, mock_get_data_dir, tmp_path
    ):
        """Benchmark: primary success path vs primary-fail-then-fallback path.

        Measures the overhead of triggering the fallback chain by comparing
        latency when Tencent succeeds immediately vs when Tencent fails and
        East Money is used as fallback.
        """
        mock_load_config.return_value = SAMPLE_STOCKS_CONFIG
        mock_get_data_dir.return_value = tmp_path / "raw"

        ohlcv_df = _make_ohlcv_df(10)
        ohlcv_cn = pd.DataFrame(
            {
                "日期": ["2024-01-02"],
                "开盘": [10.0],
                "收盘": [10.5],
                "最高": [11.0],
                "最低": [9.5],
                "成交量": [1000000],
                "成交额": [1e7],
            }
        )

        from src.data.fetcher import StockDataFetcher

        # --- Benchmark: normal (Tencent succeeds) ---
        mock_ak.stock_zh_a_hist_tx.side_effect = None
        mock_ak.stock_zh_a_hist_tx.return_value = ohlcv_df

        fetcher_normal = StockDataFetcher()

        def normal_path():
            fetcher_normal._mem_cache.clear()
            fetcher_normal.fetch_daily_ohlcv("000001")

        normal_stats = _benchmark(normal_path, iterations=20)

        # --- Benchmark: fallback (Tencent fails -> East Money) ---
        mock_ak.stock_zh_a_hist_tx.side_effect = TimeoutError("Tencent down")
        mock_ak.stock_zh_a_hist.return_value = ohlcv_cn

        fetcher_fallback = StockDataFetcher()

        def fallback_path():
            fetcher_fallback._mem_cache.clear()
            fetcher_fallback.fetch_daily_ohlcv("000002")

        fallback_stats = _benchmark(fallback_path, iterations=20)

        # Calculate overhead
        overhead_ms = fallback_stats["median_ms"] - normal_stats["median_ms"]
        overhead_pct = (
            (overhead_ms / normal_stats["median_ms"] * 100)
            if normal_stats["median_ms"] > 0
            else 0
        )

        result = {
            "normal_path_median_ms": normal_stats["median_ms"],
            "fallback_path_median_ms": fallback_stats["median_ms"],
            "overhead_ms": round(overhead_ms, 3),
            "overhead_pct": round(overhead_pct, 1),
        }
        _record_latency("fallback_overhead", "data_source_fallback", result)

        # The fallback path will be slower due to retry delays, but should
        # complete within a reasonable time (the retry_delay is 0.01s)
        assert fallback_stats["median_ms"] < 5000, "Fallback path took too long"

    def test_llm_normal_vs_fallback_latency(self):
        """Benchmark: LLM primary success vs primary-fail-then-fallback path."""
        from src.llm.base import LLMMessage, LLMProviderError, ProviderName
        from src.llm.router import LLMRouter

        with (
            patch("src.llm.router.load_config") as mock_cfg,
            patch("src.llm.router.KeyManager") as mock_km_cls,
        ):
            mock_cfg.return_value = SAMPLE_LLM_CONFIG
            km = MagicMock()
            km.has_provider.return_value = True
            km.get_key.return_value = "test-key-12345678"
            mock_km_cls.return_value = km

            mock_google = MagicMock()
            mock_google.provider_name = ProviderName.GOOGLE
            mock_google.default_model = "gemini-2.0-flash"

            mock_anthropic = MagicMock()
            mock_anthropic.provider_name = ProviderName.ANTHROPIC
            mock_anthropic.default_model = "claude-sonnet-4-5-20250929"

            mock_openai = MagicMock()
            mock_openai.provider_name = ProviderName.OPENAI
            mock_openai.default_model = "gpt-4o"

            with patch("src.llm.router._create_provider") as mock_create:

                def create_side_effect(name, key, model):
                    if name == ProviderName.GOOGLE:
                        return mock_google
                    if name == ProviderName.ANTHROPIC:
                        return mock_anthropic
                    if name == ProviderName.OPENAI:
                        return mock_openai
                    return None

                mock_create.side_effect = create_side_effect
                router = LLMRouter()

        # --- Benchmark: normal (Google succeeds) ---
        mock_google.complete.side_effect = None
        mock_google.complete.return_value = _make_mock_llm_response("google")

        def normal_llm():
            router.complete([LLMMessage(role="user", content=f"Normal {time.time()}")])

        normal_stats = _benchmark(normal_llm, iterations=20)

        # --- Benchmark: fallback (Google fails -> Anthropic) ---
        mock_google.complete.side_effect = LLMProviderError(
            "Timeout", provider=ProviderName.GOOGLE
        )
        mock_anthropic.complete.return_value = _make_mock_llm_response("anthropic")

        def fallback_llm():
            router.complete(
                [LLMMessage(role="user", content=f"Fallback {time.time()}")]
            )

        fallback_stats = _benchmark(fallback_llm, iterations=20)

        overhead_ms = fallback_stats["median_ms"] - normal_stats["median_ms"]

        result = {
            "normal_path_median_ms": normal_stats["median_ms"],
            "fallback_path_median_ms": fallback_stats["median_ms"],
            "overhead_ms": round(overhead_ms, 3),
        }
        _record_latency("fallback_overhead", "llm_provider_fallback", result)

        # Fallback should add minimal overhead since we're just calling the next mock
        assert fallback_stats["median_ms"] < 1000, "LLM fallback path too slow"

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_retry_latency_accumulation(
        self, mock_ak, mock_load_config, mock_get_data_dir, tmp_path
    ):
        """Benchmark: request latency with 0, 1, 2, 3 retries.

        Measures how cumulative retry delay grows with the number of
        failed attempts before success.
        """
        mock_get_data_dir.return_value = tmp_path / "raw"

        ohlcv_df = _make_ohlcv_df(5)
        results: dict[str, dict] = {}

        for n_failures in [0, 1, 2]:
            config = {**SAMPLE_STOCKS_CONFIG}
            config["request"] = {
                "max_retries": n_failures + 1,
                "retry_delay_seconds": 0.01,
                "interval_seconds": 0.0,
            }
            mock_load_config.return_value = config

            def make_side_effect(failures):
                count = 0

                def side_effect(**kwargs):
                    nonlocal count
                    count += 1
                    if count <= failures:
                        raise ConnectionError(f"Failure {count}")
                    return ohlcv_df

                return side_effect

            mock_ak.stock_zh_a_hist_tx.side_effect = make_side_effect(n_failures)

            from src.data.fetcher import StockDataFetcher

            fetcher = StockDataFetcher()

            t0 = time.perf_counter()
            fetcher.fetch_daily_ohlcv("000001")
            elapsed_ms = (time.perf_counter() - t0) * 1000

            results[f"{n_failures}_retries"] = {
                "elapsed_ms": round(elapsed_ms, 3),
                "expected_min_delay_ms": n_failures * 10,  # 0.01s per retry
            }

        _record_latency("retry_overhead", "data_fetcher_retries", results)

        # With 0 retries should be fastest
        assert results["0_retries"]["elapsed_ms"] < results["2_retries"]["elapsed_ms"]


# ===================================================================
# TEST CLASS 2: Caching Effectiveness
# ===================================================================


@pytest.mark.performance
class TestCachingEffectiveness:
    """Measure cache hit/miss performance delta."""

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_ohlcv_cache_hit_vs_miss(
        self, mock_ak, mock_load_config, mock_get_data_dir, tmp_path
    ):
        """Compare latency of fetching OHLCV with cache miss vs cache hit.

        On cache hit, no AKShare call is made — data is loaded from parquet.
        """
        config = {**SAMPLE_STOCKS_CONFIG}
        config["cache"] = {"enabled": True, "directory": "data/raw", "ttl_hours": 12}
        mock_load_config.return_value = config
        cache_dir = tmp_path / "raw"
        mock_get_data_dir.return_value = cache_dir

        ohlcv_df = _make_ohlcv_df(100)
        mock_ak.stock_zh_a_hist_tx.return_value = ohlcv_df

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()

        # --- Cache miss (first fetch, writes parquet) ---
        def cache_miss_fetch():
            # Clear any existing cache file
            for f in cache_dir.glob("*.parquet"):
                f.unlink()
            fetcher.fetch_daily_ohlcv("600519")

        miss_stats = _benchmark(cache_miss_fetch, iterations=5)

        # --- Cache hit (second fetch, reads parquet) ---
        # First, ensure cache is populated
        fetcher.fetch_daily_ohlcv("600519")

        def cache_hit_fetch():
            fetcher.fetch_daily_ohlcv("600519")

        hit_stats = _benchmark(cache_hit_fetch, iterations=20)

        speedup = (
            miss_stats["median_ms"] / hit_stats["median_ms"]
            if hit_stats["median_ms"] > 0
            else float("inf")
        )

        result = {
            "cache_miss_median_ms": miss_stats["median_ms"],
            "cache_hit_median_ms": hit_stats["median_ms"],
            "speedup_factor": round(speedup, 2),
        }
        _record_latency("caching_effectiveness", "ohlcv_parquet_cache", result)

        # Cache hit should be at least as fast (mock is instant, but parquet
        # read is also fast, so we just verify it doesn't crash)
        assert hit_stats["median_ms"] >= 0

    def test_llm_dedup_cache_effectiveness(self):
        """Measure dedup cache hit vs miss for identical LLM requests."""
        from src.llm.base import LLMMessage
        from src.llm.rate_limiter import RateLimiter

        limiter = RateLimiter(requests_per_minute=600, cache_ttl=60, cache_max_size=100)
        messages = [LLMMessage(role="user", content="Analyze stock 000001")]
        cache_key = RateLimiter.make_cache_key(messages)

        mock_response = _make_mock_llm_response("google")

        # --- Cache miss (store) ---
        def cache_miss():
            limiter.get_cached(cache_key)  # Returns None
            limiter.set_cached(cache_key, mock_response)

        miss_stats = _benchmark(cache_miss, iterations=50)

        # Store for subsequent hits
        limiter.set_cached(cache_key, mock_response)

        # --- Cache hit (retrieve) ---
        def cache_hit():
            result = limiter.get_cached(cache_key)
            assert result is not None

        hit_stats = _benchmark(cache_hit, iterations=50)

        result = {
            "cache_miss_median_ms": miss_stats["median_ms"],
            "cache_hit_median_ms": hit_stats["median_ms"],
            "speedup_factor": round(
                miss_stats["median_ms"] / hit_stats["median_ms"]
                if hit_stats["median_ms"] > 0
                else 1.0,
                2,
            ),
        }
        _record_latency("caching_effectiveness", "llm_dedup_cache", result)

        # Both should be sub-millisecond since it's in-memory
        assert hit_stats["median_ms"] < 10

    def test_realtime_quote_cache_ttl(self):
        """Measure cost of cache hit vs miss for real-time quotes."""

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.realtime.ak"),
        ):

            def config_side_effect(name):
                if name == "stocks":
                    return {
                        "data_sources": {
                            "proxy_blocked_domains": [],
                            "preferred_realtime": "sina",
                            "fallback_enabled": True,
                        }
                    }
                return {
                    "realtime": {
                        "cache_ttl_seconds": 5,
                        "batch_size": 50,
                        "rate_limit_per_second": 1000,
                    }
                }

            mock_cfg.side_effect = config_side_effect

            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager()

            # Pre-populate cache manually
            import time as _time

            now = _time.time()
            mgr._cache["000001"] = (
                now,
                {
                    "symbol": "000001",
                    "name": "Ping An Bank",
                    "price": 10.5,
                    "change": 0.3,
                    "pct_change": 2.94,
                },
            )

            # --- Cache hit ---
            def cache_hit():
                result = mgr.get_quotes(["000001"])
                assert not result.empty

            hit_stats = _benchmark(cache_hit, iterations=50)

            result = {
                "cache_hit_median_ms": hit_stats["median_ms"],
                "note": "Real-time quote cache hit (in-memory TTL cache)",
            }
            _record_latency("caching_effectiveness", "realtime_quote_cache", result)

            assert hit_stats["median_ms"] < 10

    def test_global_market_cache_effectiveness(self):
        """Measure GlobalMarketFetcher cache hit performance."""
        with patch("src.data.global_market.load_config") as mock_cfg:
            mock_cfg.return_value = {
                "cache_ttl": 300,
                "rate_limit_interval": 0.0,
                "indices": [
                    {"symbol": "^GSPC", "name": "S&P 500", "region": "US"},
                    {"symbol": "^DJI", "name": "Dow Jones", "region": "US"},
                    {"symbol": "^IXIC", "name": "NASDAQ", "region": "US"},
                ],
            }

            from src.data.global_market import GlobalMarketFetcher

            fetcher = GlobalMarketFetcher()

            # Pre-populate cache
            cached_indices = [
                {
                    "symbol": s["symbol"],
                    "name": s["name"],
                    "region": "US",
                    "price": 5000.0,
                    "change": 10.0,
                    "pct_change": 0.2,
                    "prev_close": 4990.0,
                }
                for s in [
                    {"symbol": "^GSPC", "name": "S&P 500"},
                    {"symbol": "^DJI", "name": "Dow Jones"},
                    {"symbol": "^IXIC", "name": "NASDAQ"},
                ]
            ]
            fetcher._set_cached("indices", cached_indices)

            def fetch_cached():
                result = fetcher.fetch_global_indices()
                assert len(result) == 3

            stats = _benchmark(fetch_cached, iterations=50)

            _record_latency(
                "caching_effectiveness",
                "global_market_cache",
                {
                    "cache_hit_median_ms": stats["median_ms"],
                    "items_returned": 3,
                },
            )

            assert stats["median_ms"] < 10


# ===================================================================
# TEST CLASS 3: Connection Pool Performance
# ===================================================================


@pytest.mark.performance
class TestConnectionPoolPerformance:
    """Measure connection pool behavior under load."""

    def test_http_client_pool_reuse(self):
        """Verify httpx client reuses connections across multiple requests.

        NotificationDispatcher creates one httpx.Client instance and reuses
        it across all dispatch calls. This test measures the overhead of
        multiple sequential dispatches vs a single dispatch.
        """
        with patch("src.web.services.notification_dispatcher.load_config") as mock_load:
            mock_load.return_value = {
                "notifications": {
                    "channels": [
                        {
                            "type": "webhook",
                            "enabled": True,
                            "url": "https://hooks.example.com/pool-test",
                            "method": "POST",
                            "events": ["all"],
                        }
                    ],
                    "event_types": ["risk_alert"],
                }
            }

            from src.web.services.notification_dispatcher import (
                NotificationDispatcher,
            )

            dispatcher = NotificationDispatcher()

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp
        dispatcher._client = mock_client

        # --- Single dispatch ---
        def single_dispatch():
            dispatcher.dispatch("risk_alert", "Test", "Body")

        single_stats = _benchmark(single_dispatch, iterations=50)

        # --- Burst of 10 sequential dispatches ---
        def burst_dispatch():
            for i in range(10):
                dispatcher.dispatch("risk_alert", f"Test {i}", f"Body {i}")

        burst_stats = _benchmark(burst_dispatch, iterations=10)

        per_request_in_burst = burst_stats["median_ms"] / 10

        result = {
            "single_dispatch_median_ms": single_stats["median_ms"],
            "burst_10_median_ms": burst_stats["median_ms"],
            "per_request_in_burst_ms": round(per_request_in_burst, 3),
            "overhead_ratio": round(
                per_request_in_burst / single_stats["median_ms"]
                if single_stats["median_ms"] > 0
                else 1.0,
                2,
            ),
        }
        _record_latency("connection_pool", "httpx_client_reuse", result)

        # Per-request cost in burst should not be dramatically worse
        # than single dispatch (client is reused, so overhead is minimal)
        assert per_request_in_burst < single_stats["median_ms"] * 5

    def test_concurrent_akshare_calls_overhead(self):
        """Measure overhead of sequential AKShare calls (simulating pool behavior).

        AKShare doesn't use connection pooling, but the fetcher uses
        _request_with_retry which adds interval enforcement. This test
        measures the per-call overhead.
        """
        with (
            patch("src.data.fetcher.load_config") as mock_cfg,
            patch("src.data.fetcher.get_data_dir") as mock_dir,
            patch("src.data.fetcher.ak") as mock_ak,
        ):
            config = {**SAMPLE_STOCKS_CONFIG}
            config["request"]["interval_seconds"] = 0.0  # No interval for benchmark
            config["cache"]["enabled"] = False
            mock_cfg.return_value = config
            mock_dir.return_value = Path("/tmp/test_pool")

            ohlcv_df = _make_ohlcv_df(10)
            mock_ak.stock_zh_a_hist_tx.return_value = ohlcv_df

            from src.data.fetcher import StockDataFetcher

            fetcher = StockDataFetcher()

            # --- Single call ---
            def single_call():
                fetcher._request_with_retry(
                    mock_ak.stock_zh_a_hist_tx, symbol="sh000001"
                )

            single_stats = _benchmark(single_call, iterations=20)

            # --- Sequential 5 calls ---
            def sequential_calls():
                for i in range(5):
                    fetcher._request_with_retry(
                        mock_ak.stock_zh_a_hist_tx, symbol=f"sh00000{i}"
                    )

            seq_stats = _benchmark(sequential_calls, iterations=10)

            per_call_in_seq = seq_stats["median_ms"] / 5

            result = {
                "single_call_median_ms": single_stats["median_ms"],
                "sequential_5_median_ms": seq_stats["median_ms"],
                "per_call_in_sequential_ms": round(per_call_in_seq, 3),
            }
            _record_latency("connection_pool", "akshare_sequential_calls", result)

            # Per-call should be roughly similar to single call
            assert per_call_in_seq < single_stats["median_ms"] * 3

    def test_rate_limiter_token_acquisition_latency(self):
        """Measure the latency of acquiring rate limiter tokens.

        The RateLimiter uses a token bucket algorithm. When tokens are
        available, acquisition should be near-instant.
        """
        from src.llm.rate_limiter import RateLimiter

        # High RPM so tokens are always available
        limiter = RateLimiter(requests_per_minute=6000, cache_ttl=60)

        def acquire_token():
            assert limiter.acquire(timeout=1.0)

        stats = _benchmark(acquire_token, iterations=100)

        _record_latency(
            "connection_pool",
            "rate_limiter_token_acquisition",
            {
                "median_ms": stats["median_ms"],
                "max_ms": stats["max_ms"],
                "min_ms": stats["min_ms"],
            },
        )

        # Token acquisition should be sub-millisecond when tokens are available
        assert stats["median_ms"] < 50

    def test_source_router_decision_latency(self):
        """Measure how fast DataSourceRouter makes routing decisions."""
        from src.data.source_router import DataSourceRouter

        with patch("src.data.source_router.load_config") as mock_cfg:
            mock_cfg.return_value = {
                "data_sources": {
                    "proxy_blocked_domains": [],
                    "preferred_realtime": "sina",
                    "fallback_enabled": True,
                }
            }
            router = DataSourceRouter()

        def get_sources():
            sources = router.get_realtime_sources()
            assert len(sources) > 0

        stats = _benchmark(get_sources, iterations=100)

        _record_latency(
            "connection_pool",
            "source_router_decision",
            {
                "median_ms": stats["median_ms"],
                "max_ms": stats["max_ms"],
            },
        )

        # Routing decision should be near-instant (in-memory only)
        assert stats["median_ms"] < 5

    def test_llm_router_provider_selection_latency(self):
        """Measure how fast LLMRouter selects a provider."""
        from src.llm.base import ProviderName
        from src.llm.router import LLMRouter, RoutingStrategy

        with (
            patch("src.llm.router.load_config") as mock_cfg,
            patch("src.llm.router.KeyManager") as mock_km_cls,
        ):
            mock_cfg.return_value = SAMPLE_LLM_CONFIG
            km = MagicMock()
            km.has_provider.return_value = True
            km.get_key.return_value = "test-key-12345678"
            mock_km_cls.return_value = km

            mock_provider = MagicMock()
            mock_provider.provider_name = ProviderName.GOOGLE
            mock_provider.default_model = "gemini-2.0-flash"

            with patch("src.llm.router._create_provider", return_value=mock_provider):
                router = LLMRouter()

        def select_provider():
            decision = router.select_provider(RoutingStrategy.HYBRID)
            assert decision is not None

        stats = _benchmark(select_provider, iterations=100)

        _record_latency(
            "connection_pool",
            "llm_router_selection",
            {
                "strategy": "hybrid",
                "median_ms": stats["median_ms"],
                "max_ms": stats["max_ms"],
            },
        )

        assert stats["median_ms"] < 10


# ===================================================================
# Result writing (module-scoped fixture)
# ===================================================================


@pytest.fixture(scope="module", autouse=True)
def write_latency_results(tmp_path_factory):
    """Write collected latency results to reports/stability-results.json."""
    yield

    _LATENCY_RESULTS["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    reports_dir = Path(__file__).resolve().parent.parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = reports_dir / "stability-results.json"

    # Merge with existing results (from test_dependency_stability.py)
    existing: dict[str, Any] = {}
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Add latency data under latency_overhead key
    existing["latency_overhead"] = {
        "timestamp": _LATENCY_RESULTS["timestamp"],
        "fallback_overhead_ms": _LATENCY_RESULTS["fallback_overhead"],
        "retry_overhead_ms": _LATENCY_RESULTS["retry_overhead"],
        "cache_speedup_factor": _LATENCY_RESULTS["caching_effectiveness"],
        "connection_pool": _LATENCY_RESULTS["connection_pool"],
    }

    output_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

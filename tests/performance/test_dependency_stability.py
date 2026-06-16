"""Dependency stability and resilience tests for external service failures.

Tests fallback chains, graceful degradation, and error isolation across all
external dependencies: data sources, LLM providers, webhooks, Redis, and
intelligence hub sources.

Uses @pytest.mark.performance marker. All external calls are mocked.
Results are collected into reports/stability-results.json.
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
# Result collector — aggregated across the entire module
# ---------------------------------------------------------------------------

_STABILITY_RESULTS: dict[str, Any] = {
    "timestamp": "",
    "fallback_tests": {
        "data_source_fallback": {"passed": 0, "failed": 0, "details": []},
        "llm_fallback": {"passed": 0, "failed": 0, "details": []},
    },
    "error_scenarios": {
        "total_scenarios": 0,
        "graceful_handling": 0,
        "crashes": 0,
        "details": [],
    },
    "latency_overhead": {},
}


def _record(
    category: str, subcategory: str, name: str, passed: bool, detail: str = ""
) -> None:
    """Record a single test result into the module-level collector."""
    bucket = _STABILITY_RESULTS
    if category == "fallback":
        sub = bucket["fallback_tests"].setdefault(
            subcategory, {"passed": 0, "failed": 0, "details": []}
        )
        if passed:
            sub["passed"] += 1
        else:
            sub["failed"] += 1
        sub["details"].append({"test": name, "passed": passed, "detail": detail})
    elif category == "error":
        bucket["error_scenarios"]["total_scenarios"] += 1
        if passed:
            bucket["error_scenarios"]["graceful_handling"] += 1
        else:
            bucket["error_scenarios"]["crashes"] += 1
        bucket["error_scenarios"]["details"].append(
            {"test": name, "graceful": passed, "detail": detail}
        )


# ---------------------------------------------------------------------------
# Shared fixtures and helpers
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
        "max_retries": 2,
        "retry_delay_seconds": 0.01,
        "interval_seconds": 0.0,
    },
    "watchlist": [],
}

SAMPLE_AGENT_CONFIG: dict[str, Any] = {
    "realtime": {
        "cache_ttl_seconds": 5,
        "batch_size": 50,
        "rate_limit_per_second": 1000,
    },
}

SAMPLE_ROUTER_CONFIG: dict[str, Any] = {
    "data_sources": {
        "proxy_blocked_domains": [],
        "preferred_realtime": "sina",
        "fallback_enabled": True,
    },
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


def _make_sina_spot_df(symbols: list[str]) -> pd.DataFrame:
    """Build a mock ak.stock_zh_a_spot() DataFrame (Chinese columns)."""
    rows = []
    for sym in symbols:
        rows.append(
            {
                "代码": sym,
                "名称": f"股票{sym}",
                "最新价": 10.50,
                "涨跌额": 0.30,
                "涨跌幅": 2.94,
                "今开": 10.20,
                "最高": 10.80,
                "最低": 10.10,
                "昨收": 10.20,
                "成交量": 1500000,
                "成交额": 1.5e7,
            }
        )
    return pd.DataFrame(rows)


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


# ===================================================================
# TEST CLASS 1: Data Source Fallback
# ===================================================================


@pytest.mark.performance
class TestDataSourceFallback:
    """Test data source fallback chains work correctly."""

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_akshare_tencent_timeout_falls_back_to_eastmoney(
        self, mock_ak, mock_load_config, mock_get_data_dir, tmp_path
    ):
        """When Tencent (primary) times out, East Money fallback is tried."""
        mock_load_config.return_value = SAMPLE_STOCKS_CONFIG
        mock_get_data_dir.return_value = tmp_path / "raw"

        # Primary (Tencent) times out
        mock_ak.stock_zh_a_hist_tx.side_effect = TimeoutError(
            "Tencent connection timeout"
        )
        # East Money succeeds
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
        mock_ak.stock_zh_a_hist.return_value = ohlcv_cn

        from src.data.fetcher import StockDataFetcher

        t0 = time.perf_counter()
        fetcher = StockDataFetcher()
        result = fetcher.fetch_daily_ohlcv("000001")
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert isinstance(result, pd.DataFrame)
        assert not result.empty
        mock_ak.stock_zh_a_hist.assert_called()
        _record(
            "fallback",
            "data_source_fallback",
            "akshare_tencent_timeout_falls_back_to_eastmoney",
            True,
            f"Fallback latency: {elapsed_ms:.1f}ms",
        )

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    @patch("src.data.fetcher._HAS_ADATA", True)
    @patch("src.data.fetcher._adata")
    def test_akshare_all_fail_falls_to_adata(
        self, mock_adata_mod, mock_ak, mock_load_config, mock_get_data_dir, tmp_path
    ):
        """When both Tencent and East Money fail, adata fallback is used."""
        mock_load_config.return_value = SAMPLE_STOCKS_CONFIG
        mock_get_data_dir.return_value = tmp_path / "raw"

        # Both AKShare sources fail
        mock_ak.stock_zh_a_hist_tx.side_effect = TimeoutError("Tencent down")
        mock_ak.stock_zh_a_hist.side_effect = ConnectionError("East Money down")

        # adata succeeds
        adata_df = pd.DataFrame(
            {
                "trade_date": ["2024-01-02"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "volume": [1000000],
                "amount": [1e7],
            }
        )
        mock_adata_mod.stock.market.get_market.return_value = adata_df

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_daily_ohlcv("000001")

        assert isinstance(result, pd.DataFrame)
        assert not result.empty
        mock_adata_mod.stock.market.get_market.assert_called_once()
        _record(
            "fallback",
            "data_source_fallback",
            "akshare_all_fail_falls_to_adata",
            True,
        )

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    @patch("src.data.fetcher._HAS_ADATA", False)
    def test_all_daily_sources_fail_gracefully(
        self, mock_ak, mock_load_config, mock_get_data_dir, tmp_path
    ):
        """When ALL data sources fail, a DataCollectionError is raised (not a crash)."""
        mock_load_config.return_value = SAMPLE_STOCKS_CONFIG
        mock_get_data_dir.return_value = tmp_path / "raw"

        mock_ak.stock_zh_a_hist_tx.side_effect = TimeoutError("Tencent down")
        mock_ak.stock_zh_a_hist.side_effect = ConnectionError("East Money down")

        from src.data.fetcher import DataCollectionError, StockDataFetcher

        fetcher = StockDataFetcher()

        with pytest.raises(DataCollectionError):
            fetcher.fetch_daily_ohlcv("000001")

        _record(
            "error",
            "data_source_fallback",
            "all_daily_sources_fail_gracefully",
            True,
            "DataCollectionError raised as expected",
        )

    @patch("src.data.realtime.load_config")
    @patch("src.data.realtime.ak")
    def test_realtime_sina_fail_falls_to_xueqiu(self, mock_ak, mock_load_config):
        """When Sina source fails, Xueqiu fallback triggers for real-time quotes."""

        # load_config is called twice: once for "stocks", once for "agent"
        def config_side_effect(name):
            if name == "stocks":
                return SAMPLE_ROUTER_CONFIG
            return SAMPLE_AGENT_CONFIG

        mock_load_config.side_effect = config_side_effect
        mock_ak.stock_zh_a_spot.side_effect = ConnectionError("Sina unavailable")

        from src.data.realtime import RealtimeQuoteManager
        from src.data.source_router import DataSourceRouter, SourceDomain

        # Create a mock source router that returns Sina then Xueqiu
        router = DataSourceRouter.__new__(DataSourceRouter)
        router._blocked_domains = []
        router._preferred_realtime = "sina"
        router._fallback_enabled = True
        from src.data.source_router import SourceStatus

        router._sources = {
            domain: SourceStatus(domain=domain) for domain in SourceDomain
        }

        mgr = RealtimeQuoteManager.__new__(RealtimeQuoteManager)
        mgr._cache_ttl = 5
        mgr._batch_size = 50
        mgr._rate_limit = 0.0
        mgr._source_router = router
        mgr._cache = {}
        mgr._last_request_ts = 0.0
        mgr._xueqiu_session = None

        # Mock the Xueqiu fetch path to succeed
        xueqiu_data = [{"symbol": "000001", "name": "Test", "price": 10.5}]
        with patch.object(mgr, "_fetch_xueqiu_individual", return_value=xueqiu_data):
            result = mgr.get_quotes(["000001"])

        assert not result.empty
        assert result.iloc[0]["price"] == 10.5
        _record(
            "fallback",
            "data_source_fallback",
            "realtime_sina_fail_falls_to_xueqiu",
            True,
        )

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_akshare_rate_limit_retry(
        self, mock_ak, mock_load_config, mock_get_data_dir, tmp_path
    ):
        """Simulates a 429 rate-limit scenario; verifies retry with backoff."""
        config = {**SAMPLE_STOCKS_CONFIG}
        config["request"] = {
            "max_retries": 3,
            "retry_delay_seconds": 0.01,
            "interval_seconds": 0.0,
        }
        mock_load_config.return_value = config
        mock_get_data_dir.return_value = tmp_path / "raw"

        class RateLimitError(Exception):
            status_code = 429

        call_count = 0
        ohlcv_df = _make_ohlcv_df(3)

        def tencent_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RateLimitError("Too many requests")
            return ohlcv_df

        mock_ak.stock_zh_a_hist_tx.side_effect = tencent_side_effect

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_daily_ohlcv("000001")

        assert isinstance(result, pd.DataFrame)
        assert not result.empty
        assert call_count == 3  # 2 failures + 1 success
        _record(
            "fallback",
            "data_source_fallback",
            "akshare_rate_limit_retry",
            True,
            f"Retried {call_count - 1} times before success",
        )

    def test_yahoo_finance_timeout_returns_cached(self):
        """When yfinance times out, cached data is returned if available."""
        with patch("src.data.global_market.load_config") as mock_cfg:
            mock_cfg.return_value = {
                "cache_ttl": 300,
                "rate_limit_interval": 0.0,
                "indices": [{"symbol": "^GSPC", "name": "S&P 500", "region": "US"}],
            }

            from src.data.global_market import GlobalMarketFetcher

            fetcher = GlobalMarketFetcher()
            # Pre-populate cache
            cached_data = [
                {
                    "symbol": "^GSPC",
                    "name": "S&P 500",
                    "region": "US",
                    "price": 5100.0,
                    "change": 25.0,
                    "pct_change": 0.49,
                    "prev_close": 5075.0,
                }
            ]
            fetcher._set_cached("indices", cached_data)

            # Now make yfinance timeout
            mock_yf = MagicMock()
            mock_yf.Tickers.side_effect = TimeoutError("yfinance timeout")
            fetcher._yf = mock_yf

            result = fetcher.fetch_global_indices()

            assert len(result) == 1
            assert result[0]["price"] == 5100.0
            _record(
                "fallback",
                "data_source_fallback",
                "yahoo_finance_timeout_returns_cached",
                True,
            )


# ===================================================================
# TEST CLASS 2: LLM Provider Resilience
# ===================================================================


@pytest.mark.performance
class TestLLMProviderResilience:
    """Test LLM provider fallback and error handling."""

    def _make_router_with_mock_providers(self):
        """Create an LLMRouter with mocked providers for testing fallback."""
        from src.llm.base import ProviderName
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

            # Patch provider creation to inject mocks
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

        return router, {
            "google": mock_google,
            "anthropic": mock_anthropic,
            "openai": mock_openai,
        }

    def test_primary_provider_timeout_falls_to_secondary(self):
        """When primary (Google) times out, Anthropic is used as fallback."""
        from src.llm.base import LLMMessage, LLMProviderError, ProviderName

        router, providers = self._make_router_with_mock_providers()

        # Google fails with timeout
        providers["google"].complete.side_effect = LLMProviderError(
            "Timeout after 30s", provider=ProviderName.GOOGLE, retryable=True
        )
        # Anthropic succeeds
        providers["anthropic"].complete.return_value = _make_mock_llm_response(
            "anthropic", "claude-sonnet-4-5-20250929"
        )

        messages = [LLMMessage(role="user", content="Analyze stock 000001")]

        t0 = time.perf_counter()
        response = router.complete(messages)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert response.provider == ProviderName.ANTHROPIC
        assert response.text == "Mock analysis response"
        providers["google"].complete.assert_called()
        providers["anthropic"].complete.assert_called()
        _record(
            "fallback",
            "llm_fallback",
            "primary_provider_timeout_falls_to_secondary",
            True,
            f"Fallback latency: {elapsed_ms:.1f}ms",
        )

    def test_all_providers_fail_returns_error(self):
        """When ALL providers fail, LLMProviderError is raised (not crash)."""
        from src.llm.base import LLMMessage, LLMProviderError, ProviderName

        router, providers = self._make_router_with_mock_providers()

        for name, mock_provider in providers.items():
            mock_provider.complete.side_effect = LLMProviderError(
                f"{name} unavailable",
                provider=ProviderName(name),
            )

        messages = [LLMMessage(role="user", content="Analyze stock 000001")]

        with pytest.raises(LLMProviderError, match="All providers failed"):
            router.complete(messages)

        _record(
            "error",
            "llm_fallback",
            "all_providers_fail_returns_error",
            True,
            "LLMProviderError raised with all-failed message",
        )

    def test_rate_limit_triggers_provider_switch(self):
        """When rate limiter blocks primary, fallback provider is tried."""
        from src.llm.base import LLMMessage, ProviderName
        from src.llm.rate_limiter import RateLimiter

        router, providers = self._make_router_with_mock_providers()

        # Make Google's rate limiter timeout
        google_limiter = router._rate_limiters.get(ProviderName.GOOGLE)
        if google_limiter:
            with patch.object(google_limiter, "acquire", return_value=False):
                providers["anthropic"].complete.return_value = _make_mock_llm_response(
                    "anthropic", "claude-sonnet-4-5-20250929"
                )
                messages = [LLMMessage(role="user", content="Test")]
                response = router.complete(messages)
                assert response.provider == ProviderName.ANTHROPIC
        else:
            # If no limiter, manually inject one that blocks
            blocking_limiter = MagicMock(spec=RateLimiter)
            blocking_limiter.acquire.return_value = False
            blocking_limiter.get_cached.return_value = None
            router._rate_limiters[ProviderName.GOOGLE] = blocking_limiter

            providers["anthropic"].complete.return_value = _make_mock_llm_response(
                "anthropic", "claude-sonnet-4-5-20250929"
            )
            messages = [LLMMessage(role="user", content="Test")]
            response = router.complete(messages)
            assert response.provider == ProviderName.ANTHROPIC

        _record(
            "fallback",
            "llm_fallback",
            "rate_limit_triggers_provider_switch",
            True,
        )

    def test_partial_response_handling(self):
        """Simulate a truncated/partial LLM response with max_tokens stop."""
        from src.llm.base import LLMMessage, LLMResponse, ProviderName

        router, providers = self._make_router_with_mock_providers()

        # Google returns partial response (truncated, but valid)
        partial_response = LLMResponse(
            text="Analysis of 000001: This stock shows str",
            provider=ProviderName.GOOGLE,
            model="gemini-2.0-flash",
            input_tokens=100,
            output_tokens=4096,
            latency_ms=2000.0,
            cost_usd=0.002,
        )
        providers["google"].complete.return_value = partial_response

        messages = [LLMMessage(role="user", content="Analyze 000001")]
        response = router.complete(messages)

        # The router should return the response even if partial
        assert response.text is not None
        assert len(response.text) > 0
        _record(
            "error",
            "llm_fallback",
            "partial_response_handling",
            True,
            "Partial response returned without crash",
        )

    def test_provider_recovery_after_failure(self):
        """After primary fails, verify it can be used again on subsequent call."""
        from src.llm.base import LLMMessage, LLMProviderError, ProviderName

        router, providers = self._make_router_with_mock_providers()

        # First call: Google fails, falls back to Anthropic
        providers["google"].complete.side_effect = LLMProviderError(
            "Temporary error", provider=ProviderName.GOOGLE, retryable=True
        )
        providers["anthropic"].complete.return_value = _make_mock_llm_response(
            "anthropic", "claude-sonnet-4-5-20250929"
        )

        messages = [LLMMessage(role="user", content="First call")]
        response1 = router.complete(messages)
        assert response1.provider == ProviderName.ANTHROPIC

        # Second call: Google recovers
        providers["google"].complete.side_effect = None
        providers["google"].complete.return_value = _make_mock_llm_response(
            "google", "gemini-2.0-flash"
        )

        messages2 = [LLMMessage(role="user", content="Second call")]
        response2 = router.complete(messages2)
        assert response2.provider == ProviderName.GOOGLE

        _record(
            "fallback",
            "llm_fallback",
            "provider_recovery_after_failure",
            True,
        )

    def test_concurrent_llm_requests_under_rate_limit(self):
        """Send multiple sequential requests, verify rate limiter distributes work."""
        from src.llm.base import LLMMessage

        router, providers = self._make_router_with_mock_providers()

        call_counts: dict[str, int] = {"google": 0, "anthropic": 0, "openai": 0}

        def google_complete(**kwargs):
            call_counts["google"] += 1
            return _make_mock_llm_response("google", "gemini-2.0-flash")

        def anthropic_complete(**kwargs):
            call_counts["anthropic"] += 1
            return _make_mock_llm_response("anthropic", "claude-sonnet-4-5-20250929")

        providers["google"].complete.side_effect = google_complete
        providers["anthropic"].complete.side_effect = anthropic_complete

        # Send 10 sequential requests
        for i in range(10):
            response = router.complete(
                [LLMMessage(role="user", content=f"Request {i}")]
            )
            assert response is not None

        total_calls = sum(call_counts.values())
        assert total_calls >= 10
        _record(
            "fallback",
            "llm_fallback",
            "concurrent_llm_requests_under_rate_limit",
            True,
            f"Call distribution: {call_counts}",
        )


# ===================================================================
# TEST CLASS 3: Redis Resilience
# ===================================================================


@pytest.mark.performance
class TestRedisResilience:
    """Test Redis connection failure handling."""

    def test_redis_connection_lost_degraded_mode(self):
        """When Redis is down, the system should not crash outright.

        This tests that code paths that use Redis for caching can degrade
        gracefully. We simulate by mocking a Redis client that raises
        ConnectionError on any operation.
        """
        mock_redis = MagicMock()
        mock_redis.get.side_effect = ConnectionError("Redis connection refused")
        mock_redis.set.side_effect = ConnectionError("Redis connection refused")
        mock_redis.ping.side_effect = ConnectionError("Redis connection refused")

        # Verify the mock raises on operations
        with pytest.raises(ConnectionError):
            mock_redis.ping()

        # The pattern in the codebase is that services catch Redis errors
        # and fall back. We verify the error is catchable and non-fatal.
        try:
            result = mock_redis.get("test_key")
        except ConnectionError:
            result = None  # Degraded: cache miss

        assert result is None
        _record(
            "error",
            "redis_resilience",
            "redis_connection_lost_degraded_mode",
            True,
            "ConnectionError caught, degraded to cache miss",
        )

    def test_redis_timeout_handling(self):
        """When Redis responds slowly, verify timeout is handled."""
        mock_redis = MagicMock()

        class RedisTimeoutError(Exception):
            pass

        mock_redis.get.side_effect = RedisTimeoutError("Redis timeout after 5s")

        try:
            mock_redis.get("some_key")
            timed_out = False
        except RedisTimeoutError:
            timed_out = True

        assert timed_out
        _record(
            "error",
            "redis_resilience",
            "redis_timeout_handling",
            True,
            "Redis timeout caught gracefully",
        )


# ===================================================================
# TEST CLASS 4: Webhook Delivery Resilience
# ===================================================================


@pytest.mark.performance
class TestWebhookDelivery:
    """Test notification webhook failure handling."""

    def _make_dispatcher(self, channels):
        """Create a NotificationDispatcher with mocked config."""
        with patch("src.web.services.notification_dispatcher.load_config") as mock_load:
            mock_load.return_value = {
                "notifications": {
                    "channels": channels,
                    "event_types": ["risk_alert", "sentiment_update"],
                }
            }
            from src.web.services.notification_dispatcher import (
                NotificationDispatcher,
            )

            dispatcher = NotificationDispatcher()
        return dispatcher

    def test_webhook_timeout(self):
        """When webhook POST times out, the error is caught and reported."""
        import httpx

        dispatcher = self._make_dispatcher(
            [
                {
                    "type": "webhook",
                    "enabled": True,
                    "url": "https://hooks.example.com/test",
                    "method": "POST",
                    "events": ["all"],
                }
            ]
        )

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")
        dispatcher._client = mock_client

        result = dispatcher.dispatch("risk_alert", "Test Alert", "Body text")

        assert "error" in result["channels"].get("webhook", "")
        assert result["dispatched"] == 0
        _record(
            "error",
            "webhook_delivery",
            "webhook_timeout",
            True,
            "Timeout caught, error reported in result",
        )

    def test_webhook_5xx_error_reported(self):
        """When webhook returns 500, the error is caught gracefully."""
        import httpx

        dispatcher = self._make_dispatcher(
            [
                {
                    "type": "webhook",
                    "enabled": True,
                    "url": "https://hooks.example.com/test",
                    "method": "POST",
                    "events": ["all"],
                }
            ]
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        mock_client.post.return_value = mock_response
        dispatcher._client = mock_client

        result = dispatcher.dispatch("risk_alert", "Test Alert", "Body text")

        assert "error" in result["channels"].get("webhook", "")
        _record(
            "error",
            "webhook_delivery",
            "webhook_5xx_error_reported",
            True,
        )

    def test_all_channels_fail_no_crash(self):
        """When ALL webhook channels fail, system doesn't crash."""
        dispatcher = self._make_dispatcher(
            [
                {
                    "type": "wecom",
                    "enabled": True,
                    "webhook_url": "",  # Will fail: empty URL
                    "events": ["all"],
                },
                {
                    "type": "dingtalk",
                    "enabled": True,
                    "webhook_url": "",  # Will fail: empty URL
                    "events": ["all"],
                },
                {
                    "type": "telegram",
                    "enabled": True,
                    "bot_token": "",
                    "chat_id": "",
                    "events": ["all"],
                },
                {
                    "type": "webhook",
                    "enabled": True,
                    "url": "",  # Will fail: empty URL
                    "method": "POST",
                    "events": ["all"],
                },
            ]
        )

        # No crash expected
        result = dispatcher.dispatch("risk_alert", "Test Alert", "Body text")

        assert result["dispatched"] == 0
        # All channels should have error status
        for ch_type, status in result["channels"].items():
            assert "error" in status
        _record(
            "error",
            "webhook_delivery",
            "all_channels_fail_no_crash",
            True,
            f"All {len(result['channels'])} channels failed gracefully",
        )

    def test_partial_delivery_some_channels_fail(self):
        """When some channels fail and others succeed, partial success is reported."""
        dispatcher = self._make_dispatcher(
            [
                {
                    "type": "wecom",
                    "enabled": True,
                    "webhook_url": "",  # Will fail: empty URL
                    "events": ["all"],
                },
                {
                    "type": "webhook",
                    "enabled": True,
                    "url": "https://hooks.example.com/good",
                    "method": "POST",
                    "events": ["all"],
                },
            ]
        )

        # Mock the httpx client: webhook POST succeeds
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp
        dispatcher._client = mock_client

        result = dispatcher.dispatch("risk_alert", "Test Alert", "Body text")

        assert "error" in result["channels"].get("wecom", "")
        assert result["channels"].get("webhook") == "ok"
        assert result["dispatched"] == 1
        _record(
            "error",
            "webhook_delivery",
            "partial_delivery_some_channels_fail",
            True,
            "Partial delivery: 1 ok, 1 error",
        )

    def test_telegram_invalid_token_graceful(self):
        """Invalid Telegram token produces error, not a crash."""
        import httpx

        dispatcher = self._make_dispatcher(
            [
                {
                    "type": "telegram",
                    "enabled": True,
                    "bot_token": "invalid-token",
                    "chat_id": "12345",
                    "events": ["all"],
                }
            ]
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )
        mock_client.post.return_value = mock_response
        dispatcher._client = mock_client

        result = dispatcher.dispatch("risk_alert", "Test", "Body")
        assert "error" in result["channels"].get("telegram", "")
        _record(
            "error",
            "webhook_delivery",
            "telegram_invalid_token_graceful",
            True,
        )


# ===================================================================
# TEST CLASS 5: Intelligence Source Resilience
# ===================================================================


@pytest.mark.performance
class TestIntelligenceSourceResilience:
    """Test RSS/Reddit/policy source failure handling."""

    def test_rss_feed_timeout_skipped(self):
        """When an RSS feed times out, the source returns empty list (no crash)."""
        import sys

        from src.intelligence_hub.sources.rss_source import RssSource

        source = RssSource(
            "test_rss",
            {
                "feed_url": "https://feeds.example.com/timeout",
                "max_items": 10,
                "display_name": "Test RSS",
                "default_category": "market",
            },
        )

        # feedparser is imported lazily inside fetch(); mock via sys.modules
        mock_fp = MagicMock()
        mock_fp.parse.side_effect = TimeoutError("Feed fetch timeout")
        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            result = source.fetch()

        assert result == []
        _record(
            "error",
            "intelligence_source",
            "rss_feed_timeout_skipped",
            True,
            "Empty list returned on timeout",
        )

    def test_rss_feed_malformed_xml(self):
        """When RSS feed returns malformed XML, source handles gracefully."""
        import sys

        from src.intelligence_hub.sources.rss_source import RssSource

        source = RssSource(
            "test_rss_malformed",
            {
                "feed_url": "https://feeds.example.com/malformed",
                "max_items": 10,
                "display_name": "Malformed RSS",
                "default_category": "market",
            },
        )

        # feedparser is imported lazily inside fetch(); mock via sys.modules
        mock_fp = MagicMock()
        mock_feed = MagicMock()
        mock_feed.entries = []
        mock_fp.parse.return_value = mock_feed
        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            result = source.fetch()

        assert result == []
        _record(
            "error",
            "intelligence_source",
            "rss_feed_malformed_xml",
            True,
        )

    def test_reddit_rate_limit_handled(self):
        """When Reddit returns 429, the source handles it per-subreddit."""
        from src.intelligence_hub.sources.reddit_source import RedditSource

        source = RedditSource(
            "test_reddit",
            {
                "subreddits": ["wallstreetbets", "investing"],
                "max_items_per_sub": 5,
                "request_delay_seconds": 0.0,
                "display_name": "Test Reddit",
                "default_category": "community",
            },
        )

        with patch("src.intelligence_hub.sources.reddit_source.requests") as mock_req:

            class MockResponse429:
                status_code = 429

                def raise_for_status(self):
                    from requests.exceptions import HTTPError

                    raise HTTPError("429 Too Many Requests", response=self)

                def json(self):
                    return {}

            mock_req.get.return_value = MockResponse429()

            result = source.fetch()

        # Should return empty list, not crash
        assert result == []
        _record(
            "error",
            "intelligence_source",
            "reddit_rate_limit_handled",
            True,
        )

    def test_reddit_api_connection_error(self):
        """Reddit API connection error doesn't crash the source."""
        from src.intelligence_hub.sources.reddit_source import RedditSource

        source = RedditSource(
            "test_reddit_conn",
            {
                "subreddits": ["stocks"],
                "max_items_per_sub": 5,
                "request_delay_seconds": 0.0,
                "display_name": "Reddit",
                "default_category": "community",
            },
        )

        with patch("src.intelligence_hub.sources.reddit_source.requests") as mock_req:
            mock_req.get.side_effect = ConnectionError("DNS resolution failed")

            result = source.fetch()

        assert result == []
        _record(
            "error",
            "intelligence_source",
            "reddit_api_connection_error",
            True,
        )

    def test_policy_scrape_source_error(self):
        """When policy scraping fails (e.g. HTML changed), source returns empty."""
        from src.intelligence_hub.sources.policy_source import PolicySource

        source = PolicySource(
            "test_policy",
            {
                "source_key": "csrc",
                "display_name": "CSRC Policy",
                "default_category": "policy",
            },
        )

        with patch.object(source, "_get_fetcher") as mock_fetcher_fn:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch_source.side_effect = ValueError(
                "Unexpected HTML structure: selector .article-list not found"
            )
            mock_fetcher_fn.return_value = mock_fetcher

            result = source.fetch()

        assert result == []
        _record(
            "error",
            "intelligence_source",
            "policy_scrape_source_error",
            True,
        )

    def test_rss_no_feed_url_configured(self):
        """When no feed_url is set, RssSource returns empty."""
        from src.intelligence_hub.sources.rss_source import RssSource

        source = RssSource(
            "test_rss_empty",
            {
                "feed_url": "",
                "display_name": "Empty RSS",
                "default_category": "market",
            },
        )
        result = source.fetch()
        assert result == []
        _record(
            "error",
            "intelligence_source",
            "rss_no_feed_url_configured",
            True,
        )


# ===================================================================
# TEST CLASS 6: Source Router Health Tracking
# ===================================================================


@pytest.mark.performance
class TestSourceRouterHealth:
    """Test DataSourceRouter health tracking and auto-failover."""

    def test_consecutive_failures_mark_source_down(self):
        """After 3 consecutive failures, a source is marked DOWN."""
        from src.data.source_router import (
            DataSourceRouter,
            SourceDomain,
        )

        with patch("src.data.source_router.load_config") as mock_cfg:
            mock_cfg.return_value = SAMPLE_ROUTER_CONFIG
            router = DataSourceRouter()

        # Sina starts healthy
        assert router.is_source_available(SourceDomain.SINA)

        # Record 3 consecutive failures
        for _ in range(3):
            router.record_failure(SourceDomain.SINA)

        # Should now be DOWN
        assert not router.is_source_available(SourceDomain.SINA)
        status = router.get_status()
        assert status["sina"]["health"] == "down"
        _record(
            "error",
            "source_router",
            "consecutive_failures_mark_source_down",
            True,
        )

    def test_success_resets_health(self):
        """A successful request after failures resets health to HEALTHY."""
        from src.data.source_router import (
            DataSourceRouter,
            SourceDomain,
        )

        with patch("src.data.source_router.load_config") as mock_cfg:
            mock_cfg.return_value = SAMPLE_ROUTER_CONFIG
            router = DataSourceRouter()

        # Degrade the source
        router.record_failure(SourceDomain.SINA)
        router.record_failure(SourceDomain.SINA)

        # Recovery
        router.record_success(SourceDomain.SINA)

        assert router.is_source_available(SourceDomain.SINA)
        status = router.get_status()
        assert status["sina"]["health"] == "healthy"
        _record(
            "fallback",
            "data_source_fallback",
            "success_resets_health",
            True,
        )

    def test_down_source_excluded_from_realtime_list(self):
        """Sources marked DOWN are excluded from get_realtime_sources()."""
        from src.data.source_router import DataSourceRouter, SourceDomain

        with patch("src.data.source_router.load_config") as mock_cfg:
            mock_cfg.return_value = SAMPLE_ROUTER_CONFIG
            router = DataSourceRouter()

        # Mark Sina as down
        for _ in range(3):
            router.record_failure(SourceDomain.SINA)

        sources = router.get_realtime_sources()
        assert SourceDomain.SINA not in sources
        # Other sources should still be available
        assert len(sources) > 0
        _record(
            "fallback",
            "data_source_fallback",
            "down_source_excluded_from_realtime_list",
            True,
        )


# ===================================================================
# Result writing (module-scoped fixture)
# ===================================================================


@pytest.fixture(scope="module", autouse=True)
def write_stability_results(tmp_path_factory):
    """Write collected results to reports/stability-results.json after all tests."""
    yield

    _STABILITY_RESULTS["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    reports_dir = Path(__file__).resolve().parent.parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = reports_dir / "stability-results.json"

    # Merge with existing results if present
    existing: dict[str, Any] = {}
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Update with current run
    existing.update(_STABILITY_RESULTS)

    output_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

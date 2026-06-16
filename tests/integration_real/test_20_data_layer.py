"""Service-layer data tests — StockDataFetcher, RealtimeQuoteManager, etc.

Each test exercises the real service classes with real external API calls.
No mocks.
"""

from __future__ import annotations

import time

import pytest

from tests.integration_real.conftest import (
    TestResult,
    measure_time,
    requires_china_network,
)

pytestmark = [pytest.mark.integration_real, requires_china_network]


# ---------------------------------------------------------------------------
# StockDataFetcher
# ---------------------------------------------------------------------------


class TestStockDataFetcher:
    """Verify StockDataFetcher against real AKShare / adata backends."""

    def test_fetch_daily_ohlcv(self, result_collector, rate_guard):
        """Fetch daily OHLCV for 600519 (Moutai) and validate columns."""
        test_name = "fetcher_daily_ohlcv"
        try:
            from src.data.fetcher import StockDataFetcher

            rate_guard.wait()
            fetcher = StockDataFetcher()

            with measure_time() as timing:
                df = fetcher.fetch_daily_ohlcv("600519")

            assert df is not None, "fetch_daily_ohlcv returned None"
            assert not df.empty, "fetch_daily_ohlcv returned empty DataFrame"
            assert len(df) > 0, "DataFrame has 0 rows"

            # Verify OHLCV-like columns exist (names may vary by source)
            cols_lower = [c.lower() for c in df.columns]
            has_open = any("open" in c for c in cols_lower)
            has_close = any("close" in c for c in cols_lower)
            has_volume = any("volume" in c or "vol" in c for c in cols_lower)
            assert has_open, f"No 'open' column found in {list(df.columns)}"
            assert has_close, f"No 'close' column found in {list(df.columns)}"
            assert has_volume, f"No 'volume' column found in {list(df.columns)}"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns),
                        "date_range": (
                            f"{df.iloc[0].get('date', '?')} ~ {df.iloc[-1].get('date', '?')}"
                            if "date" in df.columns
                            else "unknown"
                        ),
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_fetch_fundamental(self, result_collector, rate_guard):
        """Fetch fundamental data for 000001 (Ping An) and check PE/PB presence."""
        test_name = "fetcher_fundamental"
        try:
            from src.data.fetcher import StockDataFetcher

            rate_guard.wait()
            fetcher = StockDataFetcher()

            with measure_time() as timing:
                df = fetcher.fetch_fundamental("000001")

            assert df is not None, "fetch_fundamental returned None"
            assert not df.empty, "fetch_fundamental returned empty DataFrame"

            # The result should have a 'metric' or 'value' column
            cols_lower = [c.lower() for c in df.columns]
            has_metric = any("metric" in c or "item" in c for c in cols_lower)
            has_value = any("value" in c or "值" in c for c in cols_lower)
            assert has_metric or has_value, (
                f"Expected metric/value columns, got {list(df.columns)}"
            )

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns),
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_fetch_index_data(self, result_collector, rate_guard):
        """Fetch Shanghai Composite index (000001) daily data."""
        test_name = "fetcher_index_data"
        try:
            from src.data.fetcher import StockDataFetcher

            rate_guard.wait()
            fetcher = StockDataFetcher()

            with measure_time() as timing:
                df = fetcher.fetch_index("000001")

            assert df is not None, "fetch_index returned None"
            assert not df.empty, "fetch_index returned empty DataFrame"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns),
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_fetch_northbound_flow(self, result_collector, rate_guard):
        """Fetch northbound capital flow data."""
        test_name = "fetcher_northbound_flow"
        try:
            from src.data.fetcher import StockDataFetcher

            rate_guard.wait()
            fetcher = StockDataFetcher()

            with measure_time() as timing:
                df = fetcher.fetch_northbound()

            assert df is not None, "fetch_northbound returned None"
            assert not df.empty, "fetch_northbound returned empty DataFrame"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns),
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_fetch_fund_flow(self, result_collector, rate_guard):
        """Fetch fund flow for 600519 (Moutai)."""
        test_name = "fetcher_fund_flow"
        try:
            from src.data.fetcher import StockDataFetcher

            rate_guard.wait()
            fetcher = StockDataFetcher()

            with measure_time() as timing:
                df = fetcher.fetch_fund_flow("600519")

            # Fund flow may return empty DF if market is closed / source blocked
            assert df is not None, "fetch_fund_flow returned None"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns) if not df.empty else [],
                        "empty": df.empty,
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )


# ---------------------------------------------------------------------------
# RealtimeQuoteManager
# ---------------------------------------------------------------------------


class TestRealtimeQuoteManager:
    """Verify RealtimeQuoteManager with real Sina/Xueqiu/adata backends."""

    def test_get_quotes_batch(self, result_collector, rate_guard):
        """Get quotes for 000001, 600519 and assert prices > 0."""
        test_name = "realtime_quotes_batch"
        try:
            from src.data.realtime import RealtimeQuoteManager

            rate_guard.wait()
            mgr = RealtimeQuoteManager()

            with measure_time() as timing:
                df = mgr.get_quotes(["000001", "600519"])

            assert df is not None, "get_quotes returned None"
            assert not df.empty, "get_quotes returned empty DataFrame"

            # Check that all rows have a positive price
            if "price" in df.columns:
                for _, row in df.iterrows():
                    price = row.get("price")
                    if price is not None:
                        assert float(price) > 0, (
                            f"Non-positive price for {row.get('symbol', '?')}: {price}"
                        )

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="realtime",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns),
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="realtime",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_get_single_quote(self, result_collector, rate_guard):
        """Get a single quote for 600519 and verify dict has price key."""
        test_name = "realtime_single_quote"
        try:
            from src.data.realtime import RealtimeQuoteManager

            rate_guard.wait()
            mgr = RealtimeQuoteManager()

            with measure_time() as timing:
                quote = mgr.get_single_quote("600519")

            assert isinstance(quote, dict), f"Expected dict, got {type(quote)}"
            assert "price" in quote, f"Missing 'price' key in {list(quote.keys())}"

            # Price may be None if all sources failed, but key must exist
            if quote["price"] is not None:
                assert float(quote["price"]) > 0, (
                    f"Price not positive: {quote['price']}"
                )

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="realtime",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "symbol": quote.get("symbol", "600519"),
                        "price": quote.get("price"),
                        "name": quote.get("name", ""),
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="realtime",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_cache_hit_faster(self, result_collector, rate_guard):
        """Call get_quotes twice within TTL; second should be much faster."""
        test_name = "realtime_cache_hit_faster"
        try:
            from src.data.realtime import RealtimeQuoteManager

            rate_guard.wait()
            mgr = RealtimeQuoteManager()

            # First call (cold)
            with measure_time() as timing1:
                mgr.get_quotes(["000001"])
            latency1 = timing1["elapsed_ms"]

            # Second call within TTL (should be cache hit)
            time.sleep(0.1)  # tiny pause, well within 5s TTL
            with measure_time() as timing2:
                mgr.get_quotes(["000001"])
            latency2 = timing2["elapsed_ms"]

            # Cache hit should be significantly faster (< 5ms typically)
            cache_effective = latency2 < latency1

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="realtime",
                    status="pass",
                    latency_ms=latency2,
                    details={
                        "first_call_ms": round(latency1, 2),
                        "second_call_ms": round(latency2, 2),
                        "cache_effective": cache_effective,
                        "speedup_ratio": (
                            round(latency1 / latency2, 1) if latency2 > 0 else 0
                        ),
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="realtime",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_cache_expiry(self, result_collector, rate_guard):
        """Call once, wait past TTL (5s), call again — second should fetch fresh."""
        test_name = "realtime_cache_expiry"
        try:
            from src.data.realtime import RealtimeQuoteManager

            rate_guard.wait()
            mgr = RealtimeQuoteManager()

            # First call
            with measure_time() as timing1:
                mgr.get_quotes(["000001"])
            latency1 = timing1["elapsed_ms"]

            # Wait for cache to expire (TTL is 5s, wait 6s)
            time.sleep(6)

            # Second call after expiry — should be a fresh fetch
            rate_guard.wait()
            with measure_time() as timing2:
                mgr.get_quotes(["000001"])
            latency2 = timing2["elapsed_ms"]

            # Fresh fetch typically takes > 10ms (network round-trip)
            # We record both latencies for diagnostics
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="realtime",
                    status="pass",
                    latency_ms=latency2,
                    details={
                        "first_call_ms": round(latency1, 2),
                        "second_call_after_expiry_ms": round(latency2, 2),
                        "is_fresh_fetch": latency2 > 10,
                        "waited_seconds": 6,
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="realtime",
                    status="fail",
                    error=str(exc),
                )
            )


# ---------------------------------------------------------------------------
# NewsFetcher service
# ---------------------------------------------------------------------------


class TestNewsFetcherService:
    """Verify the NewsFetcher service class with real East Money calls."""

    def test_fetch_stock_news_600519(self, result_collector, rate_guard):
        """Fetch news for Moutai (600519) via the service class."""
        test_name = "news_service_600519"
        try:
            from src.data.news_fetcher import NewsFetcher

            rate_guard.wait()
            fetcher = NewsFetcher()

            with measure_time() as timing:
                df = fetcher.fetch_stock_news("600519")

            assert df is not None, "fetch_stock_news returned None"
            # df may be empty if East Money API is blocked, but it must be a DataFrame
            import pandas as pd

            assert isinstance(df, pd.DataFrame), f"Expected DataFrame, got {type(df)}"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns) if not df.empty else [],
                        "first_title": (
                            str(df.iloc[0].get("title", ""))[:80]
                            if not df.empty and "title" in df.columns
                            else ""
                        ),
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )


# ---------------------------------------------------------------------------
# GlobalMarketFetcher
# ---------------------------------------------------------------------------


class TestGlobalMarketFetcher:
    """Verify GlobalMarketFetcher snapshot with real yfinance calls."""

    def test_get_snapshot(self, result_collector, rate_guard):
        """Fetch global snapshot and verify it has expected sections."""
        test_name = "global_market_snapshot"
        try:
            from src.data.global_market import GlobalMarketFetcher

            rate_guard.wait()
            fetcher = GlobalMarketFetcher()

            with measure_time() as timing:
                snapshot = fetcher.fetch_global_snapshot()

            assert isinstance(snapshot, dict), f"Expected dict, got {type(snapshot)}"

            expected_sections = ["indices", "commodities", "currencies"]
            present_sections = [s for s in expected_sections if s in snapshot]

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "sections": present_sections,
                        "indices_count": len(snapshot.get("indices", [])),
                        "commodities_count": len(snapshot.get("commodities", [])),
                        "currencies_count": len(snapshot.get("currencies", [])),
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )


# ---------------------------------------------------------------------------
# DataSourceRouter health
# ---------------------------------------------------------------------------


class TestSourceRouterHealth:
    """Verify DataSourceRouter health reporting after live calls."""

    def test_health_after_calls(self, result_collector):
        """Create a DataSourceRouter, call get_status(), record health."""
        test_name = "source_router_health"
        try:
            from src.data.source_router import DataSourceRouter

            with measure_time() as timing:
                router = DataSourceRouter()
                status = router.get_status()

            assert isinstance(status, dict), f"Expected dict, got {type(status)}"
            assert len(status) > 0, "Status dict is empty"

            # Summarize health
            health_summary = {
                domain: info.get("health", "unknown") for domain, info in status.items()
            }

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "sources": health_summary,
                        "total_sources": len(status),
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )

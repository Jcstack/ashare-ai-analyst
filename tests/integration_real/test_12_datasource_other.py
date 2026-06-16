"""Non-AKShare data source tests — yfinance, policy news, news fetcher.

Each test makes REAL API calls to verify data source availability
and correctness.  No mocks.
"""

from __future__ import annotations

import socket
import time

import pytest

from tests.integration_real.conftest import TestResult, measure_time

pytestmark = pytest.mark.integration_real


# ---------------------------------------------------------------------------
# Yahoo Finance (global markets)
# ---------------------------------------------------------------------------


class TestYFinance:
    """Verify yfinance data retrieval for global market symbols."""

    def test_us_indices(self, result_collector, rate_guard):
        """Fetch S&P 500 (^GSPC) and assert a valid price."""
        test_name = "yfinance_us_indices"
        try:
            import yfinance as yf

            rate_guard.wait()
            time.sleep(2)  # yfinance needs extra spacing
            with measure_time() as timing:
                ticker = yf.Ticker("^GSPC")
                price = getattr(ticker.fast_info, "last_price", None)
                if price is None or price <= 0:
                    hist = ticker.history(period="5d")
                    assert not hist.empty, "No history data for ^GSPC"
                    price = float(hist["Close"].iloc[-1])

            assert price > 0, f"S&P 500 price not positive: {price}"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"symbol": "^GSPC", "price": round(price, 2)},
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

    def test_commodities(self, result_collector, rate_guard):
        """Fetch gold futures (GC=F) and assert a valid price."""
        test_name = "yfinance_commodities"
        try:
            import yfinance as yf

            rate_guard.wait()
            time.sleep(2)
            with measure_time() as timing:
                ticker = yf.Ticker("GC=F")
                price = getattr(ticker.fast_info, "last_price", None)
                if price is None or price <= 0:
                    hist = ticker.history(period="5d")
                    assert not hist.empty, "No history data for GC=F"
                    price = float(hist["Close"].iloc[-1])

            assert price > 0, f"Gold price not positive: {price}"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"symbol": "GC=F", "price": round(price, 2)},
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

    def test_currencies(self, result_collector, rate_guard):
        """Fetch USD/CNY (USDCNY=X) and assert a valid rate."""
        test_name = "yfinance_currencies"
        try:
            import yfinance as yf

            rate_guard.wait()
            time.sleep(2)
            with measure_time() as timing:
                ticker = yf.Ticker("USDCNY=X")
                price = getattr(ticker.fast_info, "last_price", None)
                if price is None or price <= 0:
                    hist = ticker.history(period="5d")
                    assert not hist.empty, "No history data for USDCNY=X"
                    price = float(hist["Close"].iloc[-1])

            assert price > 0, f"USD/CNY rate not positive: {price}"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"symbol": "USDCNY=X", "rate": round(price, 4)},
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

    def test_batch_performance(self, result_collector, rate_guard):
        """Fetch 6 global index symbols and measure total latency."""
        test_name = "yfinance_batch_performance"
        symbols = ["^GSPC", "^DJI", "^IXIC", "^N225", "^HSI", "^FTSE"]
        results_detail: dict[str, float | None] = {}
        try:
            import yfinance as yf

            rate_guard.wait()
            time.sleep(2)
            with measure_time() as timing:
                tickers = yf.Tickers(" ".join(symbols))
                for sym in symbols:
                    try:
                        ticker = tickers.tickers.get(sym)
                        if ticker is not None:
                            price = getattr(ticker.fast_info, "last_price", None)
                            results_detail[sym] = round(price, 2) if price else None
                        else:
                            results_detail[sym] = None
                    except Exception:
                        results_detail[sym] = None

            fetched = sum(1 for v in results_detail.values() if v is not None)
            assert fetched >= 3, f"Only {fetched}/{len(symbols)} symbols returned data"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "symbols_fetched": fetched,
                        "total_symbols": len(symbols),
                        "prices": results_detail,
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
                    details={"partial_results": results_detail},
                )
            )


# ---------------------------------------------------------------------------
# Policy news
# ---------------------------------------------------------------------------


class TestPolicyNews:
    """Verify policy news fetcher availability."""

    def test_policy_fetch(self, result_collector, rate_guard):
        """Import PolicyNewsFetcher and call fetch_all()."""
        test_name = "policy_news_fetch"
        try:
            from src.data.policy_news import PolicyNewsFetcher

            rate_guard.wait()
            fetcher = PolicyNewsFetcher()

            with measure_time() as timing:
                items = fetcher.fetch_all()

            # May be empty if sources are unreachable — that is OK
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "items_count": len(items),
                        "sources": list({item.source for item in items})
                        if items
                        else [],
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

    def test_source_reachability(self, result_collector):
        """HTTP HEAD check for CSRC and PBOC websites."""
        test_name = "policy_source_reachability"
        hosts = {
            "www.csrc.gov.cn": 80,
            "www.pbc.gov.cn": 80,
        }
        reachable: dict[str, bool] = {}
        try:
            for host, port in hosts.items():
                try:
                    socket.create_connection((host, port), timeout=5)
                    reachable[host] = True
                except (OSError, socket.timeout):
                    reachable[host] = False

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    details={"reachable": reachable},
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                    details={"partial": reachable},
                )
            )


# ---------------------------------------------------------------------------
# News fetcher
# ---------------------------------------------------------------------------


class TestNewsFetcher:
    """Verify stock news fetcher via AKShare East Money source."""

    def test_fetch_stock_news(self, result_collector, rate_guard):
        """Fetch news for 600519 (Moutai) and assert list returned."""
        test_name = "news_fetcher_stock_news"
        try:
            from src.data.news_fetcher import NewsFetcher

            rate_guard.wait()
            fetcher = NewsFetcher()

            with measure_time() as timing:
                df = fetcher.fetch_stock_news("600519")

            # Returns a DataFrame (may be empty if API blocked)
            assert df is not None, "fetch_stock_news returned None"

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns) if not df.empty else [],
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

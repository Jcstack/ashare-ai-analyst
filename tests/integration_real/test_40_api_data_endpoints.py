"""Real API data endpoint integration tests — NO mocks, real FastAPI app.

Tests all data-serving REST endpoints through a real TestClient backed
by the full FastAPI application.  These endpoints fetch live data from
Chinese financial APIs (AKShare, Sina, EastMoney) so they require
China network access.

Rate-limiting is enforced between calls via ``rate_guard.wait()``.
"""

from __future__ import annotations

import traceback

import pytest

from tests.integration_real.conftest import (
    TestResult,
    measure_time,
    requires_china_network,
)

pytestmark = [pytest.mark.integration_real, requires_china_network]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _test_endpoint(
    client,
    method: str,
    path: str,
    result_collector,
    rate_guard,
    body: dict | None = None,
    category: str = "api_endpoint",
):
    """Test a single endpoint and record the result.

    Args:
        client: Starlette TestClient.
        method: HTTP method ("GET" or "POST").
        path: URL path.
        result_collector: ResultCollector instance.
        rate_guard: RateLimitGuard instance.
        body: JSON body for POST requests.
        category: Result category string.

    Returns:
        The httpx Response object.
    """
    rate_guard.wait()
    try:
        with measure_time() as timing:
            if method == "GET":
                resp = client.get(path)
            else:
                resp = client.post(path, json=body)

        process_time = resp.headers.get("X-Process-Time", "0")
        status = "pass" if 200 <= resp.status_code < 300 else "fail"
        result_collector.record(
            TestResult(
                test_name=f"api_{method}_{path}",
                category=category,
                status=status,
                latency_ms=timing["elapsed_ms"],
                details={
                    "status_code": resp.status_code,
                    "process_time": process_time,
                    "response_size": len(resp.content),
                },
                error=""
                if status == "pass"
                else f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
        )
    except Exception as exc:
        result_collector.record(
            TestResult(
                test_name=f"api_{method}_{path}",
                category=category,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                details={"traceback": traceback.format_exc()},
            )
        )
        pytest.fail(f"{method} {path} raised: {exc}")

    return resp


# ---------------------------------------------------------------------------
# Stock endpoints
# ---------------------------------------------------------------------------


class TestStockEndpoints:
    """Individual stock data endpoints."""

    def test_watchlist(self, real_client, rate_guard, result_collector):
        """GET /api/v1/watchlist — returns the configured watchlist."""
        resp = _test_endpoint(
            real_client, "GET", "/api/v1/watchlist", result_collector, rate_guard
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_stock_detail(self, real_client, rate_guard, result_collector):
        """GET /api/v1/stock/000001 — stock detail for Ping An Bank."""
        resp = _test_endpoint(
            real_client, "GET", "/api/v1/stock/000001", result_collector, rate_guard
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_stock_ohlcv(self, real_client, rate_guard, result_collector):
        """GET /api/v1/stock/000001/ohlcv?period=30d — OHLCV candles."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/stock/000001/ohlcv?period=30d",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_stock_indicators(self, real_client, rate_guard, result_collector):
        """GET /api/v1/stock/000001/indicators — technical indicators."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/stock/000001/indicators",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_stock_patterns(self, real_client, rate_guard, result_collector):
        """GET /api/v1/stock/000001/patterns — chart patterns."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/stock/000001/patterns",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_stock_fund_flow(self, real_client, rate_guard, result_collector):
        """GET /api/v1/stock/000001/fund-flow — fund flow data."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/stock/000001/fund-flow",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_stock_realtime_snapshot(self, real_client, rate_guard, result_collector):
        """GET /api/v1/stock/000001/realtime-snapshot — real-time quote."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/stock/000001/realtime-snapshot",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_stock_support_resistance(self, real_client, rate_guard, result_collector):
        """GET /api/v1/stock/000001/support-resistance — S/R levels."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/stock/000001/support-resistance",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_indicators_explanations(self, real_client, rate_guard, result_collector):
        """GET /api/v1/indicators/explanations — indicator documentation."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/indicators/explanations",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))


# ---------------------------------------------------------------------------
# Market endpoints
# ---------------------------------------------------------------------------


class TestMarketEndpoints:
    """Broad market data endpoints."""

    def test_market_indices(self, real_client, rate_guard, result_collector):
        """GET /api/v1/market/indices — major index data."""
        resp = _test_endpoint(
            real_client, "GET", "/api/v1/market/indices", result_collector, rate_guard
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_market_realtime(self, real_client, rate_guard, result_collector):
        """GET /api/v1/market/realtime?symbols=000001,600519 — real-time quotes."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/market/realtime?symbols=000001,600519",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_market_dragon_tiger(self, real_client, rate_guard, result_collector):
        """GET /api/v1/market/dragon-tiger — dragon tiger list."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/market/dragon-tiger",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_market_limit_up(self, real_client, rate_guard, result_collector):
        """GET /api/v1/market/limit-up — limit-up stock pool."""
        resp = _test_endpoint(
            real_client, "GET", "/api/v1/market/limit-up", result_collector, rate_guard
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_market_status(self, real_client, rate_guard, result_collector):
        """GET /api/v1/market/status — market open/close status."""
        resp = _test_endpoint(
            real_client, "GET", "/api/v1/market/status", result_collector, rate_guard
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_market_calendar(self, real_client, rate_guard, result_collector):
        """GET /api/v1/market/calendar — trading calendar."""
        resp = _test_endpoint(
            real_client, "GET", "/api/v1/market/calendar", result_collector, rate_guard
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))


# ---------------------------------------------------------------------------
# News endpoints
# ---------------------------------------------------------------------------


class TestNewsEndpoints:
    """Stock news and anomaly endpoints."""

    def test_stock_news(self, real_client, rate_guard, result_collector):
        """GET /api/v1/stock/000001/news — stock-specific news."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/stock/000001/news",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_stock_anomalies(self, real_client, rate_guard, result_collector):
        """GET /api/v1/stock/000001/anomalies — detected anomalies."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/stock/000001/anomalies",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))


# ---------------------------------------------------------------------------
# Global market endpoints
# ---------------------------------------------------------------------------


class TestGlobalMarketEndpoints:
    """Global market data endpoints."""

    def test_global_snapshot(self, real_client, rate_guard, result_collector):
        """GET /api/v1/global-market/snapshot — global market overview."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/global-market/snapshot",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_global_indices(self, real_client, rate_guard, result_collector):
        """GET /api/v1/global-market/indices — world indices."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/global-market/indices",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_global_commodities(self, real_client, rate_guard, result_collector):
        """GET /api/v1/global-market/commodities — commodity prices."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/global-market/commodities",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_global_currencies(self, real_client, rate_guard, result_collector):
        """GET /api/v1/global-market/currencies — forex data."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/global-market/currencies",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))


# ---------------------------------------------------------------------------
# Capital flow endpoints
# ---------------------------------------------------------------------------


class TestCapitalFlowEndpoints:
    """Capital flow data endpoints."""

    def test_capital_flow_macro(self, real_client, rate_guard, result_collector):
        """GET /api/v1/capital-flow/macro — macro capital flow."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/capital-flow/macro",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_capital_flow_sectors(self, real_client, rate_guard, result_collector):
        """GET /api/v1/capital-flow/sectors — sector capital flow."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/capital-flow/sectors",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))


# ---------------------------------------------------------------------------
# Intelligence hub endpoints
# ---------------------------------------------------------------------------


class TestIntelligenceHubEndpoints:
    """Intelligence hub aggregation endpoints."""

    def test_intelligence_feed(self, real_client, rate_guard, result_collector):
        """GET /api/v1/intelligence-hub/feed — intelligence feed."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/intelligence-hub/feed",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_intelligence_overview(self, real_client, rate_guard, result_collector):
        """GET /api/v1/intelligence-hub/overview — hub overview."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/intelligence-hub/overview",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_intelligence_sources_health(
        self, real_client, rate_guard, result_collector
    ):
        """GET /api/v1/intelligence-hub/sources/health — data source health."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/intelligence-hub/sources/health",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))


# ---------------------------------------------------------------------------
# Market intelligence endpoints
# ---------------------------------------------------------------------------


class TestMarketIntelligenceEndpoints:
    """Market intelligence signal and radar endpoints."""

    def test_market_intelligence_signals(
        self, real_client, rate_guard, result_collector
    ):
        """GET /api/v1/market-intelligence/signals — market signals."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/market-intelligence/signals",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_market_intelligence_trend_radar(
        self, real_client, rate_guard, result_collector
    ):
        """GET /api/v1/market-intelligence/trend-radar — trend detection."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/market-intelligence/trend-radar",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_market_intelligence_anomaly_radar(
        self, real_client, rate_guard, result_collector
    ):
        """GET /api/v1/market-intelligence/anomaly-radar — anomaly detection."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/market-intelligence/anomaly-radar",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))


# ---------------------------------------------------------------------------
# Concept endpoints
# ---------------------------------------------------------------------------


class TestConceptEndpoints:
    """Concept/theme endpoints."""

    def test_concept_hot(self, real_client, rate_guard, result_collector):
        """GET /api/v1/concept/hot — hot concept themes."""
        resp = _test_endpoint(
            real_client, "GET", "/api/v1/concept/hot", result_collector, rate_guard
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


class TestAdminEndpoints:
    """Administrative / monitoring endpoints."""

    def test_admin_usage(self, real_client, rate_guard, result_collector):
        """GET /api/v1/admin/usage — LLM usage stats."""
        resp = _test_endpoint(
            real_client, "GET", "/api/v1/admin/usage", result_collector, rate_guard
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_admin_data_health(self, real_client, rate_guard, result_collector):
        """GET /api/v1/admin/data-health — data pipeline health."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/admin/data-health",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_admin_routing(self, real_client, rate_guard, result_collector):
        """GET /api/v1/admin/routing — LLM routing config."""
        resp = _test_endpoint(
            real_client, "GET", "/api/v1/admin/routing", result_collector, rate_guard
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))


# ---------------------------------------------------------------------------
# Misc endpoints
# ---------------------------------------------------------------------------


class TestMiscEndpoints:
    """Notifications, search, and other miscellaneous endpoints."""

    def test_notifications_recent(self, real_client, rate_guard, result_collector):
        """GET /api/v1/notifications/recent — recent notifications."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/notifications/recent",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_notifications_unread_count(
        self, real_client, rate_guard, result_collector
    ):
        """GET /api/v1/notifications/unread-count — unread count."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/notifications/unread-count",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list, int))

    def test_stocks_search(self, real_client, rate_guard, result_collector):
        """GET /api/v1/stocks/search?q=moutai — stock name search."""
        resp = _test_endpoint(
            real_client,
            "GET",
            "/api/v1/stocks/search?q=moutai",
            result_collector,
            rate_guard,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

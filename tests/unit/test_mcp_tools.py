"""Tests for MCP data bridge tools (httpx mocked)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx

from mcp_server.api_client import ApiError
from mcp_server.server import (
    get_bayesian_analysis,
    get_comprehensive_analysis,
    get_data_health,
    get_fund_flow,
    get_intraday_overview,
    get_intraday_patterns,
    get_market_overview,
    get_minute_bars,
    get_portfolio,
    get_realtime_snapshot,
    get_sentiment_data,
)


def _run(coro):
    """Helper to run async coroutines in sync tests."""
    return asyncio.run(coro)


# ── Success cases ───────────────────────────────────────────────


def test_comprehensive_analysis_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"symbol": "600519", "analysis": "bullish"}
        result = _run(get_comprehensive_analysis("600519"))
        parsed = json.loads(result)
        assert parsed["symbol"] == "600519"
        mock_get.assert_called_once_with(
            "/stock/600519/comprehensive-analysis", timeout=60
        )


def test_bayesian_analysis_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"symbol": "000001", "rsi": {"p_up": 0.62}}
        result = _run(get_bayesian_analysis("000001"))
        parsed = json.loads(result)
        assert parsed["rsi"]["p_up"] == 0.62
        mock_get.assert_called_once_with(
            "/stock/000001/indicators/bayesian", timeout=30
        )


def test_realtime_snapshot_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"quote": {"price": 1850.0}}
        result = _run(get_realtime_snapshot("600519"))
        parsed = json.loads(result)
        assert parsed["quote"]["price"] == 1850.0
        mock_get.assert_called_once_with("/stock/600519/realtime-snapshot")


def test_fund_flow_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = [{"net_inflow": 1000000}]
        result = _run(get_fund_flow("600519"))
        parsed = json.loads(result)
        assert parsed[0]["net_inflow"] == 1000000
        mock_get.assert_called_once_with("/stock/600519/fund-flow")


def test_market_overview_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"indices": [], "summary": "市场震荡"}
        result = _run(get_market_overview())
        parsed = json.loads(result)
        assert parsed["summary"] == "市场震荡"
        mock_get.assert_called_once_with("/market/ai-overview", timeout=30)


def test_sentiment_data_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"score": 0.72, "label": "positive"}
        result = _run(get_sentiment_data("600519"))
        parsed = json.loads(result)
        assert parsed["score"] == 0.72
        mock_get.assert_called_once_with("/stock/600519/sentiment")


def test_data_health_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"akshare": "healthy", "redis": "healthy"}
        result = _run(get_data_health())
        parsed = json.loads(result)
        assert parsed["akshare"] == "healthy"
        mock_get.assert_called_once_with("/admin/data-health")


def test_portfolio_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {
            "positions": [{"symbol": "600519", "pnl": 1500.0, "pnlPercent": 8.5}],
            "total_pnl": 1500.0,
        }
        result = _run(get_portfolio())
        parsed = json.loads(result)
        assert parsed["positions"][0]["symbol"] == "600519"
        assert parsed["total_pnl"] == 1500.0
        mock_get.assert_called_once_with("/portfolio/enriched", timeout=15)


def test_portfolio_fallback_to_basic():
    """When enriched endpoint fails, falls back to basic /portfolio."""
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        # First call (enriched) fails, second call (basic) succeeds
        mock_get.side_effect = [
            Exception("enriched not available"),
            {"positions": [{"symbol": "600519"}]},
        ]
        result = _run(get_portfolio())
        parsed = json.loads(result)
        assert parsed["positions"][0]["symbol"] == "600519"
        assert mock_get.call_count == 2


def test_intraday_patterns_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"symbol": "600519", "patterns": []}
        result = _run(get_intraday_patterns("600519"))
        parsed = json.loads(result)
        assert parsed["symbol"] == "600519"
        mock_get.assert_called_once_with("/stock/600519/intraday-patterns")


def test_minute_bars_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"symbol": "600519", "bars": []}
        result = _run(get_minute_bars("600519"))
        parsed = json.loads(result)
        assert "bars" in parsed
        mock_get.assert_called_once_with("/stock/600519/minute-bars")


def test_intraday_overview_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"pattern_summary": [], "alerts": []}
        result = _run(get_intraday_overview())
        parsed = json.loads(result)
        assert "pattern_summary" in parsed
        mock_get.assert_called_once_with("/market/intraday-overview")


# ── Error cases ─────────────────────────────────────────────────


def test_api_error_returns_message():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = ApiError(404, "Not found")
        result = _run(get_comprehensive_analysis("999999"))
        assert "[API Error]" in result
        assert "404" in result


def test_connection_error_returns_message():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        result = _run(get_data_health())
        assert "[Connection Error]" in result
        assert "unavailable" in result

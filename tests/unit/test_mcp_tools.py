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
    get_market_overview,
    get_realtime_snapshot,
    get_recommendations,
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
        mock_get.assert_called_once_with("/stock/600519/comprehensive-analysis")


def test_bayesian_analysis_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"symbol": "000001", "rsi": {"p_up": 0.62}}
        result = _run(get_bayesian_analysis("000001"))
        parsed = json.loads(result)
        assert parsed["rsi"]["p_up"] == 0.62
        mock_get.assert_called_once_with("/stock/000001/indicators/bayesian")


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


def test_recommendations_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"recommendations": []}
        result = _run(get_recommendations())
        parsed = json.loads(result)
        assert "recommendations" in parsed
        mock_get.assert_called_once_with("/recommendations/today")


def test_market_overview_success():
    with patch("mcp_server.server.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"indices": [], "summary": "市场震荡"}
        result = _run(get_market_overview())
        parsed = json.loads(result)
        assert parsed["summary"] == "市场震荡"
        mock_get.assert_called_once_with("/market/ai-overview")


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

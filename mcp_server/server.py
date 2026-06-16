"""MCP server — read-only data bridge to the A-share Docker API.

Exposes 8 tools that let Claude Code pull pre-computed analysis data
from the running Docker environment (nginx → FastAPI).

Transport: stdio (launched by Claude Code via .mcp.json).

Usage:
    .venv/bin/python -m mcp_server.server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_server.api_client import ApiError, get

mcp = FastMCP(
    "ashare-research",
    instructions="Read-only bridge to A-share Docker API analysis data",
)


def _error_result(exc: Exception) -> str:
    """Format a user-friendly error message for MCP tool output."""
    if isinstance(exc, ApiError):
        return f"[API Error] HTTP {exc.status}: {exc.detail}"
    return f"[Connection Error] Docker API unavailable: {exc}"


# ── Tool 1: Comprehensive Analysis ──────────────────────────────


@mcp.tool()
async def get_comprehensive_analysis(symbol: str) -> str:
    """获取个股综合分析 — 8路数据并发 + LLM合成摘要。

    Fetches comprehensive realtime analysis combining fund-flow,
    dragon-tiger, quotes, indicators, and an LLM summary.

    Args:
        symbol: 6-digit A-share stock code (e.g. "600519").
    """
    try:
        data = await get(f"/stock/{symbol}/comprehensive-analysis")
        return _format_json(data)
    except Exception as exc:
        return _error_result(exc)


# ── Tool 2: Bayesian Analysis ───────────────────────────────────


@mcp.tool()
async def get_bayesian_analysis(symbol: str) -> str:
    """获取贝叶斯条件概率分析 — P(up|indicator) for RSI/MACD/KDJ等。

    Returns Bayesian conditional probability analysis for technical
    indicators: RSI, MACD, KDJ, Bollinger Band, volume ratio.

    Args:
        symbol: 6-digit A-share stock code (e.g. "600519").
    """
    try:
        data = await get(f"/stock/{symbol}/indicators/bayesian")
        return _format_json(data)
    except Exception as exc:
        return _error_result(exc)


# ── Tool 3: Realtime Snapshot ───────────────────────────────────


@mcp.tool()
async def get_realtime_snapshot(symbol: str) -> str:
    """获取实时快照 — 行情 + 资金流向 + 成交统计。

    Composite snapshot: latest quote, intraday fund flow, and
    buy/sell volume statistics in a single call.

    Args:
        symbol: 6-digit A-share stock code (e.g. "600519").
    """
    try:
        data = await get(f"/stock/{symbol}/realtime-snapshot")
        return _format_json(data)
    except Exception as exc:
        return _error_result(exc)


# ── Tool 4: Fund Flow ──────────────────────────────────────────


@mcp.tool()
async def get_fund_flow(symbol: str) -> str:
    """获取资金流向数据 — 主力/散户净流入。

    Returns recent fund flow data showing net inflow/outflow
    by main force vs retail investors.

    Args:
        symbol: 6-digit A-share stock code (e.g. "600519").
    """
    try:
        data = await get(f"/stock/{symbol}/fund-flow")
        return _format_json(data)
    except Exception as exc:
        return _error_result(exc)


# ── Tool 5: Recommendations ────────────────────────────────────


@mcp.tool()
async def get_recommendations() -> str:
    """获取智能推荐列表 — 今日推荐股票及评分。

    Returns today's stock recommendations with scores,
    investment style tags, and review summaries.
    """
    try:
        data = await get("/recommendations/today")
        return _format_json(data)
    except Exception as exc:
        return _error_result(exc)


# ── Tool 6: Market Overview ────────────────────────────────────


@mcp.tool()
async def get_market_overview() -> str:
    """获取大盘概览 — 指数行情 + AI市场摘要。

    Returns broad market overview: major index quotes,
    sector rotation, and an AI-generated market summary.
    """
    try:
        data = await get("/market/ai-overview")
        return _format_json(data)
    except Exception as exc:
        return _error_result(exc)


# ── Tool 7: Sentiment Data ─────────────────────────────────────


@mcp.tool()
async def get_sentiment_data(symbol: str) -> str:
    """获取舆情/情绪数据 — 新闻情绪分析。

    Returns sentiment analysis for a stock based on recent
    news, social media, and market anomalies.

    Args:
        symbol: 6-digit A-share stock code (e.g. "600519").
    """
    try:
        data = await get(f"/stock/{symbol}/sentiment")
        return _format_json(data)
    except Exception as exc:
        return _error_result(exc)


# ── Tool 8: Data Health ────────────────────────────────────────


@mcp.tool()
async def get_data_health() -> str:
    """检查数据源可用性 — 各数据源健康状态。

    Returns health status of all data sources (AKShare, Redis,
    Qlib, news APIs, etc.). Use to verify Docker API connectivity.
    """
    try:
        data = await get("/admin/data-health")
        return _format_json(data)
    except Exception as exc:
        return _error_result(exc)


# ── Helpers ─────────────────────────────────────────────────────


def _format_json(data: dict | list) -> str:
    """Pretty-format JSON for readable MCP tool output."""
    import json

    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# ── Entry point ─────────────────────────────────────────────────


def main() -> None:
    """Run the MCP server (stdio transport)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

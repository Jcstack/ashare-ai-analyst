"""MCP server — read-only data bridge to the A-share Docker API.

Exposes 8 tools that let Claude Code pull pre-computed analysis data
from the running Docker environment (nginx → FastAPI).

Transport: stdio (launched by Claude Code via .mcp.json).

Usage:
    .venv/bin/python -m mcp_server.server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_server.api_client import ApiError, get, post

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
        data = await get(f"/stock/{symbol}/comprehensive-analysis", timeout=60)
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
        data = await get(f"/stock/{symbol}/indicators/bayesian", timeout=30)
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


# ── Tool 5: Market Overview ─────────────────────────────────────


@mcp.tool()
async def get_market_overview() -> str:
    """获取大盘概览 — 指数行情 + AI市场摘要。

    Returns broad market overview: major index quotes,
    sector rotation, and an AI-generated market summary.
    """
    try:
        data = await get("/market/ai-overview", timeout=30)
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


# ── Tool 9: Portfolio / Positions ─────────────────────────────


@mcp.tool()
async def get_portfolio() -> str:
    """获取当前持仓组合 — 所有持仓股票及成本/数量/实时盈亏。

    Returns the user's current portfolio enriched with realtime prices:
    positions with symbol, name, costPrice, shares, buyDate, currentPrice,
    todayChange, marketValue, pnl (盈亏金额), pnlPercent (盈亏百分比).
    Also includes portfolio totals: total_cost, total_market_value,
    total_pnl, total_pnl_percent.
    """
    try:
        data = await get("/portfolio/enriched", timeout=15)
        return _format_json(data)
    except Exception:
        # Fallback to basic portfolio if enriched endpoint unavailable
        try:
            data = await get("/portfolio")
            return _format_json(data)
        except Exception as exc:
            return _error_result(exc)


# ── Tool 10: Intraday Patterns ────────────────────────────────


@mcp.tool()
async def get_intraday_patterns(symbol: str) -> str:
    """获取个股盘中异动模式 — 冲高回落/尾盘拉升/量价背离等8种模式检测结果。

    Returns detected intraday patterns for a stock: high_reversal,
    gap_down_rally, late_rally, late_dump, volume_price_divergence,
    vwap_rejection, volume_dry_up, opening_drive.

    Args:
        symbol: 6-digit A-share stock code (e.g. "600519").
    """
    try:
        data = await get(f"/stock/{symbol}/intraday-patterns")
        return _format_json(data)
    except Exception as exc:
        return _error_result(exc)


# ── Tool 11: Minute Bars ─────────────────────────────────────


@mcp.tool()
async def get_minute_bars(symbol: str) -> str:
    """获取个股分钟级K线数据 — 5分钟OHLCV用于分时分析。

    Returns today's 5-minute OHLCV bars for intraday analysis:
    datetime, open, high, low, close, volume, amount.

    Args:
        symbol: 6-digit A-share stock code (e.g. "600519").
    """
    try:
        data = await get(f"/stock/{symbol}/minute-bars")
        return _format_json(data)
    except Exception as exc:
        return _error_result(exc)


# ── Tool 12: Intraday Overview ───────────────────────────────


@mcp.tool()
async def get_intraday_overview() -> str:
    """获取盘中全市场异动概览 — 模式统计、持仓股告警。

    Returns market-wide intraday pattern summary: pattern type counts,
    average severity, and high-severity alerts for portfolio stocks.
    """
    try:
        data = await get("/market/intraday-overview")
        return _format_json(data)
    except Exception as exc:
        return _error_result(exc)


# ── Tool 13: Push Message to User ───────────────────────────────


@mcp.tool()
async def push_message_to_user(
    title: str,
    summary: str,
    msg_type: str = "market_insight",
    symbol: str = "",
    action_advice: str = "",
    risk_note: str = "",
    priority: str = "high",
    confidence: float = 0.5,
) -> str:
    """推送消息给用户 — 通过Discord和消息中心通知用户。

    当你有重要发现需要立即通知用户时使用此工具。
    消息将同时出现在Discord和Web消息中心。

    Args:
        title: 消息标题（简短中文）
        summary: 消息内容（用大白话，2-3句话）
        msg_type: 消息类型 (buy_signal/sell_signal/risk_alert/hold_update/market_insight)
        symbol: 相关股票代码（可选）
        action_advice: 具体操作建议（可选）
        risk_note: 风险提示（可选）
        priority: 优先级 (critical/high/medium/low)
        confidence: 信心值 0-1（可选）
    """
    try:
        await post(
            "/messages/push",
            json={
                "msg_type": msg_type,
                "title": title,
                "summary": summary,
                "symbol": symbol or None,
                "action_advice": action_advice or None,
                "risk_note": risk_note or None,
                "priority": priority,
                "confidence": confidence,
            },
            timeout=10,
        )
        return f"消息已推送: {title}"
    except Exception as exc:
        return f"推送失败: {exc}"


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

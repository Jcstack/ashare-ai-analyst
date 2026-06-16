"""Build context summaries for multi-turn follow-up conversations.

Each function returns ``(context_summary, thread_context_kwargs)`` where
*context_summary* is a Chinese-language text string summarising the command
result, and *thread_context_kwargs* is a dict suitable for constructing a
``ThreadContext`` instance.
"""

from __future__ import annotations

from typing import Any


def stock_context(
    symbol: str,
    analysis: dict[str, Any] | None,
    quote: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    """Context from ``/stock`` analysis result."""
    parts = [f"个股分析: {symbol}"]

    if analysis:
        signal = analysis.get("signal", "")
        if signal:
            parts.append(f"信号: {signal}")
        summary = analysis.get("summary", "")
        if summary:
            parts.append(summary[:300])
        risks = analysis.get("risks", [])
        if risks:
            parts.append("风险: " + "; ".join(str(r) for r in risks[:3]))

    if quote:
        price = quote.get("price") or quote.get("current_price")
        pct = quote.get("pct_change") or quote.get("change_pct")
        if price is not None:
            parts.append(f"价格: {price}")
        if pct is not None:
            parts.append(f"涨跌幅: {pct}%")

    ctx_summary = "\n".join(parts)
    kwargs: dict[str, Any] = {"symbol": symbol, "mode": "stock"}
    return ctx_summary, kwargs


def recommend_context(
    recs: list[dict[str, Any]],
    style: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Context from ``/recommend`` result."""
    parts = ["AI推荐股票"]
    if style:
        parts[0] += f" (风格: {style})"

    for rec in recs[:5]:
        symbol = rec.get("symbol", rec.get("code", ""))
        name = rec.get("name", rec.get("stock_name", ""))
        score = rec.get("score", rec.get("total_score", ""))
        parts.append(f"- {symbol} {name} 评分:{score}")

    return "\n".join(parts), {"mode": "market"}


def market_context(indices: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Context from ``/market`` indices data."""
    parts = ["大盘概览"]
    for idx in indices[:4]:
        name = idx.get("name", idx.get("index_name", ""))
        price = idx.get("price", idx.get("close", ""))
        pct = idx.get("pct_change", idx.get("change_pct", ""))
        parts.append(f"- {name}: {price} ({pct}%)")

    return "\n".join(parts), {"mode": "market"}


def flow_context(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Context from ``/flow`` capital flow data."""
    parts = ["资金面概览"]

    signal = data.get("signal", "")
    if signal:
        parts.append(f"信号: {signal}")
    score = data.get("score", data.get("composite_score"))
    if score is not None:
        parts.append(f"综合评分: {score}")
    nb = data.get("northbound", data.get("northbound_flow"))
    if nb is not None:
        parts.append(f"北向资金: {nb}")
    interp = data.get("interpretation", "")
    if interp:
        parts.append(interp[:200])

    return "\n".join(parts), {"mode": "market"}


def portfolio_context(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Context from ``/portfolio`` diagnosis."""
    parts = ["持仓诊断"]

    health = data.get("health_score")
    if health is not None:
        parts.append(f"健康评分: {health}")
    pnl = data.get("total_pnl") or data.get("pnl")
    if pnl is not None:
        parts.append(f"盈亏: {pnl}")

    positions = data.get("positions", [])
    for pos in positions[:5]:
        sym = pos.get("symbol", "")
        name = pos.get("name", pos.get("stock_name", ""))
        p = pos.get("pnl", pos.get("profit", ""))
        parts.append(f"- {sym} {name} 盈亏:{p}")

    warnings = data.get("warnings", [])
    if warnings:
        parts.append("警告: " + "; ".join(str(w) for w in warnings[:3]))

    symbols = [p.get("symbol", "") for p in positions[:5] if p.get("symbol")]
    kwargs: dict[str, Any] = {"mode": "portfolio"}
    if symbols:
        kwargs["matched_portfolio_symbols"] = symbols
    return "\n".join(parts), kwargs


def intel_context(
    items: list[dict[str, Any]],
    query: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Context from ``/intel`` feed."""
    parts = ["情报动态"]
    if query:
        parts[0] += f" (搜索: {query})"

    item_ids = []
    for item in items[:3]:
        title = item.get("title", "")
        parts.append(f"- {title}")
        iid = item.get("id")
        if iid:
            item_ids.append(str(iid))

    kwargs: dict[str, Any] = {"mode": "general"}
    if item_ids:
        kwargs["intel_item_ids"] = item_ids
    return "\n".join(parts), kwargs


def sentiment_context(
    data: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Context from ``/sentiment`` or ``/pulse`` result."""
    parts = ["舆情分析"]

    outlook = data.get("overall_outlook", "")
    if outlook:
        parts.append(str(outlook)[:200])

    trends = data.get("core_trends", [])
    for t in trends[:3]:
        if isinstance(t, str):
            parts.append(f"- {t}")
        elif isinstance(t, dict):
            parts.append(f"- {t.get('title', str(t))}")

    risks = data.get("risk_alerts", [])
    for r in risks[:2]:
        if isinstance(r, str):
            parts.append(f"- 风险: {r}")
        elif isinstance(r, dict):
            parts.append(f"- 风险: {r.get('title', str(r))}")

    # For pulse data
    hot = data.get("hot_events", [])
    for ev in hot[:3]:
        if isinstance(ev, str):
            parts.append(f"- 热点: {ev}")
        elif isinstance(ev, dict):
            parts.append(f"- 热点: {ev.get('title', str(ev))}")

    return "\n".join(parts), {"mode": "market"}


def global_market_context(
    snapshot: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Context from ``/global`` market snapshot."""
    parts = ["全球市场概览"]

    for idx in snapshot.get("indices", [])[:4]:
        name = idx.get("name", "")
        pct = idx.get("pct_change", "")
        parts.append(f"- {name}: {pct}%")

    for c in snapshot.get("commodities", [])[:2]:
        name = c.get("name", "")
        pct = c.get("pct_change", "")
        parts.append(f"- {name}: {pct}%")

    return "\n".join(parts), {"mode": "market"}


def concept_context(
    boards: list[Any],
    limit: int = 10,
) -> tuple[str, dict[str, Any]]:
    """Context from ``/concept`` board data."""
    parts = ["概念板块热度"]

    for board in boards[: min(limit, 5)]:
        if isinstance(board, dict):
            name = board.get("name", "")
            pct = board.get("pct_change", 0)
        else:
            name = getattr(board, "name", "")
            pct = getattr(board, "pct_change", 0)
        parts.append(f"- {name}: {pct}%")

    return "\n".join(parts), {"mode": "market"}


def nl_context(
    intent: str,
    ctx: dict[str, Any],
    result_data: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Delegate to the matching builder based on NL intent."""
    if intent == "stock_analysis" and result_data:
        return stock_context(
            ctx.get("symbol", ""),
            result_data.get("analysis"),
            result_data.get("quote"),
        )
    if intent == "recommend" and result_data:
        return recommend_context(
            result_data if isinstance(result_data, list) else [], None
        )
    if intent == "market_overview" and result_data:
        return market_context(result_data if isinstance(result_data, list) else [])
    if intent == "flow" and result_data:
        return flow_context(result_data if isinstance(result_data, dict) else {})
    if intent == "portfolio" and result_data:
        return portfolio_context(result_data if isinstance(result_data, dict) else {})
    if intent == "intel" and result_data:
        items = result_data.get("items", []) if isinstance(result_data, dict) else []
        return intel_context(items, ctx.get("query"))
    # Fallback for agent_qa or unknown
    return ctx.get("question", "自由问答"), {"mode": "general"}

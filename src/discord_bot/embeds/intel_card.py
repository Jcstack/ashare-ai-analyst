"""Build Discord embeds for intelligence feed items and reports."""

from __future__ import annotations

from typing import Any

import discord

_PRIORITY_COLOR: dict[str, int] = {
    "breaking": 0xFF1744,
    "high": 0xFF9100,
    "normal": 0x2196F3,
    "low": 0x9E9E9E,
}

_CATEGORY_BADGE: dict[str, str] = {
    "policy": "🏛️",
    "macro": "🌐",
    "industry": "🏭",
    "company": "🏢",
    "market": "📈",
    "global": "🌍",
    "social": "💬",
    "community": "👥",
}

_CATEGORY_LABEL: dict[str, str] = {
    "policy": "政策",
    "macro": "宏观",
    "industry": "行业",
    "company": "公司",
    "market": "市场",
    "global": "全球",
    "social": "社交",
    "community": "社区",
}


def build_intel_embed(
    items: list[dict[str, Any]],
    *,
    category: str | None = None,
    query: str | None = None,
    total: int | None = None,
) -> discord.Embed:
    """Build an embed listing intelligence feed items for ``/intel``.

    Args:
        items: ``feed["items"]`` from ``IntelligenceHubService.get_feed()``.
        category: Active category filter (for title).
        query: Active search query (for title).
        total: Total items count from the feed response.
    """
    # Build dynamic title
    title_parts = ["🔍 情报中心"]
    if category:
        label = _CATEGORY_LABEL.get(category, category)
        title_parts.append(f"— {label}")
    if query:
        title_parts.append(f'"{query}"')

    embed = discord.Embed(title=" ".join(title_parts), color=0x2196F3)

    if not items:
        embed.description = "暂无情报"
        return embed

    if total is not None and total > len(items):
        embed.description = f"共 {total} 条，显示最新 {len(items)} 条"

    for item in items[:12]:
        title_text = item.get("title", "无标题")
        summary = item.get("summary", "")[:300]
        priority = item.get("priority", "normal")
        cat = item.get("category", "market")
        source = item.get("source_name", "")
        symbols = item.get("related_symbols", [])
        score = item.get("content_score")

        # Category badge + priority indicator
        cat_badge = _CATEGORY_BADGE.get(cat, "📄")
        pri_badge = "🔴" if priority in ("breaking", "high") else ""

        meta_parts: list[str] = []
        cat_label = _CATEGORY_LABEL.get(cat, cat)
        meta_parts.append(cat_label)
        if source:
            meta_parts.append(source)
        if symbols:
            meta_parts.append(" ".join(symbols[:3]))
        if score is not None:
            try:
                meta_parts.append(f"评分 {float(score):.1f}")
            except (ValueError, TypeError):
                meta_parts.append(f"评分 {score}")
        meta = " | ".join(meta_parts)

        value = f"{summary}\n_{meta}_" if meta else summary
        field_name = f"{pri_badge}{cat_badge} {title_text}"[:256]
        embed.add_field(name=field_name, value=value[:1024], inline=False)

    embed.set_footer(text="情报中心 | A股分析师")
    return embed


def build_intel_overview_embed(overview: dict[str, Any]) -> discord.Embed:
    """Build an embed showing intel category overview stats."""
    embed = discord.Embed(title="🔍 情报中心 — 分类概览", color=0x2196F3)

    total = overview.get("total_items", 0)
    sources = overview.get("sources_count", 0)
    embed.description = f"**{total}** 条情报 · **{sources}** 个来源"

    categories = overview.get("categories", {})
    if categories:
        lines: list[str] = []
        for cat, stats in categories.items():
            badge = _CATEGORY_BADGE.get(cat, "📄")
            label = _CATEGORY_LABEL.get(cat, cat)
            cat_total = stats.get("total", 0) if isinstance(stats, dict) else stats
            unread = stats.get("unread", 0) if isinstance(stats, dict) else 0
            line = f"{badge} **{label}**: {cat_total} 条"
            if unread:
                line += f" ({unread} 未读)"
            lines.append(line)
        embed.add_field(name="分类统计", value="\n".join(lines), inline=False)

    embed.set_footer(text="使用 /intel category:<分类> 查看具体分类 | A股分析师")
    return embed


def build_intel_clusters_embed(clusters: list[dict[str, Any]]) -> discord.Embed:
    """Build an embed for event clusters (cross-source verification)."""
    embed = discord.Embed(title="🔗 热点事件聚合", color=0xFF9100)

    if not clusters:
        embed.description = "暂无热点事件聚合"
        return embed

    for cluster in clusters[:8]:
        title = cluster.get("representative_title", "无标题")
        sources_count = cluster.get("unique_sources", 0)
        score = cluster.get("cross_verification_score", 0)
        items = cluster.get("items", [])

        lines: list[str] = []
        lines.append(f"📰 {sources_count} 个来源 · 交叉验证 {score:.0%}")
        if items:
            for it in items[:3]:
                src = it.get("source_name", "")
                lines.append(f"  • {src}: {it.get('title', '')[:60]}")

        embed.add_field(
            name=title[:256],
            value="\n".join(lines)[:1024],
            inline=False,
        )

    embed.set_footer(text="多源交叉验证 | A股分析师")
    return embed


def build_report_embed(report: dict[str, Any]) -> discord.Embed:
    """Build a single intel analysis report embed."""
    symbol = report.get("symbol", "???")
    name = report.get("stock_name", symbol)
    action = report.get("action", "hold")
    signal = report.get("signal", "neutral")
    confidence = report.get("confidence", 0.5)

    # Color by signal
    if signal == "bullish":
        colour = 0x00C853
    elif signal == "bearish":
        colour = 0xFF1744
    else:
        colour = 0x9E9E9E

    action_labels = {
        "buy": "买入",
        "sell": "卖出",
        "hold": "持有",
        "strong_buy": "强烈买入",
        "strong_sell": "强烈卖出",
    }
    action_label = action_labels.get(action, action)

    embed = discord.Embed(
        title=f"📋 {name}({symbol}) — 情报分析",
        color=colour,
    )

    # Summary
    summary = report.get("summary", "")
    if summary:
        embed.description = summary[:4096]

    # Key metrics
    try:
        conf_str = f"{float(confidence):.0%}"
    except (ValueError, TypeError):
        conf_str = str(confidence)
    embed.add_field(name="操作建议", value=f"**{action_label}**", inline=True)
    embed.add_field(name="信号", value=signal, inline=True)
    embed.add_field(name="置信度", value=conf_str, inline=True)

    # Factors
    factors = report.get("factors", [])
    if factors:
        factor_lines: list[str] = []
        for f in factors[:8]:
            if isinstance(f, dict):
                cat = f.get("category", "")
                impact = f.get("impact", "")
                desc = f.get("description", "")[:60]
                factor_lines.append(f"• [{cat}] {impact}: {desc}")
            else:
                factor_lines.append(f"• {str(f)[:80]}")
        embed.add_field(
            name="分析因素", value="\n".join(factor_lines)[:1024], inline=False
        )

    # Risk warnings
    warnings = report.get("risk_warnings", [])
    if warnings:
        embed.add_field(
            name="风险提示",
            value="\n".join(f"⚠️ {w}" for w in warnings[:5])[:1024],
            inline=False,
        )

    # Outlook
    outlook = report.get("outlook", "")
    if outlook:
        embed.add_field(name="前景展望", value=str(outlook)[:1024], inline=False)

    embed.set_footer(text="情报分析 · 仅供参考 | A股分析师")
    return embed


def build_report_list_embed(
    reports: list[dict[str, Any]], total: int = 0
) -> discord.Embed:
    """Build an embed listing multiple intel reports."""
    embed = discord.Embed(title="📋 情报分析报告", color=0x2196F3)

    if not reports:
        embed.description = "暂无分析报告"
        return embed

    if total > len(reports):
        embed.description = f"共 {total} 份报告，显示最新 {len(reports)} 份"

    for rpt in reports[:10]:
        symbol = rpt.get("symbol", "???")
        name = rpt.get("stock_name", symbol)
        action = rpt.get("action", "hold")
        signal = rpt.get("signal", "neutral")
        confidence = rpt.get("confidence", 0.5)
        summary = rpt.get("summary", "")[:100]
        is_read = rpt.get("is_read", False)

        action_labels = {
            "buy": "买入",
            "sell": "卖出",
            "hold": "持有",
            "strong_buy": "强烈买入",
            "strong_sell": "强烈卖出",
        }
        action_label = action_labels.get(action, action)

        try:
            conf_str = f"{float(confidence):.0%}"
        except (ValueError, TypeError):
            conf_str = str(confidence)

        signal_emoji = (
            "🟢" if signal == "bullish" else "🔴" if signal == "bearish" else "⚪"
        )
        read_mark = "" if is_read else "🆕 "

        header = f"{read_mark}{signal_emoji} {name}({symbol})"
        value = f"**{action_label}** · 置信度 {conf_str}\n{summary}"

        embed.add_field(name=header[:256], value=value[:1024], inline=False)

    embed.set_footer(text="情报分析 · 仅供参考 | A股分析师")
    return embed

"""Build Discord embeds for sentiment / market pulse data."""

from __future__ import annotations

from typing import Any

import discord


def build_sentiment_embed(report: dict[str, Any]) -> discord.Embed:
    """Build a rich embed for ``SentimentService.get_sentiment_report()``.

    Renders: overall_outlook, core_trends, policy_signals, risk_alerts,
    sector_outlook.
    """
    outlook = report.get("overall_outlook", "")
    status = report.get("status", "ok")

    if status != "ok":
        embed = discord.Embed(
            title="📊 市场舆情分析",
            description=report.get("message", "舆情数据暂不可用"),
            color=0x9E9E9E,
        )
        return embed

    # Pick colour from outlook text
    if any(w in str(outlook) for w in ("乐观", "偏多", "看涨", "积极")):
        colour = 0x00C853
    elif any(w in str(outlook) for w in ("悲观", "偏空", "看跌", "谨慎")):
        colour = 0xFF1744
    else:
        colour = 0x2196F3

    embed = discord.Embed(
        title="📊 市场舆情分析",
        description=str(outlook)[:4096] if outlook else None,
        color=colour,
    )

    # Core trends
    trends = report.get("core_trends", [])
    if trends:
        lines = [
            f"• {t}" if isinstance(t, str) else f"• {t.get('title', str(t))}"
            for t in trends[:6]
        ]
        embed.add_field(name="核心趋势", value="\n".join(lines)[:1024], inline=False)

    # Policy signals
    policies = report.get("policy_signals", [])
    if policies:
        lines = [
            f"• {p}" if isinstance(p, str) else f"• {p.get('title', str(p))}"
            for p in policies[:5]
        ]
        embed.add_field(name="政策信号", value="\n".join(lines)[:1024], inline=False)

    # Risk alerts
    risks = report.get("risk_alerts", [])
    if risks:
        lines = [
            f"⚠️ {r}" if isinstance(r, str) else f"⚠️ {r.get('title', str(r))}"
            for r in risks[:5]
        ]
        embed.add_field(name="风险提示", value="\n".join(lines)[:1024], inline=False)

    # Sector outlook
    sectors = report.get("sector_outlook", [])
    if sectors:
        lines = [
            f"• {s}"
            if isinstance(s, str)
            else f"• {s.get('sector', '')}: {s.get('outlook', str(s))}"
            for s in sectors[:6]
        ]
        embed.add_field(name="板块展望", value="\n".join(lines)[:1024], inline=False)

    embed.set_footer(text="舆情分析 · 仅供参考 | A股分析师")
    return embed


def build_pulse_embed(pulse: dict[str, Any]) -> discord.Embed:
    """Build a rich embed for ``SentimentService.get_market_pulse()``.

    Renders: hot_events, holdings_news, global_snapshot.
    """
    status = pulse.get("status", "ok")

    if status != "ok":
        embed = discord.Embed(
            title="💓 市场脉搏",
            description=pulse.get("message", "脉搏数据暂不可用"),
            color=0x9E9E9E,
        )
        return embed

    embed = discord.Embed(title="💓 市场脉搏", color=0xFF9100)

    # Hot events
    hot = pulse.get("hot_events", [])
    if hot:
        lines: list[str] = []
        for ev in hot[:8]:
            if isinstance(ev, str):
                lines.append(f"🔥 {ev}")
            else:
                title = ev.get("title", str(ev))
                heat = ev.get("heat_score", "")
                heat_str = (
                    f" ({heat:.0f})" if isinstance(heat, (int, float)) and heat else ""
                )
                lines.append(f"🔥 {title}{heat_str}")
        embed.add_field(name="热点事件", value="\n".join(lines)[:1024], inline=False)

    # Holdings news
    holdings = pulse.get("holdings_news", {})
    if isinstance(holdings, dict):
        items = holdings.get("items", holdings.get("news", []))
        if items:
            lines = []
            for item in items[:5]:
                if isinstance(item, str):
                    lines.append(f"• {item}")
                else:
                    lines.append(f"• {item.get('title', str(item))}")
            embed.add_field(
                name="持仓相关新闻", value="\n".join(lines)[:1024], inline=False
            )

    # Global snapshot summary
    gs = pulse.get("global_snapshot", {})
    if isinstance(gs, dict) and gs:
        parts: list[str] = []
        for idx in gs.get("indices", [])[:4]:
            name = idx.get("name", "")
            pct = idx.get("pct_change", 0)
            arrow = "📈" if pct > 0 else "📉" if pct < 0 else "➡️"
            parts.append(f"{arrow} {name}: {pct:+.2f}%")
        if parts:
            embed.add_field(
                name="全球市场", value="\n".join(parts)[:1024], inline=False
            )

    generated = pulse.get("generated_at", "")
    footer = "市场脉搏 | A股分析师"
    if generated:
        footer = f"{generated} · {footer}"
    embed.set_footer(text=footer)
    return embed

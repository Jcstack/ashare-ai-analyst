"""Build Discord embed for portfolio diagnosis."""

from __future__ import annotations

from typing import Any

import discord

_GREEN = 0x00C853
_RED = 0xFF1744
_ORANGE = 0xFF9100
_GRAY = 0x9E9E9E


def build_portfolio_embed(data: dict[str, Any]) -> discord.Embed:
    """Build a portfolio diagnosis embed for ``/portfolio``.

    Args:
        data: Result from ``PortfolioService`` or agent analysis.
              Expected keys vary; the builder is defensive.
    """
    health = data.get("health_score") or data.get("score")
    if health is not None:
        if health >= 70:
            colour = _GREEN
        elif health >= 40:
            colour = _ORANGE
        else:
            colour = _RED
    else:
        colour = _GRAY

    embed = discord.Embed(title="📂 持仓诊断", color=colour)

    if health is not None:
        embed.add_field(name="健康评分", value=f"**{health:.0f}** / 100", inline=True)

    total_value = data.get("total_value") or data.get("total_market_value")
    if total_value is not None:
        embed.add_field(name="总市值", value=f"¥{total_value:,.0f}", inline=True)

    pnl = data.get("total_pnl") or data.get("unrealized_pnl")
    if pnl is not None:
        pnl_str = f"{'🟢' if pnl >= 0 else '🔴'} ¥{pnl:+,.0f}"
        embed.add_field(name="浮动盈亏", value=pnl_str, inline=True)

    # Position summaries
    positions = data.get("positions", [])
    if positions:
        lines: list[str] = []
        for pos in positions[:8]:
            sym = pos.get("symbol", "?")
            name = pos.get("name", sym)
            pct = pos.get("pnl_pct", 0)
            lines.append(f"• {name}({sym}) {pct:+.1f}%")
        embed.add_field(name="持仓明细", value="\n".join(lines)[:1024], inline=False)

    # Risk warnings
    warnings = data.get("risk_warnings", data.get("warnings", []))
    if warnings:
        embed.add_field(
            name="风险提示",
            value="\n".join(f"⚠️ {w}" for w in warnings[:5]),
            inline=False,
        )

    advice = data.get("position_advice", data.get("advice", ""))
    if advice:
        embed.add_field(name="建议", value=str(advice)[:1024], inline=False)

    embed.set_footer(text="仅供参考，不构成投资建议 | A股分析师")
    return embed

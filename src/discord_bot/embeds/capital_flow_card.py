"""Build Discord embed for macro capital flow overview."""

from __future__ import annotations

from typing import Any

import discord

_GREEN = 0x00C853
_RED = 0xFF1744
_GRAY = 0x9E9E9E
_ORANGE = 0xFF9100


def build_capital_flow_embed(data: dict[str, Any]) -> discord.Embed:
    """Build an embed for ``/flow`` from ``get_macro_overview()`` result.

    Args:
        data: Dict from ``CapitalFlowService.get_macro_overview()``.
    """
    signal = str(data.get("signal", "neutral")).lower()
    try:
        score = float(data.get("environment_score", 0))
    except (ValueError, TypeError):
        score = 0.0

    if signal == "bullish":
        colour = _GREEN
    elif signal == "bearish":
        colour = _RED
    else:
        colour = _GRAY

    title = f"💰 资金面概览 — {data.get('date', '今日')}"
    embed = discord.Embed(title=title, color=colour)
    embed.add_field(name="环境评分", value=f"**{score:.1f}**", inline=True)
    embed.add_field(name="信号", value=signal.upper(), inline=True)

    nb = data.get("northbound_net")
    if nb is not None:
        embed.add_field(name="北向净流入", value=f"{nb:+.2f} 亿", inline=True)

    margin = data.get("margin_balance")
    if margin is not None:
        embed.add_field(name="融资余额", value=f"{margin:.0f} 亿", inline=True)

    etf = data.get("etf_net_flow")
    if etf is not None:
        embed.add_field(name="ETF净流入", value=f"{etf:+.2f} 亿", inline=True)

    interp = data.get("interpretation", "")
    if interp:
        embed.add_field(name="解读", value=interp[:1024], inline=False)

    warnings = data.get("warnings", [])
    if warnings:
        embed.add_field(
            name="预警",
            value="\n".join(f"⚠️ {w}" for w in warnings[:5]),
            inline=False,
        )

    embed.set_footer(text="资金面分析 | A股分析师")
    return embed

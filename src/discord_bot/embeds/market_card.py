"""Build Discord embed for market overview."""

from __future__ import annotations

from typing import Any

import discord

_GREEN = 0x00C853
_RED = 0xFF1744
_GRAY = 0x9E9E9E


def build_market_embed(indices: list[dict[str, Any]]) -> discord.Embed:
    """Build a market overview embed from index data.

    Args:
        indices: List from ``MarketService.get_market_indices()``.
    """
    embed = discord.Embed(title="📊 A股大盘概览", color=0x2196F3)

    if not indices:
        embed.description = "行情数据暂不可用"
        return embed

    for idx in indices[:6]:
        name = idx.get("name", "?")
        price = idx.get("price", 0)
        pct = idx.get("pct_change", 0) or 0
        change = idx.get("change", 0) or 0

        arrow = "🟢" if pct > 0 else "🔴" if pct < 0 else "⚪"
        val_str = f"{arrow} **{price:.2f}**  {change:+.2f} ({pct:+.2f}%)"
        embed.add_field(name=name, value=val_str, inline=True)

    embed.set_footer(text="实时行情 | A股分析师")
    return embed

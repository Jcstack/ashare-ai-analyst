"""Build Discord embed for global market overview."""

from __future__ import annotations

from typing import Any

import discord


def _fmt_change(pct: Any) -> str:
    """Format a percentage change with direction emoji."""
    try:
        val = float(pct)
    except (TypeError, ValueError):
        return str(pct)
    if val > 0:
        return f"📈 +{val:.2f}%"
    if val < 0:
        return f"📉 {val:.2f}%"
    return f"➡️ {val:.2f}%"


def _fmt_price(price: Any) -> str:
    try:
        p = float(price)
        return f"{p:,.2f}" if p < 100_000 else f"{p:,.0f}"
    except (TypeError, ValueError):
        return str(price) if price else "—"


def build_global_market_embed(snapshot: dict[str, Any]) -> discord.Embed:
    """Build a global market overview embed.

    Args:
        snapshot: Result from ``GlobalMarketFetcher.fetch_global_snapshot()``.
            Keys: ``indices``, ``commodities``, ``currencies``.
    """
    embed = discord.Embed(title="🌍 全球市场概览", color=0x2196F3)

    # Indices
    indices = snapshot.get("indices", [])
    if indices:
        lines: list[str] = []
        for idx in indices[:8]:
            name = idx.get("name", "")
            price = _fmt_price(idx.get("price"))
            pct = _fmt_change(idx.get("pct_change", 0))
            lines.append(f"**{name}**: {price} ({pct})")
        embed.add_field(name="📊 主要指数", value="\n".join(lines)[:1024], inline=False)

    # Commodities
    commodities = snapshot.get("commodities", [])
    if commodities:
        lines = []
        for c in commodities[:6]:
            name = c.get("name", "")
            price = _fmt_price(c.get("price"))
            pct = _fmt_change(c.get("pct_change", 0))
            unit = c.get("unit", "")
            unit_str = f" {unit}" if unit else ""
            lines.append(f"**{name}**: {price}{unit_str} ({pct})")
        embed.add_field(name="🏷️ 商品", value="\n".join(lines)[:1024], inline=False)

    # Currencies
    currencies = snapshot.get("currencies", [])
    if currencies:
        lines = []
        for cur in currencies[:6]:
            name = cur.get("name", "")
            price = _fmt_price(cur.get("price"))
            pct = _fmt_change(cur.get("pct_change", 0))
            lines.append(f"**{name}**: {price} ({pct})")
        embed.add_field(name="💱 汇率", value="\n".join(lines)[:1024], inline=False)

    if not indices and not commodities and not currencies:
        embed.description = "全球市场数据暂不可用"

    embed.set_footer(text="全球市场 | A股分析师")
    return embed

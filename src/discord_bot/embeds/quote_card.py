"""Build Discord embed for a single realtime quote."""

from __future__ import annotations

from typing import Any

import discord

_GREEN = 0x00C853
_RED = 0xFF1744
_GRAY = 0x9E9E9E


def build_quote_embed(quote: dict[str, Any]) -> discord.Embed:
    """Build a compact quote embed for ``/quote`` results.

    Args:
        quote: Dict from ``get_single_quote()`` or ``get_quotes()``.
    """
    symbol = quote.get("symbol", "???")
    name = quote.get("name", symbol)
    price = quote.get("price") or quote.get("close")
    pct = quote.get("pct_change", 0) or 0

    if pct > 0:
        colour = _GREEN
    elif pct < 0:
        colour = _RED
    else:
        colour = _GRAY

    pct_str = f"{pct:+.2f}%"
    title = f"{'🟢' if pct > 0 else '🔴' if pct < 0 else '⚪'} {name} ({symbol})"
    desc = f"**{price:.2f}**  {pct_str}" if price is not None else "行情暂不可用"

    embed = discord.Embed(title=title, description=desc, color=colour)

    for label, key in [
        ("开盘", "open"),
        ("最高", "high"),
        ("最低", "low"),
        ("昨收", "prev_close"),
    ]:
        val = quote.get(key)
        if val is not None:
            embed.add_field(name=label, value=f"{val:.2f}", inline=True)

    vol = quote.get("volume")
    if vol:
        vol_str = f"{vol / 10000:.0f}万" if vol >= 10000 else str(int(vol))
        embed.add_field(name="成交量", value=vol_str, inline=True)

    amt = quote.get("amount")
    if amt:
        amt_str = f"{amt / 1e8:.2f}亿" if amt >= 1e8 else f"{amt / 1e4:.0f}万"
        embed.add_field(name="成交额", value=amt_str, inline=True)

    embed.set_footer(text="实时行情 | A股分析师")
    return embed

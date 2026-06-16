"""Build Discord embed for comprehensive stock analysis."""

from __future__ import annotations

from typing import Any

import discord

# Colour constants (matching config/discord.yaml)
_GREEN = 0x00C853
_RED = 0xFF1744
_GRAY = 0x9E9E9E

_SIGNAL_MAP: dict[str, tuple[str, int]] = {
    "buy": ("买入", _GREEN),
    "strong_buy": ("强烈买入", _GREEN),
    "sell": ("卖出", _RED),
    "strong_sell": ("强烈卖出", _RED),
    "neutral": ("观望", _GRAY),
    "hold": ("持有", _GRAY),
}


def build_stock_embed(
    analysis: dict[str, Any],
    quote: dict[str, Any] | None = None,
) -> discord.Embed:
    """Build a rich embed card for ``/stock`` command results.

    Args:
        analysis: Result from ``analyze_comprehensive_realtime()``.
        quote: Optional realtime quote dict.
    """
    symbol = analysis.get("symbol", "???")
    signal_raw = str(analysis.get("signal", "neutral")).lower()
    label, colour = _SIGNAL_MAP.get(signal_raw, ("观望", _GRAY))

    title = f"{'📈' if colour == _GREEN else '📉' if colour == _RED else '📊'} {symbol} — {label}"
    summary = analysis.get("summary", "暂无摘要")

    embed = discord.Embed(title=title, description=summary[:4096], color=colour)

    # Quote snapshot
    if quote:
        price = quote.get("price") or quote.get("close")
        pct = quote.get("pct_change", 0)
        vol = quote.get("volume", 0)
        if price is not None:
            pct_str = f"{pct:+.2f}%" if pct else "—"
            embed.add_field(name="现价", value=f"{price:.2f} ({pct_str})", inline=True)
        if vol:
            vol_str = f"{vol / 10000:.0f}万" if vol >= 10000 else str(vol)
            embed.add_field(name="成交量", value=vol_str, inline=True)

    # Risk warnings
    risks = analysis.get("risks", [])
    if risks:
        embed.add_field(
            name="风险提示",
            value="\n".join(f"• {r}" for r in risks[:8])[:1024],
            inline=False,
        )

    # Analysis points
    points = analysis.get("points", [])
    if points:
        pts_text = "\n".join(
            f"• {p}" if isinstance(p, str) else f"• {p.get('text', str(p))}"
            for p in points[:10]
        )
        embed.add_field(name="分析要点", value=pts_text[:1024], inline=False)

    embed.set_footer(text="仅供参考，不构成投资建议 | A股分析师")
    return embed

"""Discord embed builder for assistant inbox messages (plain language)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import discord

# Color mapping per message type
_TYPE_COLORS: dict[str, int] = {
    "buy_signal": 0x22C55E,  # green
    "sell_signal": 0xEF4444,  # red
    "risk_alert": 0xF59E0B,  # amber
    "market_watch": 0x3B82F6,  # blue
}

# Emoji badge per type
_TYPE_BADGES: dict[str, str] = {
    "buy_signal": "📈",
    "sell_signal": "📉",
    "risk_alert": "🚨",
    "market_watch": "📰",
}

_DEFAULT_COLOR = 0x9E9E9E


def build_assistant_message_embed(message: dict[str, Any]) -> discord.Embed:
    """Convert a plain-language assistant message to a Discord embed.

    Expected *message* keys:
        type: str — buy_signal | sell_signal | risk_alert | market_watch
        title: str — e.g. "建议买入 比亚迪(002594)"
        summary: str — plain-language explanation
        action_advice: str — what user should do
        risk_note: str — risk callout
        symbol: str (optional) — stock symbol
        impact: str (optional) — HIGH / MEDIUM / LOW (for market_watch)
        timestamp: str (optional) — ISO timestamp
    """
    msg_type = message.get("type", "")
    color = _TYPE_COLORS.get(msg_type, _DEFAULT_COLOR)
    badge = _TYPE_BADGES.get(msg_type, "💬")

    title = message.get("title", "投资助手消息")
    summary = message.get("summary", "")

    embed = discord.Embed(
        title=f"{badge} {title}",
        description=summary[:4096] if summary else None,
        color=color,
    )

    # -- 操作建议 --
    action_advice = message.get("action_advice")
    if action_advice:
        embed.add_field(
            name="操作建议",
            value=str(action_advice)[:1024],
            inline=False,
        )

    # -- 风险提示 --
    risk_note = message.get("risk_note")
    if risk_note:
        embed.add_field(
            name="风险提示",
            value=str(risk_note)[:1024],
            inline=False,
        )

    # -- 标的 --
    symbol = message.get("symbol")
    if symbol:
        name = message.get("name", "")
        label = f"{name} ({symbol})" if name else symbol
        embed.add_field(name="标的", value=label, inline=True)

    # -- 影响级别 (market_watch only) --
    impact = message.get("impact")
    if impact:
        embed.add_field(name="影响级别", value=str(impact), inline=True)

    # -- Timestamp footer --
    ts = message.get("timestamp")
    if ts:
        footer_text = f"投资助手 | {ts}"
    else:
        footer_text = f"投资助手 | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    embed.set_footer(text=footer_text)

    return embed

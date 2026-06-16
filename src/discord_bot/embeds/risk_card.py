"""Build Discord embed for risk alert notifications."""

from __future__ import annotations

from typing import Any

import discord

_SEVERITY_COLOR: dict[str, int] = {
    "critical": 0xFF1744,
    "high": 0xFF9100,
    "medium": 0x9E9E9E,
    "low": 0x2196F3,
}


def build_risk_embed(payload: dict[str, Any]) -> discord.Embed:
    """Build a risk alert embed from a push notification payload.

    Args:
        payload: Notification dict with type ``risk_alert``.
    """
    severity = str(payload.get("severity", "medium")).lower()
    colour = _SEVERITY_COLOR.get(severity, 0xFF9100)
    title = payload.get("title", "风险预警")
    summary = payload.get("summary", payload.get("message", ""))

    embed = discord.Embed(
        title=f"🚨 {title}",
        description=summary[:4096] if summary else "无详情",
        color=colour,
    )

    if payload.get("symbol"):
        embed.add_field(name="标的", value=payload["symbol"], inline=True)
    if payload.get("level"):
        embed.add_field(name="级别", value=payload["level"], inline=True)

    embed.set_footer(text="风险预警 | A股分析师")
    return embed

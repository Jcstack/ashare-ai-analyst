"""Build Discord embed for stock recommendations."""

from __future__ import annotations

from typing import Any

import discord

_GREEN = 0x00C853
_RED = 0xFF1744
_GRAY = 0x9E9E9E

_STYLE_LABELS: dict[str, str] = {
    "value": "价值",
    "growth": "成长",
    "momentum": "动量",
    "reversal": "反转",
    "dividend": "红利",
    "balanced": "均衡",
}

_CONFIDENCE_LABELS: dict[str, str] = {
    "high": "高",
    "medium": "中",
    "low": "低",
}


def _safe_float(val: Any, fmt: str = ".2f") -> str | None:
    """Format a value as float, return None if not numeric."""
    if val is None:
        return None
    try:
        return f"{float(val):{fmt}}"
    except (ValueError, TypeError):
        return str(val)


def build_recommendation_embed(
    recommendations: list[dict[str, Any]],
    style: str | None = None,
) -> discord.Embed:
    """Build an embed listing top recommendations.

    Args:
        recommendations: List from ``get_recommendations()``.
        style: Optional investment style filter label.
    """
    style_label = _STYLE_LABELS.get(style or "", style or "全部")
    title = f"📋 推荐列表 — {style_label}风格"

    embed = discord.Embed(title=title, color=0x2196F3)

    if not recommendations:
        embed.description = "当前无推荐股票"
        return embed

    for rec in recommendations[:12]:
        symbol = rec.get("symbol", "???")
        name = rec.get("name", symbol)
        score = rec.get("score", 0)
        confidence = rec.get("confidence", "medium")
        entry = rec.get("entry_price")
        target = rec.get("target_price")
        stop = rec.get("stop_loss")
        reasoning = rec.get("reasoning") or rec.get("reason", "")

        # Format score — always numeric
        score_str = _safe_float(score, ".1f") or "N/A"

        # Format confidence — TEXT in DB ('high'/'medium'/'low') or numeric
        if isinstance(confidence, (int, float)):
            conf_str = f"{confidence:.0%}"
        else:
            conf_str = _CONFIDENCE_LABELS.get(str(confidence), str(confidence))

        lines = [f"评分 **{score_str}** | 置信度 {conf_str}"]

        entry_str = _safe_float(entry)
        target_str = _safe_float(target)
        stop_str = _safe_float(stop)

        price_parts: list[str] = []
        if entry_str:
            price_parts.append(f"入场 {entry_str}")
        if target_str:
            price_parts.append(f"目标 {target_str}")
        if stop_str:
            price_parts.append(f"止损 {stop_str}")
        if price_parts:
            lines.append(" → ".join(price_parts))

        if reasoning:
            lines.append(str(reasoning)[:200])

        embed.add_field(
            name=f"{name} ({symbol})",
            value="\n".join(lines)[:1024],
            inline=False,
        )

    embed.set_footer(text="仅供参考，不构成投资建议 | A股分析师")
    return embed

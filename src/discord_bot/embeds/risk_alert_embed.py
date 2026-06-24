"""Rich Discord embeds for risk alerts — thesis invalidation, regime change.

Routed to #risk-alerts channel.
"""

from __future__ import annotations

from typing import Any

import discord

_RED = 0xFF1744
_ORANGE = 0xFF9800
_YELLOW = 0xFFEB3B

_SEVERITY_COLOR: dict[str, int] = {
    "critical": _RED,
    "high": _ORANGE,
    "medium": _YELLOW,
}


def _safe_float(val: Any, fmt: str = ".2f") -> str | None:
    if val is None:
        return None
    try:
        return f"{float(val):{fmt}}"
    except (ValueError, TypeError):
        return str(val)


def _truncate(text: str, limit: int = 300) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


def build_thesis_invalidation_embed(thesis: dict[str, Any]) -> discord.Embed:
    """Build an embed for thesis invalidation alert.

    Expected *thesis* keys:
        symbol, name, confidence, initial_confidence,
        reason, suggestion
    """
    symbol: str = thesis.get("symbol", "??????")
    name: str = thesis.get("name", symbol)

    embed = discord.Embed(
        title=f"\U0001f534 **论文失效: {name} {symbol}**",
        color=_RED,
    )

    # -- Confidence drop ---------------------------------------------------
    conf = thesis.get("confidence")
    initial = thesis.get("initial_confidence")
    if conf is not None:
        conf_text = f"{float(conf):.0%}"
        if initial is not None:
            conf_text += f" \u2193 (初始: {float(initial):.0%})"
        embed.description = f"信心: {conf_text}"

    # -- Reason ------------------------------------------------------------
    reason = thesis.get("reason")
    if reason:
        embed.add_field(
            name="原因",
            value=_truncate(str(reason), 500),
            inline=False,
        )

    # -- Suggestion --------------------------------------------------------
    suggestion = thesis.get("suggestion")
    if suggestion:
        embed.add_field(
            name="\U0001f4cb 建议",
            value=_truncate(str(suggestion), 300),
            inline=False,
        )

    embed.set_footer(text="风险预警 | A股分析师")
    return embed


def build_regime_change_embed(
    old_phase: str,
    new_phase: str,
    data: dict[str, Any],
) -> discord.Embed:
    """Build an embed for sentiment regime change alert.

    Args:
        old_phase: Previous sentiment phase name.
        new_phase: New sentiment phase name.
        data: Extra context — limit_up_count, delta, portfolio_adjustment.
    """
    embed = discord.Embed(
        title=f"\u26a0\ufe0f **情绪周期变化: {old_phase} \u2192 {new_phase}**",
        color=_ORANGE,
    )

    # -- Limit-up stats ----------------------------------------------------
    limit_up = data.get("limit_up_count")
    delta = data.get("delta")
    if limit_up is not None:
        desc_parts = [f"涨停板数: {limit_up}"]
        if delta is not None:
            sign = "+" if int(delta) >= 0 else ""
            desc_parts.append(f"({sign}{delta} vs 昨日)")
        embed.description = " ".join(desc_parts)

    # -- Portfolio adjustment ----------------------------------------------
    adjustment = data.get("portfolio_adjustment")
    if adjustment:
        embed.add_field(
            name="\U0001f4cb 组合调整",
            value=_truncate(str(adjustment), 500),
            inline=False,
        )

    embed.set_footer(text="风险预警 | A股分析师")
    return embed


def build_generic_risk_embed(payload: dict[str, Any]) -> discord.Embed:
    """Build a generic risk alert embed.

    Fallback for risk alerts that don't match thesis/regime types.
    """
    severity = str(payload.get("severity", "medium")).lower()
    colour = _SEVERITY_COLOR.get(severity, _ORANGE)
    title = payload.get("title", "风险预警")
    summary = payload.get("summary", payload.get("message", ""))

    embed = discord.Embed(
        title=f"\U0001f6a8 {title}",
        description=_truncate(str(summary), 4096) if summary else "无详情",
        color=colour,
    )

    if payload.get("symbol"):
        embed.add_field(name="标的", value=payload["symbol"], inline=True)
    if payload.get("level"):
        embed.add_field(name="级别", value=payload["level"], inline=True)

    suggestion = payload.get("suggestion")
    if suggestion:
        embed.add_field(
            name="\U0001f4cb 建议",
            value=_truncate(str(suggestion), 300),
            inline=False,
        )

    embed.set_footer(text="风险预警 | A股分析师")
    return embed

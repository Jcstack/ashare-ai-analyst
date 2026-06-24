"""Rich Discord embeds for morning brief and close review.

Routed to #morning-brief and #close-review channels respectively.
"""

from __future__ import annotations

from typing import Any

import discord

_BLUE = 0x2196F3
_ORANGE = 0xFF9800

_ACTION_EMOJI: dict[str, str] = {
    "sell": "\U0001f534",  # red
    "buy": "\U0001f7e2",  # green
    "hold": "\U0001f7e2",  # green
    "watch": "\U0001f7e1",  # yellow
    "reduce": "\U0001f7e0",  # orange
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


# ---------------------------------------------------------------------------
# Morning brief
# ---------------------------------------------------------------------------


def build_morning_brief_embed(plan: dict[str, Any]) -> discord.Embed:
    """Build a rich embed for the 08:00 morning brief.

    Expected *plan* keys:
        date, weekday, sentiment_phase, hmm_state, hmm_prob,
        overnight (dict with us, cny), actions (list of dicts),
        macro_events, key_levels
    """
    date_str = plan.get("date", "")
    weekday = plan.get("weekday", "")
    title_date = f"{date_str} ({weekday})" if weekday else date_str
    title = f"\U0001f4cb **早盘计划 {title_date}**"

    embed = discord.Embed(title=title, color=_BLUE)

    # -- Sentiment / HMM header -------------------------------------------
    header_parts: list[str] = []
    phase = plan.get("sentiment_phase")
    if phase:
        header_parts.append(f"\U0001f321\ufe0f 情绪: {phase}")
    hmm_state = plan.get("hmm_state")
    hmm_prob = plan.get("hmm_prob")
    if hmm_state:
        hmm_text = f"大盘: {hmm_state}"
        if hmm_prob is not None:
            hmm_text += f" ({float(hmm_prob):.2f})"
        header_parts.append(hmm_text)
    if header_parts:
        embed.description = " | ".join(header_parts)

    # -- Overnight markets -------------------------------------------------
    overnight = plan.get("overnight")
    if overnight:
        if isinstance(overnight, dict):
            ov_parts: list[str] = []
            us = overnight.get("us")
            if us is not None:
                sign = "+" if float(us) >= 0 else ""
                ov_parts.append(f"美股{sign}{_safe_float(us, '.1f')}%")
            cny = overnight.get("cny")
            if cny is not None:
                ov_parts.append(f"人民币{cny}")
            for key in ("europe", "hk", "gold", "oil"):
                val = overnight.get(key)
                if val is not None:
                    ov_parts.append(f"{key.upper()}: {val}")
            ov_text = ", ".join(ov_parts)
        else:
            ov_text = str(overnight)
        embed.add_field(
            name="\U0001f4ca 隔夜",
            value=_truncate(ov_text, 500),
            inline=False,
        )

    # -- Macro events ------------------------------------------------------
    macro_events = plan.get("macro_events")
    if macro_events:
        if isinstance(macro_events, list):
            events_text = "\n".join(f"\u2022 {e}" for e in macro_events)
        else:
            events_text = str(macro_events)
        embed.add_field(
            name="\U0001f4c5 宏观日历",
            value=_truncate(events_text, 500),
            inline=False,
        )

    # -- Today's actions ---------------------------------------------------
    actions = plan.get("actions")
    if actions and isinstance(actions, list):
        action_lines: list[str] = []
        for i, item in enumerate(actions, 1):
            if isinstance(item, dict):
                act = item.get("action", "watch")
                name = item.get("name", item.get("symbol", "?"))
                emoji = _ACTION_EMOJI.get(act, "\u26aa")
                time_str = item.get("time", "")
                line = f"{i}. {emoji}"
                if time_str:
                    line += f" {time_str}"
                line += f" {act.upper() if act in ('sell', 'buy') else act} {name}"
                action_lines.append(line)
            else:
                action_lines.append(f"{i}. {item}")
        embed.add_field(
            name="\U0001f4cb 今日操作",
            value="\n".join(action_lines),
            inline=False,
        )

    # -- Key levels --------------------------------------------------------
    key_levels = plan.get("key_levels")
    if key_levels:
        if isinstance(key_levels, list):
            level_lines: list[str] = []
            for lvl in key_levels:
                if isinstance(lvl, dict):
                    sym = lvl.get("symbol", "?")
                    sup = _safe_float(lvl.get("support"))
                    res = _safe_float(lvl.get("resistance"))
                    parts: list[str] = [f"**{sym}**"]
                    if sup:
                        parts.append(f"支撑 \u00a5{sup}")
                    if res:
                        parts.append(f"阻力 \u00a5{res}")
                    level_lines.append(" | ".join(parts))
                else:
                    level_lines.append(str(lvl))
            levels_text = "\n".join(level_lines)
        else:
            levels_text = str(key_levels)
        embed.add_field(
            name="关键价位",
            value=_truncate(levels_text, 500),
            inline=False,
        )

    embed.set_footer(
        text=f"早盘计划 | {date_str}" if date_str else "早盘计划 | A股分析师"
    )
    return embed


# ---------------------------------------------------------------------------
# Close review
# ---------------------------------------------------------------------------


def build_close_review_embed(review: dict[str, Any]) -> discord.Embed:
    """Build a rich embed for the 15:30 close review.

    Expected *review* keys:
        date, pnl_amount, pnl_pct, positions (list of dicts),
        signal_accuracy, thesis_updates, outlook
    """
    date_str = review.get("date", "")
    title = f"\U0001f4ca **收盘复盘 {date_str}**"

    embed = discord.Embed(title=title, color=_ORANGE)

    # -- PnL ---------------------------------------------------------------
    pnl_amount = review.get("pnl_amount")
    pnl_pct = review.get("pnl_pct")
    if pnl_amount is not None or pnl_pct is not None:
        pnl_parts: list[str] = ["收益:"]
        if pnl_amount is not None:
            sign = "+" if float(pnl_amount) >= 0 else ""
            pnl_parts.append(f"{sign}\u00a5{_safe_float(pnl_amount, ',.0f')}")
        if pnl_pct is not None:
            sign = "+" if float(pnl_pct) >= 0 else ""
            pnl_parts.append(f"({sign}{float(pnl_pct):.1%})")
        embed.description = " ".join(pnl_parts)

    # -- Positions summary -------------------------------------------------
    positions = review.get("positions")
    if positions and isinstance(positions, list):
        pos_lines: list[str] = []
        for pos in positions:
            if isinstance(pos, dict):
                name = pos.get("name", pos.get("symbol", "?"))
                pct = pos.get("pct_change")
                if pct is not None:
                    pct_f = float(pct)
                    emoji = "\u2705" if pct_f >= 0 else "\u274c"
                    sign = "+" if pct_f >= 0 else ""
                    pos_lines.append(f"{emoji} {name} {sign}{pct_f:.1f}%")
                else:
                    pos_lines.append(f"\u26aa {name}")
            else:
                pos_lines.append(str(pos))
        embed.add_field(
            name="持仓表现",
            value="\n".join(pos_lines),
            inline=False,
        )

    # -- Signal accuracy ---------------------------------------------------
    accuracy = review.get("signal_accuracy")
    if accuracy is not None:
        embed.add_field(
            name="\U0001f4c8 信号准确率",
            value=f"{float(accuracy):.0%}",
            inline=True,
        )

    # -- Thesis updates ----------------------------------------------------
    thesis_updates = review.get("thesis_updates")
    if thesis_updates:
        if isinstance(thesis_updates, list):
            updates_text = "\n".join(f"\u2022 {u}" for u in thesis_updates)
        else:
            updates_text = str(thesis_updates)
        embed.add_field(
            name="论点更新",
            value=_truncate(updates_text, 500),
            inline=False,
        )

    # -- Outlook -----------------------------------------------------------
    outlook = review.get("outlook")
    if outlook:
        embed.add_field(
            name="明日展望",
            value=_truncate(str(outlook), 500),
            inline=False,
        )

    embed.set_footer(
        text=f"收盘复盘 | {date_str}" if date_str else "收盘复盘 | A股分析师"
    )
    return embed

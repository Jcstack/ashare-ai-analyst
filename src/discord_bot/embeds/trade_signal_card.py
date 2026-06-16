"""Rich Discord embed builders for autonomous trade signals and briefings."""

from __future__ import annotations

from typing import Any

import discord

_GREEN = 0x00C853
_RED = 0xFF1744
_GRAY = 0x9E9E9E
_BLUE = 0x2196F3
_ORANGE = 0xFF9800

_ACTION_COLORS: dict[str, int] = {
    "buy": _GREEN,
    "add": _GREEN,
    "sell": _RED,
    "reduce": _RED,
    "hold": _GRAY,
}


def _confidence_label(conf: float) -> str:
    """Map numeric confidence to Chinese label."""
    if conf >= 0.8:
        return "高"
    if conf >= 0.6:
        return "中"
    return "低"


def _action_label(action: str) -> str:
    """Map English action to Chinese badge."""
    labels = {
        "buy": "买入信号",
        "sell": "卖出信号",
        "add": "加仓信号",
        "reduce": "减仓信号",
        "hold": "持有观察",
    }
    return labels.get(action, action)


def _safe_float(val: Any, fmt: str = ".2f") -> str | None:
    """Format a value as float string, return ``None`` if not numeric."""
    if val is None:
        return None
    try:
        return f"{float(val):{fmt}}"
    except (ValueError, TypeError):
        return str(val)


def _truncate(text: str, limit: int = 300) -> str:
    """Truncate *text* to *limit* chars, appending ellipsis if needed."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Trade signal embed
# ---------------------------------------------------------------------------


def build_trade_signal_embed(proposal: dict[str, Any]) -> discord.Embed:
    """Build a rich embed for an autonomous trade signal.

    Expected *proposal* keys (all optional except ``action`` and ``symbol``):
        action, symbol, name, confidence, shares, price,
        target_price, stop_loss, reward_risk_ratio,
        thesis, bull_score, bear_score, bull_points, bear_points,
        risk_notes, portfolio_impact, overnight_risk_pct
    """
    action: str = proposal.get("action", "hold")
    symbol: str = proposal.get("symbol", "??????")
    name: str = proposal.get("name", symbol)

    title = f"{_action_label(action)} | {name} ({symbol})"
    color = _ACTION_COLORS.get(action, _GRAY)

    embed = discord.Embed(title=title, color=color)

    # -- 决策置信度 ----------------------------------------------------------
    confidence = proposal.get("confidence")
    if confidence is not None:
        conf_val = float(confidence)
        level = _confidence_label(conf_val)
        embed.add_field(
            name="决策置信度",
            value=f"{conf_val:.0%}（{level}）",
            inline=True,
        )

    # -- 建议操作 ------------------------------------------------------------
    shares = proposal.get("shares")
    price = proposal.get("price")
    if shares is not None or price is not None:
        parts: list[str] = []
        if shares is not None:
            parts.append(f"{int(shares)} 股")
        if price is not None:
            parts.append(f"@ ¥{_safe_float(price)}")
        embed.add_field(name="建议操作", value=" ".join(parts), inline=True)

    # -- 目标价 / 止损价 / 盈亏比 -------------------------------------------
    target = _safe_float(proposal.get("target_price"))
    stop = _safe_float(proposal.get("stop_loss"))
    rr = _safe_float(proposal.get("reward_risk_ratio"), ".1f")

    price_parts: list[str] = []
    if target:
        price_parts.append(f"目标 ¥{target}")
    if stop:
        price_parts.append(f"止损 ¥{stop}")
    if rr:
        price_parts.append(f"盈亏比 {rr}")
    if price_parts:
        embed.add_field(
            name="目标价 / 止损价 / 盈亏比",
            value=" | ".join(price_parts),
            inline=False,
        )

    # -- 投资论点 ------------------------------------------------------------
    thesis = proposal.get("thesis")
    if thesis:
        embed.add_field(
            name="投资论点",
            value=_truncate(str(thesis)),
            inline=False,
        )

    # -- 辩论摘要 ------------------------------------------------------------
    bull_score = proposal.get("bull_score")
    bear_score = proposal.get("bear_score")
    if bull_score is not None or bear_score is not None:
        debate_lines: list[str] = []
        if bull_score is not None and bear_score is not None:
            debate_lines.append(
                f"多方 **{_safe_float(bull_score, '.0f')}** vs "
                f"空方 **{_safe_float(bear_score, '.0f')}**"
            )
        bull_points = proposal.get("bull_points")
        if bull_points and isinstance(bull_points, list):
            debate_lines.append(
                "多方要点: " + "；".join(str(p) for p in bull_points[:3])
            )
        bear_points = proposal.get("bear_points")
        if bear_points and isinstance(bear_points, list):
            debate_lines.append(
                "空方要点: " + "；".join(str(p) for p in bear_points[:3])
            )
        if debate_lines:
            embed.add_field(
                name="辩论摘要",
                value=_truncate("\n".join(debate_lines), 500),
                inline=False,
            )

    # -- 风险提示 ------------------------------------------------------------
    risk_notes = proposal.get("risk_notes")
    if risk_notes:
        if isinstance(risk_notes, list):
            risk_text = "；".join(str(n) for n in risk_notes)
        else:
            risk_text = str(risk_notes)
        embed.add_field(
            name="风险提示",
            value=_truncate(risk_text, 400),
            inline=False,
        )

    # -- 组合影响 ------------------------------------------------------------
    portfolio_impact = proposal.get("portfolio_impact")
    if portfolio_impact:
        if isinstance(portfolio_impact, dict):
            impact_lines: list[str] = []
            for key, val in portfolio_impact.items():
                impact_lines.append(f"{key}: {val}")
            impact_text = " | ".join(impact_lines)
        else:
            impact_text = str(portfolio_impact)
        embed.add_field(
            name="组合影响",
            value=_truncate(impact_text, 300),
            inline=False,
        )

    # -- T+1 隔夜风险 -------------------------------------------------------
    overnight_risk = proposal.get("overnight_risk_pct")
    if overnight_risk is not None:
        embed.add_field(
            name="T+1隔夜风险",
            value=f"{float(overnight_risk):.1%}",
            inline=True,
        )

    embed.set_footer(text="自主决策 | 仅供参考 | A股分析师")
    return embed


# ---------------------------------------------------------------------------
# Morning briefing embed
# ---------------------------------------------------------------------------


def build_morning_briefing_embed(briefing: dict[str, Any]) -> discord.Embed:
    """Build a rich embed for the daily morning briefing.

    Expected *briefing* keys:
        date, global_summary, macro_events, thesis_status,
        planned_actions, key_levels
    """
    date_str = briefing.get("date", "")
    title = f"晨间简报 | {date_str}" if date_str else "晨间简报"

    embed = discord.Embed(title=title, color=_BLUE)

    # -- 隔夜全球市场 --------------------------------------------------------
    global_summary = briefing.get("global_summary")
    if global_summary:
        embed.add_field(
            name="隔夜全球市场",
            value=_truncate(str(global_summary), 500),
            inline=False,
        )

    # -- 今日宏观日历 --------------------------------------------------------
    macro_events = briefing.get("macro_events")
    if macro_events:
        if isinstance(macro_events, list):
            events_text = "\n".join(f"• {e}" for e in macro_events)
        else:
            events_text = str(macro_events)
        embed.add_field(
            name="今日宏观日历",
            value=_truncate(events_text, 500),
            inline=False,
        )

    # -- 持仓论点状态 --------------------------------------------------------
    thesis_status = briefing.get("thesis_status")
    if thesis_status:
        if isinstance(thesis_status, list):
            status_lines: list[str] = []
            for item in thesis_status:
                if isinstance(item, dict):
                    sym = item.get("symbol", "?")
                    valid = item.get("valid", True)
                    tag = "有效" if valid else "已失效"
                    note = item.get("note", "")
                    status_lines.append(f"**{sym}** [{tag}] {note}".strip())
                else:
                    status_lines.append(str(item))
            status_text = "\n".join(status_lines)
        else:
            status_text = str(thesis_status)
        embed.add_field(
            name="持仓论点状态",
            value=_truncate(status_text, 500),
            inline=False,
        )

    # -- 今日计划操作 --------------------------------------------------------
    planned_actions = briefing.get("planned_actions")
    if planned_actions:
        if isinstance(planned_actions, list):
            actions_text = "\n".join(f"• {a}" for a in planned_actions)
        else:
            actions_text = str(planned_actions)
        embed.add_field(
            name="今日计划操作",
            value=_truncate(actions_text, 500),
            inline=False,
        )

    # -- 关键价位 ------------------------------------------------------------
    key_levels = briefing.get("key_levels")
    if key_levels:
        if isinstance(key_levels, list):
            levels_lines: list[str] = []
            for lvl in key_levels:
                if isinstance(lvl, dict):
                    sym = lvl.get("symbol", "?")
                    sup = _safe_float(lvl.get("support"))
                    res = _safe_float(lvl.get("resistance"))
                    parts_kl: list[str] = [f"**{sym}**"]
                    if sup:
                        parts_kl.append(f"支撑 ¥{sup}")
                    if res:
                        parts_kl.append(f"阻力 ¥{res}")
                    levels_lines.append(" | ".join(parts_kl))
                else:
                    levels_lines.append(str(lvl))
            levels_text = "\n".join(levels_lines)
        else:
            levels_text = str(key_levels)
        embed.add_field(
            name="关键价位",
            value=_truncate(levels_text, 500),
            inline=False,
        )

    embed.set_footer(
        text=f"晨间简报 | {date_str}" if date_str else "晨间简报 | A股分析师"
    )
    return embed


# ---------------------------------------------------------------------------
# Evening review embed
# ---------------------------------------------------------------------------


def build_evening_review_embed(review: dict[str, Any]) -> discord.Embed:
    """Build a rich embed for the daily evening review.

    Expected *review* keys:
        date, daily_pnl, trades, thesis_updates,
        intel_triggers, outlook
    """
    date_str = review.get("date", "")
    title = f"收盘复盘 | {date_str}" if date_str else "收盘复盘"

    embed = discord.Embed(title=title, color=_ORANGE)

    # -- 今日盈亏 ------------------------------------------------------------
    daily_pnl = review.get("daily_pnl")
    if daily_pnl is not None:
        if isinstance(daily_pnl, dict):
            pnl_val = daily_pnl.get("amount")
            pnl_pct = daily_pnl.get("pct")
            pnl_parts: list[str] = []
            if pnl_val is not None:
                sign = "+" if float(pnl_val) >= 0 else ""
                pnl_parts.append(f"¥{sign}{_safe_float(pnl_val)}")
            if pnl_pct is not None:
                sign = "+" if float(pnl_pct) >= 0 else ""
                pnl_parts.append(f"({sign}{float(pnl_pct):.2%})")
            pnl_text = " ".join(pnl_parts) if pnl_parts else str(daily_pnl)
        elif isinstance(daily_pnl, (int, float)):
            sign = "+" if daily_pnl >= 0 else ""
            pnl_text = f"¥{sign}{_safe_float(daily_pnl)}"
        else:
            pnl_text = str(daily_pnl)
        embed.add_field(name="今日盈亏", value=pnl_text, inline=True)

    # -- 已执行交易 ----------------------------------------------------------
    trades = review.get("trades")
    if trades:
        if isinstance(trades, list):
            trade_lines: list[str] = []
            for t in trades:
                if isinstance(t, dict):
                    act = _action_label(t.get("action", ""))
                    sym = t.get("symbol", "?")
                    shares = t.get("shares", "")
                    price = _safe_float(t.get("price"))
                    line = f"{act} **{sym}**"
                    if shares:
                        line += f" {int(shares)}股"
                    if price:
                        line += f" @ ¥{price}"
                    trade_lines.append(line)
                else:
                    trade_lines.append(str(t))
            trades_text = "\n".join(trade_lines)
        else:
            trades_text = str(trades)
        embed.add_field(
            name="已执行交易",
            value=_truncate(trades_text, 500),
            inline=False,
        )

    # -- 论点更新 ------------------------------------------------------------
    thesis_updates = review.get("thesis_updates")
    if thesis_updates:
        if isinstance(thesis_updates, list):
            updates_text = "\n".join(f"• {u}" for u in thesis_updates)
        else:
            updates_text = str(thesis_updates)
        embed.add_field(
            name="论点更新",
            value=_truncate(updates_text, 500),
            inline=False,
        )

    # -- 情报触发 ------------------------------------------------------------
    intel_triggers = review.get("intel_triggers")
    if intel_triggers:
        if isinstance(intel_triggers, list):
            triggers_text = "\n".join(f"• {t}" for t in intel_triggers)
        else:
            triggers_text = str(intel_triggers)
        embed.add_field(
            name="情报触发",
            value=_truncate(triggers_text, 500),
            inline=False,
        )

    # -- 明日展望 ------------------------------------------------------------
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

"""Rich Discord embed for actionable trading signals (buy/sell/reduce).

Routed to #trading-alerts channel.
"""

from __future__ import annotations

from typing import Any

import discord

_GREEN = 0x00C853
_RED = 0xFF1744
_ORANGE = 0xFF9800
_GRAY = 0x9E9E9E

_ACTION_EMOJI: dict[str, str] = {
    "buy": "\U0001f7e2",  # green circle
    "add": "\U0001f7e2",
    "sell": "\U0001f534",  # red circle
    "reduce": "\U0001f7e0",  # orange circle
    "hold": "\u26aa",  # white circle
}

_ACTION_LABEL: dict[str, str] = {
    "buy": "买入信号",
    "sell": "卖出信号",
    "add": "加仓信号",
    "reduce": "减仓信号",
    "hold": "持有观察",
}

_ACTION_COLOR: dict[str, int] = {
    "buy": _GREEN,
    "add": _GREEN,
    "sell": _RED,
    "reduce": _ORANGE,
    "hold": _GRAY,
}


def _safe_float(val: Any, fmt: str = ".2f") -> str | None:
    """Format a value as float string, return ``None`` if not numeric."""
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


def build_trading_signal_embed(action_item: dict[str, Any]) -> discord.Embed:
    """Build a rich embed for an actionable trading signal.

    Expected *action_item* keys:
        action, symbol, name, confidence, domains_confirmed,
        sentiment_phase, timing, position_pct, position_amount,
        price, stop_loss, stop_loss_pct, target, target_pct,
        reason, risk, abandon_condition
    """
    action: str = action_item.get("action", "hold")
    symbol: str = action_item.get("symbol", "??????")
    name: str = action_item.get("name", symbol)

    emoji = _ACTION_EMOJI.get(action, "\u26aa")
    label = _ACTION_LABEL.get(action, action)
    color = _ACTION_COLOR.get(action, _GRAY)

    embed = discord.Embed(
        title=f"{emoji} **{label}: {name} {symbol}**",
        color=color,
    )

    # -- Confidence header ---------------------------------------------------
    header_parts: list[str] = []
    confidence = action_item.get("confidence")
    if confidence is not None:
        pct = float(confidence)
        bar = "\u2588" * int(pct * 10) + "\u2591" * (10 - int(pct * 10))
        header_parts.append(f"信心: {bar} {pct:.0%}")
    phase = action_item.get("sentiment_phase")
    if phase:
        header_parts.append(f"情绪:{phase}")
    if header_parts:
        embed.description = " | ".join(header_parts)

    # -- Execution instructions -------------------------------------------
    exec_lines: list[str] = []
    timing = action_item.get("timing")
    if timing:
        exec_lines.append(f"\u2022 时间: {timing}")
    # Shares (from DecisionHandler trade_data)
    shares = action_item.get("shares")
    if shares is not None:
        exec_lines.append(f"\u2022 数量: **{int(shares)}股**")
    pos_pct = action_item.get("position_pct")
    pos_amt = action_item.get("position_amount")
    if pos_pct is not None or pos_amt is not None:
        pos_parts: list[str] = []
        if pos_pct is not None:
            pos_parts.append(f"{pos_pct}%")
        if pos_amt is not None:
            pos_parts.append(f"(约\u00a5{_safe_float(pos_amt, ',.0f')})")
        exec_lines.append(f"\u2022 仓位: {' '.join(pos_parts)}")
    # Accept both "price" and "entry_price" (DecisionHandler naming)
    price = action_item.get("price") or action_item.get("entry_price")
    if price is not None:
        exec_lines.append(f"\u2022 价格: \u2264\u00a5{_safe_float(price)}")
    stop_loss = action_item.get("stop_loss")
    stop_loss_pct = action_item.get("stop_loss_pct")
    if stop_loss is not None:
        sl_text = f"\u2022 止损: \u00a5{_safe_float(stop_loss)}"
        if stop_loss_pct is not None:
            sl_text += f" ({_safe_float(stop_loss_pct, '.1f')}%)"
        exec_lines.append(sl_text)
    # Accept both "target" and "target_price"
    target = action_item.get("target") or action_item.get("target_price")
    target_pct = action_item.get("target_pct")
    if target is not None:
        tgt_text = f"\u2022 目标: \u00a5{_safe_float(target)}"
        if target_pct is not None:
            tgt_text += f" (+{_safe_float(target_pct, '.1f')}%)"
        exec_lines.append(tgt_text)
    if exec_lines:
        embed.add_field(
            name="\U0001f4cb **执行指令**",
            value="\n".join(exec_lines),
            inline=False,
        )

    # -- Reason (accepts both "reason" and "summary" from DecisionHandler) --
    reason = action_item.get("reason") or action_item.get("summary")
    if reason:
        embed.add_field(
            name="\U0001f4a1 **原因**",
            value=_truncate(str(reason), 500),
            inline=False,
        )

    # -- Risk (accepts both "risk" and "risk_note" from DecisionHandler) ---
    risk = action_item.get("risk") or action_item.get("risk_note")
    if risk:
        embed.add_field(
            name="\u26a0\ufe0f **风险**",
            value=_truncate(str(risk), 400),
            inline=False,
        )

    # -- Abandon condition -------------------------------------------------
    abandon = action_item.get("abandon_condition")
    if abandon:
        embed.add_field(
            name="\U0001f6ab **放弃条件**",
            value=_truncate(str(abandon), 300),
            inline=False,
        )

    embed.set_footer(
        text="交易信号 | 执行后回复「买了/卖了 X股 代码 @价格」记录 | A股分析师"
    )
    return embed

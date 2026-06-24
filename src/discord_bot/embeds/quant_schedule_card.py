"""Discord embed builders for v37.0 quant schedule push notifications.

Provides themed embeds for each scheduled push type:
- Call auction analysis (pre-market)
- Late session buy recommendations (highest priority)
- Post-market review
- Holiday intel
- Intraday signals
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import discord

# -- Colors ------------------------------------------------------------------
_BLUE = 0x2196F3
_ORANGE_RED = 0xFF6B35
_PURPLE = 0x9C27B0
_TEAL = 0x009688
_GREEN = 0x4CAF50

# -- Helpers -----------------------------------------------------------------


def _truncate(text: str, limit: int = 1024) -> str:
    """Truncate *text* to *limit* chars for Discord field safety."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


def _safe_str(val: Any, default: str = "-") -> str:
    """Convert a value to string, returning *default* for None."""
    if val is None:
        return default
    return str(val)


def _now_footer() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# 1. Call Auction Embed (pre_market / call_auction)
# ---------------------------------------------------------------------------


def build_call_auction_embed(data: dict[str, Any]) -> discord.Embed:
    """Build embed for call auction analysis (Phase 1 or 2).

    Expected *data* keys:
        phase: int (1 or 2)
        overnight: str — global overnight market summary
        tone: str — aggressive/steady/defensive
        tone_reason: str — reason for tone
        portfolio_outlook: str — portfolio stock outlook
        watchlist: str — watchlist highlights
        timestamp: str (optional)
    """
    phase = data.get("phase", 1)
    title = f"集合竞价分析 \u2014 Phase {phase}"

    embed = discord.Embed(title=title, color=_BLUE)

    overnight = data.get("overnight")
    if overnight:
        embed.add_field(
            name="全球隔夜",
            value=_truncate(str(overnight)),
            inline=False,
        )

    tone = data.get("tone", "")
    tone_reason = data.get("tone_reason", "")
    if tone:
        tone_text = str(tone)
        if tone_reason:
            tone_text += f"\n{tone_reason}"
        embed.add_field(
            name="今日基调",
            value=_truncate(tone_text),
            inline=False,
        )

    portfolio_outlook = data.get("portfolio_outlook")
    if portfolio_outlook:
        embed.add_field(
            name="持仓预期",
            value=_truncate(str(portfolio_outlook)),
            inline=False,
        )

    watchlist = data.get("watchlist")
    if watchlist:
        embed.add_field(
            name="关注个股",
            value=_truncate(str(watchlist)),
            inline=False,
        )

    ts = data.get("timestamp", _now_footer())
    embed.set_footer(text=f"集合竞价 Phase {phase} | {ts}")
    return embed


# ---------------------------------------------------------------------------
# 2. Late Session Embed (late_session) ★ highest priority
# ---------------------------------------------------------------------------


def build_late_session_embed(data: dict[str, Any]) -> discord.Embed:
    """Build visually distinct embed for late session buy recommendations.

    Expected *data* keys:
        confirm: bool — True for 14:50 final confirmation
        recommendations: list[dict] — up to 3 stocks, each with:
            symbol, name, entry_range, position_size,
            stop_loss, target, holding_days, reason
        sentiment: str — market sentiment level
        risk_warning: str — overall risk warning
        timestamp: str (optional)
    """
    is_confirm = data.get("confirm", False)
    if is_confirm:
        title = "\u2705 尾盘确认 \u2014 最终清单"
    else:
        title = "\U0001f525 尾盘决策 \u2014 买入推荐"

    embed = discord.Embed(title=title, color=_ORANGE_RED)

    recommendations = data.get("recommendations", [])
    for i, rec in enumerate(recommendations[:3], 1):
        symbol = _safe_str(rec.get("symbol"))
        name = _safe_str(rec.get("name"), symbol)

        # Build a compact field value for this stock
        lines: list[str] = []
        lines.append(f"**{name}({symbol})**")

        entry_range = rec.get("entry_range")
        if entry_range:
            lines.append(f"买入区间: {entry_range}")

        position_size = rec.get("position_size")
        if position_size:
            lines.append(f"建议仓位: {position_size}")

        stop_loss = rec.get("stop_loss")
        if stop_loss:
            lines.append(f"止损位: {stop_loss}")

        target = rec.get("target")
        if target:
            lines.append(f"目标: {target}")

        holding_days = rec.get("holding_days")
        if holding_days:
            lines.append(f"持有天数: {holding_days}")

        reason = rec.get("reason")
        if reason:
            # Limit reason to 2 lines max
            reason_lines = str(reason).split("\n")[:2]
            lines.append(f"理由: {''.join(reason_lines)}")

        field_name = f"\U0001f4cc 推荐 {i}"
        embed.add_field(
            name=field_name,
            value=_truncate("\n".join(lines)),
            inline=False,
        )

    # -- Bottom fields --
    sentiment = data.get("sentiment")
    if sentiment:
        embed.add_field(
            name="市场情绪",
            value=_truncate(str(sentiment), 256),
            inline=True,
        )

    risk_warning = data.get("risk_warning")
    if risk_warning:
        embed.add_field(
            name="\u26a0 风险提示",
            value=_truncate(str(risk_warning)),
            inline=False,
        )

    ts = data.get("timestamp", _now_footer())
    label = "尾盘最终确认" if is_confirm else "尾盘决策"
    embed.set_footer(text=f"{label} | 仅供参考 | {ts}")
    return embed


# ---------------------------------------------------------------------------
# 3. Post-Market Review Embed (post_market)
# ---------------------------------------------------------------------------


def build_review_embed(data: dict[str, Any]) -> discord.Embed:
    """Build embed for post-market review + next day outlook.

    Expected *data* keys:
        pnl_summary: str — today's P&L
        accuracy: str — recommendation hit rate
        position_status: str — per-stock status
        next_day_plan: str — next day plan
        error_analysis: str (optional) — what went wrong
        timestamp: str (optional)
    """
    title = "盘后复盘 + 明日预判"

    embed = discord.Embed(title=title, color=_PURPLE)

    pnl = data.get("pnl_summary")
    if pnl:
        embed.add_field(
            name="今日盈亏",
            value=_truncate(str(pnl)),
            inline=False,
        )

    accuracy = data.get("accuracy")
    if accuracy:
        embed.add_field(
            name="推荐命中率",
            value=_truncate(str(accuracy), 256),
            inline=True,
        )

    position_status = data.get("position_status")
    if position_status:
        embed.add_field(
            name="持仓评估",
            value=_truncate(str(position_status)),
            inline=False,
        )

    next_day_plan = data.get("next_day_plan")
    if next_day_plan:
        embed.add_field(
            name="明日计划",
            value=_truncate(str(next_day_plan)),
            inline=False,
        )

    error_analysis = data.get("error_analysis")
    if error_analysis:
        embed.add_field(
            name="错误分析",
            value=_truncate(str(error_analysis)),
            inline=False,
        )

    ts = data.get("timestamp", _now_footer())
    embed.set_footer(text=f"盘后复盘 | {ts}")
    return embed


# ---------------------------------------------------------------------------
# 4. Holiday Intel Embed (holiday_intel)
# ---------------------------------------------------------------------------


def build_holiday_intel_embed(data: dict[str, Any]) -> discord.Embed:
    """Build embed for non-trading day intel analysis.

    Expected *data* keys:
        date: str — the date
        global_markets: str — global market movements
        policy_news: str — policy / regulatory news
        industry_updates: str — industry developments
        portfolio_relevant: str — portfolio-relevant intel
        action_plan: str — recommended actions
        timestamp: str (optional)
    """
    date_str = data.get("date", "")
    title = f"假期情报 \u2014 {date_str}" if date_str else "假期情报"

    embed = discord.Embed(title=title, color=_TEAL)

    global_markets = data.get("global_markets")
    if global_markets:
        embed.add_field(
            name="全球市场",
            value=_truncate(str(global_markets)),
            inline=False,
        )

    policy_news = data.get("policy_news")
    if policy_news:
        embed.add_field(
            name="政策动态",
            value=_truncate(str(policy_news)),
            inline=False,
        )

    industry_updates = data.get("industry_updates")
    if industry_updates:
        embed.add_field(
            name="行业新闻",
            value=_truncate(str(industry_updates)),
            inline=False,
        )

    portfolio_relevant = data.get("portfolio_relevant")
    if portfolio_relevant:
        embed.add_field(
            name="持仓相关",
            value=_truncate(str(portfolio_relevant)),
            inline=False,
        )

    action_plan = data.get("action_plan")
    if action_plan:
        embed.add_field(
            name="操作建议",
            value=_truncate(str(action_plan)),
            inline=False,
        )

    ts = data.get("timestamp", _now_footer())
    embed.set_footer(text=f"假期情报 | {ts}")
    return embed


# ---------------------------------------------------------------------------
# 5. Intraday Signal Embed (intraday_signal)
# ---------------------------------------------------------------------------


def build_intraday_signal_embed(data: dict[str, Any]) -> discord.Embed:
    """Build embed for intraday market signals.

    Expected *data* keys:
        session_label: str — "早盘" or "午后"
        sector_strength: str — sector strength/weakness
        unusual_movers: str — unusual stock movers
        capital_flow: str — capital flow direction
        action_hints: str — action suggestions
        timestamp: str (optional)
    """
    session_label = data.get("session_label", "盘中")
    title = f"盘中信号 \u2014 {session_label}"

    embed = discord.Embed(title=title, color=_GREEN)

    sector_strength = data.get("sector_strength")
    if sector_strength:
        embed.add_field(
            name="板块强弱",
            value=_truncate(str(sector_strength)),
            inline=False,
        )

    unusual_movers = data.get("unusual_movers")
    if unusual_movers:
        embed.add_field(
            name="异动个股",
            value=_truncate(str(unusual_movers)),
            inline=False,
        )

    capital_flow = data.get("capital_flow")
    if capital_flow:
        embed.add_field(
            name="资金动向",
            value=_truncate(str(capital_flow)),
            inline=False,
        )

    action_hints = data.get("action_hints")
    if action_hints:
        embed.add_field(
            name="操作提示",
            value=_truncate(str(action_hints)),
            inline=False,
        )

    ts = data.get("timestamp", _now_footer())
    embed.set_footer(text=f"盘中信号 | {ts}")
    return embed

"""A-share market session detection utility.

Provides market-hours awareness for AI analysis services so that prompts
include context about whether data is real-time (during trading), delayed
(lunch break), or historical (after-hours / non-trading day).

A-share trading schedule (CST / Asia/Shanghai):
- Pre-market:       before 09:15
- Auction:          09:15 – 09:25  (集合竞价)
- Auction freeze:   09:25 – 09:30  (撮合冻结)
- Morning session:  09:30 – 11:30  (上午连续竞价)
- Lunch break:      11:30 – 13:00  (午间休市)
- Afternoon session: 13:00 – 14:57 (下午连续竞价)
- Closing auction:  14:57 – 15:00  (尾盘集合竞价)
- After-hours:      15:00+         (收盘后)
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

CST = ZoneInfo("Asia/Shanghai")

# ── TradingCalendar singleton (avoid repeated akshare API calls) ────
_calendar_instance: Any = None


def _get_calendar():
    """Return a module-level cached TradingCalendar instance."""
    global _calendar_instance
    if _calendar_instance is None:
        from src.data.trading_calendar import TradingCalendar

        _calendar_instance = TradingCalendar()
    return _calendar_instance


# Session boundary times (CST)
_T_AUCTION_START = time(9, 15)
_T_AUCTION_END = time(9, 25)
_T_MORNING_START = time(9, 30)
_T_MORNING_END = time(11, 30)
_T_AFTERNOON_START = time(13, 0)
_T_CLOSING_AUCTION = time(14, 57)
_T_CLOSE = time(15, 0)


def get_market_session(now: datetime | None = None) -> dict[str, Any]:
    """Detect current A-share market session.

    Args:
        now: Optional datetime for testing. If None, uses current CST time.

    Returns:
        Dict with keys:
        - session: Machine-readable session id.
        - label: Chinese label for the session.
        - description: Human-readable description for AI prompt context.
        - is_trading: Whether regular trading is happening right now.
        - current_time: Formatted CST time string.
    """
    if now is None:
        now = datetime.now(CST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=CST)

    current_time_str = now.strftime("%Y-%m-%d %H:%M CST")
    t = now.time()
    weekday = now.weekday()  # 0=Mon, 6=Sun

    # Weekend — but check holidays first
    if weekday >= 5:
        try:
            _cal = _get_calendar()
            _hp = _cal.get_holiday_period_info(now.date())
            if _hp:
                ntd = _cal.next_trading_day(now.date())
                return {
                    "session": "non_trading",
                    "label": f"非交易日（{_hp['name']}）",
                    "description": (
                        f"当前时间: {current_time_str}，今日为{_hp['name']}假期，A股休市。"
                        f"下一交易日: {ntd.isoformat()}。"
                        "行情数据为上一个交易日收盘数据，分析应基于最近交易日的收盘价。"
                    ),
                    "is_trading": False,
                    "current_time": current_time_str,
                }
        except Exception:
            pass

        return {
            "session": "non_trading",
            "label": "非交易日（周末）",
            "description": (
                f"当前时间: {current_time_str}，今日为非交易日（周末）。"
                "行情数据为上一个交易日收盘数据，分析应基于最近交易日的收盘价。"
            ),
            "is_trading": False,
            "current_time": current_time_str,
        }

    # Holiday / emergency closure on a weekday — consult TradingCalendar
    try:
        _cal = _get_calendar()
        _today = now.date()
        if not _cal.is_trading_day(_today):
            # Build a descriptive label
            holiday_name = _cal.get_holiday_name(_today)
            emergency_reason = _cal.get_emergency_reason(_today)
            if emergency_reason:
                label = f"紧急休市（{emergency_reason}）"
                desc_detail = f"因「{emergency_reason}」紧急休市"
            elif holiday_name:
                label = f"非交易日（{holiday_name}）"
                desc_detail = f"今日为{holiday_name}假期，A股休市"
            else:
                label = "非交易日"
                desc_detail = "今日为非交易日，A股休市"

            ntd = _cal.next_trading_day(_today)
            return {
                "session": "non_trading",
                "label": label,
                "description": (
                    f"当前时间: {current_time_str}，{desc_detail}。"
                    f"下一交易日: {ntd.isoformat()}。"
                    "行情数据为上一个交易日收盘数据，分析应基于最近交易日的收盘价。"
                ),
                "is_trading": False,
                "current_time": current_time_str,
            }
    except Exception:
        pass  # TradingCalendar unavailable — fall through to time-based detection

    # Before auction
    if t < _T_AUCTION_START:
        return {
            "session": "pre_market",
            "label": "盘前",
            "description": (
                f"当前时间: {current_time_str}，尚未开盘。"
                "行情数据为昨日收盘数据，分析应基于上一交易日收盘价和盘前消息面。"
            ),
            "is_trading": False,
            "current_time": current_time_str,
        }

    # Auction 9:15-9:25
    if t < _T_AUCTION_END:
        return {
            "session": "auction",
            "label": "集合竞价",
            "description": (
                f"当前时间: {current_time_str}，正在集合竞价阶段(9:15-9:25)。"
                "行情数据显示的是竞价撮合价格，尚未正式开盘，成交量数据仅反映竞价情况。"
            ),
            "is_trading": False,
            "current_time": current_time_str,
        }

    # Freeze 9:25-9:30
    if t < _T_MORNING_START:
        return {
            "session": "auction_freeze",
            "label": "竞价冻结",
            "description": (
                f"当前时间: {current_time_str}，集合竞价已结束，等待开盘(9:30)。"
                "开盘价已确定，但连续交易尚未开始。"
            ),
            "is_trading": False,
            "current_time": current_time_str,
        }

    # Morning session 9:30-11:30
    if t < _T_MORNING_END:
        return {
            "session": "morning",
            "label": "盘中（上午）",
            "description": (
                f"当前时间: {current_time_str}，上午交易时段(9:30-11:30)。"
                "行情数据为实时数据，价格和成交量仍在变化中，日内涨跌幅和成交量为截至当前值。"
            ),
            "is_trading": True,
            "current_time": current_time_str,
        }

    # Lunch break 11:30-13:00
    if t < _T_AFTERNOON_START:
        return {
            "session": "lunch",
            "label": "午间休市",
            "description": (
                f"当前时间: {current_time_str}，午间休市(11:30-13:00)。"
                "行情数据为上午收盘数据，下午开盘后价格可能变化。"
                "成交量仅反映上午交易情况。"
            ),
            "is_trading": False,
            "current_time": current_time_str,
        }

    # Afternoon session 13:00-14:57
    if t < _T_CLOSING_AUCTION:
        return {
            "session": "afternoon",
            "label": "盘中（下午）",
            "description": (
                f"当前时间: {current_time_str}，下午交易时段(13:00-15:00)。"
                "行情数据为实时数据，价格和成交量仍在变化中。"
            ),
            "is_trading": True,
            "current_time": current_time_str,
        }

    # Closing auction 14:57-15:00
    if t < _T_CLOSE:
        return {
            "session": "closing_auction",
            "label": "尾盘集合竞价",
            "description": (
                f"当前时间: {current_time_str}，尾盘集合竞价阶段(14:57-15:00)。"
                "最终收盘价尚未确定，当前价格为最后连续交易价。"
            ),
            "is_trading": False,
            "current_time": current_time_str,
        }

    # After hours 15:00+
    return {
        "session": "after_hours",
        "label": "收盘后",
        "description": (
            f"当前时间: {current_time_str}，今日已收盘(15:00)。"
            "行情数据为今日收盘数据（最终确定值），成交量为全天总成交量。"
            "分析应基于完整的日内数据。"
        ),
        "is_trading": False,
        "current_time": current_time_str,
    }


_PREDICTION_TARGETS: dict[str, dict[str, str]] = {
    "non_trading": {
        "target": "next_trading_day",
        "instruction": (
            "预测目标: 下一个交易日。"
            "基于上一交易日收盘数据和休市期间消息面，预测下一交易日开盘方向和整体走势。"
        ),
    },
    "pre_market": {
        "target": "today_full_day",
        "instruction": (
            "预测目标: 今日全天。基于昨日收盘和盘前消息面，预测今日开盘方向和日内走势。"
        ),
    },
    "auction": {
        "target": "today_full_day",
        "instruction": (
            "预测目标: 今日全天。"
            "开盘价基本确定，基于竞价数据和消息面，预测今日整体走势。"
        ),
    },
    "auction_freeze": {
        "target": "today_full_day",
        "instruction": ("预测目标: 今日全天。开盘价已确定，预测今日开盘后走势。"),
    },
    "morning": {
        "target": "afternoon_session",
        "instruction": (
            "预测目标: 下午盘走势。"
            "基于上午盘量价表现和资金流向，预测午后走势和尾盘方向。"
        ),
    },
    "lunch": {
        "target": "afternoon_session",
        "instruction": (
            "预测目标: 下午盘走势。上午行情已确定，预测下午开盘方向和尾盘走势。"
        ),
    },
    "afternoon": {
        "target": "end_of_day",
        "instruction": (
            "预测目标: 尾盘及收盘。基于全天量价走势，预测尾盘方向和收盘价区间。"
        ),
    },
    "closing_auction": {
        "target": "end_of_day",
        "instruction": (
            "预测目标: 收盘价方向。连续交易已结束，判断尾盘集合竞价收盘价偏离方向。"
        ),
    },
    "after_hours": {
        "target": "next_trading_day",
        "instruction": (
            "预测目标: 下一个交易日。"
            "今日已收盘，基于全天表现和盘后消息面，预测下一交易日走势。"
        ),
    },
}


def get_prediction_target(session: dict[str, Any] | None = None) -> dict[str, str]:
    """Determine the AI prediction time window based on current market session.

    Args:
        session: Session dict from get_market_session(). If None, auto-detects.

    Returns:
        Dict with keys ``target`` (machine-readable) and ``instruction`` (Chinese).
    """
    if session is None:
        session = get_market_session()
    return _PREDICTION_TARGETS.get(
        session["session"],
        _PREDICTION_TARGETS["after_hours"],
    )


def format_session_for_prompt(session: dict[str, Any] | None = None) -> str:
    """Format market session info as a prompt section.

    When in a holiday period, includes holiday name, days remaining,
    and guidance for holiday-aware analysis.

    Args:
        session: Session dict from get_market_session(). If None, auto-detects.

    Returns:
        Formatted string suitable for embedding in an AI analysis prompt.
    """
    if session is None:
        session = get_market_session()
    target = get_prediction_target(session)

    base = (
        f"市场时段: {session['label']}\n{session['description']}\n\n"
        f"**{target['instruction']}**"
    )

    # Enrich with holiday context when applicable
    holiday_ctx = _get_holiday_prompt_context()
    if holiday_ctx:
        base += f"\n\n{holiday_ctx}"

    return base


def _get_holiday_prompt_context() -> str | None:
    """Build holiday context string for AI prompts, or None if not in holiday."""
    try:
        cal = _get_calendar()
        today = datetime.now(CST).date()
        info = cal.get_holiday_period_info(today)
        if info:
            return (
                f"**休市信息: 当前为{info['name']}假期，"
                f"休市至{info['end_date']}，距下一交易日还有{info['days_remaining']}天。**\n"
                "关注全球市场动态、政策变化对A股潜在影响，预测节后首个交易日走势。"
            )

        # Check if it's a non-weekend non-trading day with a holiday name
        holiday_name = cal.get_holiday_name(today)
        if holiday_name:
            ntd = cal.next_trading_day(today)
            days_until = (ntd - today).days
            return (
                f"**今日为{holiday_name}，A股休市。下一交易日: {ntd.isoformat()} (还有{days_until}天)。**\n"
                "关注全球市场动态、政策变化对A股潜在影响，预测节后首个交易日走势。"
            )

        # Emergency closure
        if cal.is_emergency_closure(today):
            reason = cal.get_emergency_reason(today) or "紧急停牌"
            return f"**紧急休市: {reason}。关注最新公告和市场消息。**"

    except Exception:
        pass
    return None


def is_a_share_trading_open(now: datetime | None = None) -> bool:
    """Authoritative gate: is A-share trading happening right now?

    Combines TradingCalendar date check with time-of-day session check.
    Returns True only during MORNING or AFTERNOON sessions on a trading day.
    """
    from src.data.trading_calendar import MarketSession

    cal = _get_calendar()

    if now is None:
        now = datetime.now(CST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=CST)

    if not cal.is_trading_day(now.date()):
        return False

    session = cal.current_session(now.replace(tzinfo=None))
    return session in (MarketSession.MORNING, MarketSession.AFTERNOON)


def get_market_status_for_ui(now: datetime | None = None) -> dict[str, Any]:
    """Comprehensive market status for frontend display.

    Returns:
        Dict with status, label, is_trading, next_event, holiday_info,
        is_emergency, emergency_reason.
    """
    from src.data.trading_calendar import MarketSession

    cal = _get_calendar()

    if now is None:
        now = datetime.now(CST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=CST)

    today = now.date()
    t = now.time()
    is_td = cal.is_trading_day(today)
    session = cal.current_session(now.replace(tzinfo=None))
    is_emergency = cal.is_emergency_closure(today)
    emergency_reason = cal.get_emergency_reason(today)

    # Holiday info — check period (covers adjacent weekends)
    holiday_info: dict | None = None
    hp = cal.get_holiday_period_info(today)
    if hp:
        holiday_info = {
            "name": hp["name"],
            "end_date": hp["end_date"],
            "days_remaining": hp["days_remaining"],
        }

    # Determine status + label + next_event
    if is_emergency:
        status = "emergency"
        label = "紧急停牌"
        ntd = cal.next_trading_day(today)
        next_event = {
            "type": "open",
            "time": f"{ntd.isoformat()} 09:30",
            "countdown_seconds": _seconds_until(
                now, datetime(ntd.year, ntd.month, ntd.day, 9, 30, tzinfo=CST)
            ),
        }
    elif not is_td:
        # Non-trading day
        if holiday_info:
            status = "holiday"
            label = f"{holiday_info['name']}休市"
            if holiday_info["days_remaining"] > 0:
                label += f" (还剩{holiday_info['days_remaining']}天)"
        else:
            status = "closed"
            label = "已休市"

        ntd = cal.next_trading_day(today)
        next_event = {
            "type": "open",
            "time": f"{ntd.isoformat()} 09:30",
            "countdown_seconds": _seconds_until(
                now, datetime(ntd.year, ntd.month, ntd.day, 9, 30, tzinfo=CST)
            ),
        }
    elif session == MarketSession.PRE_MARKET:
        status = "pre_market"
        label = "盘前"
        next_event = {
            "type": "open",
            "time": f"{today.isoformat()} 09:30",
            "countdown_seconds": _seconds_until(
                now, datetime(today.year, today.month, today.day, 9, 30, tzinfo=CST)
            ),
        }
    elif session == MarketSession.MORNING:
        status = "trading"
        label = "交易中"
        next_event = {
            "type": "lunch",
            "time": f"{today.isoformat()} 11:30",
            "countdown_seconds": _seconds_until(
                now, datetime(today.year, today.month, today.day, 11, 30, tzinfo=CST)
            ),
        }
    elif session == MarketSession.LUNCH_BREAK:
        status = "lunch"
        label = "午间休市"
        next_event = {
            "type": "open",
            "time": f"{today.isoformat()} 13:00",
            "countdown_seconds": _seconds_until(
                now, datetime(today.year, today.month, today.day, 13, 0, tzinfo=CST)
            ),
        }
    elif session == MarketSession.AFTERNOON:
        status = "trading"
        label = "交易中"
        next_event = {
            "type": "close",
            "time": f"{today.isoformat()} 15:00",
            "countdown_seconds": _seconds_until(
                now, datetime(today.year, today.month, today.day, 15, 0, tzinfo=CST)
            ),
        }
    elif session == MarketSession.AFTER_HOURS:
        status = "closed"
        label = "已休市"
        ntd = cal.next_trading_day(today)
        next_event = {
            "type": "open",
            "time": f"{ntd.isoformat()} 09:30",
            "countdown_seconds": _seconds_until(
                now, datetime(ntd.year, ntd.month, ntd.day, 9, 30, tzinfo=CST)
            ),
        }
    else:
        # CLOSED (before pre-market on a trading day, or late night)
        status = "closed"
        label = "已休市"
        if is_td and t < time(9, 15):
            next_event = {
                "type": "open",
                "time": f"{today.isoformat()} 09:30",
                "countdown_seconds": _seconds_until(
                    now, datetime(today.year, today.month, today.day, 9, 30, tzinfo=CST)
                ),
            }
        else:
            ntd = cal.next_trading_day(today)
            next_event = {
                "type": "open",
                "time": f"{ntd.isoformat()} 09:30",
                "countdown_seconds": _seconds_until(
                    now, datetime(ntd.year, ntd.month, ntd.day, 9, 30, tzinfo=CST)
                ),
            }

    return {
        "status": status,
        "label": label,
        "is_trading": status == "trading",
        "next_event": next_event,
        "holiday_info": holiday_info,
        "is_emergency": is_emergency,
        "emergency_reason": emergency_reason,
    }


def _seconds_until(now: datetime, target: datetime) -> int:
    """Calculate seconds from now until target, minimum 0."""
    delta = (target - now).total_seconds()
    return max(0, int(delta))

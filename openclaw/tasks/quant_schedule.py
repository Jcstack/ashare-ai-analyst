"""Celery tasks for the Quant Agent Schedule (v37.0).

Provides fine-grained scheduled tasks for a quantitative trading workflow:
  - Call auction analysis (9:10, 9:26)
  - Market open briefing (9:30)
  - Morning signals (10:00)
  - Midday summary (11:35)
  - Afternoon scan (13:30)
  - Late session decision (14:30) ★
  - Late session confirm (14:50) ★
  - Close briefing (15:05)
  - Holiday intel (09:00 daily)
  - Holiday outlook (18:00 daily)
"""

from __future__ import annotations

import asyncio
import logging

from openclaw.celery_app import app

logger = logging.getLogger(__name__)


def _get_loop():
    """Lazy-import the trading loop singleton."""
    from src.web.dependencies import get_trading_loop

    return get_trading_loop()


def _run_async(coro):
    """Run an async coroutine from sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Trading-day tasks
# ---------------------------------------------------------------------------


@app.task(
    bind=True,
    name="openclaw.tasks.quant_schedule.task_call_auction_phase1",
    soft_time_limit=60,
    time_limit=90,
    max_retries=1,
    default_retry_delay=20,
)
def task_call_auction_phase1(self):
    """集合竞价预分析 Phase 1 (09:10 CST).

    Early call-auction snapshot: capture order-book imbalance and
    overnight gap expectations before the matching phase begins.
    """
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        logger.debug("Not a trading day — skipping call_auction_phase1")
        return {"skipped": True, "reason": "not_trading_day"}

    logger.info("=== Call Auction Phase 1 (09:10) START ===")
    try:
        trading_loop = _get_loop()
        result = _run_async(trading_loop.run_cycle())
        logger.info("=== Call Auction Phase 1 (09:10) END ===")
        return {
            "task": "call_auction_phase1",
            "session": "pre_open",
            **result.to_dict(),
        }
    except Exception as exc:
        logger.warning("call_auction_phase1 failed, retrying: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    bind=True,
    name="openclaw.tasks.quant_schedule.task_call_auction_phase2",
    soft_time_limit=60,
    time_limit=90,
    max_retries=1,
    default_retry_delay=20,
)
def task_call_auction_phase2(self):
    """集合竞价撮合分析 Phase 2 (09:26 CST).

    Post-matching snapshot: the call auction price is determined at 09:25.
    Capture the matched price vs. previous close for gap analysis.
    """
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        logger.debug("Not a trading day — skipping call_auction_phase2")
        return {"skipped": True, "reason": "not_trading_day"}

    logger.info("=== Call Auction Phase 2 (09:26) START ===")
    try:
        trading_loop = _get_loop()
        result = _run_async(trading_loop.run_cycle())
        logger.info("=== Call Auction Phase 2 (09:26) END ===")
        return {
            "task": "call_auction_phase2",
            "session": "pre_open",
            **result.to_dict(),
        }
    except Exception as exc:
        logger.warning("call_auction_phase2 failed, retrying: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="openclaw.tasks.quant_schedule.task_market_open_briefing",
    soft_time_limit=120,
    time_limit=180,
)
def task_market_open_briefing():
    """开盘简报 (09:30 CST).

    Combines the pre-market briefing with the first live-market snapshot.
    """
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        logger.debug("Not a trading day — skipping market_open_briefing")
        return {"skipped": True, "reason": "not_trading_day"}

    logger.info("=== Market Open Briefing (09:30) START ===")
    trading_loop = _get_loop()
    briefing = _run_async(trading_loop.run_premarket())
    logger.info("=== Market Open Briefing (09:30) END ===")
    return {"task": "market_open_briefing", "session": "open", "briefing": briefing}


@app.task(
    name="openclaw.tasks.quant_schedule.task_morning_signal",
    soft_time_limit=120,
    time_limit=180,
)
def task_morning_signal():
    """早盘信号扫描 (10:00 CST).

    First full OODA cycle after the opening volatility settles.
    Focused on capturing morning momentum and gap-fill patterns.
    """
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        logger.debug("Not a trading day — skipping morning_signal")
        return {"skipped": True, "reason": "not_trading_day"}

    logger.info("=== Morning Signal Scan (10:00) START ===")
    trading_loop = _get_loop()
    result = _run_async(trading_loop.run_cycle())
    logger.info("=== Morning Signal Scan (10:00) END ===")
    return {"task": "morning_signal", "session": "morning", **result.to_dict()}


@app.task(
    name="openclaw.tasks.quant_schedule.task_midday_summary",
    soft_time_limit=120,
    time_limit=180,
)
def task_midday_summary():
    """午盘总结 (11:35 CST).

    End-of-morning session summary. Captures the morning's action
    and prepares positioning for the afternoon session.
    """
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        logger.debug("Not a trading day — skipping midday_summary")
        return {"skipped": True, "reason": "not_trading_day"}

    logger.info("=== Midday Summary (11:35) START ===")
    trading_loop = _get_loop()
    result = _run_async(trading_loop.run_cycle())
    logger.info("=== Midday Summary (11:35) END ===")
    return {"task": "midday_summary", "session": "midday", **result.to_dict()}


@app.task(
    name="openclaw.tasks.quant_schedule.task_afternoon_scan",
    soft_time_limit=120,
    time_limit=180,
)
def task_afternoon_scan():
    """午后扫描 (13:30 CST).

    Afternoon session opening scan. Checks for lunch-break news
    and early afternoon momentum shifts.
    """
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        logger.debug("Not a trading day — skipping afternoon_scan")
        return {"skipped": True, "reason": "not_trading_day"}

    logger.info("=== Afternoon Scan (13:30) START ===")
    trading_loop = _get_loop()
    result = _run_async(trading_loop.run_cycle())
    logger.info("=== Afternoon Scan (13:30) END ===")
    return {"task": "afternoon_scan", "session": "afternoon", **result.to_dict()}


@app.task(
    bind=True,
    name="openclaw.tasks.quant_schedule.task_late_session_decision",
    soft_time_limit=180,
    time_limit=240,
    max_retries=1,
    default_retry_delay=20,
)
def task_late_session_decision(self):
    """尾盘决策 (14:30 CST) ★.

    Critical decision window: evaluate all pending signals and make
    final buy/sell decisions before the close. Higher time limits
    to allow thorough AI reasoning.
    """
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        logger.debug("Not a trading day — skipping late_session_decision")
        return {"skipped": True, "reason": "not_trading_day"}

    logger.info("=== Late Session Decision (14:30) ★ START ===")
    try:
        trading_loop = _get_loop()
        briefing = _run_async(trading_loop.run_late_session_decision())
        logger.info("=== Late Session Decision (14:30) ★ END ===")
        return {"task": "late_session_decision", "session": "late", "briefing": briefing}
    except Exception as exc:
        logger.warning("late_session_decision failed, retrying: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    bind=True,
    name="openclaw.tasks.quant_schedule.task_late_session_confirm",
    soft_time_limit=120,
    time_limit=180,
    max_retries=1,
    default_retry_delay=20,
)
def task_late_session_confirm(self):
    """尾盘确认 (14:50 CST) ★.

    Final confirmation pass: verify that pending orders are still valid,
    check for last-minute news, and confirm or cancel proposals from 14:30.
    """
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        logger.debug("Not a trading day — skipping late_session_confirm")
        return {"skipped": True, "reason": "not_trading_day"}

    logger.info("=== Late Session Confirm (14:50) ★ START ===")
    try:
        trading_loop = _get_loop()
        briefing = _run_async(trading_loop.run_late_session_confirm())
        logger.info("=== Late Session Confirm (14:50) ★ END ===")
        return {"task": "late_session_confirm", "session": "late", "briefing": briefing}
    except Exception as exc:
        logger.warning("late_session_confirm failed, retrying: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="openclaw.tasks.quant_schedule.task_close_briefing",
    soft_time_limit=120,
    time_limit=180,
)
def task_close_briefing():
    """收盘简报 (15:05 CST).

    Immediate post-close briefing: daily P&L, executed trades,
    thesis updates, and next-day outlook.
    """
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if not scheduler.is_trading_day():
        logger.debug("Not a trading day — skipping close_briefing")
        return {"skipped": True, "reason": "not_trading_day"}

    logger.info("=== Close Briefing (15:05) START ===")
    trading_loop = _get_loop()
    review = _run_async(trading_loop.run_postmarket())
    logger.info("=== Close Briefing (15:05) END ===")
    return {"task": "close_briefing", "session": "close", "review": review}


# ---------------------------------------------------------------------------
# Holiday / every-day tasks
# ---------------------------------------------------------------------------


@app.task(
    name="openclaw.tasks.quant_schedule.task_holiday_intel",
    soft_time_limit=180,
    time_limit=240,
)
def task_holiday_intel():
    """假期情报收集 (09:00, every day).

    Runs on NON-trading days only. On trading days the regular intraday
    tasks cover intelligence gathering.
    """
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if scheduler.is_trading_day():
        logger.debug("Trading day — holiday_intel defers to regular tasks")
        return {"skipped": True, "reason": "trading_day"}

    logger.info("=== Holiday Intel (09:00) START ===")
    trading_loop = _get_loop()
    briefing = _run_async(trading_loop.run_premarket())
    logger.info("=== Holiday Intel (09:00) END ===")
    return {"task": "holiday_intel", "session": "holiday", "briefing": briefing}


@app.task(
    name="openclaw.tasks.quant_schedule.task_holiday_outlook",
    soft_time_limit=180,
    time_limit=240,
)
def task_holiday_outlook():
    """假期展望 (18:00, every day).

    Runs on NON-trading days only. Produces an end-of-day outlook
    covering global market developments and next-session expectations.
    """
    from openclaw.timeline_scheduler import TimelineScheduler

    scheduler = TimelineScheduler()
    if scheduler.is_trading_day():
        logger.debug("Trading day — holiday_outlook defers to regular tasks")
        return {"skipped": True, "reason": "trading_day"}

    logger.info("=== Holiday Outlook (18:00) START ===")
    trading_loop = _get_loop()
    result = _run_async(trading_loop.run_overnight())
    logger.info("=== Holiday Outlook (18:00) END ===")
    return {"task": "holiday_outlook", "session": "holiday", "result": result}

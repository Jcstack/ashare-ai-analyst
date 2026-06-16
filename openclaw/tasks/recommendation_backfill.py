"""Recommendation outcome backfill task.

Fetches actual stock prices at T+1/3/5/10 trading days after recommendation
and records whether the recommendation's direction was correct.

Per PRD v28.0 FR-REC041: T+N outcome tracking.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.recommendation_backfill")

# T+N windows to backfill (trading days)
WINDOWS = [1, 3, 5, 10]


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


def _get_price_at_date(symbol: str, target_date: str) -> float | None:
    """Fetch closing price for a symbol at a specific date.

    Uses akshare stock_zh_a_hist to get the price.
    Returns None if data is unavailable.
    """
    try:
        import akshare as ak

        # Fetch a small window around the target date
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        start = (dt - timedelta(days=3)).strftime("%Y%m%d")
        end = (dt + timedelta(days=3)).strftime("%Y%m%d")

        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        if df is None or df.empty:
            return None

        # Find the closest date <= target_date
        df["日期"] = df["日期"].astype(str)
        valid = df[df["日期"] <= target_date]
        if valid.empty:
            # Use the first available date after
            valid = df
        if valid.empty:
            return None

        return float(valid.iloc[-1]["收盘"])
    except Exception as exc:
        logger.debug("Failed to get price for %s at %s: %s", symbol, target_date, exc)
        return None


def _estimate_trading_date(created_at: str, window: int) -> str:
    """Estimate target date by adding calendar days (window * 1.5 for weekends)."""
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        dt = datetime.now()

    # Rough calendar-day estimate: multiply by 1.5 to account for weekends
    cal_days = int(window * 1.5) + 1
    target = dt + timedelta(days=cal_days)
    return target.strftime("%Y-%m-%d")


@app.task(
    name="openclaw.tasks.recommendation_backfill.task_recommendation_backfill",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
def task_recommendation_backfill(self) -> dict[str, Any]:
    """Backfill T+N outcomes for past recommendations.

    Runs daily at 16:45 Mon-Fri after market close.
    For each window (T+1, T+3, T+5, T+10), finds recommendations
    that are old enough but missing outcome data, fetches the actual
    price, and records the result.
    """
    if not _should_execute("task_recommendation_backfill"):
        logger.info("task_recommendation_backfill: skipped (timeline guard)")
        return {"status": "skipped", "reason": "non-trading"}

    try:
        from src.recommendation.rec_store import RecStore

        rec_store = RecStore()
    except Exception as exc:
        logger.error("Failed to initialize RecStore: %s", exc)
        raise self.retry(exc=exc)

    total_filled = 0

    for window in WINDOWS:
        try:
            pending = rec_store.get_pending_backfills(window)
            logger.info(
                "T+%d: %d recommendations pending backfill", window, len(pending)
            )

            for rec in pending:
                rec_id = rec["id"]
                symbol = rec["symbol"]
                entry_price = rec.get("entry_price")
                created_at = rec.get("created_at", "")

                if not entry_price or entry_price <= 0:
                    continue

                target_date = _estimate_trading_date(created_at, window)
                actual_price = _get_price_at_date(symbol, target_date)

                if actual_price is None:
                    continue

                actual_change = (actual_price - entry_price) / entry_price * 100
                ok = rec_store.backfill_outcome(
                    rec_id, window, actual_price, actual_change
                )
                if ok:
                    total_filled += 1

        except Exception as exc:
            logger.error("Failed to backfill T+%d: %s", window, exc)

    logger.info("Recommendation backfill complete: %d outcomes filled", total_filled)
    return {"status": "ok", "total_filled": total_filled}

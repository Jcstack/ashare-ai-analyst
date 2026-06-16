"""Celery task for decision outcome backfill.

Runs daily after market close to backfill T+1/T+3/T+5 outcomes
for past trading decisions, enabling the learning loop.
"""

from __future__ import annotations

import logging

from openclaw.app import app

logger = logging.getLogger(__name__)


@app.task(
    name="openclaw.tasks.decision_backfill.task_decision_backfill",
    soft_time_limit=120,
    time_limit=180,
)
def task_decision_backfill():
    """Backfill T+1/T+3/T+5 outcomes for recent decisions."""
    from src.web.dependencies import get_decision_log, get_stock_service

    decision_log = get_decision_log()
    stock_service = get_stock_service()

    filled = 0

    for horizon in ("t1", "t3", "t5"):
        pending = decision_log.get_pending_backfill(horizon)
        for outcome in pending:
            try:
                quote = stock_service.get_stock_quote(outcome.symbol)
                if quote and quote.get("current_price"):
                    decision_log.backfill_outcome(
                        decision_id=outcome.decision_id,
                        horizon=horizon,
                        price=quote["current_price"],
                    )
                    filled += 1
            except Exception as exc:
                logger.warning(
                    "Failed to backfill %s for %s: %s",
                    horizon,
                    outcome.symbol,
                    exc,
                )

    logger.info("Decision backfill complete: %d outcomes filled", filled)
    return {"filled": filled}

"""Nightly calibration task — closes the feedback loop.

Reads completed outcomes from DecisionLog, triggers debate reflections
for outcomes that had associated debates, and logs calibration summary.

Scheduled via Celery beat at 20:00 CST daily.
"""

from __future__ import annotations

import logging
from typing import Any

from openclaw.celery_app import app as celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="task_nightly_calibration",
    bind=True,
    max_retries=1,
    soft_time_limit=120,
    time_limit=180,
)
def task_nightly_calibration(self: Any) -> dict[str, Any]:
    """Run the nightly calibration pipeline.

    1. Load recent outcomes from DecisionLog
    2. Trigger debate reflections for outcomes with debate records
    3. Cleanup old debate memory (>90 days)
    4. Return summary dict

    Returns:
        Summary with calibration metrics.
    """
    result: dict[str, Any] = {
        "outcomes_processed": 0,
        "reflections_created": 0,
        "debates_cleaned": 0,
    }

    try:
        # 1. Get accuracy stats
        from src.web.dependencies import get_decision_log

        decision_log = get_decision_log()
        stats = decision_log.get_accuracy_stats(lookback_days=60)
        result["accuracy_stats"] = stats
        result["outcomes_processed"] = stats.get("total_decisions", 0)

        logger.info(
            "Calibration: %d decisions, direction accuracy %.1f%%",
            stats.get("total_decisions", 0),
            stats.get("direction_accuracy", 0) * 100,
        )

    except Exception as exc:
        logger.warning("Calibration outcome loading failed: %s", exc)
        result["outcome_error"] = str(exc)

    try:
        # 2. Generate debate reflections from recent decision outcomes
        from src.web.dependencies import get_debate_memory

        memory = get_debate_memory()

        # Use decision_log to find completed decisions with outcomes
        completed = decision_log.get_completed(lookback_days=7)
        for outcome in completed:
            # Only reflect on decisions that had debates stored
            debate_results = memory.retrieve(
                query=outcome.get("symbol", ""),
                symbol=outcome.get("symbol", ""),
                top_k=1,
            )
            if not debate_results:
                continue

            lessons = _generate_reflection_lessons(outcome)
            if lessons:
                memory.store_reflection(
                    debate_id=debate_results[0]["debate_id"],
                    outcome=outcome,
                    lessons=lessons,
                )
                result["reflections_created"] += 1

        logger.info(
            "Calibration: %d debate reflections created",
            result["reflections_created"],
        )

    except Exception as exc:
        logger.warning("Calibration reflection generation failed: %s", exc)
        result["reflection_error"] = str(exc)

    try:
        # 3. Cleanup old debate memory
        from src.web.dependencies import get_debate_memory

        memory = get_debate_memory()
        cleaned = memory.cleanup(max_age_days=90)
        result["debates_cleaned"] = cleaned

    except Exception as exc:
        logger.warning("Calibration cleanup failed: %s", exc)

    logger.info("Nightly calibration complete: %s", result)
    return result


def _generate_reflection_lessons(outcome: dict[str, Any]) -> list[str]:
    """Generate simple reflection lessons from an outcome.

    Args:
        outcome: Dict with t1_return_pct, direction_correct, action, etc.

    Returns:
        List of lesson strings.
    """
    lessons: list[str] = []
    action = outcome.get("action", "")
    t1_ret = outcome.get("t1_return_pct")
    correct = outcome.get("direction_correct")

    if correct is True:
        lessons.append(f"{action}决策方向正确")
        if t1_ret is not None and t1_ret > 3:
            lessons.append(f"收益显著(T+1 {t1_ret:+.1f}%)，该类信号可增加信心")
    elif correct is False:
        lessons.append(f"{action}决策方向错误")
        if t1_ret is not None:
            if t1_ret < -3:
                lessons.append(f"亏损严重(T+1 {t1_ret:+.1f}%)，需检查止损是否过宽")
            else:
                lessons.append(f"小幅亏损(T+1 {t1_ret:+.1f}%)，时机或仓位需调整")

    return lessons

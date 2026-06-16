"""Nightly batch evaluation task.

Runs the EvaluatorAgent on cached analysis results from the day,
generates an aggregate quality report, and flags analyses below
a quality threshold for review.

Part of WS5: Independent Evaluation Agent.

Schedule: Daily 17:00 CST (after market close + backfill).
"""

from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.evaluation_report")

# Quality threshold — analyses below this are flagged for review
QUALITY_THRESHOLD = 0.6


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


@app.task(
    name="evaluation_report.run_batch_evaluation",
    bind=True,
    max_retries=1,
    soft_time_limit=600,
    time_limit=720,
)
def task_run_batch_evaluation(self: Any) -> dict[str, Any]:
    """Run evaluator on today's cached analyses.

    Scans the RealtimeAnalyzer cache for unified analysis results,
    runs the EvaluatorAgent on each, and produces an aggregate report.

    Returns:
        Dict with total_evaluated, avg_quality, flagged_symbols.
    """
    if not _should_execute("batch_evaluation"):
        return {"status": "skipped", "reason": "timeline_profile"}

    from src.agents.evaluator_agent import EvaluatorAgent

    evaluator = EvaluatorAgent()

    # Collect cached analyses from the realtime analyzer
    try:
        from src.web.dependencies import get_realtime_analyzer

        analyzer = get_realtime_analyzer()
        cache = getattr(analyzer, "_cache", {})
    except Exception:
        logger.warning("Could not access analyzer cache")
        return {"status": "error", "reason": "cache_access_failed"}

    results: list[dict[str, Any]] = []
    flagged_symbols: list[str] = []

    for key, (ts, data) in list(cache.items()):
        if not key.startswith("unified_"):
            continue

        symbol = key.replace("unified_", "")

        try:
            report = evaluator.evaluate(data)
            entry = {
                "symbol": symbol,
                "quality_score": report.quality_score,
                "checks_passed": report.checks_passed,
                "checks_total": report.checks_total,
                "flag_count": len(report.flags),
            }
            results.append(entry)

            if report.quality_score < QUALITY_THRESHOLD:
                flagged_symbols.append(symbol)
                logger.warning(
                    "Low quality analysis: %s (score=%.2f, flags=%d)",
                    symbol,
                    report.quality_score,
                    len(report.flags),
                )
        except Exception as exc:
            logger.warning("Evaluation failed for %s: %s", symbol, exc)

    # Aggregate metrics
    total = len(results)
    avg_quality = sum(r["quality_score"] for r in results) / total if total > 0 else 0.0

    report_summary = {
        "status": "success",
        "total_evaluated": total,
        "avg_quality_score": round(avg_quality, 3),
        "flagged_count": len(flagged_symbols),
        "flagged_symbols": flagged_symbols,
        "results": results,
    }

    logger.info(
        "Batch evaluation complete: %d analyses, avg quality=%.2f, %d flagged",
        total,
        avg_quality,
        len(flagged_symbols),
    )

    return report_summary

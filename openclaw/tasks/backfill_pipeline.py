"""Prediction accuracy backfill and drift detection pipeline.

v12.0 Phase 4: Automated tasks to backfill actual price outcomes
for predictions tracked by ModelMonitor, and detect accuracy drift.

Schedule:
- task_backfill_predictions: Daily 16:30 CST (after market close)
- task_detect_drift: Weekly Sunday 10:00 CST
"""

from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.backfill_pipeline")


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


@app.task(
    bind=True,
    max_retries=2,
    name="openclaw.tasks.backfill_pipeline.task_backfill_predictions",
)
def task_backfill_predictions(self: Any) -> dict[str, Any]:
    """Backfill actual price outcomes for pending predictions.

    For each backfill window (T+3, T+5, T+10), finds predictions
    that have not yet been backfilled and fetches the actual price
    change from StockService.

    Returns:
        Dict with per-window backfill counts.
    """
    if not _should_execute("task_backfill_predictions"):
        logger.info("task_backfill_predictions: skipped (timeline guard)")
        return {"_skipped": True}

    logger.info("task_backfill_predictions: starting")

    try:
        from src.intelligence.model_monitor import ModelMonitor
        from src.web.services.stock_service import StockService

        monitor = ModelMonitor()
        stock_service = StockService()

        results: dict[str, Any] = {}

        for window in [3, 5, 10]:
            pending = monitor.get_pending_backfills(window)
            filled = 0
            errors = 0

            for pred in pending:
                symbol = pred["symbol"]
                pred_date = pred["predicted_at"]
                pred_id = pred["prediction_id"]

                try:
                    pct_change = stock_service.get_price_change(
                        symbol, pred_date, window
                    )
                    if pct_change is not None:
                        monitor.backfill_outcome(pred_id, window, pct_change)
                        filled += 1
                    else:
                        logger.debug(
                            "No price data for %s from %s T+%d",
                            symbol,
                            pred_date,
                            window,
                        )
                except Exception:
                    errors += 1
                    logger.warning(
                        "Backfill failed for %s T+%d",
                        pred_id,
                        window,
                        exc_info=True,
                    )

            results[f"t{window}"] = {
                "pending": len(pending),
                "filled": filled,
                "errors": errors,
            }

        logger.info("task_backfill_predictions: completed — %s", results)
        return results

    except Exception as exc:
        logger.error("task_backfill_predictions failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


@app.task(
    bind=True,
    max_retries=1,
    name="openclaw.tasks.backfill_pipeline.task_detect_drift",
)
def task_detect_drift(self: Any) -> dict[str, Any]:
    """Run drift detection across all tracked symbols.

    Checks overall accuracy and per-symbol accuracy against baseline.
    Logs warnings for any detected drift.

    Returns:
        Dict with drift detection results.
    """
    if not _should_execute("task_detect_drift"):
        logger.info("task_detect_drift: skipped (timeline guard)")
        return {"_skipped": True}

    logger.info("task_detect_drift: starting")

    try:
        from src.intelligence.model_monitor import ModelMonitor

        monitor = ModelMonitor()

        # Overall drift check
        report = monitor.detect_drift()

        result: dict[str, Any] = {
            "total_predictions": report.total_predictions,
            "accuracy_t5": report.accuracy_t5,
            "drift_detected": report.drift_detected,
            "drift_amount": report.drift_amount,
            "warnings": report.warnings,
        }

        if report.drift_detected:
            logger.warning(
                "Accuracy drift detected: T+5 accuracy %.1f%%, "
                "baseline %.1f%%, drift %.1f%%",
                (report.accuracy_t5 or 0) * 100,
                report.baseline_accuracy * 100,
                report.drift_amount * 100,
            )
            # Emit system alert for drift
            try:
                from src.intelligence.alert_engine import SystemAlertEngine

                alert_engine = SystemAlertEngine()
                alert_engine.evaluate({
                    "drift_detected": True,
                    "drift_amount": report.drift_amount,
                    "accuracy_t5": report.accuracy_t5,
                })
            except Exception:
                logger.debug("Failed to emit drift alert", exc_info=True)

        # Run PredictionMonitorAgent for structured, schema-compliant report
        try:
            import asyncio
            from src.web.dependencies import get_agent_registry

            registry = get_agent_registry()
            monitor_agent = registry.get("monitor")
            if monitor_agent:
                from src.agents.base import AgentMessage

                msg = AgentMessage(
                    from_agent="scheduler",
                    to_agent="monitor",
                    task="Weekly drift detection report",
                    context={"window_days": 30},
                )
                agent_result = asyncio.run(monitor_agent.execute(msg))
                result["agent_report"] = agent_result.result
                logger.info("PredictionMonitorAgent report attached")
        except Exception:
            logger.debug("Monitor agent invocation failed", exc_info=True)

        logger.info("task_detect_drift: completed — %s", result)
        return result

    except Exception as exc:
        logger.error("task_detect_drift failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)

"""AI news aggregation pipeline task.

Fetches global AI news from 10+ RSS sources every 30 minutes.
Runs 24/7 since AI news is global and not tied to trading hours.
"""

from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.ai_news_pipeline")


@app.task(
    name="openclaw.tasks.ai_news_pipeline.task_fetch_ai_news",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def task_fetch_ai_news(self: Any) -> dict[str, Any]:
    """Fetch and persist AI news from all configured sources.

    Scheduled every 30 minutes, 24/7.
    """
    logger.info("Starting AI news fetch pipeline")

    try:
        from src.web.services.ai_news_service import AiNewsService

        svc = AiNewsService()
        results = svc.refresh()
        total_new = sum(results.values())

        logger.info(
            "AI news pipeline complete: %d new items from %d sources",
            total_new,
            len(results),
        )

        return {
            "status": "ok",
            "new_items": total_new,
            "by_source": results,
        }

    except Exception as exc:
        logger.error("AI news pipeline failed: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="openclaw.tasks.ai_news_pipeline.task_cleanup_ai_news",
    bind=True,
    max_retries=1,
)
def task_cleanup_ai_news(self: Any, days: int = 30) -> dict[str, Any]:
    """Remove AI news items older than N days.

    Scheduled once daily at 04:00 CST.
    """
    logger.info("Starting AI news cleanup (older than %d days)", days)

    try:
        from src.web.services.ai_news_service import AiNewsService

        svc = AiNewsService()
        deleted = svc.cleanup_old(days=days)

        logger.info("AI news cleanup: removed %d old items", deleted)
        return {"status": "ok", "deleted": deleted}

    except Exception as exc:
        logger.error("AI news cleanup failed: %s", exc)
        raise self.retry(exc=exc)

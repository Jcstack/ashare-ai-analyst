"""Expire old stock recommendations.

Runs daily to expire recommendations older than the configured threshold.

Per PRD v28.0: Smart stock recommendation system — cleanup task.
"""

from __future__ import annotations

from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.recommendation_cleanup")


@app.task(
    name="openclaw.tasks.recommendation_cleanup.task_recommendation_cleanup",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def task_recommendation_cleanup(self) -> dict[str, Any]:
    """Expire old recommendations (>3 days)."""
    try:
        from src.recommendation.rec_store import RecStore

        store = RecStore()
        expired = store.expire_old_recommendations(days=3)
        logger.info("Recommendation cleanup: expired %d old recommendations", expired)
        return {"status": "ok", "expired": expired}

    except Exception as exc:
        logger.error("Recommendation cleanup failed: %s", exc)
        raise self.retry(exc=exc)

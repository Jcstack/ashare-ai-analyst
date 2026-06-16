"""Global market data pipeline task.

Fetches global indices, commodities, and currencies on a regular
schedule. Runs regardless of A-share trading hours since foreign
markets have different schedules.

Per PRD v3.2 FR-GM001 + FR-HS002.
"""

from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.global_market_pipeline")


@app.task(
    name="openclaw.tasks.global_market_pipeline.task_fetch_global_snapshot",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def task_fetch_global_snapshot(self) -> dict[str, Any]:
    """Fetch a global market snapshot (indices + commodities + currencies).

    Scheduled every 15 minutes during 07:00-23:00 CST, all days.
    Global markets operate on different schedules, so this runs
    on weekends too (e.g., crypto futures, Middle East markets).
    """
    logger.info("Starting global market snapshot fetch")

    try:
        from src.data.global_market import GlobalMarketFetcher

        fetcher = GlobalMarketFetcher()
        snapshot = fetcher.fetch_global_snapshot()

        n_indices = len(snapshot.get("indices", []))
        n_commodities = len(snapshot.get("commodities", []))
        n_currencies = len(snapshot.get("currencies", []))

        logger.info(
            "Global snapshot fetched: %d indices, %d commodities, %d currencies",
            n_indices,
            n_commodities,
            n_currencies,
        )

        return {
            "status": "ok",
            "indices": n_indices,
            "commodities": n_commodities,
            "currencies": n_currencies,
        }

    except Exception as exc:
        logger.error("Global market snapshot failed: %s", exc)
        raise self.retry(exc=exc)

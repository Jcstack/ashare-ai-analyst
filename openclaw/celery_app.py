"""Celery application factory for the A-share analysis pipeline.

Configures the Celery app with Redis broker and beat schedule for
automated daily data collection, analysis, and prediction tasks.

The configuration is loaded from ``config/openclaw.yaml`` following the
project's config-driven design principle. The broker URL can be
overridden via the ``CELERY_BROKER_URL`` environment variable.

Per PRD FR-O001/FR-O002: OpenClaw automation scheduling layer.
"""

import os
from typing import Any

from celery import Celery
from celery.schedules import crontab

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("openclaw.celery_app")


def _build_beat_schedule(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a Celery beat schedule dict from the openclaw YAML config.

    Translates the ``beat_schedule`` section of ``config/openclaw.yaml``
    into the ``dict[str, dict]`` format that Celery expects for
    ``beat_schedule``.

    Args:
        config: Parsed openclaw.yaml configuration dictionary.

    Returns:
        A dictionary suitable for ``app.conf.beat_schedule``, with each
        entry containing ``task`` and ``schedule`` (a ``crontab`` object).
    """
    raw_schedule: dict[str, Any] = config.get("beat_schedule", {})
    beat_schedule: dict[str, dict[str, Any]] = {}

    for name, entry in raw_schedule.items():
        task_path: str = entry.get("task", "")
        cron_cfg: dict[str, Any] = entry.get("schedule", {}).get("crontab", {})

        if not task_path:
            logger.warning(
                "Skipping beat schedule entry '%s': missing 'task' field",
                name,
            )
            continue

        schedule = crontab(
            minute=str(cron_cfg.get("minute", "*")),
            hour=str(cron_cfg.get("hour", "*")),
            day_of_week=str(cron_cfg.get("day_of_week", "*")),
            day_of_month=str(cron_cfg.get("day_of_month", "*")),
            month_of_year=str(cron_cfg.get("month_of_year", "*")),
        )

        beat_entry: dict[str, Any] = {
            "task": task_path,
            "schedule": schedule,
        }

        # Optional: pass positional or keyword arguments to the task
        if "args" in entry:
            beat_entry["args"] = tuple(entry["args"])
        if "kwargs" in entry:
            beat_entry["kwargs"] = dict(entry["kwargs"])

        beat_schedule[name] = beat_entry

        logger.debug("Registered beat schedule '%s' -> %s", name, task_path)

    return beat_schedule


def create_celery_app() -> Celery:
    """Create and configure the Celery application instance.

    Loads configuration from ``config/openclaw.yaml``, sets up the
    Redis broker and result backend, registers the beat schedule, and
    discovers task modules.

    The broker URL resolution order:
        1. ``CELERY_BROKER_URL`` environment variable (highest priority)
        2. ``celery.broker_url`` in ``config/openclaw.yaml``
        3. Fallback to ``redis://localhost:6379/0``

    Returns:
        A fully configured ``Celery`` application instance.
    """
    try:
        config = load_config("openclaw")
    except FileNotFoundError:
        logger.warning("config/openclaw.yaml not found; using default Celery settings")
        config = {}

    celery_cfg: dict[str, Any] = config.get("celery", {})

    # Resolve broker URL: env var > config > fallback
    default_broker = celery_cfg.get("broker_url", "redis://localhost:6379/0")
    broker_url: str = os.environ.get("CELERY_BROKER_URL", default_broker)

    result_backend: str = celery_cfg.get("result_backend", "redis://localhost:6379/1")
    timezone: str = celery_cfg.get("timezone", "Asia/Shanghai")

    app = Celery("astock", broker=broker_url, backend=result_backend)

    # Core Celery configuration
    app.conf.update(
        timezone=timezone,
        enable_utc=False,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_track_started=True,
        worker_hijack_root_logger=False,
        # Memory management: recycle worker after 512MB to prevent OOM.
        worker_max_memory_per_child=512_000,  # 512MB in KB
        # Reduce prefetch to 1 so workers don't queue memory-heavy tasks
        worker_prefetch_multiplier=1,
        # Default concurrency (overridable via CLI --concurrency)
        worker_concurrency=2,
    )

    # Beat schedule from config
    beat_schedule = _build_beat_schedule(config)
    if beat_schedule:
        app.conf.beat_schedule = beat_schedule
        logger.info("Loaded %d beat schedule entries from config", len(beat_schedule))

    # Auto-discover task modules
    app.autodiscover_tasks(["openclaw.tasks"])

    # Install EastMoney proxy patch so akshare calls in tasks use auth proxy
    try:
        from src.data.eastmoney_proxy import init_proxy_patch

        init_proxy_patch()
    except Exception as exc:
        logger.warning("EastMoney proxy patch init failed: %s", exc)

    logger.info(
        "Celery app 'astock' created (broker=%s, timezone=%s)",
        broker_url,
        timezone,
    )

    return app


# Module-level app instance used by workers and tasks.
# Gracefully handle connection issues on import (e.g., Redis not running).
try:
    app = create_celery_app()
except Exception as exc:
    logger.warning(
        "Failed to create Celery app on import: %s. "
        "Creating app with default settings. "
        "Tasks will fail until the broker is available.",
        exc,
    )
    app = Celery("astock")
    app.conf.update(
        timezone="Asia/Shanghai",
        enable_utc=False,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
    )

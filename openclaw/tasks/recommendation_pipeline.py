"""Automatic stock recommendation generation task.

Generates smart stock recommendations for the current trading session
based on configured investment styles and multi-factor screening.

Per PRD v28.0: Smart stock recommendation system — scheduled generation.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from celery.exceptions import SoftTimeLimitExceeded

from openclaw.celery_app import app
from src.utils.config import load_config
from src.utils.logger import get_logger

_CST = ZoneInfo("Asia/Shanghai")

# Fallback session windows when config/recommendation.yaml is unavailable
_DEFAULT_SESSIONS: dict[str, dict[str, str]] = {
    "pre_market": {"start": "07:00", "end": "09:29"},
    "early": {"start": "09:30", "end": "10:30"},
    "mid": {"start": "10:30", "end": "14:00"},
    "late": {"start": "14:00", "end": "15:00"},
    "post_market": {"start": "15:00", "end": "17:00"},
}

logger = get_logger("openclaw.tasks.recommendation_pipeline")


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


def _current_session() -> str:
    """Determine the current trading session based on time (Asia/Shanghai).

    Returns session key.  Falls back to ``"anytime"`` when outside all
    configured time windows so recommendations are available 24/7.
    """
    try:
        config = load_config("recommendation")
        sessions = config.get("sessions", {}) or {}
    except Exception:
        logger.warning("Failed to load recommendation config, using default sessions")
        sessions = {}

    if not sessions:
        sessions = _DEFAULT_SESSIONS

    now = datetime.now(_CST)
    current_time = now.strftime("%H:%M")

    for session_key, session_cfg in sessions.items():
        # Skip the fallback 'anytime' entry (no start/end)
        start = session_cfg.get("start")
        end = session_cfg.get("end")
        if not start or not end:
            continue
        if start <= current_time <= end:
            return session_key

    logger.info(
        "Outside configured sessions (%s), using 'anytime' fallback", current_time
    )
    return "anytime"


@app.task(
    name="openclaw.tasks.recommendation_pipeline.task_recommendation_generate",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    soft_time_limit=900,
    time_limit=960,
)
def task_recommendation_generate(
    self,
    force_session: str | None = None,
    force_styles: list[str] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Generate stock recommendations for a trading session.

    When called without arguments (scheduled), uses timeline guard and auto-detects
    session/styles. When called with force_session/force_styles (manual refresh),
    skips guards and uses the provided values.
    """
    if not force_session and not _should_execute("task_recommendation_generate"):
        logger.info("task_recommendation_generate: skipped (timeline guard)")
        return {"status": "skipped", "reason": "non-trading"}

    session = force_session or _current_session()

    logger.info("Starting recommendation generation for session: %s", session)

    try:
        config = load_config("recommendation")
    except Exception:
        config = {}

    if force_styles:
        styles = force_styles
    else:
        sessions_cfg = config.get("sessions", {})
        session_cfg = sessions_cfg.get(session, {})
        styles = session_cfg.get("styles", [])

    if not styles:
        logger.info("No styles configured for session: %s", session)
        return {"status": "skipped", "reason": "no_styles"}

    try:
        from src.recommendation.rec_store import RecStore
        from src.recommendation.review_agent import ReviewAgent
        from src.recommendation.screener import StockScreener
        from src.web.services.recommendation_service import RecommendationService
        from src.web.services.user_config_service import UserConfigService

        rec_store = RecStore()

        # Set up Redis for notifications + screener snapshot cache
        redis_client = None
        try:
            import redis

            broker = (
                load_config("openclaw")
                .get("celery", {})
                .get("broker_url", "redis://redis:6379/0")
            )
            redis_client = redis.from_url(broker, decode_responses=True)
        except Exception:
            pass

        screener = StockScreener(config, redis_client=redis_client)

        # Try to set up LLM router (separated from audit log to avoid
        # unrelated failures killing AI review — see I-074)
        llm_router = None
        try:
            from src.llm.gateway import LLMGateway
            from src.llm.router import LLMRouter

            router = LLMRouter()
            if not router.available_providers:
                logger.warning(
                    "LLM router initialized but no providers available "
                    "(check API keys and network/proxy settings)"
                )
            else:
                logger.info(
                    "LLM router ready: providers=%s",
                    [p.value for p in router.available_providers],
                )

            # Audit log is optional — don't let it break LLM
            audit_log = None
            try:
                from src.audit.immutable_log import ImmutableAuditLog

                audit_log = ImmutableAuditLog()
            except Exception as audit_exc:
                logger.warning("Audit log unavailable (non-fatal): %s", audit_exc)

            llm_router = LLMGateway(router=router, audit_log=audit_log)
        except Exception as llm_exc:
            logger.error(
                "LLM initialization FAILED — all recommendations will be "
                "score-only (no AI review): %s",
                llm_exc,
                exc_info=True,
            )

        trading_profile = config.get("trading_profile", {})
        review_agent = ReviewAgent(
            llm_router=llm_router, trading_profile=trading_profile
        )
        user_config = UserConfigService()

        # Set up InfoStore for news context
        info_store = None
        try:
            from src.intelligence_hub.info_store import InfoStore

            info_store = InfoStore()
        except Exception:
            logger.info("InfoStore not available, skipping news context")

        # Set up MacroRadar and IntelReportStore for enriched context (I-089)
        macro_radar = None
        report_store = None
        try:
            from src.market_intelligence.macro_radar import MacroRadarService
            from src.data.global_market import GlobalMarketFetcher

            macro_radar = MacroRadarService(
                global_fetcher=GlobalMarketFetcher(),
                info_store=info_store,
            )
        except Exception:
            logger.info("MacroRadar not available, skipping macro context")
        try:
            from src.intelligence_hub.report_store import IntelReportStore

            report_store = IntelReportStore()
        except Exception:
            logger.info("IntelReportStore not available, skipping report context")

        service = RecommendationService(
            rec_store=rec_store,
            screener=screener,
            review_agent=review_agent,
            user_config_service=user_config,
            redis_client=redis_client,
            info_store=info_store,
            macro_radar=macro_radar,
            report_store=report_store,
        )

        # Pre-warm screener snapshot cache (avoid concurrent first-fetch)
        try:
            screener._fetch_market_snapshot()
            logger.info("Market snapshot cache pre-warmed")
        except Exception as exc:
            logger.warning("Snapshot pre-warm failed (will retry per-style): %s", exc)

        def _run_style(s: str) -> tuple[str, int, str | None]:
            """Generate recommendations for one style. Returns (style, count, error)."""
            try:
                recs = service.generate_recommendations(s, session, run_id=run_id)
                logger.info(
                    "Generated %d recommendations for style=%s, session=%s",
                    len(recs),
                    s,
                    session,
                )
                return (s, len(recs), None)
            except Exception as exc:
                logger.error(
                    "Failed to generate recommendations for style=%s: %s", s, exc
                )
                return (s, 0, f"{s}: {exc}")

        total_recs = 0
        errors: list[str] = []
        max_workers = min(len(styles), 3)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_run_style, s): s for s in styles}
            for future in as_completed(futures):
                style_key = futures[future]
                try:
                    _, count, err = future.result(timeout=300)
                    total_recs += count
                    if err:
                        errors.append(err)
                except Exception as exc:
                    logger.error("Style %s timed out or crashed: %s", style_key, exc)
                    errors.append(f"{style_key}: {exc}")

        if errors and total_recs == 0:
            service.fail_run(run_id, f"All styles failed: {'; '.join(errors)[:200]}")
        else:
            service.complete_run(run_id, total_recs)

        logger.info(
            "Recommendation generation complete: session=%s, total=%d",
            session,
            total_recs,
        )
        return {
            "status": "ok",
            "session": session,
            "styles": styles,
            "total_recommendations": total_recs,
        }

    except SoftTimeLimitExceeded:
        logger.error(
            "Recommendation pipeline TIMEOUT (soft_time_limit): session=%s", session
        )
        if run_id:
            try:
                import redis as _redis_mod

                broker = (
                    load_config("openclaw")
                    .get("celery", {})
                    .get("broker_url", "redis://redis:6379/0")
                )
                _rc = _redis_mod.from_url(broker, decode_responses=True)
                _rc.hset(
                    f"rec:run:{run_id}",
                    mapping={"status": "failed", "error": "timeout"},
                )
            except Exception:
                pass
        return {
            "status": "failed",
            "session": session,
            "error": "timeout",
        }

    except Exception as exc:
        logger.error("Recommendation generation failed: %s", exc)
        # Try to mark run as failed before retrying
        if run_id:
            try:
                import redis as _redis_mod

                broker = (
                    load_config("openclaw")
                    .get("celery", {})
                    .get("broker_url", "redis://redis:6379/0")
                )
                _rc = _redis_mod.from_url(broker, decode_responses=True)
                _rc.hset(
                    f"rec:run:{run_id}",
                    mapping={
                        "status": "failed",
                        "error": str(exc)[:200],
                    },
                )
            except Exception:
                pass
        raise self.retry(exc=exc)

"""Stock recommendation API endpoints.

Per PRD v28.0: Smart stock recommendation system — REST API.
"""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from src.utils.config import load_config
from src.web.dependencies import get_recommendation_service
from src.web.services.recommendation_service import RecommendationService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["recommendations"])


@router.get("/")
async def list_recommendations(
    style: str | None = Query(None, description="Investment style filter"),
    session: str | None = Query(None, description="Trading session filter"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    svc: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    """List active recommendations with optional filters."""
    recs = await asyncio.to_thread(
        svc.get_recommendations, style=style, session=session, limit=limit
    )
    return {"items": recs, "count": len(recs)}


@router.get("/today")
async def today_recommendations(
    style: str | None = Query(None, description="Investment style filter"),
    svc: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    """Get today's recommendations."""
    recs = await asyncio.to_thread(svc.get_today_recommendations, style=style)
    return {"items": recs, "count": len(recs)}


@router.get("/count")
async def recommendation_count(
    svc: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    """Count today's active recommendations (for unread badge)."""
    count = await asyncio.to_thread(svc.count_today_active)
    return {"count": count}


@router.get("/performance")
async def get_performance(
    style: str | None = Query(None, description="Filter by investment style"),
    session: str | None = Query(None, description="Filter by trading session"),
    days: int = Query(90, ge=1, le=365, description="Look-back days"),
    svc: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    """Get aggregated recommendation performance statistics (FR-REC054)."""
    stats = await asyncio.to_thread(
        svc.get_performance_stats, style=style, session=session, days=days
    )
    return stats


def _run_sync_generation(
    svc: RecommendationService,
    session: str,
    styles: list[str],
    run_id: str | None = None,
) -> None:
    """Run recommendation generation synchronously (fallback when Celery unavailable)."""
    total = 0
    errors: list[str] = []
    for style in styles:
        try:
            recs = svc.generate_recommendations(style, session, run_id=run_id)
            total += len(recs)
            logger.info(
                "Sync fallback: generated %d recommendations for style=%s, session=%s",
                len(recs),
                style,
                session,
            )
        except Exception as exc:
            logger.error("Sync fallback: failed for style=%s: %s", style, exc)
            errors.append(f"{style}: {exc}")

    if errors and total == 0:
        svc.fail_run(run_id, f"All styles failed: {'; '.join(errors)[:200]}")
    else:
        svc.complete_run(run_id, total)


@router.post("/refresh", status_code=202)
async def manual_refresh(
    background_tasks: BackgroundTasks,
    svc: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    """Manually trigger recommendation generation with 30-min cooldown (FR-REC052).

    Tries Celery dispatch first; falls back to in-process background task
    if Celery/Redis is unavailable.
    """
    # Quick cooldown + session check (synchronous, fast)
    preflight = await asyncio.to_thread(svc.preflight_refresh)
    if preflight.get("status") != "ok":
        return preflight

    session = preflight["session"]
    styles = preflight["styles"]
    run_id = preflight.get("run_id")

    # Try Celery dispatch first; fall back to sync background task
    try:
        from openclaw.tasks.recommendation_pipeline import task_recommendation_generate

        task_recommendation_generate.delay(
            force_session=session,
            force_styles=styles,
            run_id=run_id,
        )
        logger.info("Recommendation task dispatched to Celery: session=%s", session)
    except Exception as exc:
        logger.warning("Celery dispatch failed (%s), using sync fallback", exc)
        background_tasks.add_task(_run_sync_generation, svc, session, styles, run_id)

    return {
        "status": "accepted",
        "message": "推荐生成中，请稍候...",
        "session": session,
        "run_id": run_id,
    }


@router.get("/styles")
async def list_styles() -> dict:
    """List available investment styles from config."""
    try:
        config = load_config("recommendation")
    except Exception:
        config = {}

    styles = config.get("styles", {})
    result = []
    for key, cfg in styles.items():
        result.append(
            {
                "key": key,
                "label": cfg.get("label", key),
            }
        )
    return {"styles": result}


@router.get("/preferences")
async def get_preferences(
    svc: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    """Get user's full recommendation preferences (FR-REC053)."""
    config = await asyncio.to_thread(svc.get_full_preferences)
    return config


@router.put("/preferences")
async def update_preferences(
    body: dict,
    svc: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    """Update user's recommendation preferences (FR-REC053).

    Accepts full InvestmentStyleConfig JSON or legacy {investment_style: str}.
    """
    # Support legacy single-style format
    if "investment_style" in body and "styles" not in body:
        body["styles"] = [body.pop("investment_style")]

    config = await asyncio.to_thread(svc.update_full_preferences, body)
    return config


@router.get("/refresh/status")
async def refresh_status(
    run_id: str | None = Query(None, description="Run ID from refresh response"),
    svc: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    """Get the status of a recommendation refresh run (I-041)."""
    return await asyncio.to_thread(svc.get_run_status, run_id)


# --- Parameterized routes MUST come after all static paths ---


@router.get("/{rec_id}")
async def get_recommendation(
    rec_id: str,
    svc: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    """Get a single recommendation by ID (FR-REC051)."""
    rec = await asyncio.to_thread(svc.get_recommendation, rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return rec


@router.post("/{rec_id}/dismiss")
async def dismiss_recommendation(
    rec_id: str,
    svc: RecommendationService = Depends(get_recommendation_service),
) -> dict:
    """Dismiss a recommendation."""
    ok = await asyncio.to_thread(svc.dismiss, rec_id)
    return {"success": ok}

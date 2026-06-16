"""Scheduler API endpoints for managing timeline scheduling.

Per PRD v3.2 FR-SS004: Scheduler API endpoints.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException

from src.web.dependencies import (
    get_sentinel_config_service,
    get_timeline_scheduler,
    get_trading_calendar,
)

router = APIRouter(tags=["scheduler"])


@router.get("/status")
async def get_scheduler_status(
    scheduler=Depends(get_timeline_scheduler),
) -> dict:
    """Get current scheduler status (mode, next switch)."""
    return await asyncio.to_thread(scheduler.get_status)


@router.get("/plans")
async def get_schedule_plans(
    scheduler=Depends(get_timeline_scheduler),
) -> dict:
    """Get all schedule plans with their task configurations."""
    return await asyncio.to_thread(_build_plans, scheduler)


@router.put("/plans/{plan}")
async def update_schedule_plan(
    plan: str,
    tasks: dict[str, bool] = Body(..., embed=True),
    scheduler=Depends(get_timeline_scheduler),
) -> dict:
    """Update task configurations for a specific plan.

    Args:
        plan: Plan name (trading_day, holiday, pre_market, after_hours).
        tasks: Dict of task_name -> enabled/disabled.
    """
    from openclaw.timeline_scheduler import ScheduleProfile

    valid_plans = [p.value for p in ScheduleProfile]
    if plan not in valid_plans:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid plan '{plan}'. Valid: {valid_plans}",
        )

    # Update the config in memory
    profiles_config = scheduler._config.setdefault("profiles", {})
    plan_cfg = profiles_config.setdefault(plan, {})
    tasks_cfg = plan_cfg.setdefault("tasks", {})
    tasks_cfg.update(tasks)

    return {"status": "success", "message": f"Plan '{plan}' updated"}


@router.post("/override")
async def set_scheduler_override(
    profile: str | None = Body(None, embed=True),
    scheduler=Depends(get_timeline_scheduler),
) -> dict:
    """Manually override the current schedule profile.

    Pass null to clear the override.
    """
    from openclaw.timeline_scheduler import ScheduleProfile

    if profile is None:
        scheduler.set_override(None)
        return {"status": "success", "message": "Override cleared"}

    try:
        p = ScheduleProfile(profile)
    except ValueError:
        valid = [v.value for v in ScheduleProfile]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid profile '{profile}'. Valid: {valid}",
        )

    scheduler.set_override(p)
    return {"status": "success", "message": f"Override set to {p.value}"}


@router.get("/calendar")
async def get_scheduler_calendar(
    days: int = 30,
    calendar=Depends(get_trading_calendar),
) -> dict:
    """Get trading calendar for the next N days."""
    return await asyncio.to_thread(_build_calendar, calendar, days)


@router.get("/sentinel-config")
async def get_sentinel_config(
    svc=Depends(get_sentinel_config_service),
) -> dict:
    """Get the current sentinel configuration (data sources + notifications)."""
    return svc.get_config()


@router.put("/sentinel-config")
async def update_sentinel_config(
    config: dict = Body(...),
    svc=Depends(get_sentinel_config_service),
) -> dict:
    """Update sentinel configuration."""
    svc.update_config(config)
    return {"status": "success", "message": "Sentinel config updated"}


def _build_plans(scheduler) -> dict:
    """Build the plans response from scheduler config."""
    from openclaw.timeline_scheduler import ScheduleProfile

    profiles_config = scheduler._config.get("profiles", {})

    plan_labels = {
        "trading_day": "交易日计划",
        "holiday": "假期计划",
        "pre_market": "盘前计划",
        "after_hours": "盘后计划",
    }

    # All known tasks
    all_tasks = {
        "task_fetch_all": "日终数据采集",
        "task_analyze_all": "日终技术分析",
        "task_predict_all": "日终 AI 预测",
        "task_weekly_report": "每周汇总报告",
        "task_sentiment_scan": "舆情扫描",
        "task_market_overview": "市场概览",
        "task_fetch_global_snapshot": "全球市场快照",
    }

    plans = []
    for profile in ScheduleProfile:
        cfg = profiles_config.get(profile.value, {})
        default = cfg.get("default", True)
        tasks_cfg = cfg.get("tasks", {})

        task_list = []
        for task_name, desc in all_tasks.items():
            enabled = tasks_cfg.get(task_name, default)
            task_list.append(
                {
                    "name": task_name,
                    "enabled": bool(enabled),
                    "description": desc,
                }
            )

        plans.append(
            {
                "name": profile.value,
                "label": plan_labels.get(profile.value, profile.value),
                "default_enabled": default,
                "tasks": task_list,
            }
        )

    return {"plans": plans}


def _build_calendar(calendar, days: int) -> dict:
    """Build the calendar response."""
    today = date.today()
    result = []

    for i in range(min(days, 60)):
        d = today + timedelta(days=i)
        is_trading = calendar.is_trading_day(d)
        result.append(
            {
                "date": d.isoformat(),
                "is_trading_day": is_trading,
                "is_weekend": d.weekday() >= 5,
                "is_holiday": not is_trading and d.weekday() < 5,
                "day_of_week": d.weekday(),
            }
        )

    return {
        "days": result,
        "today": today.isoformat(),
        "next_trading_day": calendar.next_trading_day(today).isoformat(),
    }

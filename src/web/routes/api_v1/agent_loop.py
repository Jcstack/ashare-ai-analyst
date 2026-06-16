"""Agent Loop API — exposes autonomous trading agent status and controls.

GET  /api/v1/agent/status     — current agent state (theses, recent decisions, accuracy)
GET  /api/v1/agent/theses     — all active investment theses
GET  /api/v1/agent/decisions   — recent decision log with outcomes
POST /api/v1/agent/cycle      — manually trigger one OODA cycle (debug)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/agent", tags=["agent-loop"])


@router.get("/status")
async def agent_status() -> dict[str, Any]:
    """Return current agent state summary."""
    from src.web.dependencies import (
        get_decision_log,
        get_thesis_store,
    )

    thesis_store = get_thesis_store()
    decision_log = get_decision_log()

    theses = thesis_store.get_active()
    stats = decision_log.get_accuracy_stats(lookback_days=30)
    recent = decision_log.get_recent(limit=5)

    return {
        "active_theses": len(theses),
        "theses": [t.to_dict() for t in theses],
        "accuracy": stats,
        "recent_decisions": [d.to_dict() for d in recent],
    }


@router.get("/theses")
async def list_theses(include_invalidated: bool = False) -> list[dict[str, Any]]:
    """Return all investment theses."""
    from src.web.dependencies import get_thesis_store

    store = get_thesis_store()
    theses = store.get_all(include_invalidated=include_invalidated)
    return [t.to_dict() for t in theses]


@router.get("/theses/{symbol}")
async def get_thesis(symbol: str) -> dict[str, Any]:
    """Return thesis for a specific symbol."""
    from src.web.dependencies import get_thesis_store

    store = get_thesis_store()
    thesis = store.get(symbol)
    if thesis is None:
        raise HTTPException(status_code=404, detail=f"No active thesis for {symbol}")
    return thesis.to_dict()


@router.get("/decisions")
async def list_decisions(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent decisions with outcomes."""
    from src.web.dependencies import get_decision_log

    log = get_decision_log()
    decisions = log.get_recent(limit=limit)
    return [d.to_dict() for d in decisions]


@router.get("/accuracy")
async def accuracy_stats(lookback_days: int = 30) -> dict[str, Any]:
    """Return decision accuracy statistics."""
    from src.web.dependencies import get_decision_log

    log = get_decision_log()
    return log.get_accuracy_stats(lookback_days=lookback_days)


@router.get("/calibration")
async def calibration_report() -> dict[str, Any]:
    """Return confidence calibration report (Phase 5)."""
    from src.web.dependencies import get_confidence_calibrator

    calibrator = get_confidence_calibrator()
    return calibrator.get_calibration_report()


@router.post("/cycle")
async def trigger_cycle() -> dict[str, Any]:
    """Manually trigger one OODA cycle (for debugging)."""
    from src.web.dependencies import get_trading_loop

    loop = get_trading_loop()
    result = await loop.run_cycle()
    return result.to_dict()

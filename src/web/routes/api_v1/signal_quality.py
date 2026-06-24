"""Signal Quality API — monitoring endpoints for signal accuracy and learning.

Provides visibility into signal accuracy by source, missed opportunities,
Bayesian calibration status, and factor predictive power rankings.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from src.web.dependencies import (
    get_factor_validator,
    get_outcome_tracker,
)

router = APIRouter(tags=["signal-quality"])

logger = logging.getLogger(__name__)

_CST = ZoneInfo("Asia/Shanghai")


@router.get("/accuracy")
async def get_accuracy(
    source: str | None = Query(None, description="Filter by signal source"),
    lookback_days: int = Query(60, ge=1, le=365),
    outcome_tracker=Depends(get_outcome_tracker),
) -> dict:
    """Get signal accuracy by source."""
    results = outcome_tracker.get_accuracy_by_source(
        source=source, lookback_days=lookback_days
    )
    return {
        "lookback_days": lookback_days,
        "source_filter": source,
        "sources": [
            {
                "source": r.source,
                "total_signals": r.total_signals,
                "direction_correct": r.direction_correct,
                "accuracy": round(r.accuracy, 4),
                "avg_return_correct": round(r.avg_return_correct, 2),
                "avg_return_incorrect": round(r.avg_return_incorrect, 2),
            }
            for r in results
        ],
    }


@router.get("/missed")
async def get_missed_opportunities(
    date: str | None = Query(
        None, description="Date (YYYY-MM-DD), defaults to yesterday"
    ),
    threshold_pct: float = Query(5.0, ge=1.0, le=20.0),
    outcome_tracker=Depends(get_outcome_tracker),
) -> dict:
    """Get recent missed opportunities."""
    if date is None:
        date = (datetime.now(_CST) - timedelta(days=1)).strftime("%Y-%m-%d")

    missed = await outcome_tracker.get_missed_opportunities(date)
    return {
        "date": date,
        "threshold_pct": threshold_pct,
        "count": len(missed),
        "missed": [m.to_dict() for m in missed],
    }


@router.get("/calibration")
async def get_calibration_status(
    lookback_days: int = Query(90, ge=1, le=365),
    outcome_tracker=Depends(get_outcome_tracker),
) -> dict:
    """Get current vs empirical likelihood tables for Bayesian engine."""
    calibration = outcome_tracker.get_calibration_data(lookback_days=lookback_days)

    buckets = []
    for key, (p_bull, p_bear) in calibration.items():
        parts = key.split("/", 1)
        buckets.append(
            {
                "source": parts[0] if len(parts) > 0 else key,
                "confidence_bucket": parts[1] if len(parts) > 1 else "unknown",
                "p_given_bull": round(p_bull, 4),
                "p_given_bear": round(p_bear, 4),
            }
        )

    return {
        "lookback_days": lookback_days,
        "bucket_count": len(buckets),
        "buckets": buckets,
    }


@router.get("/factors")
async def get_factor_rankings(
    lookback_days: int = Query(90, ge=1, le=365),
    factor_validator=Depends(get_factor_validator),
) -> dict:
    """Get factor predictive power rankings."""
    reports = await factor_validator.rank_factors(lookback_days=lookback_days)

    redundant = await factor_validator.detect_redundancy(lookback_days=lookback_days)

    return {
        "lookback_days": lookback_days,
        "factor_count": len(reports),
        "factors": [r.to_dict() for r in reports],
        "redundant_pairs": [
            {"factor_a": a, "factor_b": b, "correlation": c} for a, b, c in redundant
        ],
    }


@router.get("/summary")
async def get_quality_summary(
    outcome_tracker=Depends(get_outcome_tracker),
) -> dict:
    """Get overall signal quality summary.

    Returns aggregate stats: total signals tracked, overall accuracy,
    top sources by accuracy, recent missed count, and calibration coverage.
    """
    # Accuracy by source (60-day default)
    accuracy_results = outcome_tracker.get_accuracy_by_source(lookback_days=60)

    total_signals = sum(r.total_signals for r in accuracy_results)
    total_correct = sum(r.direction_correct for r in accuracy_results)
    overall_accuracy = total_correct / total_signals if total_signals > 0 else 0.0

    # Top 5 sources by total signals
    top_sources = [
        {
            "source": r.source,
            "accuracy": round(r.accuracy, 4),
            "total": r.total_signals,
        }
        for r in accuracy_results[:5]
    ]

    # Recent missed (last 7 days)
    recent_missed_count = 0
    for days_ago in range(1, 8):
        date_str = (datetime.now(_CST) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        missed = await outcome_tracker.get_missed_opportunities(date_str)
        recent_missed_count += len(missed)

    # Calibration coverage
    calibration = outcome_tracker.get_calibration_data(lookback_days=90)
    # Estimate total possible buckets (sources × 3 confidence levels)
    unique_sources = len(set(r.source for r in accuracy_results))
    total_possible = max(1, unique_sources * 3)
    calibration_coverage = min(1.0, len(calibration) / total_possible)

    return {
        "total_signals_tracked": total_signals,
        "overall_accuracy": round(overall_accuracy, 4),
        "accuracy_by_source": top_sources,
        "recent_missed_count": recent_missed_count,
        "calibration_coverage": round(calibration_coverage, 4),
    }

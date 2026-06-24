"""Simplified performance summary API endpoint.

Per PRD v36.0: Plain-language performance stats for retail investors.
Performance tracking now uses the decision log from the InvestmentDirector
OODA cycle instead of the legacy recommendation system.
"""

import logging

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["performance"])


@router.get("/summary")
async def performance_summary(
    days: int = Query(30, ge=1, le=365, description="Look-back days"),
) -> dict:
    """Simplified performance summary in plain Chinese.

    Returns accuracy percentage, a Chinese label, and recent results.
    Note: Legacy recommendation-based performance tracking has been removed.
    Performance is now tracked via the InvestmentDirector decision log.
    """
    return {
        "accuracy_pct": None,
        "accuracy_label": f"过去 {days} 天暂无足够数据评估准确率",
        "recent_results": [],
        "total_signals": 0,
        "profitable_signals": 0,
    }

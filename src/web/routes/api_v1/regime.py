"""Regime API endpoint.

Exposes current market regime state: sentiment cycle phase, HMM state,
reflexivity loop, and risk budget.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends

from src.web.dependencies import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["regime"])

# Phase name mapping (English -> Chinese)
_PHASE_CN = {
    "accumulation": "蓄势",
    "acceleration": "加速",
    "euphoria": "亢奋",
    "distribution": "派发",
    "panic": "恐慌",
    "capitulation": "投降",
    "unknown": "未知",
}


def _safe_redis_hget(redis_client, hash_key: str, field: str) -> dict:
    """Read a JSON field from a Redis hash, returning empty dict on failure."""
    if not redis_client:
        return {}
    try:
        raw = redis_client.hget(hash_key, field)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {}


def _safe_redis_json(redis_client, key: str) -> dict:
    """Read a JSON blob from Redis, returning empty dict on any failure."""
    if not redis_client:
        return {}
    try:
        raw = redis_client.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        logger.debug("Failed to read %s from Redis", key, exc_info=True)
    return {}


@router.get("/regime")
async def get_regime(
    redis_client=Depends(get_redis),
) -> dict:
    """Return full regime state from Redis caches.

    Aggregates sentiment cycle, HMM regime, reflexivity loop, and risk budget.
    Returns safe defaults when data is unavailable.
    """
    # Read from SharedBeliefState Redis hash (primary) with fallback to legacy keys
    regime = _safe_redis_hget(
        redis_client, "belief_state", "regime"
    ) or _safe_redis_json(redis_client, "regime:current")
    sentiment = _safe_redis_json(redis_client, "regime:sentiment")
    reflexivity = _safe_redis_json(redis_client, "regime:reflexivity")
    risk_budget = _safe_redis_hget(
        redis_client, "belief_state", "risk_budget"
    ) or _safe_redis_json(redis_client, "regime:risk_budget")

    # Sentiment phase
    phase = regime.get("sentiment_phase") or sentiment.get("phase", "unknown")
    phase_cn = _PHASE_CN.get(phase, "未知")

    return {
        "sentiment": {
            "phase": phase,
            "phase_cn": phase_cn,
            "signals": {
                "limit_up_count": sentiment.get("limit_up_count", 0),
                "consecutive_board_height": sentiment.get(
                    "consecutive_board_height", 0
                ),
                "limit_down_count": sentiment.get("limit_down_count", 0),
                "volume_change_pct": sentiment.get("volume_change_pct", 0.0),
                "northbound_flow_net": sentiment.get("northbound_flow_net", 0),
            },
            "position_limits": {
                "max_position_pct": sentiment.get("max_position_pct", 0.25),
                "max_equity_pct": sentiment.get("max_equity_pct", 0.80),
            },
        },
        "hmm": {
            "state": regime.get("hmm_state", "unknown"),
            "probability": regime.get("hmm_probability", 0.0),
            "switch_probability": regime.get("hmm_switch_probability", 0.0),
        },
        "reflexivity": {
            "state": reflexivity.get("state", "unknown"),
            "loop_type": reflexivity.get("loop_type", "unknown"),
        },
        "risk_budget": {
            "daily_limit_pct": risk_budget.get("daily_limit_pct", 0.03),
            "used_pct": risk_budget.get("used_pct", 0.0),
            "remaining_pct": risk_budget.get("remaining_pct", 0.03),
        },
    }

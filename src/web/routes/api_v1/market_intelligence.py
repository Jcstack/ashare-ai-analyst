"""Market Intelligence API endpoints — signals, trends, anomalies, macro regime.

Per PRD v20.0 Phase 5: Market Intelligence API surface exposing signal store,
sector rotation, correlation, macro classification, and notification timeline.
Phase 7 adds signal accuracy history endpoint.
"""

import logging
from datetime import UTC, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from src.web.dependencies import (
    get_correlation_service,
    get_macro_classifier,
    get_notification_log,
    get_sector_rotation_detector,
    get_signal_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["market-intelligence"])


@router.get("/signals")
async def list_signals(
    signal_type: str | None = Query(None, description="Filter by signal type"),
    asset: str | None = Query(None, description="Filter by asset/symbol"),
    phase: str | None = Query(None, description="Filter by trading phase"),
    limit: int = Query(50, ge=1, le=500, description="Max signals to return"),
    days: int = Query(7, ge=1, le=90, description="Lookback window in days"),
    store=Depends(get_signal_store),
) -> list[dict]:
    """List signals with optional filters.

    Returns up to *limit* signals from the last *days* days, optionally
    filtered by signal_type, asset, and/or phase.
    """
    try:
        signals = store.get_signals(
            signal_type=signal_type,
            asset=asset,
            phase=phase,
            limit=limit,
            days=days,
        )
        return signals
    except Exception as exc:
        logger.warning("Failed to fetch signals: %s", exc)
        return []


@router.get("/trend-radar")
async def trend_radar(
    store=Depends(get_signal_store),
) -> dict:
    """Trend signals summary.

    Aggregates S1_TREND and S2_MOMENTUM_SHIFT signals, groups by asset,
    and returns the top movers.
    """
    try:
        trend_signals = store.get_signals(signal_type="S1_TREND", limit=200, days=7)
        momentum_signals = store.get_signals(
            signal_type="S2_MOMENTUM_SHIFT", limit=200, days=7
        )

        all_signals = trend_signals + momentum_signals

        # Group by asset
        by_asset: dict[str, list[dict]] = {}
        for sig in all_signals:
            asset_key = sig.get("asset", "unknown")
            by_asset.setdefault(asset_key, []).append(sig)

        # Build summary sorted by signal count (top movers first)
        trends = [
            {
                "asset": asset_key,
                "signal_count": len(sigs),
                "latest_signal": max(sigs, key=lambda s: s.get("timestamp", "")),
                "types": list({s.get("signal_type") for s in sigs}),
            }
            for asset_key, sigs in sorted(
                by_asset.items(), key=lambda x: len(x[1]), reverse=True
            )
        ]

        return {
            "trends": trends,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning("Failed to build trend radar: %s", exc)
        return {"trends": [], "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/anomaly-radar")
async def anomaly_radar(
    store=Depends(get_signal_store),
) -> dict:
    """Anomaly signals summary.

    Aggregates S4_ANOMALY and S5_VOLATILITY signals and returns them
    sorted by recency.
    """
    try:
        anomaly_signals = store.get_signals(signal_type="S4_ANOMALY", limit=200, days=7)
        volatility_signals = store.get_signals(
            signal_type="S5_VOLATILITY", limit=200, days=7
        )

        all_signals = anomaly_signals + volatility_signals

        # Sort by timestamp descending
        anomalies = sorted(
            all_signals, key=lambda s: s.get("timestamp", ""), reverse=True
        )

        return {
            "anomalies": anomalies,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning("Failed to build anomaly radar: %s", exc)
        return {"anomalies": [], "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/sector-rotation")
async def sector_rotation(
    detector=Depends(get_sector_rotation_detector),
) -> dict:
    """Sector rotation data.

    Runs the sector rotation detector and returns the current rotation
    analysis including leading/lagging sectors and rotation direction.
    """
    try:
        result = detector.detect_rotation()
        return result
    except Exception as exc:
        logger.warning("Failed to detect sector rotation: %s", exc)
        return {"error": str(exc), "sectors": []}


@router.get("/correlation")
async def correlation_matrix(
    symbols: str = Query(
        ..., description="Comma-separated stock symbols (e.g. '600519,000858,601318')"
    ),
    lookback_days: int = Query(60, ge=5, le=365, description="Lookback window in days"),
    service=Depends(get_correlation_service),
) -> dict:
    """Correlation matrix for the given symbols.

    Computes a pairwise correlation matrix over the specified lookback
    window and returns it as a nested dict.
    """
    symbols_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if len(symbols_list) < 2:
        return {"error": "At least 2 symbols required", "matrix": {}}

    try:
        matrix = service.compute_matrix(symbols_list, lookback_days)
        return matrix
    except Exception as exc:
        logger.warning("Failed to compute correlation matrix: %s", exc)
        return {"error": str(exc), "matrix": {}}


@router.get("/macro-regime")
async def macro_regime(
    classifier=Depends(get_macro_classifier),
) -> dict:
    """Current macro regime classification.

    Returns the current macro regime label, confidence score, and
    contributing indicators.
    """
    try:
        result = classifier.classify()
        return result
    except Exception as exc:
        logger.warning("Failed to classify macro regime: %s", exc)
        return {"error": str(exc), "regime": "unknown"}


@router.get("/timeline")
async def notification_timeline(
    limit: int = Query(50, ge=1, le=500, description="Max entries to return"),
    days: int = Query(1, ge=1, le=30, description="Lookback window in days"),
    log=Depends(get_notification_log),
) -> list[dict]:
    """Notification timeline.

    Returns recent notification delivery records for the intelligence
    timeline view.
    """
    try:
        entries = log.get_recent(limit)
        return entries
    except Exception as exc:
        logger.warning("Failed to fetch notification timeline: %s", exc)
        return []


@router.get("/signal-accuracy")
async def signal_accuracy(
    signal_type: str | None = Query(None, description="Filter by signal type"),
    window_days: int = Query(30, ge=1, le=365, description="Evaluation window in days"),
    store=Depends(get_signal_store),
) -> dict:
    """Signal accuracy statistics.

    Evaluates signal prediction accuracy over the given window, optionally
    filtered to a specific signal type.
    """
    try:
        result = store.get_signal_accuracy(signal_type, window_days)
        return result
    except Exception as exc:
        logger.warning("Failed to compute signal accuracy: %s", exc)
        return {"error": str(exc), "accuracy": {}}


@router.get("/signal-accuracy/history")
async def signal_accuracy_history(
    signal_type: str | None = Query(None, description="Filter by signal type"),
    granularity: str = Query(
        "daily",
        description="Granularity: 'daily' or 'weekly'",
        pattern="^(daily|weekly)$",
    ),
    window_days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    store=Depends(get_signal_store),
) -> dict:
    """Signal accuracy trend over time.

    Computes accuracy for each day (or week) in the window, returning a
    time series of T+3 and T+5 accuracy values with sample counts.

    Per PRD v20.0 Phase 7: Observability.
    """
    try:
        data = _compute_accuracy_history(store, signal_type, granularity, window_days)
        return {
            "data": data,
            "signal_type": signal_type or "ALL",
            "granularity": granularity,
            "window_days": window_days,
        }
    except Exception as exc:
        logger.warning("Failed to compute signal accuracy history: %s", exc)
        return {
            "data": [],
            "signal_type": signal_type or "ALL",
            "granularity": granularity,
            "window_days": window_days,
            "error": str(exc),
        }


def _compute_accuracy_history(
    store,
    signal_type: str | None,
    granularity: str,
    window_days: int,
) -> list[dict]:
    """Build accuracy history by querying the store for each time bucket.

    Groups signals into daily or weekly buckets and computes accuracy
    for each bucket independently.

    Args:
        store: SignalStore instance.
        signal_type: Optional signal type filter.
        granularity: "daily" or "weekly".
        window_days: Total lookback window in days.

    Returns:
        List of dicts with date, accuracy_t3, accuracy_t5, sample_count.
    """
    import sqlite3
    from typing import Any

    now = datetime.now(UTC)
    start = now - timedelta(days=window_days)

    # Determine bucket boundaries
    if granularity == "weekly":
        # Group by ISO week start (Monday)
        bucket_days = 7
    else:
        bucket_days = 1

    results: list[dict] = []

    conn = sqlite3.connect(str(store._db_path))
    conn.row_factory = sqlite3.Row
    try:
        current = start
        while current < now:
            bucket_end = current + timedelta(days=bucket_days)
            if bucket_end > now:
                bucket_end = now

            where_clauses = [
                "s.timestamp >= ?",
                "s.timestamp < ?",
            ]
            params: list[Any] = [
                current.isoformat(),
                bucket_end.isoformat(),
            ]

            if signal_type is not None:
                where_clauses.append("s.signal_type = ?")
                params.append(signal_type)

            where = " AND ".join(where_clauses)

            rows = conn.execute(
                f"SELECT o.correct_t3, o.correct_t5 "  # noqa: S608
                f"FROM signals s "
                f"JOIN signal_outcomes o ON s.signal_id = o.signal_id "
                f"WHERE {where}",
                params,
            ).fetchall()

            correct_t3_vals = [
                r["correct_t3"] for r in rows if r["correct_t3"] is not None
            ]
            correct_t5_vals = [
                r["correct_t5"] for r in rows if r["correct_t5"] is not None
            ]
            sample_count = max(len(correct_t3_vals), len(correct_t5_vals))

            accuracy_t3 = (
                round(sum(correct_t3_vals) / len(correct_t3_vals), 4)
                if correct_t3_vals
                else None
            )
            accuracy_t5 = (
                round(sum(correct_t5_vals) / len(correct_t5_vals), 4)
                if correct_t5_vals
                else None
            )

            results.append(
                {
                    "date": current.strftime("%Y-%m-%d"),
                    "accuracy_t3": accuracy_t3,
                    "accuracy_t5": accuracy_t5,
                    "sample_count": sample_count,
                }
            )

            current = bucket_end
    finally:
        conn.close()

    return results

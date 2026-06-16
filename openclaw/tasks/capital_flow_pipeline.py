"""Capital flow anomaly scanning pipeline task.

Periodically scans for capital flow anomalies (macro + sector), injects
anomaly events into the intelligence hub, and pushes notifications for
high-severity events.

Per PRD v26.0 FR-CF009: Scheduled capital flow scan during trading hours.
Per PRD v26.0 FR-CF013: Intelligence hub integration.
Per PRD v26.0 FR-CF017: Notification push for anomalies.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from openclaw.celery_app import app
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.capital_flow_pipeline")

NOTIFICATIONS_KEY = "notifications:alerts"
MAX_NOTIFICATIONS = 200


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


def _get_redis():
    """Get a Redis client for notification storage."""
    import redis

    config = load_config("openclaw")
    broker = config.get("celery", {}).get("broker_url", "redis://redis:6379/0")
    return redis.from_url(broker, decode_responses=True)


@app.task(
    name="openclaw.tasks.capital_flow_pipeline.task_capital_flow_scan",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def task_capital_flow_scan(self) -> dict[str, Any]:
    """Scan for capital flow anomalies, inject into intelligence hub, and push notifications.

    Runs every 10 minutes during trading hours (9:30-15:00 CST, Mon-Fri).
    Non-trading days are handled by the timeline guard which may skip execution.

    Pipeline:
        1. Fetch macro snapshot via MacroFlowFetcher
        2. Fetch sector flows via SectorFlowFetcher
        3. Run anomaly detection via FlowAnomalyDetector
        4. Inject anomaly events into InfoStore as InfoItems
        5. Push notifications for high-severity anomalies via Redis
    """
    if not _should_execute("task_capital_flow_scan"):
        logger.info("task_capital_flow_scan: skipped (timeline guard)")
        return {"status": "skipped", "events": 0, "notifications": 0}

    logger.info("Starting capital flow anomaly scan")

    try:
        from src.analysis.flow_anomaly_detector import (
            FlowAnomalyDetector,
            FlowAnomalyEvent,
        )
        from src.data.macro_flow_fetcher import MacroFlowFetcher
        from src.data.sector_flow_fetcher import SectorFlowFetcher
        from src.intelligence_hub.info_store import InfoStore
        from src.intelligence_hub.models import InfoItem

        detector = FlowAnomalyDetector()
        macro_fetcher = MacroFlowFetcher()
        sector_fetcher = SectorFlowFetcher()
        store = InfoStore()
        events: list[FlowAnomalyEvent] = []

        # ── Step 1: Fetch macro snapshot and detect anomalies ────────
        try:
            snapshot = macro_fetcher.get_latest_snapshot()
            history = macro_fetcher.get_macro_history(days=30)
            nb_history = [s.northbound_net for s in history if s.northbound_net != 0]

            if snapshot.northbound_net != 0:
                macro_events = detector.detect_macro_anomalies(
                    snapshot.northbound_net, nb_history
                )
                events.extend(macro_events)
                logger.info("Macro anomaly detection: %d events", len(macro_events))
        except Exception as exc:
            logger.warning("Macro flow fetch/detect failed: %s", exc)

        # ── Step 2: Fetch sector flows and detect anomalies ──────────
        try:
            df = sector_fetcher.fetch_industry_flow(period="today")
            if (
                not df.empty
                and "sector_name" in df.columns
                and "net_inflow" in df.columns
            ):
                sector_flows = dict(
                    zip(df["sector_name"].astype(str), df["net_inflow"].astype(float))
                )
                # Build sector history from multi-period data
                sector_history: dict[str, list[float]] = {}
                for period in ("3d", "5d", "10d"):
                    hist_df = sector_fetcher.fetch_industry_flow(period=period)
                    if not hist_df.empty and "sector_name" in hist_df.columns:
                        for _, row in hist_df.iterrows():
                            name = str(row.get("sector_name", ""))
                            val = float(row.get("net_inflow", 0) or 0)
                            sector_history.setdefault(name, []).append(val)

                if sector_flows and sector_history:
                    sector_events = detector.detect_sector_anomalies(
                        sector_flows, sector_history
                    )
                    events.extend(sector_events)
                    logger.info(
                        "Sector anomaly detection: %d events", len(sector_events)
                    )
        except Exception as exc:
            logger.warning("Sector flow fetch/detect failed: %s", exc)

        if not events:
            logger.info("Capital flow scan complete: no anomalies detected")
            return {"status": "ok", "events": 0, "notifications": 0}

        # ── Step 3: Inject anomaly events into InfoStore ─────────────
        severity_priority_map = {
            "high": "breaking",
            "medium": "high",
            "low": "normal",
        }

        info_items: list[InfoItem] = []
        for event in events:
            priority = severity_priority_map.get(event.severity, "normal")
            item = InfoItem(
                source_id="capital_flow_anomaly",
                source_name="资金流向异动检测",
                title=event.title,
                summary=event.summary,
                category="market",
                priority=priority,
                tags=[event.event_type, "capital_flow", "anomaly"],
                related_symbols=event.related_symbols,
                extra={"anomaly_data": event.data, "event_type": event.event_type},
            )
            info_items.append(item)

        stored_count, _new_ids = store.store_batch(info_items)
        logger.info("Stored %d anomaly items in InfoStore", stored_count)

        # ── Step 4: Push notifications for high-severity anomalies ───
        notifications_pushed = 0
        high_events = [e for e in events if e.severity == "high"]

        if high_events:
            try:
                r = _get_redis()
                for event in high_events:
                    notification = {
                        "id": str(uuid.uuid4()),
                        "type": "capital_flow_anomaly",
                        "title": event.title,
                        "summary": event.summary,
                        "symbol": None,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "read": False,
                        "action": "/market?tab=capital-flow",
                    }
                    r.lpush(
                        NOTIFICATIONS_KEY,
                        json.dumps(notification, ensure_ascii=False),
                    )
                    notifications_pushed += 1

                r.ltrim(NOTIFICATIONS_KEY, 0, MAX_NOTIFICATIONS - 1)

                # Publish to push channel for real-time delivery
                if notifications_pushed > 0:
                    r.publish(
                        "notifications:push",
                        json.dumps(
                            {
                                "type": "capital_flow_anomaly",
                                "count": notifications_pushed,
                            },
                            ensure_ascii=False,
                        ),
                    )
            except Exception as exc:
                logger.warning("Failed to push capital flow notifications: %s", exc)

        logger.info(
            "Capital flow scan complete: %d events, %d stored, %d notifications",
            len(events),
            stored_count,
            notifications_pushed,
        )
        return {
            "status": "ok",
            "events": len(events),
            "stored": stored_count,
            "notifications": notifications_pushed,
        }

    except Exception as exc:
        logger.error("Capital flow scan failed: %s", exc)
        raise self.retry(exc=exc)

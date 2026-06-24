"""Intelligence pipeline tasks for v34.0 Intelligent Investment Agent.

Schedule:
- black_swan_scan: Every 15 min during trading hours (09:00-15:00 Mon-Fri)
- portfolio_macro_scan: Every 2 hours during trading hours (09:30, 11:30, 13:30, 15:00)
- rotation_scan: Every 2 hours during trading (09:30, 11:30, 13:30, 15:15)
- portfolio_snapshot: Daily 15:05 CST (post-close, captures daily net value)
"""

from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.intelligence_pipeline")


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


def _publish_to_event_bus(stream: str, events: list[dict]) -> int:
    """Publish events to the EventBus (fire-and-forget).

    Lazily initializes the EventBus singleton. Never raises — publishing
    failure must not break the intelligence pipeline.

    Returns:
        Number of events successfully published.
    """
    if not events:
        return 0
    try:
        import asyncio

        from src.intelligence.event_bus import get_event_bus

        bus = get_event_bus()

        async def _do_publish() -> int:
            count = 0
            for evt in events:
                result = await bus.publish(stream, evt)
                if result is not None:
                    count += 1
            return count

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, _do_publish()).result(timeout=5)
            return loop.run_until_complete(_do_publish())
        except RuntimeError:
            return asyncio.run(_do_publish())
    except Exception as exc:
        logger.warning("Event bus publish failed (non-critical): %s", exc)
        return 0


@app.task(
    bind=True,
    max_retries=1,
    name="openclaw.tasks.intelligence_pipeline.black_swan_scan",
    soft_time_limit=60,
    time_limit=90,
)
def black_swan_scan(self: Any) -> dict[str, Any]:
    """Scan for black swan indicators using global market data.

    Runs every 15 min during trading hours. Fetches real-time global
    market data and runs the BlackSwanDetector multi-indicator scan.
    Emits S10_BLACK_SWAN signal when alert level >= ELEVATED.

    Returns:
        Dict with alert level and breached indicators.
    """
    if not _should_execute("black_swan_scan"):
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("black_swan_scan: starting")

    try:
        from src.data.global_market import GlobalMarketFetcher
        from src.intelligence.black_swan_detector import BlackSwanDetector

        fetcher = GlobalMarketFetcher()
        snapshot = fetcher.fetch_global_snapshot()

        detector = BlackSwanDetector()
        scan_input = detector.build_scan_input_from_snapshot(snapshot)
        alerts = detector.scan(scan_input)

        if not alerts:
            logger.debug("black_swan_scan: no anomalies")
            return {"alert_level": "NONE", "indicators": []}

        # Return the highest-severity alert
        alert = alerts[0]
        logger.warning(
            "black_swan_scan: alert_level=%s, breached=%d",
            alert.level,
            len(alert.triggered_indicators),
        )

        # Publish to event bus for trading loop consumption
        _publish_to_event_bus(
            "sentinel:raw_intel",
            [
                {
                    "event_type": "NEWS_EVENT",
                    "sub_type": "black_swan",
                    "alert_level": str(alert.level),
                    "breached_count": len(alert.triggered_indicators),
                    "source": "black_swan_scan",
                }
            ],
        )

        return alert.to_dict()

    except Exception as exc:
        logger.error("black_swan_scan failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


@app.task(
    bind=True,
    max_retries=1,
    name="openclaw.tasks.intelligence_pipeline.portfolio_macro_scan",
    soft_time_limit=120,
    time_limit=180,
)
def portfolio_macro_scan(self: Any) -> dict[str, Any]:
    """Scan portfolio positions for macro sensitivity and rotation signals.

    Runs every 2 hours during trading hours. Reads portfolio from
    PortfolioStore, analyzes each position against current macro
    environment, and flags positions needing rotation.

    Returns:
        Dict with position profiles and rotation signals.
    """
    if not _should_execute("portfolio_macro_scan"):
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("portfolio_macro_scan: starting")

    try:
        from src.intelligence.position_macro_mapper import (
            MacroEnvironment,
            PositionMacroMapper,
        )
        from src.web.services.portfolio_store import PortfolioStore

        store = PortfolioStore()
        data = store.get_portfolio_data()
        positions = [
            {"symbol": p["symbol"], "name": p.get("name", p["symbol"])}
            for p in data.get("positions", [])
        ]

        if not positions:
            logger.debug("portfolio_macro_scan: empty portfolio")
            return {"position_count": 0, "profiles": []}

        mapper = PositionMacroMapper()
        env = MacroEnvironment()  # neutral default; real data injected in future
        profiles = mapper.analyze_portfolio(positions, env)

        stressed = [p for p in profiles if p.rotation_signal in ("exit", "reduce")]
        if stressed:
            logger.warning(
                "portfolio_macro_scan: %d positions under macro stress",
                len(stressed),
            )
            # Publish macro stress events for trading loop consumption
            _publish_to_event_bus(
                "analyst:event_understood",
                [
                    {
                        "event_type": "POLICY_EVENT",
                        "sub_type": "macro_stress",
                        "symbol": p.symbol,
                        "rotation_signal": p.rotation_signal,
                        "macro_score": getattr(p, "macro_score", 0),
                        "source": "portfolio_macro_scan",
                    }
                    for p in stressed
                ],
            )

        return {
            "position_count": len(positions),
            "profiles": [p.to_dict() for p in profiles],
            "stressed_count": len(stressed),
        }

    except Exception as exc:
        logger.error("portfolio_macro_scan failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


@app.task(
    bind=True,
    max_retries=1,
    name="openclaw.tasks.intelligence_pipeline.rotation_scan",
    soft_time_limit=180,
    time_limit=240,
)
def rotation_scan(self: Any) -> dict[str, Any]:
    """Generate portfolio rotation plans based on macro environment.

    Runs every 2 hours during trading hours (09:30, 11:30, 13:30, 15:15).
    Scans all positions, identifies macro-stressed holdings, and generates
    sell→buy rotation plans with constraint filtering (main board only, T+1).
    Persists plans to data/rotation_signals.db.

    Returns:
        Dict with rotation plans and candidate counts.
    """
    if not _should_execute("rotation_scan"):
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("rotation_scan: starting rotation analysis")

    try:
        from src.intelligence.position_macro_mapper import MacroEnvironment
        from src.intelligence.rotation_engine import RotationEngine
        from src.web.services.portfolio_store import PortfolioStore

        store = PortfolioStore()
        data = store.get_portfolio_data()
        positions = [
            {"symbol": p["symbol"], "name": p.get("name", p["symbol"])}
            for p in data.get("positions", [])
        ]

        if not positions:
            logger.debug("rotation_scan: empty portfolio")
            return {"position_count": 0, "plans": []}

        engine = RotationEngine()
        env = MacroEnvironment()
        plans = engine.scan_portfolio(positions, env)

        # Persist rotation plans to SQLite
        if plans:
            _persist_rotation_plans(plans)

        logger.info(
            "rotation_scan: %d positions, %d rotation plans generated",
            len(positions),
            len(plans),
        )

        return {
            "position_count": len(positions),
            "rotation_plans": [p.to_dict() for p in plans],
            "plans_count": len(plans),
        }

    except Exception as exc:
        logger.error("rotation_scan failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


def _persist_rotation_plans(plans: list) -> None:
    """Persist rotation plans to data/rotation_signals.db."""
    import json
    import sqlite3
    from datetime import date

    from src.utils.config import get_project_root

    try:
        db_path = get_project_root() / "data" / "rotation_signals.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rotation_plans (
                plan_id TEXT PRIMARY KEY,
                date TEXT,
                sell_symbol TEXT,
                sell_name TEXT,
                sell_macro_score REAL,
                sell_reason TEXT,
                buy_candidates_json TEXT,
                plans_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        today = date.today().isoformat()
        for plan in plans:
            d = plan.to_dict()
            conn.execute(
                """INSERT OR REPLACE INTO rotation_plans
                   (plan_id, date, sell_symbol, sell_name, sell_macro_score,
                    sell_reason, buy_candidates_json, plans_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    d["plan_id"],
                    today,
                    d["sell"]["symbol"],
                    d["sell"]["name"],
                    d["sell"]["macro_score"],
                    d["sell"]["reason"],
                    json.dumps(d["buy_candidates"], ensure_ascii=False),
                    json.dumps(d, ensure_ascii=False),
                ),
            )
        conn.commit()
        conn.close()
        logger.info("Persisted %d rotation plans to rotation_signals.db", len(plans))
    except Exception as e:
        logger.warning("Failed to persist rotation plans: %s", e)


@app.task(
    bind=True,
    max_retries=1,
    name="openclaw.tasks.intelligence_pipeline.portfolio_snapshot",
    soft_time_limit=60,
    time_limit=90,
)
def portfolio_snapshot(self: Any) -> dict[str, Any]:
    """Capture daily portfolio net value snapshot.

    Runs daily at 15:05 CST after market close. Reads current portfolio
    positions and records total value, cash, and per-position data
    to a snapshot log for equity curve tracking.

    Returns:
        Dict with snapshot summary.
    """
    if not _should_execute("portfolio_snapshot"):
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("portfolio_snapshot: capturing daily snapshot")

    try:
        import json
        import sqlite3
        from datetime import date

        from src.utils.config import get_project_root
        from src.web.services.portfolio_store import PortfolioStore

        store = PortfolioStore()
        data = store.get_portfolio_data()
        positions = data.get("positions", [])

        total_value = sum(
            p.get("current_value", p.get("cost_price", 0) * p.get("shares", 0))
            for p in positions
        )
        total_cost = sum(p.get("cost_price", 0) * p.get("shares", 0) for p in positions)
        unrealized_pnl = total_value - total_cost

        # Store in SQLite
        db_path = get_project_root() / "data" / "portfolio_snapshots.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                date TEXT PRIMARY KEY,
                total_value REAL,
                total_cost REAL,
                unrealized_pnl REAL,
                position_count INTEGER,
                positions_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        today = date.today().isoformat()
        positions_slim = [
            {
                "symbol": p.get("symbol"),
                "name": p.get("name"),
                "shares": p.get("shares"),
                "cost_price": p.get("cost_price"),
                "current_value": p.get("current_value"),
            }
            for p in positions
        ]
        conn.execute(
            """INSERT OR REPLACE INTO snapshots
               (date, total_value, total_cost, unrealized_pnl,
                position_count, positions_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                today,
                total_value,
                total_cost,
                unrealized_pnl,
                len(positions),
                json.dumps(positions_slim, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()

        logger.info(
            "portfolio_snapshot: captured — value=%.2f, pnl=%.2f, positions=%d",
            total_value,
            unrealized_pnl,
            len(positions),
        )
        return {
            "date": today,
            "total_value": total_value,
            "unrealized_pnl": unrealized_pnl,
            "position_count": len(positions),
        }

    except Exception as exc:
        logger.error("portfolio_snapshot failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)

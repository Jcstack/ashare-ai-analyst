"""Level-2 data pipeline tasks.

Manages order book snapshot collection, seal state machine updates,
and large order tracking using QMT Level-2 data.

These tasks only fire when QMT is available (Level-2 data source).
When QMT is offline, all tasks gracefully skip.
"""

from __future__ import annotations

from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.level2_pipeline")


def _should_execute(task_name: str) -> bool:
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


def _is_qmt_available() -> bool:
    """Check if QMT is enabled and connected."""
    try:
        from src.data.qmt_adapter import QmtDataAdapter
        from src.utils.config import load_config

        config = load_config("stocks")
        if not config.get("qmt", {}).get("enabled", False):
            return False
        adapter = QmtDataAdapter()
        return adapter.is_available()
    except Exception:
        return False


@app.task(
    name="openclaw.tasks.level2_pipeline.task_orderbook_snapshot",
    bind=True,
    max_retries=0,
    soft_time_limit=30,
    time_limit=45,
)
def task_orderbook_snapshot(self) -> dict[str, Any]:
    """Capture order book snapshots for active symbols.

    Runs every 10 seconds during trading hours (via custom scheduler).
    Feeds into: orderbook factors, seal state machine, large order tracker.
    """
    if not _should_execute("task_orderbook_snapshot"):
        return {"status": "skipped", "reason": "non-trading"}

    if not _is_qmt_available():
        return {"status": "skipped", "reason": "qmt_unavailable"}

    try:
        import redis

        from src.data.level2_provider import Level2Provider
        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)

        provider = Level2Provider(redis_client=redis_client)

        # Get active symbols
        from openclaw.tasks.intraday_pipeline import _get_active_symbols

        symbols = _get_active_symbols(redis_client)

        if not symbols:
            return {"status": "ok", "captured": 0}

        snapshots = provider.get_snapshots_batch(symbols)
        captured = sum(1 for s in snapshots.values() if s is not None)

        logger.info(
            "Order book snapshot: %d/%d symbols captured", captured, len(symbols)
        )
        return {"status": "ok", "captured": captured, "total": len(symbols)}
    except Exception as exc:
        logger.error("Order book snapshot failed: %s", exc)
        return {"status": "failed", "error": str(exc)[:200]}


@app.task(
    name="openclaw.tasks.level2_pipeline.task_seal_lifecycle_update",
    bind=True,
    max_retries=0,
    soft_time_limit=30,
    time_limit=45,
)
def task_seal_lifecycle_update(self) -> dict[str, Any]:
    """Update seal state machines for stocks near/at limit-up.

    Runs every 10 seconds. Tracks limit-up board lifecycle:
    approaching -> sealed -> broken -> resealed -> failed.
    """
    if not _should_execute("task_seal_lifecycle_update"):
        return {"status": "skipped", "reason": "non-trading"}

    try:
        import redis

        from src.agent_loop.seal_state_machine import SealStateMachine
        from src.data.realtime import RealtimeQuoteManager
        from src.data.seal_strength import SealStrengthAnalyzer
        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)

        # Get or create state machine (stored in Redis for persistence)
        machine = SealStateMachine(redis_client=redis_client)
        rtm = RealtimeQuoteManager()
        seal_analyzer = SealStrengthAnalyzer(redis_client=redis_client)

        from openclaw.tasks.intraday_pipeline import _get_active_symbols

        symbols = _get_active_symbols(redis_client)

        updated = 0
        for symbol in symbols:
            quote = rtm.get_quote(symbol)
            if not quote:
                continue

            seal_info = seal_analyzer.analyze(symbol, quote=quote)
            seal_vol = 0
            board_type = "main"
            if seal_info:
                seal_vol = int(
                    seal_info.get("seal_amount_yuan", 0)
                    / max(quote.get("price", 1), 0.01)
                )
                board_type = seal_info.get("board_type", "main")

            prev_close = quote.get("prev_close", 0)
            if prev_close <= 0:
                continue

            machine.update(
                symbol=symbol,
                price=quote.get("price", 0),
                volume=quote.get("volume", 0),
                prev_close=prev_close,
                seal_volume=seal_vol,
                board_type=board_type,
            )
            updated += 1

        active = machine.get_all_active()
        logger.info(
            "Seal lifecycle: %d symbols updated, %d active boards",
            updated,
            len(active),
        )
        return {"status": "ok", "updated": updated, "active_boards": len(active)}
    except Exception as exc:
        logger.error("Seal lifecycle update failed: %s", exc)
        return {"status": "failed", "error": str(exc)[:200]}


@app.task(
    name="openclaw.tasks.level2_pipeline.task_large_order_scan",
    bind=True,
    max_retries=0,
    soft_time_limit=60,
    time_limit=90,
)
def task_large_order_scan(self) -> dict[str, Any]:
    """Scan for large institutional orders across active symbols.

    Runs every 5 minutes. Uses tick data to merge trades into
    institutional orders and track net flow direction.
    """
    if not _should_execute("task_large_order_scan"):
        return {"status": "skipped", "reason": "non-trading"}

    if not _is_qmt_available():
        return {"status": "skipped", "reason": "qmt_unavailable"}

    try:
        import json

        import redis

        from src.data.large_order_tracker import LargeOrderTracker
        from src.data.level2_provider import Level2Provider
        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)

        provider = Level2Provider(redis_client=redis_client)
        tracker = LargeOrderTracker(redis_client=redis_client)

        from openclaw.tasks.intraday_pipeline import _get_active_symbols

        symbols = _get_active_symbols(redis_client)

        results = {}
        for symbol in symbols:
            ticks = provider.get_recent_ticks(symbol, count=200)
            if not ticks:
                continue

            # Add symbol to tick objects for merge_ticks
            for t in ticks:
                if hasattr(t, "__dataclass_fields__"):
                    object.__setattr__(t, "symbol", symbol)
                elif not getattr(t, "symbol", None):
                    setattr(t, "symbol", symbol)

            merged = tracker.merge_ticks(ticks)
            if merged:
                flow = tracker.compute_flow_summary(merged)
                results[symbol] = flow

                # Store in Redis
                redis_client.set(
                    f"large_order_flow:{symbol}",
                    json.dumps(flow),
                    ex=600,  # 10 min TTL
                )

        logger.info("Large order scan: %d symbols with flow data", len(results))
        return {"status": "ok", "symbols_with_flow": len(results)}
    except Exception as exc:
        logger.error("Large order scan failed: %s", exc)
        return {"status": "failed", "error": str(exc)[:200]}


@app.task(
    name="openclaw.tasks.level2_pipeline.task_microstructure_factors",
    bind=True,
    max_retries=0,
    soft_time_limit=60,
    time_limit=90,
)
def task_microstructure_factors(self) -> dict[str, Any]:
    """Compute and cache microstructure factors for active symbols.

    Runs every 5 minutes. Computes order book factors and alternative
    bar factors, stores in Redis for screener enrichment.
    """
    if not _should_execute("task_microstructure_factors"):
        return {"status": "skipped", "reason": "non-trading"}

    try:
        import json

        import redis

        from src.data.level2_provider import Level2Provider
        from src.quant.orderbook_factors import OrderBookFactorEngine
        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)

        provider = Level2Provider(redis_client=redis_client)
        engine = OrderBookFactorEngine()

        from openclaw.tasks.intraday_pipeline import _get_active_symbols

        symbols = _get_active_symbols(redis_client)

        computed = 0
        for symbol in symbols:
            snapshot = provider.get_snapshot(symbol)
            if not snapshot:
                continue

            history = provider.get_snapshot_history(symbol, count=20)
            ticks = provider.get_recent_ticks(symbol, count=100)

            factors = engine.compute(snapshot, history, ticks)

            # Store in Redis
            redis_client.set(
                f"microstructure:{symbol}",
                json.dumps(factors),
                ex=600,
            )
            computed += 1

        logger.info("Microstructure factors: %d symbols computed", computed)
        return {"status": "ok", "computed": computed}
    except Exception as exc:
        logger.error("Microstructure factors failed: %s", exc)
        return {"status": "failed", "error": str(exc)[:200]}

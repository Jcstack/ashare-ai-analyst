"""Signal scan pipeline tasks for v20.0 Market Intelligence Phase 3.

Provides Celery tasks for signal outcome backfill, phase transition
detection, digest notification dispatch, and old signal/log cleanup.

Schedule:
- signal_backfill: Daily 17:00 CST (post-close, T+3/T+5 outcome backfill)
- signal_phase_check: Every 5 minutes during trading hours
- signal_dispatch_digest: Every 15 minutes during trading hours
- signal_cleanup: Daily 02:00 CST
"""

from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.signal_scan")


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


@app.task(
    bind=True,
    max_retries=2,
    name="openclaw.tasks.signal_scan.signal_backfill",
)
def signal_backfill(self: Any) -> dict[str, Any]:
    """Backfill T+3/T+5 actual price outcomes for pending signals.

    Runs daily at 17:00 CST after market close. For each backfill
    window, retrieves pending signals from SignalStore, fetches the
    actual price change, and records the outcome via backfill_outcome().

    Returns:
        Dict with per-window backfill counts, or ``{"_skipped": True}``
        when the timeline guard suppresses execution.
    """
    if not _should_execute("signal_backfill"):
        logger.info("signal_backfill: skipped (timeline guard)")
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("signal_backfill: starting post-close outcome backfill")

    try:
        from src.intelligence.signal_store import SignalStore
        from src.web.services.stock_service import StockService

        signal_store = SignalStore()
        stock_service = StockService()

        results: dict[str, Any] = {}

        for window in [3, 5]:
            pending = signal_store.get_pending_backfills(window)
            filled = 0
            errors = 0

            for signal in pending:
                symbol = signal["symbol"]
                signal_date = signal["created_at"]
                signal_id = signal["signal_id"]

                try:
                    pct_change = stock_service.get_price_change(
                        symbol, signal_date, window
                    )
                    if pct_change is not None:
                        signal_store.backfill_outcome(signal_id, window, pct_change)
                        filled += 1
                    else:
                        logger.debug(
                            "No price data for %s from %s T+%d",
                            symbol,
                            signal_date,
                            window,
                        )
                except Exception:
                    errors += 1
                    logger.warning(
                        "Backfill failed for signal %s T+%d",
                        signal_id,
                        window,
                        exc_info=True,
                    )

            results[f"t{window}"] = {
                "pending": len(pending),
                "filled": filled,
                "errors": errors,
            }

        logger.info("signal_backfill: completed — %s", results)
        return results

    except Exception as exc:
        logger.error("signal_backfill failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


@app.task(
    bind=True,
    max_retries=1,
    name="openclaw.tasks.signal_scan.signal_phase_check",
)
def signal_phase_check(self: Any) -> dict[str, Any]:
    """Periodic phase transition detector.

    Runs every 5 minutes during trading hours. Queries the PhaseEngine
    for the current market phase and logs any transitions compared to
    the previously recorded phase.

    Returns:
        Dict with current phase and transition info, or
        ``{"_skipped": True}`` when the timeline guard suppresses
        execution.
    """
    if not _should_execute("signal_phase_check"):
        logger.info("signal_phase_check: skipped (timeline guard)")
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("signal_phase_check: checking market phase")

    try:
        from src.intelligence.phase_engine import PhaseEngine

        engine = PhaseEngine()

        current_phase = engine.get_current_phase()
        previous_phase = engine.get_previous_phase()
        transitioned = current_phase != previous_phase

        if transitioned:
            logger.info(
                "signal_phase_check: phase transition detected — %s -> %s",
                previous_phase,
                current_phase,
            )
            engine.record_transition(previous_phase, current_phase)
        else:
            logger.debug(
                "signal_phase_check: no transition — phase remains %s",
                current_phase,
            )

        return {
            "current_phase": current_phase,
            "previous_phase": previous_phase,
            "transitioned": transitioned,
        }

    except Exception as exc:
        logger.error("signal_phase_check failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


@app.task(
    bind=True,
    max_retries=2,
    name="openclaw.tasks.signal_scan.signal_dispatch_digest",
)
def signal_dispatch_digest(self: Any) -> dict[str, Any]:
    """Batch digest notification dispatcher.

    Runs every 15 minutes during trading hours. Collects all signals
    with DIGEST delivery status from SignalStore and dispatches them
    as a single batched notification via NotificationDispatcher.

    Returns:
        Dict with dispatch counts, or ``{"_skipped": True}`` when the
        timeline guard suppresses execution.
    """
    if not _should_execute("signal_dispatch_digest"):
        logger.info("signal_dispatch_digest: skipped (timeline guard)")
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("signal_dispatch_digest: collecting queued signals")

    try:
        from src.intelligence.notification_dispatcher import NotificationDispatcher
        from src.intelligence.signal_store import SignalStore

        signal_store = SignalStore()
        dispatcher = NotificationDispatcher()

        queued = signal_store.get_queued_for_digest()

        if not queued:
            logger.debug("signal_dispatch_digest: no signals queued for digest")
            return {"dispatched": 0, "queued": 0}

        dispatched = dispatcher.dispatch_batch(queued)

        # Mark dispatched signals as sent
        for signal in queued[:dispatched]:
            signal_store.mark_dispatched(signal["signal_id"])

        logger.info(
            "signal_dispatch_digest: dispatched %d of %d queued signals",
            dispatched,
            len(queued),
        )
        return {"dispatched": dispatched, "queued": len(queued)}

    except Exception as exc:
        logger.error("signal_dispatch_digest failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


@app.task(
    bind=True,
    max_retries=2,
    name="openclaw.tasks.signal_scan.signal_generate",
)
def signal_generate(self: Any) -> dict[str, Any]:
    """Generate real signals from all sources.

    Scans tracked stocks for technical signals, fetches policy news,
    and classifies the macro regime.  Results are stored in SignalStore
    and routed through NotificationOrchestrator.

    Can be triggered manually via ``POST /api/v1/market-intelligence/scan``
    or scheduled periodically.

    Returns:
        Dict with per-category signal counts, or ``{"_skipped": True}``
        when the timeline guard suppresses execution.
    """
    if not _should_execute("signal_generate"):
        logger.info("signal_generate: skipped (timeline guard)")
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("signal_generate: starting full signal scan")

    try:
        from src.web.services.signal_generation_service import SignalGenerationService

        from src.market_intelligence.macro_classifier import MacroRegimeClassifier
        from src.market_intelligence.macro_radar import MacroRadarService
        from src.market_intelligence.notification_orchestrator import (
            NotificationOrchestrator,
        )
        from src.market_intelligence.phase_engine import PhaseEngine
        from src.market_intelligence.signal_store import SignalStore
        from src.data.global_market import GlobalMarketFetcher
        from src.data.policy_news import PolicyNewsFetcher
        from src.data.trading_calendar import TradingCalendar
        from src.intelligence_hub.info_store import InfoStore
        from src.quant.signal_library import SignalLibrary
        from src.web.services.notification_dispatcher import NotificationDispatcher
        from src.web.services.stock_service import StockService
        from src.web.services.user_config_service import UserConfigService
        from src.market_intelligence.notification_log import NotificationLog
        from src.market_intelligence.risk_overlay import RiskOverlayEngine
        from src.quant.regime_detector import RegimeDetector
        from src.risk.circuit_breaker import CircuitBreaker
        from src.risk.var_calculator import VaRCalculator

        global_fetcher = GlobalMarketFetcher()
        macro_classifier = MacroRegimeClassifier(global_market_fetcher=global_fetcher)
        macro_radar = MacroRadarService(
            global_fetcher=global_fetcher,
            info_store=InfoStore(),
        )

        svc = SignalGenerationService(
            stock_service=StockService(),
            signal_library=SignalLibrary(),
            policy_fetcher=PolicyNewsFetcher(),
            macro_classifier=macro_classifier,
            phase_engine=PhaseEngine(trading_calendar=TradingCalendar()),
            signal_store=SignalStore(),
            notification_orchestrator=NotificationOrchestrator(
                dispatcher=NotificationDispatcher(),
                phase_engine=PhaseEngine(trading_calendar=TradingCalendar()),
                risk_overlay=RiskOverlayEngine(
                    regime_detector=RegimeDetector(),
                    circuit_breaker=CircuitBreaker(),
                    var_calculator=VaRCalculator(),
                    macro_classifier=macro_classifier,
                ),
                notification_log=NotificationLog(),
            ),
            user_config_service=UserConfigService(),
            macro_radar=macro_radar,
        )
        result = svc.scan_all()
        logger.info("signal_generate: completed — %s", result)
        return result

    except Exception as exc:
        logger.error("signal_generate failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


@app.task(
    bind=True,
    max_retries=1,
    name="openclaw.tasks.signal_scan.trading_decision",
)
def trading_decision(
    self: Any, symbols: list[str] | None = None, trigger: str = "manual"
) -> dict[str, Any]:
    """Trigger-based collaborative trading decision.

    Can be triggered by:
    - MacroRadarService detecting a major event
    - ExtremeMarketConference detecting abnormal conditions
    - Manual invocation via admin API

    Delegates to the ``collaborative_decision`` pipeline defined in
    ``config/pipelines.yaml``.

    Returns:
        Dict with decision results per symbol, or ``{"_skipped": True}``
        when the timeline guard suppresses execution.
    """
    if not _should_execute("trading_decision"):
        logger.info("trading_decision: skipped (timeline guard)")
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("trading_decision: trigger=%s, symbols=%s", trigger, symbols)

    try:
        from src.orchestration.extreme_market_conference import (
            ExtremeMarketConference,
        )
        from src.data.global_market import GlobalMarketFetcher
        from src.market_intelligence.signal_store import SignalStore
        from src.web.services.stock_service import StockService

        stock_service = StockService()
        signal_store = SignalStore()

        conference = ExtremeMarketConference(
            signal_store=signal_store,
            global_market_fetcher=GlobalMarketFetcher(),
            stock_service=stock_service,
        )

        # If no symbols provided, use tracked symbols
        if not symbols:
            from src.web.services.user_config_service import UserConfigService

            user_cfg = UserConfigService()
            follows = user_cfg.get_follows()
            symbols = [
                s if isinstance(s, str) else s.get("symbol", "")
                for s in follows.get("stocks", [])
            ]
            symbols = [s for s in symbols if s]

        if not symbols:
            return {"_skipped": True, "_reason": "no_symbols"}

        # Check if conference should convene (when not manually triggered)
        if trigger != "manual":
            should, reason = conference.should_convene(symbols)
            if not should:
                logger.info("trading_decision: no extreme conditions detected")
                return {"convened": False, "reason": "no_extreme_conditions"}
            trigger = reason

        result = conference.convene(trigger_reason=trigger, symbols=symbols)

        logger.info(
            "trading_decision: conference convened=%s, action=%s",
            result.convened,
            result.action,
        )
        return {
            "convened": result.convened,
            "trigger_reason": result.trigger_reason,
            "symbols": result.symbols,
            "action": result.action,
            "confidence": result.confidence,
            "risk_veto": result.risk_veto,
        }

    except Exception as exc:
        logger.error("trading_decision failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


@app.task(
    bind=True,
    max_retries=1,
    name="openclaw.tasks.signal_scan.signal_cleanup",
)
def signal_cleanup(self: Any) -> dict[str, Any]:
    """Old signal and notification log cleanup.

    Runs daily at 02:00 CST. Calls SignalStore.cleanup() and
    NotificationLog.cleanup() to purge records older than the
    configured retention period.

    Returns:
        Dict with cleanup counts, or ``{"_skipped": True}`` when the
        timeline guard suppresses execution.
    """
    if not _should_execute("signal_cleanup"):
        logger.info("signal_cleanup: skipped (timeline guard)")
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("signal_cleanup: starting old record cleanup")

    try:
        from src.intelligence.notification_log import NotificationLog
        from src.intelligence.signal_store import SignalStore

        signal_store = SignalStore()
        notification_log = NotificationLog()

        signals_cleaned = signal_store.cleanup()
        logs_cleaned = notification_log.cleanup()

        logger.info(
            "signal_cleanup: completed — %d signals, %d logs purged",
            signals_cleaned,
            logs_cleaned,
        )
        return {
            "signals_cleaned": signals_cleaned,
            "logs_cleaned": logs_cleaned,
        }

    except Exception as exc:
        logger.error("signal_cleanup failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)

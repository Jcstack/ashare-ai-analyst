"""LLM result pre-warming tasks.

Pre-computes LLM analysis results into Redis L2 cache so that
FastAPI workers can serve them instantly (0ms vs 5-22s cold start).

Three tasks:
- ``task_prewarm_market_overview``: market sentiment overview (every 30min)
- ``task_prewarm_sentiment_report``: sentiment news digest (every 30min)
- ``task_prewarm_hot_stocks``: top-20 turnover + watchlist (09:25 pre-open)

Per I-068: LLM result pre-warming cache.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from openclaw.celery_app import app
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.llm_prewarm")


def _should_execute(task_name: str) -> bool:
    """Check timeline scheduler guard."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        return TimelineScheduler().should_execute(task_name)
    except Exception:
        return True


def _is_trading_day() -> bool:
    """Check if today is a trading day (skip holidays/weekends)."""
    try:
        from src.data.trading_calendar import TradingCalendar

        return TradingCalendar().is_trading_day(date.today())
    except Exception:
        # Fallback: weekday check only
        return date.today().weekday() < 5


def _get_redis():
    """Obtain a Redis client from the Celery broker URL."""
    try:
        import redis

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        return redis.from_url(broker, decode_responses=True)
    except Exception:
        return None


def _build_llm_cache(redis_client=None):
    """Construct an LLMResultCache for worker-side use."""
    from src.llm.cache import LLMResultCache

    return LLMResultCache(redis_client=redis_client)


def _build_llm_gateway():
    """Construct an LLMGateway for worker-side use."""
    from src.audit.immutable_log import ImmutableAuditLog
    from src.llm.gateway import LLMGateway
    from src.llm.router import LLMRouter

    return LLMGateway(router=LLMRouter(), audit_log=ImmutableAuditLog())


# ════════════════════════════════════════════════════════════════════════
# Task 1: Market overview pre-warm
# ════════════════════════════════════════════════════════════════════════


@app.task(
    name="openclaw.tasks.llm_prewarm_pipeline.task_prewarm_market_overview",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    soft_time_limit=240,
    time_limit=300,
)
def task_prewarm_market_overview(self) -> dict[str, Any]:
    """Pre-warm market overview LLM result into Redis L2 cache."""
    if not _should_execute("task_prewarm_market_overview"):
        return {"status": "skipped", "reason": "timeline_guard"}
    if not _is_trading_day():
        return {"status": "skipped", "reason": "non_trading_day"}

    try:
        redis_client = _get_redis()
        cache = _build_llm_cache(redis_client)
        gateway = _build_llm_gateway()

        from src.prediction.realtime_analyzer import RealtimeAnalyzer

        analyzer = RealtimeAnalyzer(router=gateway, cache=cache)

        # Gather lightweight market data
        indices_data: list[dict[str, Any]] = []
        try:
            from src.data.realtime import RealtimeQuoteManager

            qm = RealtimeQuoteManager()
            for idx in ["000001", "399001", "399006"]:
                q = qm.get_single_quote(idx)
                if q:
                    indices_data.append(q)
        except Exception as exc:
            logger.warning("Failed to fetch index quotes for prewarm: %s", exc)

        result = analyzer.get_market_overview(indices_data=indices_data)
        status = result.get("status", "unknown")
        logger.info("Prewarm market_overview done: status=%s", status)
        return {"status": "ok", "result_status": status}

    except SoftTimeLimitExceeded:
        logger.error("task_prewarm_market_overview: timeout")
        return {"status": "failed", "error": "timeout"}
    except Exception as exc:
        logger.error("task_prewarm_market_overview failed: %s", exc)
        raise self.retry(exc=exc)


# ════════════════════════════════════════════════════════════════════════
# Task 2: Sentiment report pre-warm
# ════════════════════════════════════════════════════════════════════════


@app.task(
    name="openclaw.tasks.llm_prewarm_pipeline.task_prewarm_sentiment_report",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    soft_time_limit=360,
    time_limit=420,
)
def task_prewarm_sentiment_report(self) -> dict[str, Any]:
    """Pre-warm sentiment report LLM result into Redis L2 cache."""
    if not _should_execute("task_prewarm_sentiment_report"):
        return {"status": "skipped", "reason": "timeline_guard"}
    if not _is_trading_day():
        return {"status": "skipped", "reason": "non_trading_day"}

    try:
        redis_client = _get_redis()
        cache = _build_llm_cache(redis_client)
        gateway = _build_llm_gateway()

        from src.prediction.sentiment_report import SentimentReportGenerator

        gen = SentimentReportGenerator(router=gateway, cache=cache)

        # Gather lightweight data for the report
        trend_items: list[dict[str, Any]] | None = None
        resonance_events: list[dict[str, Any]] | None = None
        global_snapshot: dict[str, Any] | None = None

        try:
            from src.data.trend_news import TrendNewsAggregator

            agg = TrendNewsAggregator()
            trend_items = agg.fetch_all()
        except Exception as exc:
            logger.warning("Prewarm: trend news fetch failed: %s", exc)

        try:
            from src.data.global_market import GlobalMarketFetcher

            global_snapshot = GlobalMarketFetcher().fetch_snapshot()
        except Exception as exc:
            logger.warning("Prewarm: global market fetch failed: %s", exc)

        result = gen.generate_report(
            trend_items=trend_items,
            resonance_events=resonance_events,
            global_snapshot=global_snapshot,
        )
        status = result.get("status", "unknown")
        logger.info("Prewarm sentiment_report done: status=%s", status)
        return {"status": "ok", "result_status": status}

    except SoftTimeLimitExceeded:
        logger.error("task_prewarm_sentiment_report: timeout")
        return {"status": "failed", "error": "timeout"}
    except Exception as exc:
        logger.error("task_prewarm_sentiment_report failed: %s", exc)
        raise self.retry(exc=exc)


# ════════════════════════════════════════════════════════════════════════
# Task 3: Hot stocks pre-warm (pre-open)
# ════════════════════════════════════════════════════════════════════════


def _pick_hot_symbols(redis_client, max_stocks: int = 20) -> list[str]:
    """Select hot stock symbols from screener snapshot + watchlist.

    Selection:
    1. ``rec:market_snapshot`` sorted by ``turnover_rate`` desc → top N
    2. Watchlist top 5 (de-duped)
    3. Skip symbols whose ``llm:result:unified_{sym}`` TTL > 300s
    """
    symbols: list[str] = []

    # From screener snapshot
    if redis_client:
        try:
            raw = redis_client.get("rec:market_snapshot")
            if raw:
                stocks = json.loads(raw)
                stocks.sort(key=lambda s: s.get("turnover_rate", 0), reverse=True)
                for s in stocks[:max_stocks]:
                    code = s.get("symbol") or s.get("code", "")
                    if code and code not in symbols:
                        symbols.append(code)
        except Exception as exc:
            logger.warning("Failed to load market snapshot for hot symbols: %s", exc)

    # From watchlist (top 5)
    try:
        from src.web.services.watchlist_service import WatchlistService

        wl = WatchlistService()
        for item in wl.list_all()[:5]:
            code = item.get("symbol", "")
            if code and code not in symbols:
                symbols.append(code)
    except Exception as exc:
        logger.warning("Failed to load watchlist for prewarm: %s", exc)

    # Skip symbols already cached with TTL > 300s
    if redis_client and symbols:
        filtered: list[str] = []
        for sym in symbols:
            try:
                ttl = redis_client.ttl(f"llm:result:unified_{sym}")
                if ttl is not None and ttl > 300:
                    logger.debug("Skipping %s (TTL=%ds still warm)", sym, ttl)
                    continue
            except Exception:
                pass
            filtered.append(sym)
        symbols = filtered

    return symbols


@app.task(
    name="openclaw.tasks.llm_prewarm_pipeline.task_prewarm_hot_stocks",
    bind=True,
    max_retries=0,
    soft_time_limit=900,
    time_limit=960,
)
def task_prewarm_hot_stocks(self) -> dict[str, Any]:
    """Pre-warm unified analysis for top turnover stocks + watchlist."""
    if not _should_execute("task_prewarm_hot_stocks"):
        return {"status": "skipped", "reason": "timeline_guard"}
    if not _is_trading_day():
        return {"status": "skipped", "reason": "non_trading_day"}

    try:
        redis_client = _get_redis()
        symbols = _pick_hot_symbols(redis_client)
        if not symbols:
            logger.info("No hot symbols to prewarm")
            return {"status": "ok", "prewarmed": 0}

        cache = _build_llm_cache(redis_client)
        gateway = _build_llm_gateway()

        from src.prediction.realtime_analyzer import RealtimeAnalyzer

        analyzer = RealtimeAnalyzer(router=gateway, cache=cache)

        prewarmed = 0
        errors = 0
        for sym in symbols:
            try:
                # Gather lightweight data per symbol
                quote: dict[str, Any] | None = None
                indicators: dict[str, Any] | None = None
                sector_info: dict[str, Any] | None = None

                try:
                    from src.data.realtime import RealtimeQuoteManager

                    quote = RealtimeQuoteManager().get_single_quote(sym)
                except Exception:
                    pass

                try:
                    from src.web.services.stock_service import StockService

                    svc = StockService()
                    indicators = svc.get_indicators_summary(sym)
                except Exception:
                    pass

                try:
                    from src.web.services.stock_service import StockService

                    sector_info = StockService().get_stock_sector_info(sym)
                except Exception:
                    pass

                result = analyzer.analyze_stock_unified(
                    symbol=sym,
                    quote=quote,
                    indicators=indicators,
                    sector_info=sector_info,
                )
                if result.get("status") != "error":
                    prewarmed += 1
                    logger.info("Prewarmed unified analysis for %s", sym)
                else:
                    errors += 1
                    logger.warning(
                        "Prewarm %s returned error: %s", sym, result.get("message", "")
                    )
            except SoftTimeLimitExceeded:
                logger.error(
                    "task_prewarm_hot_stocks: timeout after %d symbols", prewarmed
                )
                break
            except Exception as exc:
                errors += 1
                logger.warning("Prewarm failed for %s: %s", sym, exc)

        logger.info(
            "Hot stock prewarm complete: %d prewarmed, %d errors, %d total",
            prewarmed,
            errors,
            len(symbols),
        )
        return {
            "status": "ok",
            "prewarmed": prewarmed,
            "errors": errors,
            "total": len(symbols),
        }

    except SoftTimeLimitExceeded:
        logger.error("task_prewarm_hot_stocks: global timeout")
        return {"status": "failed", "error": "timeout"}
    except Exception as exc:
        logger.error("task_prewarm_hot_stocks failed: %s", exc)
        return {"status": "failed", "error": str(exc)[:200]}

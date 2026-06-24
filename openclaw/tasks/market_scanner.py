"""Market opportunity scanner — zero-LLM-cost full market scanning.

Runs every 15 minutes during trading hours. Fetches the limit-up pool,
sector capital flow, consecutive board rates, and scores all candidates
with LeaderDetector. Stores results in Redis for Agent consumption.

This is the "proactive opportunity discovery" pipeline that transforms
the Agent from a position manager into a full-market scanner.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from celery import shared_task

logger = logging.getLogger(__name__)

_CST = ZoneInfo("Asia/Shanghai")
_REDIS_KEY_PREFIX = "scanner:candidates:"
_REDIS_TTL = 6 * 3600  # 6 hours


def _is_trading_hours() -> bool:
    now = datetime.now(_CST)
    if now.weekday() >= 5:
        return False
    h, m = now.hour, now.minute
    if (h == 9 and m >= 25) or (10 <= h <= 10):
        return True
    if h == 11 and m <= 30:
        return True
    if 13 <= h <= 14:
        return True
    if h == 15 and m <= 5:
        return True
    return False


def _fetch_market_data() -> dict[str, Any]:
    """Fetch all market-wide data in one pass."""
    from src.data.consecutive_board import ConsecutiveBoardTracker
    from src.data.fetcher import StockDataFetcher
    from src.data.sector_flow_fetcher import SectorFlowFetcher

    fetcher = StockDataFetcher()
    sector_fetcher = SectorFlowFetcher()

    limit_up_df = fetcher.fetch_limit_up_pool()
    sector_flow_df = sector_fetcher.fetch_industry_flow("today")
    board_tracker = ConsecutiveBoardTracker(fetcher=fetcher)
    board_snapshot = board_tracker.compute_snapshot()

    # Sentiment phase
    sentiment_phase = "unknown"
    try:
        from src.agent_loop.sentiment_cycle import (
            SentimentCycleDetector,
            SentimentSignals,
        )

        detector = SentimentCycleDetector()
        limit_up_count = len(limit_up_df) if limit_up_df is not None else 0
        max_consec = 0
        if limit_up_df is not None and not limit_up_df.empty:
            for col in ("consecutive", "streak"):
                if col in limit_up_df.columns:
                    max_consec = int(limit_up_df[col].max())
                    break
        signals = SentimentSignals(
            limit_up_count=limit_up_count,
            max_consecutive_board=max_consec,
        )
        phase = detector.detect(signals)
        sentiment_phase = phase.phase if hasattr(phase, "phase") else str(phase)
    except Exception as exc:
        logger.debug("Sentiment detection failed: %s", exc)

    return {
        "limit_up_df": limit_up_df,
        "sector_flow_df": sector_flow_df,
        "board_snapshot": board_snapshot,
        "sentiment_phase": sentiment_phase,
    }


def _build_candidates(
    limit_up_df: Any,
    sector_flow_df: Any,
) -> list[Any]:
    """Convert limit-up pool to LeaderCandidate objects."""
    from src.agent_loop.leader_detector import LeaderCandidate

    if limit_up_df is None or limit_up_df.empty:
        return []

    # Count limit-ups per sector
    industry_col = None
    for col in ("industry", "行业"):
        if col in limit_up_df.columns:
            industry_col = col
            break

    sector_counts: dict[str, int] = {}
    if industry_col:
        sector_counts = limit_up_df[industry_col].value_counts().to_dict()

    candidates: list[LeaderCandidate] = []
    for _, row in limit_up_df.iterrows():
        symbol = str(row.get("symbol", ""))
        name = str(row.get("name", ""))
        sector = str(row.get(industry_col, "")) if industry_col else ""
        price = float(row.get("price", 0) or 0)

        # Convert amounts to volumes (手)
        amount = float(row.get("amount", 0) or 0)
        seal_amount = float(row.get("seal_amount", 0) or 0)
        total_volume = amount / (price * 100) if price > 0 else 0
        seal_volume = seal_amount / (price * 100) if price > 0 else 0

        # Consecutive boards
        consec = 0
        for col in ("consecutive", "streak"):
            if col in row.index:
                try:
                    consec = int(row[col] or 0)
                except (ValueError, TypeError):
                    pass
                break

        # First seal time — convert HHMMSS to HH:MM:SS
        raw_seal = str(row.get("first_seal_time", "") or "")
        if len(raw_seal) == 6 and raw_seal.isdigit():
            first_seal = f"{raw_seal[:2]}:{raw_seal[2:4]}:{raw_seal[4:6]}"
        else:
            first_seal = raw_seal

        # Break count → board_resealed
        break_count = int(row.get("break_count", 0) or 0)

        candidates.append(
            LeaderCandidate(
                symbol=symbol,
                name=name,
                sector=sector,
                is_limit_up=True,
                limit_up_time=first_seal if first_seal else None,
                seal_volume=seal_volume,
                total_volume=total_volume,
                consecutive_boards=consec,
                sector_limit_up_count=sector_counts.get(sector, 1),
                turnover_rate=float(row.get("turnover", 0) or 0),
                board_resealed=break_count > 0,
            )
        )

    return candidates


def _publish_opportunities(
    scored: list[Any],
    sentiment_phase: str,
    board_snapshot: Any,
) -> dict[str, Any]:
    """Publish qualifying candidates to Redis + events:signal + MessageStore."""
    import redis

    date = datetime.now(_CST).strftime("%Y%m%d")
    key = f"{_REDIS_KEY_PREFIX}{date}"

    result = {
        "total_scored": len(scored),
        "qualifying": 0,
        "published_signals": 0,
        "published_alerts": 0,
    }

    # Filter: score > 50, not in ebb/freezing phase
    skip_phases = {"freezing", "ebb"}
    qualifying = [
        s
        for s in scored
        if s.total_score > 50
        and (
            sentiment_phase not in skip_phases
            or s.scores.get("board_resilience", 0) > 0
        )
    ]
    result["qualifying"] = len(qualifying)

    if not qualifying:
        return result

    try:
        r = redis.Redis(host="redis", port=6379, db=0, decode_responses=True)

        # Clear stale data first — each scan is a fresh snapshot
        r.delete(key)

        # Realtime price verification before writing
        from src.data.realtime import RealtimeQuoteManager

        mgr = RealtimeQuoteManager()
        verified = []
        for s in qualifying:
            try:
                q = mgr.get_single_quote(s.symbol)
                if q:
                    pct = float(q.get("pct_change", 0) or 0)
                    if pct < 0:
                        logger.info(
                            "Scanner filtered %s: down %.1f%% (stale data)",
                            s.symbol,
                            pct,
                        )
                        continue
                    if pct < 5.0 and hasattr(s, "limit_up_time") and s.limit_up_time:
                        logger.info(
                            "Scanner filtered %s: claimed limit-up but pct=%.1f%%",
                            s.symbol,
                            pct,
                        )
                        continue
            except Exception:
                pass  # On error, keep candidate (fail-open)
            verified.append(s)

        for s in verified:
            member = json.dumps(
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "sector": s.sector,
                    "total_score": round(s.total_score, 1),
                    "is_leader": s.is_leader,
                    "reason": s.reason,
                    "confidence": s.confidence_level,
                    "scores": {k: round(v, 1) for k, v in s.scores.items()},
                    "sentiment_phase": sentiment_phase,
                    "scanned_at": datetime.now(_CST).strftime("%H:%M"),
                },
                ensure_ascii=False,
            )
            r.zadd(key, {member: s.total_score})

        r.expire(key, _REDIS_TTL)

    except Exception as exc:
        logger.warning("Redis publish failed: %s", exc)

    # Quick price sanity check before publishing high-score alerts
    _realtime_quotes: dict[str, dict] = {}
    try:
        from src.data.realtime import RealtimeQuoteManager

        _mgr = RealtimeQuoteManager()
        for s in qualifying:
            if s.total_score >= 70:
                q = _mgr.get_single_quote(s.symbol)
                if q and q.get("price") is not None:
                    _realtime_quotes[s.symbol] = q
    except Exception:
        pass

    # High-score candidates → events:signal + MessageStore
    for s in qualifying:
        if s.total_score >= 70:
            # Skip if realtime price shows stock is actually down
            _rt = _realtime_quotes.get(s.symbol)
            if _rt:
                _pct = float(_rt.get("pct_change", 0) or 0)
                if _pct < 0:
                    logger.info(
                        "Skipping opportunity_alert for %s (%s): "
                        "pct_change=%.1f%% (down)",
                        s.symbol,
                        s.name,
                        _pct,
                    )
                    continue
                if _pct < 5.0:
                    logger.info(
                        "Skipping opportunity_alert for %s (%s): "
                        "pct_change=%.1f%% (not near limit-up)",
                        s.symbol,
                        s.name,
                        _pct,
                    )
                    continue

            try:
                from src.event_bus.producers import publish_signal_detected

                publish_signal_detected(
                    symbol=s.symbol,
                    direction="bullish",
                    source="market_scanner",
                    confidence=s.total_score / 100.0,
                    reason=f"龙头评分{s.total_score:.0f}分: {s.reason}",
                )
                result["published_signals"] += 1
            except Exception:
                pass

            try:
                from src.web.services.message_store import MessageStore

                store = MessageStore()
                store.create_message(
                    symbol=s.symbol,
                    msg_type="opportunity_alert",
                    title=f"机会发现: {s.name}({s.symbol}) 评分{s.total_score:.0f}",
                    summary=s.reason,
                    content=s.reason,
                    priority="high",
                    stock_recommendations=json.dumps(
                        [
                            {
                                "symbol": s.symbol,
                                "name": s.name,
                                "score": s.total_score,
                                "sector": s.sector,
                            }
                        ],
                        ensure_ascii=False,
                    ),
                )
                result["published_alerts"] += 1
            except Exception:
                pass

    return result


@shared_task(
    name="openclaw.tasks.market_scanner.task_market_opportunity_scan",
    bind=True,
    max_retries=0,
    soft_time_limit=55,
    time_limit=60,
)
def task_market_opportunity_scan(self: Any) -> dict[str, Any]:
    """Scan entire market for opportunities. Zero LLM cost.

    Every 15 min during trading hours:
    1. Fetch limit-up pool (all stocks)
    2. Fetch sector flow + board rates
    3. Score with LeaderDetector
    4. Store candidates in Redis + publish high-score signals
    """
    if not _is_trading_hours():
        return {"status": "outside_trading_hours"}

    # Publish call-auction signals at ~9:26 (first scan of the day)
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now_cst = datetime.now(ZoneInfo("Asia/Shanghai"))
        if 9 <= now_cst.hour <= 9 and 25 <= now_cst.minute <= 35:
            from src.data.call_auction import CallAuctionCollector

            import redis as _redis_lib

            _r = _redis_lib.Redis(host="redis", port=6379, db=0, decode_responses=True)
            collector = CallAuctionCollector(redis_client=_r)
            auction_count = collector.publish_to_event_bus(min_volume=50000)
            logger.info("Call-auction: published %d candidates", auction_count)
    except Exception:
        logger.debug("Call-auction publish failed", exc_info=True)

    try:
        data = _fetch_market_data()
    except Exception as exc:
        logger.error("Market data fetch failed: %s", exc)
        return {"status": "data_fetch_error", "error": str(exc)}

    limit_up_df = data["limit_up_df"]
    if limit_up_df is None or limit_up_df.empty:
        return {"status": "no_limit_ups", "sentiment": data["sentiment_phase"]}

    # Build candidates
    candidates = _build_candidates(limit_up_df, data["sector_flow_df"])
    if not candidates:
        return {"status": "no_candidates"}

    # Score with LeaderDetector
    from src.agent_loop.leader_detector import LeaderDetector

    detector = LeaderDetector()
    scored = detector.identify_leaders(candidates)

    # Publish
    pub_result = _publish_opportunities(
        scored, data["sentiment_phase"], data["board_snapshot"]
    )

    board_info = ""
    if data["board_snapshot"]:
        bs = data["board_snapshot"]
        board_info = (
            f"涨停{bs.total_limit_up}家 "
            f"晋级率{bs.promotion_1to2:.0%} "
            f"最高{bs.max_consecutive}连板"
        )

    logger.info(
        "Market scan: %d limit-ups → %d candidates → %d qualifying (>50) → "
        "%d signals (>70) | %s | sentiment=%s",
        len(limit_up_df),
        len(candidates),
        pub_result["qualifying"],
        pub_result["published_signals"],
        board_info,
        data["sentiment_phase"],
    )

    return {
        "status": "ok",
        "limit_ups": len(limit_up_df),
        "candidates_scored": len(scored),
        "qualifying": pub_result["qualifying"],
        "signals_published": pub_result["published_signals"],
        "alerts_published": pub_result["published_alerts"],
        "sentiment_phase": data["sentiment_phase"],
        "board_info": board_info,
        "top_3": [
            {"symbol": s.symbol, "name": s.name, "score": round(s.total_score, 1)}
            for s in scored[:3]
        ],
    }

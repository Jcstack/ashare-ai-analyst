"""Intraday data pipeline tasks.

Manages minute-bar data collection, intraday factor computation,
pattern detection, and seal strength monitoring during trading hours.

Message push: For portfolio stocks, actionable patterns (severity >= 0.5)
are persisted to MessageStore and published to Redis ``assistant:messages``
for Discord push via AssistantPushCog.
"""

from __future__ import annotations

from typing import Any

from openclaw.celery_app import app
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.intraday_pipeline")

# ---------------------------------------------------------------------------
# Pattern name mapping (English key -> Chinese display)
# ---------------------------------------------------------------------------

_PATTERN_NAMES: dict[str, str] = {
    "high_reversal": "冲高回落",
    "gap_down_rally": "低开高走",
    "late_rally": "尾盘拉升",
    "late_dump": "尾盘跳水",
    "volume_price_divergence": "量价背离",
    "vwap_rejection": "VWAP压制/支撑",
    "volume_dry_up": "缩量",
    "opening_drive": "开盘冲击",
}

# Direction -> default action advice
_BULLISH_ADVICE = "关注加仓机会"
_BEARISH_ADVICE = "注意风险，考虑减仓"

# Pattern-specific risk notes
_RISK_NOTES: dict[str, str] = {
    "high_reversal": "冲高回落后可能继续下探，注意支撑位和成交量变化",
    "gap_down_rally": "低开高走需观察能否突破前高，否则可能二次回探",
    "late_rally": "尾盘拉升需区分主力建仓与诱多出货，次日开盘走势是关键",
    "late_dump": "尾盘跳水往往预示次日低开风险，考虑盘前减仓",
    "volume_price_divergence": "量价背离是趋势反转的前兆信号，密切关注后续走势",
    "vwap_rejection": "VWAP是日内多空分水岭，突破或跌破将确认短期方向",
    "volume_dry_up": "极度缩量后可能出现方向性变盘，做好双向准备",
    "opening_drive": "开盘冲击后的首次回踩力度决定日内趋势强弱",
}


def _should_execute(task_name: str) -> bool:
    """Check timeline guard."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        return True


def _publish_to_event_bus(stream: str, events: list[dict]) -> int:
    """Publish events to the EventBus (fire-and-forget).

    Lazily initializes the EventBus singleton. Never raises — publishing
    failure must not break the data pipeline.

    Args:
        stream: Event bus stream name (e.g. "strategist:signal").
        events: List of event data dicts to publish.

    Returns:
        Number of events successfully published.
    """
    if not events:
        return 0
    try:
        import asyncio

        from src.intelligence.event_bus import get_event_bus

        bus = get_event_bus()
        published = 0

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
                    published = pool.submit(asyncio.run, _do_publish()).result(
                        timeout=5
                    )
            else:
                published = loop.run_until_complete(_do_publish())
        except RuntimeError:
            published = asyncio.run(_do_publish())

        if published:
            logger.info("Published %d/%d events to %s", published, len(events), stream)
        return published
    except Exception as exc:
        logger.warning("Event bus publish failed (non-critical): %s", exc)
        return 0


@app.task(
    name="openclaw.tasks.intraday_pipeline.task_minute_bar_refresh",
    bind=True,
    max_retries=1,
    soft_time_limit=120,
    time_limit=150,
)
def task_minute_bar_refresh(self, symbols: list[str] | None = None) -> dict[str, Any]:
    """Refresh minute bar cache for watched/held symbols.

    Runs every 5 minutes during trading hours. Pre-warms minute bar
    cache so screener and pattern detectors don't need to fetch on demand.
    """
    if not _should_execute("task_minute_bar_refresh"):
        return {"status": "skipped", "reason": "non-trading"}

    try:
        import redis

        from src.data.minute_bar import MinuteBarFetcher
        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)
        fetcher = MinuteBarFetcher(redis_client=redis_client)

        if not symbols:
            # Get symbols from: held positions + today's recommendations + watchlist
            symbols = _get_active_symbols(redis_client)

        if not symbols:
            return {"status": "ok", "refreshed": 0}

        data = fetcher.fetch_batch(symbols, period="5", days=1)
        refreshed = sum(1 for v in data.values() if v is not None and not v.empty)

        # Run anomaly detection on fresh quotes (Phase 2: event-driven triggers)
        spikes_found = 0
        vol_anomalies_found = 0
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            from src.data.price_spike_detector import PriceSpikeDetector
            from src.data.realtime import RealtimeQuoteManager
            from src.data.volume_anomaly_detector import VolumeAnomalyDetector

            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            dow, hour, minute = now.weekday(), now.hour, now.minute

            rtm = RealtimeQuoteManager()
            quotes_raw = rtm.get_quotes(symbols)
            if quotes_raw:
                spike_det = PriceSpikeDetector(redis_client=redis_client)
                vol_det = VolumeAnomalyDetector(redis_client=redis_client)

                price_quotes = [
                    {
                        "symbol": sym,
                        "price": q.get("price", 0),
                        "prev_close": q.get("prev_close", 0),
                    }
                    for sym, q in quotes_raw.items()
                    if q.get("price") and q.get("prev_close")
                ]
                spikes = spike_det.check_batch(price_quotes, dow, hour, minute)
                spikes_found = len(spikes)

                vol_bars = [
                    {"symbol": sym, "volume": q.get("volume", 0)}
                    for sym, q in quotes_raw.items()
                    if q.get("volume")
                ]
                anomalies = vol_det.check_batch(vol_bars, dow, hour, minute)
                vol_anomalies_found = len(anomalies)
        except Exception as exc:
            logger.warning("Anomaly detection in minute bar refresh: %s", exc)

        logger.info(
            "Minute bar refresh: %d/%d symbols, %d spikes, %d vol anomalies",
            refreshed,
            len(symbols),
            spikes_found,
            vol_anomalies_found,
        )
        return {
            "status": "ok",
            "refreshed": refreshed,
            "total": len(symbols),
            "price_spikes": spikes_found,
            "volume_anomalies": vol_anomalies_found,
        }
    except Exception as exc:
        logger.error("Minute bar refresh failed: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="openclaw.tasks.intraday_pipeline.task_intraday_pattern_scan",
    bind=True,
    max_retries=1,
    soft_time_limit=180,
    time_limit=210,
)
def task_intraday_pattern_scan(self) -> dict[str, Any]:
    """Scan for intraday patterns across active symbols.

    Runs every 15 minutes during trading hours. Detects patterns like
    冲高回落, 量价背离, 尾盘拉升 and feeds them into the signal aggregator.
    """
    if not _should_execute("task_intraday_pattern_scan"):
        return {"status": "skipped", "reason": "non-trading"}

    try:
        import json
        from datetime import datetime
        from zoneinfo import ZoneInfo

        import redis

        from src.agent_loop.intraday_patterns import IntradayPatternDetector
        from src.data.minute_bar import MinuteBarFetcher
        from src.data.realtime import RealtimeQuoteManager
        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)

        fetcher = MinuteBarFetcher(redis_client=redis_client)
        detector = IntradayPatternDetector()
        rtm = RealtimeQuoteManager()

        symbols = _get_active_symbols(redis_client)
        if not symbols:
            return {"status": "ok", "patterns_found": 0}

        all_patterns: list[Any] = []
        minute_data = fetcher.fetch_batch(symbols, period="5", days=1)

        for symbol in symbols:
            bars = minute_data.get(symbol)
            if bars is None or bars.empty:
                continue
            quote = rtm.get_quote(symbol)
            if not quote:
                continue
            patterns = detector.detect_all(
                symbol,
                bars,
                quote,
                prev_close=quote.get("prev_close"),
            )
            all_patterns.extend(patterns)

        # Store significant patterns in Redis for signal aggregator to pick up
        significant = [p for p in all_patterns if p.severity > 0.3]
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        date_str = now.strftime("%Y%m%d")

        if significant:
            for p in significant:
                key = f"intraday_pattern:{date_str}:{p.symbol}"
                redis_client.lpush(
                    key,
                    json.dumps(
                        {
                            "pattern_type": p.pattern_type,
                            "symbol": p.symbol,
                            "severity": p.severity,
                            "direction": p.direction,
                            "description": p.description,
                            "timestamp": p.timestamp,
                        }
                    ),
                )
                redis_client.expire(key, 86400)  # 24h TTL

        # LLM-verify high-severity patterns before pushing
        verified_count = 0
        if significant:
            try:
                significant, verified_count = _verify_high_severity_patterns(
                    significant, minute_data, redis_client
                )
            except Exception as exc:
                logger.warning("Pattern verification step failed: %s", exc)

        # Push alerts for portfolio stocks (severity >= 0.5)
        alerts_pushed = 0
        opportunity_pushed = 0
        if significant:
            try:
                portfolio_syms = _get_portfolio_symbols(redis_client)
                alerts_pushed = _push_portfolio_alerts(
                    significant, portfolio_syms, redis_client, date_str
                )
                if alerts_pushed:
                    logger.info(
                        "Pushed %d intraday alerts for portfolio stocks",
                        alerts_pushed,
                    )
                # Also push opportunity alerts for non-portfolio stocks (severity >= 0.7)
                opportunity_pushed = _push_opportunity_alerts(
                    significant, portfolio_syms, redis_client, date_str
                )
                if opportunity_pushed:
                    logger.info(
                        "Pushed %d opportunity alerts for new stocks",
                        opportunity_pushed,
                    )
            except Exception as exc:
                logger.error("Portfolio/opportunity alert push failed: %s", exc)

        # Publish significant patterns to intelligence event bus (fire-and-forget)
        events_published = _publish_to_event_bus(
            "strategist:signal",
            [
                {
                    "event_type": "PATTERN_DETECTED",
                    "symbol": p.symbol,
                    "pattern_type": p.pattern_type,
                    "severity": p.severity,
                    "direction": p.direction,
                    "description": p.description,
                    "timestamp": p.timestamp,
                }
                for p in significant
            ],
        )

        # Also publish to standard event bus so consumers can act
        try:
            from src.event_bus.producers import publish_signal_detected

            for p in significant:
                publish_signal_detected(
                    symbol=p.symbol,
                    direction=p.direction,
                    source=f"intraday_pattern:{p.pattern_type}",
                    confidence=p.severity,
                    reason=p.description,
                )
        except Exception as exc:
            logger.warning("Standard event bus publish failed: %s", exc)

        logger.info(
            "Intraday pattern scan: %d patterns found (%d significant, "
            "%d verified, %d portfolio alerts, %d opportunity alerts, "
            "%d bus events) across %d symbols",
            len(all_patterns),
            len(significant),
            verified_count,
            alerts_pushed,
            opportunity_pushed,
            events_published,
            len(symbols),
        )
        return {
            "status": "ok",
            "symbols_scanned": len(symbols),
            "patterns_found": len(all_patterns),
            "significant": len(significant),
            "llm_verified": verified_count,
            "alerts_pushed": alerts_pushed,
            "opportunity_pushed": opportunity_pushed,
            "events_published": events_published,
        }
    except Exception as exc:
        logger.error("Intraday pattern scan failed: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="openclaw.tasks.intraday_pipeline.task_seal_strength_monitor",
    bind=True,
    max_retries=1,
    soft_time_limit=60,
    time_limit=90,
)
def task_seal_strength_monitor(self) -> dict[str, Any]:
    """Monitor seal strength for stocks near/at limit-up.

    Runs every 5 minutes during trading hours. Tracks seal quality
    for positions and watchlist stocks at limit-up.
    """
    if not _should_execute("task_seal_strength_monitor"):
        return {"status": "skipped", "reason": "non-trading"}

    try:
        import json

        import redis

        from src.data.seal_strength import SealStrengthAnalyzer
        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)

        analyzer = SealStrengthAnalyzer(redis_client=redis_client)
        symbols = _get_active_symbols(redis_client)

        results: list[dict[str, Any]] = []
        for symbol in symbols:
            result = analyzer.analyze(symbol)
            if result and result.get("at_limit_up"):
                results.append(result)

        # Store seal data in Redis
        if results:
            for r in results:
                key = f"seal_strength:{r['symbol']}"
                redis_client.set(key, json.dumps(r), ex=300)  # 5min TTL

        logger.info("Seal strength monitor: %d stocks at limit-up", len(results))
        return {"status": "ok", "at_limit_up": len(results)}
    except Exception as exc:
        logger.error("Seal strength monitor failed: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="openclaw.tasks.intraday_pipeline.task_sector_flow_refresh",
    bind=True,
    max_retries=1,
    soft_time_limit=60,
    time_limit=90,
)
def task_sector_flow_refresh(self) -> dict[str, Any]:
    """Refresh intraday sector flow data.

    Runs every 10 minutes. Detects sector rotation patterns.
    """
    if not _should_execute("task_sector_flow_refresh"):
        return {"status": "skipped", "reason": "non-trading"}

    try:
        import redis

        from src.data.intraday_sector_flow import IntradaySectorFlowTracker
        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)

        tracker = IntradaySectorFlowTracker(redis_client=redis_client)
        flow = tracker.fetch_current_flow()
        rotation = tracker.detect_rotation()

        logger.info(
            "Sector flow refresh: %d sectors tracked, %d rotating in, %d rotating out",
            len(flow),
            len(rotation.get("rotating_in", [])),
            len(rotation.get("rotating_out", [])),
        )
        return {
            "status": "ok",
            "sectors_tracked": len(flow),
            "rotation": rotation,
        }
    except Exception as exc:
        logger.error("Sector flow refresh failed: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="openclaw.tasks.intraday_pipeline.task_call_auction_capture",
    bind=True,
    max_retries=0,
    soft_time_limit=30,
    time_limit=45,
)
def task_call_auction_capture(self) -> dict[str, Any]:
    """Capture call auction snapshots during 9:15-9:25.

    Runs every minute during call auction window. Stores snapshots
    for weak-to-strong analysis.
    """
    try:
        import redis

        from src.data.call_auction import CallAuctionCollector
        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)

        collector = CallAuctionCollector(redis_client=redis_client)
        symbols = _get_active_symbols(redis_client)

        if not symbols:
            return {"status": "ok", "captured": 0}

        snapshots = collector.capture_snapshot(symbols)
        logger.info("Call auction capture: %d snapshots", len(snapshots))
        return {"status": "ok", "captured": len(snapshots)}
    except Exception as exc:
        logger.error("Call auction capture failed: %s", exc)
        return {"status": "failed", "error": str(exc)[:200]}


def _get_portfolio_symbols(redis_client: Any) -> set[str]:
    """Return symbols currently held in the portfolio."""
    try:
        positions = redis_client.hgetall("portfolio:positions") or {}
        return set(positions.keys())
    except Exception:
        return set()


def _format_pattern_message(pattern: Any) -> dict[str, str]:
    """Format an IntradayPattern into Chinese-language message fields.

    Returns dict with keys: title, summary, action_advice, risk_note, content.
    """
    cn_name = _PATTERN_NAMES.get(pattern.pattern_type, pattern.pattern_type)
    title = f"持仓异动：{cn_name}"

    # Severity label
    if pattern.severity >= 0.8:
        severity_label = "强烈"
    elif pattern.severity >= 0.6:
        severity_label = "明显"
    else:
        severity_label = "轻度"

    summary = f"{pattern.description}（{severity_label}，强度 {pattern.severity:.0%}）"

    # Use LLM-verified advice if available, otherwise fall back to defaults
    llm_advice = (pattern.factors or {}).get("llm_action_advice", "")
    action_advice = (
        llm_advice
        if llm_advice
        else (_BULLISH_ADVICE if pattern.direction == "bullish" else _BEARISH_ADVICE)
    )
    risk_note = _RISK_NOTES.get(
        pattern.pattern_type, "请结合大盘走势和个股基本面综合判断"
    )

    # Build detailed content from factors
    factor_lines: list[str] = []
    for k, v in (pattern.factors or {}).items():
        if isinstance(v, float):
            factor_lines.append(f"  {k}: {v:.4f}")
        else:
            factor_lines.append(f"  {k}: {v}")
    factors_text = "\n".join(factor_lines) if factor_lines else "  无附加数据"

    # Add LLM reasoning section when available
    llm_reasoning = (pattern.factors or {}).get("llm_reasoning", "")
    llm_section = f"\n\n### AI验证\n{llm_reasoning}" if llm_reasoning else ""
    verified_badge = (
        "（AI已验证）" if (pattern.factors or {}).get("llm_verified") else ""
    )

    content = (
        f"## {cn_name}信号{verified_badge}\n\n"
        f"**股票**: {pattern.symbol}\n"
        f"**方向**: {'看多' if pattern.direction == 'bullish' else '看空'}\n"
        f"**强度**: {pattern.severity:.0%}\n\n"
        f"### 信号描述\n{pattern.description}\n\n"
        f"### 建议\n{action_advice}\n\n"
        f"### 风险提示\n{risk_note}"
        f"{llm_section}\n\n"
        f"### 技术因子\n{factors_text}"
    )

    return {
        "title": title,
        "summary": summary,
        "action_advice": action_advice,
        "risk_note": risk_note,
        "content": content,
    }


def _severity_to_priority(severity: float) -> str:
    """Map pattern severity to message priority."""
    if severity >= 0.8:
        return "critical"
    if severity >= 0.6:
        return "high"
    return "medium"


def _push_portfolio_alerts(
    patterns: list[Any],
    portfolio_symbols: set[str],
    redis_client: Any,
    date_str: str,
) -> int:
    """Create messages and push Discord alerts for portfolio-stock patterns.

    Only processes patterns with severity >= 0.5 for portfolio stocks.
    Deduplicates by (date, symbol, pattern_type) using a Redis key with 4h TTL.

    Returns the number of alerts pushed.
    """
    import json

    from src.web.services.message_store import MessageStore

    if not portfolio_symbols:
        return 0

    # Filter: portfolio stocks only, severity >= 0.5
    actionable = [
        p for p in patterns if p.symbol in portfolio_symbols and p.severity >= 0.5
    ]
    if not actionable:
        return 0

    store = MessageStore()
    pushed = 0

    for pattern in actionable:
        # Dedup check: skip if we already alerted this pattern today
        dedup_key = f"intraday_alert:{date_str}:{pattern.symbol}:{pattern.pattern_type}"
        if redis_client.exists(dedup_key):
            logger.debug(
                "Skipping duplicate alert: %s %s %s",
                pattern.symbol,
                pattern.pattern_type,
                date_str,
            )
            continue

        # Mark as alerted (4h TTL)
        redis_client.set(dedup_key, "1", ex=14400)

        # Format message fields
        msg = _format_pattern_message(pattern)
        priority = _severity_to_priority(pattern.severity)

        # 1. Persist to MessageStore
        try:
            msg_id = store.create_message(
                symbol=pattern.symbol,
                msg_type="intraday_signal",
                title=msg["title"],
                summary=msg["summary"],
                action_advice=msg["action_advice"],
                risk_note=msg["risk_note"],
                detail_analysis=msg["content"],
                raw_data_ref={
                    "pattern_type": pattern.pattern_type,
                    "severity": pattern.severity,
                    "direction": pattern.direction,
                    "factors": pattern.factors,
                    "priority": priority,
                },
                data_freshness="realtime",
                data_collected_at=pattern.timestamp,
            )
            logger.info(
                "Created intraday_signal message #%d for %s (%s, severity=%.2f)",
                msg_id,
                pattern.symbol,
                pattern.pattern_type,
                pattern.severity,
            )
        except Exception as exc:
            logger.error(
                "Failed to create message for %s %s: %s",
                pattern.symbol,
                pattern.pattern_type,
                exc,
            )
            continue

        # 2. Publish to Redis assistant:messages channel for Discord push
        try:
            payload = {
                "type": "intraday_signal",
                "symbol": pattern.symbol,
                "title": msg["title"],
                "summary": msg["summary"],
                "priority": priority,
                "action_advice": msg["action_advice"],
                "risk_note": msg["risk_note"],
                "confidence": pattern.severity,
                "patterns": [
                    {
                        "pattern_type": pattern.pattern_type,
                        "direction": pattern.direction,
                        "severity": pattern.severity,
                        "description": pattern.description,
                    }
                ],
            }
            redis_client.publish(
                "assistant:messages",
                json.dumps(payload, ensure_ascii=False),
            )
            pushed += 1
        except Exception as exc:
            logger.warning(
                "Redis publish failed for %s %s: %s",
                pattern.symbol,
                pattern.pattern_type,
                exc,
            )

    return pushed


def _push_opportunity_alerts(
    patterns: list[Any],
    portfolio_symbols: set[str],
    redis_client: Any,
    date_str: str,
) -> int:
    """Push alerts for high-severity patterns on NON-portfolio stocks.

    These are opportunity signals — new stocks showing strong patterns
    that the user might want to watch or buy. Only patterns with
    severity >= 0.7 are pushed to avoid noise.

    Returns the number of alerts pushed.
    """
    import json

    from src.web.services.message_store import MessageStore

    # Filter: non-portfolio stocks only, severity >= 0.7, bullish direction preferred
    opportunities = [
        p
        for p in patterns
        if p.symbol not in portfolio_symbols
        and p.severity >= 0.7
        and p.direction == "bullish"
    ]
    if not opportunities:
        return 0

    store = MessageStore()
    pushed = 0

    # Limit to top 3 per scan to avoid message flood
    opportunities.sort(key=lambda p: p.severity, reverse=True)
    for pattern in opportunities[:3]:
        dedup_key = (
            f"opportunity_alert:{date_str}:{pattern.symbol}:{pattern.pattern_type}"
        )
        if redis_client.exists(dedup_key):
            continue

        redis_client.set(dedup_key, "1", ex=7200)  # 2h TTL

        cn_name = _PATTERN_NAMES.get(pattern.pattern_type, pattern.pattern_type)
        title = f"机会发现：{pattern.symbol} {cn_name}"
        summary = f"{pattern.description}（强度 {pattern.severity:.0%}）"
        action_advice = "可加入自选观察，尾盘考虑介入"
        risk_note = _RISK_NOTES.get(
            pattern.pattern_type, "新发现信号，请结合板块走势综合判断"
        )
        content = (
            f"## 机会信号：{cn_name}\n\n"
            f"**股票**: {pattern.symbol}\n"
            f"**方向**: 看多\n"
            f"**强度**: {pattern.severity:.0%}\n\n"
            f"### 信号描述\n{pattern.description}\n\n"
            f"### 建议\n{action_advice}\n\n"
            f"### 风险提示\n{risk_note}"
        )

        try:
            msg_id = store.create_message(
                symbol=pattern.symbol,
                msg_type="intraday_signal",
                title=title,
                summary=summary,
                content=content,
                action_advice=action_advice,
                risk_note=risk_note,
                priority="high",
                raw_data_ref={
                    "pattern_type": pattern.pattern_type,
                    "severity": pattern.severity,
                    "direction": pattern.direction,
                    "is_opportunity": True,
                },
                data_freshness="realtime",
                data_collected_at=pattern.timestamp,
            )

            payload = {
                "type": "intraday_signal",
                "symbol": pattern.symbol,
                "title": title,
                "summary": summary,
                "priority": "high",
                "action_advice": action_advice,
                "risk_note": risk_note,
                "confidence": pattern.severity,
            }
            redis_client.publish(
                "assistant:messages",
                json.dumps(payload, ensure_ascii=False),
            )
            pushed += 1
            logger.info(
                "Opportunity alert #%d: %s %s (severity=%.2f)",
                msg_id,
                pattern.symbol,
                pattern.pattern_type,
                pattern.severity,
            )
        except Exception as exc:
            logger.error(
                "Opportunity alert failed for %s: %s",
                pattern.symbol,
                exc,
            )

    return pushed


@app.task(
    name="openclaw.tasks.intraday_pipeline.task_advanced_signal_scan",
    bind=True,
    max_retries=1,
    soft_time_limit=180,
    time_limit=210,
)
def task_advanced_signal_scan(self) -> dict[str, Any]:
    """Scan for VWAP triggers, VPIN toxicity, and reflexivity loops.

    Runs every 15 minutes during trading hours. Detects signals from the
    5 advanced modules (VWAP, VPIN, MTF, reflexivity, sector correlation)
    and pushes alerts for portfolio stocks.
    """
    if not _should_execute("task_advanced_signal_scan"):
        return {"status": "skipped", "reason": "non-trading"}

    try:
        import json
        from datetime import datetime
        from zoneinfo import ZoneInfo

        import redis

        from src.data.minute_bar import MinuteBarFetcher
        from src.quant.vpin import VpinCalculator
        from src.quant.vwap_trigger import VwapTriggerEngine
        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)

        fetcher = MinuteBarFetcher(redis_client=redis_client)
        vwap_engine = VwapTriggerEngine()
        vpin_calc = VpinCalculator()

        symbols = _get_active_symbols(redis_client)
        if not symbols:
            return {"status": "ok", "signals_found": 0}

        minute_data = fetcher.fetch_batch(symbols, period="5", days=1)
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        date_str = now.strftime("%Y%m%d")

        portfolio_syms = _get_portfolio_symbols(redis_client)
        vwap_signals = 0
        vpin_alerts = 0
        alerts_pushed = 0

        from src.web.services.message_store import MessageStore

        store = MessageStore()

        for symbol in symbols:
            bars = minute_data.get(symbol)
            if bars is None or bars.empty:
                continue

            # VWAP trigger scan
            for vs in vwap_engine.analyze(bars, symbol):
                vwap_signals += 1
                # Store in Redis for signal aggregator
                key = f"vwap_signal:{date_str}:{symbol}"
                redis_client.set(
                    key,
                    json.dumps(
                        {
                            "signal_type": vs.signal_type,
                            "deviation_pct": vs.deviation_pct,
                            "z_score": vs.z_score,
                            "direction": vs.direction,
                            "severity": vs.severity,
                            "description": vs.description,
                        }
                    ),
                    ex=3600,
                )

                # Push alert for portfolio stocks
                if symbol in portfolio_syms and vs.severity >= 0.5:
                    dedup = f"vwap_alert:{date_str}:{symbol}:{vs.signal_type}"
                    if not redis_client.exists(dedup):
                        redis_client.set(dedup, "1", ex=7200)
                        try:
                            store.create_message(
                                symbol=symbol,
                                msg_type="intraday_signal",
                                title=f"VWAP信号：{vs.signal_type}",
                                summary=vs.description,
                                action_advice="关注均值回归机会"
                                if "reversion" in vs.signal_type
                                else "趋势确认，考虑跟随",
                                risk_note="VWAP偏离信号需结合成交量确认",
                                detail_analysis=vs.description,
                                raw_data_ref={
                                    "signal_type": vs.signal_type,
                                    "z_score": vs.z_score,
                                    "severity": vs.severity,
                                },
                                data_freshness="realtime",
                                data_collected_at=now.isoformat(),
                            )
                            alerts_pushed += 1
                        except Exception as exc:
                            logger.error("VWAP alert push failed: %s", exc)

            # VPIN toxicity scan
            vpin_result = vpin_calc.calculate(bars, symbol)
            if vpin_result and vpin_result.vpin >= 0.6:
                vpin_alerts += 1
                key = f"vpin:{date_str}:{symbol}"
                redis_client.set(
                    key,
                    json.dumps(
                        {
                            "vpin": vpin_result.vpin,
                            "toxicity_level": vpin_result.toxicity_level,
                            "alert": vpin_result.alert,
                            "trend": vpin_result.trend,
                            "description": vpin_result.description,
                        }
                    ),
                    ex=3600,
                )

                # Push VPIN alert for portfolio stocks with elevated toxicity
                if symbol in portfolio_syms and vpin_result.vpin >= 0.7:
                    dedup = f"vpin_alert:{date_str}:{symbol}"
                    if not redis_client.exists(dedup):
                        redis_client.set(dedup, "1", ex=7200)
                        try:
                            priority = "critical" if vpin_result.alert else "high"
                            store.create_message(
                                symbol=symbol,
                                msg_type="intraday_signal",
                                title="流动性毒性预警（VPIN）",
                                summary=vpin_result.description,
                                action_advice="知情资金可能在活跃交易，谨慎持仓",
                                risk_note="VPIN高值意味着信息不对称风险升高",
                                detail_analysis=vpin_result.description,
                                raw_data_ref={
                                    "vpin": vpin_result.vpin,
                                    "toxicity": vpin_result.toxicity_level,
                                    "priority": priority,
                                },
                                data_freshness="realtime",
                                data_collected_at=now.isoformat(),
                            )
                            alerts_pushed += 1
                        except Exception as exc:
                            logger.error("VPIN alert push failed: %s", exc)

        # Publish signal summary to event bus (fire-and-forget)
        signal_events: list[dict] = []
        if vwap_signals > 0:
            signal_events.append(
                {
                    "event_type": "SIGNAL_DETECTED",
                    "signal_source": "vwap",
                    "count": vwap_signals,
                    "symbols_scanned": len(symbols),
                }
            )
        if vpin_alerts > 0:
            signal_events.append(
                {
                    "event_type": "SIGNAL_DETECTED",
                    "signal_source": "vpin",
                    "count": vpin_alerts,
                    "symbols_scanned": len(symbols),
                }
            )
        events_published = _publish_to_event_bus("strategist:signal", signal_events)

        logger.info(
            "Advanced signal scan: %d VWAP signals, %d VPIN alerts, "
            "%d alerts pushed, %d bus events across %d symbols",
            vwap_signals,
            vpin_alerts,
            alerts_pushed,
            events_published,
            len(symbols),
        )
        return {
            "status": "ok",
            "symbols_scanned": len(symbols),
            "vwap_signals": vwap_signals,
            "vpin_alerts": vpin_alerts,
            "alerts_pushed": alerts_pushed,
            "events_published": events_published,
        }
    except Exception as exc:
        logger.error("Advanced signal scan failed: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="openclaw.tasks.intraday_pipeline.task_sector_pulse",
    bind=True,
    max_retries=1,
    soft_time_limit=90,
    time_limit=120,
)
def task_sector_pulse(self) -> dict[str, Any]:
    """Generate market pulse message with sector flow highlights.

    Runs every 30 minutes during trading hours. Fetches sector flow
    data and creates a human-readable market pulse message showing
    top inflow/outflow sectors (电力, 新能源, 银行 etc.).
    """
    if not _should_execute("task_sector_pulse"):
        return {"status": "skipped", "reason": "non-trading"}

    try:
        import json
        from datetime import datetime
        from zoneinfo import ZoneInfo

        import redis

        from src.data.intraday_sector_flow import IntradaySectorFlowTracker
        from src.utils.config import load_config
        from src.web.services.message_store import MessageStore

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)

        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        date_str = now.strftime("%Y%m%d")

        # Dedup: one pulse per 30-min window
        dedup_key = f"sector_pulse:{date_str}:{now.hour}:{now.minute // 30}"
        if redis_client.exists(dedup_key):
            return {"status": "ok", "skipped": "dedup"}
        redis_client.set(dedup_key, "1", ex=1800)

        tracker = IntradaySectorFlowTracker(redis_client=redis_client)
        flow = tracker.fetch_current_flow()

        if not flow or len(flow) < 5:
            logger.debug("Sector pulse: insufficient data (%d sectors)", len(flow))
            return {"status": "ok", "sectors": 0}

        # Top 5 inflow and top 5 outflow
        inflow_sectors = [s for s in flow if s.get("net_inflow", 0) > 0][:5]
        outflow_sectors = [s for s in flow if s.get("net_inflow", 0) < 0]
        outflow_sectors = sorted(outflow_sectors, key=lambda x: x["net_inflow"])[:5]

        rotation = tracker.detect_rotation()

        # Build Chinese-language pulse message
        time_label = now.strftime("%H:%M")
        title = f"市场脉搏 {time_label}"

        # Inflow summary
        inflow_lines: list[str] = []
        for s in inflow_sectors:
            amt = s["net_inflow"]
            unit = "亿" if abs(amt) < 1000 else "亿"
            leader = s.get("leader_stock", "")
            leader_info = f"（领涨: {leader}）" if leader else ""
            inflow_lines.append(
                f"  📈 {s['sector']} +{s['change_pct']:.1f}% "
                f"净流入{amt:.2f}{unit}{leader_info}"
            )

        outflow_lines: list[str] = []
        for s in outflow_sectors:
            amt = abs(s["net_inflow"])
            outflow_lines.append(
                f"  📉 {s['sector']} {s['change_pct']:+.1f}% 净流出{amt:.2f}亿"
            )

        summary_parts: list[str] = []
        if inflow_sectors:
            top = inflow_sectors[0]
            summary_parts.append(f"资金涌入{top['sector']}等板块")
        if outflow_sectors:
            top = outflow_sectors[0]
            summary_parts.append(f"{top['sector']}等板块资金流出")
        summary = "，".join(summary_parts) if summary_parts else "板块资金流动平稳"

        # Rotation info
        rotation_text = ""
        if rotation.get("rotating_in") or rotation.get("rotating_out"):
            rot_parts: list[str] = []
            for r in rotation.get("rotating_in", [])[:3]:
                rot_parts.append(f"{r['sector']}加速流入(排名↑{r['rank_improvement']})")
            for r in rotation.get("rotating_out", [])[:3]:
                rot_parts.append(f"{r['sector']}加速流出(排名↓{r['rank_decline']})")
            rotation_text = "\n\n### 板块轮动\n" + "、".join(rot_parts)

        content = (
            f"## 市场脉搏 · {time_label}\n\n"
            "### 资金流入板块 Top 5\n" + "\n".join(inflow_lines) + "\n\n"
            "### 资金流出板块 Top 5\n" + "\n".join(outflow_lines) + rotation_text
        )

        # Risk note based on concentration
        if inflow_sectors and inflow_sectors[0]["net_inflow"] > 10:
            risk_note = f"主力资金高度集中于{inflow_sectors[0]['sector']}，注意追高风险"
        elif not inflow_sectors:
            risk_note = "全市场板块资金净流出，谨慎操作"
        else:
            risk_note = "板块轮动正常，关注资金持续性"

        # Action advice
        if inflow_sectors and inflow_sectors[0]["change_pct"] > 2:
            action_advice = f"可关注{inflow_sectors[0]['sector']}板块龙头股机会"
        elif outflow_sectors and abs(outflow_sectors[0]["change_pct"]) > 2:
            action_advice = f"规避{outflow_sectors[0]['sector']}板块，等待企稳"
        else:
            action_advice = "观望为主，等待明确方向"

        store = MessageStore()
        msg_id = store.create_message(
            msg_type="market_pulse",
            title=title,
            summary=summary,
            content=content,
            action_advice=action_advice,
            risk_note=risk_note,
            priority="medium",
            raw_data_ref={
                "inflow_top5": inflow_sectors,
                "outflow_top5": [
                    {"sector": s["sector"], "net_inflow": s["net_inflow"]}
                    for s in outflow_sectors
                ],
                "rotation": rotation,
            },
            data_freshness="realtime",
            data_collected_at=now.isoformat(),
        )

        # Publish to Redis for Discord push
        payload = {
            "type": "market_pulse",
            "title": title,
            "summary": summary,
            "priority": "medium",
            "action_advice": action_advice,
            "risk_note": risk_note,
        }
        redis_client.publish(
            "assistant:messages",
            json.dumps(payload, ensure_ascii=False),
        )

        logger.info(
            "Sector pulse #%d: %d inflow, %d outflow sectors, %d rotating",
            msg_id,
            len(inflow_sectors),
            len(outflow_sectors),
            len(rotation.get("rotating_in", []))
            + len(rotation.get("rotating_out", [])),
        )
        return {
            "status": "ok",
            "message_id": msg_id,
            "inflow_sectors": len(inflow_sectors),
            "outflow_sectors": len(outflow_sectors),
        }
    except Exception as exc:
        logger.error("Sector pulse failed: %s", exc)
        raise self.retry(exc=exc)


def _verify_high_severity_patterns(
    patterns: list[Any],
    minute_data: dict[str, Any],
    redis_client: Any,
) -> tuple[list[Any], int]:
    """LLM-verify patterns with severity >= 0.7.

    Patterns below 0.7 pass through unchanged. Patterns at or above 0.7
    are sent to PatternVerifier. If the LLM says a pattern is not genuine,
    it is removed from the list. If genuine, severity and action_advice
    may be adjusted.

    Returns:
        Tuple of (filtered_patterns, verified_count).
    """
    import asyncio

    from src.agent_loop.pattern_verifier import PatternVerifier
    from src.llm.router import LLMRouter

    high = [p for p in patterns if p.severity >= 0.7]
    low = [p for p in patterns if p.severity < 0.7]

    if not high:
        return patterns, 0

    try:
        router = LLMRouter()
    except Exception as exc:
        logger.warning("Cannot create LLMRouter for verification: %s", exc)
        return patterns, 0

    verifier = PatternVerifier(llm_router=router)
    portfolio_syms = _get_portfolio_symbols(redis_client)

    verified_patterns: list[Any] = []
    verified_count = 0

    # Run verification in an event loop
    loop: asyncio.AbstractEventLoop | None = None
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()

    async def _verify_all() -> None:
        nonlocal verified_count
        for p in high:
            # Build minute data summary for context
            bars = minute_data.get(p.symbol)
            summary = ""
            if bars is not None and not bars.empty:
                last_bars = bars.tail(6)
                lines: list[str] = []
                for _, row in last_bars.iterrows():
                    lines.append(
                        f"  {row.get('datetime', '?')} "
                        f"O={row.get('open', 0):.2f} "
                        f"H={row.get('high', 0):.2f} "
                        f"L={row.get('low', 0):.2f} "
                        f"C={row.get('close', 0):.2f} "
                        f"V={row.get('volume', 0):.0f}"
                    )
                summary = "\n".join(lines)

            pattern_dict = {
                "pattern_type": p.pattern_type,
                "severity": p.severity,
                "direction": p.direction,
                "description": p.description,
                "factors": p.factors or {},
            }

            result = await verifier.verify(
                pattern=pattern_dict,
                symbol=p.symbol,
                minute_data_summary=summary,
                portfolio_held=p.symbol in portfolio_syms,
            )
            verified_count += 1

            if not result.get("is_genuine", True):
                logger.info(
                    "Pattern rejected by LLM: %s %s (severity=%.2f) — %s",
                    p.symbol,
                    p.pattern_type,
                    p.severity,
                    result.get("reasoning", ""),
                )
                continue

            # Update pattern with LLM-adjusted values
            adjusted_severity = result.get("adjusted_severity", p.severity)
            p.severity = adjusted_severity

            # Store LLM advice in factors for downstream formatting
            llm_advice = result.get("action_advice", "")
            if llm_advice:
                if p.factors is None:
                    p.factors = {}
                p.factors["llm_action_advice"] = llm_advice
                p.factors["llm_reasoning"] = result.get("reasoning", "")
                p.factors["llm_verified"] = True

            verified_patterns.append(p)

    loop.run_until_complete(_verify_all())

    return low + verified_patterns, verified_count


@app.task(
    name="openclaw.tasks.intraday_pipeline.task_event_scan",
    bind=True,
    max_retries=1,
    soft_time_limit=60,
    time_limit=90,
)
def task_event_scan(self) -> dict[str, Any]:
    """Scan realtime quotes for significant events and route to research agents.

    Runs every 5 minutes during trading hours. Compares current quotes
    with cached previous quotes in Redis, publishes events via
    IntelligenceEventBus for immediate analysis by research agents.

    Detects:
    - Price spikes (|pct_change| > 3% with volume > 2x)
    - Limit-up events (pct_change >= 9.8%)
    """
    if not _should_execute("task_event_scan"):
        return {"status": "skipped", "reason": "non-trading"}

    try:
        import asyncio
        import json

        import redis

        from src.data.realtime import RealtimeQuoteManager
        from src.intelligence.event_bus import get_intelligence_event_bus
        from src.utils.config import load_config

        broker = (
            load_config("openclaw")
            .get("celery", {})
            .get("broker_url", "redis://redis:6379/0")
        )
        redis_client = redis.from_url(broker, decode_responses=True)

        # Get active symbols
        symbols = _get_active_symbols(redis_client)
        if not symbols:
            return {"status": "ok", "events": 0, "reason": "no_symbols"}

        # Fetch current quotes
        rtm = RealtimeQuoteManager()
        quotes_df = rtm.get_quotes(symbols)
        if quotes_df.empty:
            return {"status": "ok", "events": 0, "reason": "no_quotes"}

        # Convert DataFrame to dict keyed by symbol
        current_quotes: dict[str, dict] = {}
        for _, row in quotes_df.iterrows():
            sym = row.get("symbol", "")
            if sym:
                current_quotes[sym] = row.to_dict()

        # Load previous quotes from Redis
        prev_quotes: dict[str, dict] = {}
        prev_raw = redis_client.get("event_scan:prev_quotes")
        if prev_raw:
            try:
                prev_quotes = json.loads(prev_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        # Save current quotes as previous for next scan
        slim_quotes = {}
        for sym, q in current_quotes.items():
            slim_quotes[sym] = {
                "volume": q.get("volume"),
                "pct_change": q.get("pct_change"),
                "price": q.get("price"),
            }
        try:
            redis_client.set(
                "event_scan:prev_quotes",
                json.dumps(slim_quotes, default=str),
                ex=600,  # 10min TTL
            )
        except Exception as exc:
            logger.debug("Failed to cache prev quotes: %s", exc)

        # Run event detection via IntelligenceEventBus
        event_bus = get_intelligence_event_bus()

        # Ensure research coordinator is initialized (registers handlers)
        try:
            from src.intelligence.agents.research_coordinator import (
                get_research_coordinator,
            )

            get_research_coordinator()
        except Exception as exc:
            logger.debug("Research coordinator init skipped: %s", exc)

        # Run async event detection
        try:
            loop = asyncio.new_event_loop()
            events = loop.run_until_complete(
                event_bus.check_quotes_for_events(current_quotes, prev_quotes)
            )
            loop.close()
        except Exception as exc:
            logger.warning("Async event scan failed: %s", exc)
            events = []

        logger.info(
            "Event scan: %d symbols checked, %d events detected",
            len(current_quotes),
            len(events),
        )
        return {
            "status": "ok",
            "symbols_scanned": len(current_quotes),
            "events": len(events),
            "event_types": [e.event_type.value for e in events],
        }
    except Exception as exc:
        logger.error("Event scan failed: %s", exc)
        raise self.retry(exc=exc)


def _get_active_symbols(redis_client: Any) -> list[str]:
    """Get symbols that need intraday monitoring.

    Sources: current positions + today's recommendations + watchlist.
    """
    symbols: set[str] = set()
    try:
        # Held positions
        positions = redis_client.hgetall("portfolio:positions") or {}
        for sym in positions:
            symbols.add(sym)

        # Today's recommended symbols
        from datetime import datetime
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        rec_keys = redis_client.keys(f"rec:*:{today}:*") or []
        for key in rec_keys:
            parts = key.split(":")
            if len(parts) >= 4:
                symbols.add(parts[-1])

        # Watchlist
        watchlist = redis_client.smembers("watchlist:symbols") or set()
        symbols |= watchlist

        # v57.0: Market scanner top candidates
        scanner_key = f"scanner:candidates:{today}"
        try:
            top_candidates = redis_client.zrevrange(scanner_key, 0, 9)
            for member in top_candidates:
                import json as _json

                data = _json.loads(member)
                sym = data.get("symbol", "")
                if sym:
                    symbols.add(sym)
        except Exception:
            pass

    except Exception as exc:
        logger.debug("Failed to get active symbols: %s", exc)

    # Limit to 50 symbols max to avoid overloading
    return list(symbols)[:50]

"""Intelligence-driven portfolio analysis Celery task.

When new intel items match user portfolio/watchlist symbols, this task
performs LLM analysis per-symbol and stores structured reports.

Per PRD v25.0 FR-IA002: batch analysis with 4h cooldown dedup.
"""

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from openclaw.celery_app import app
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.intel_analysis_pipeline")

_CST = ZoneInfo("Asia/Shanghai")

NOTIFICATIONS_KEY = "notifications:alerts"
MAX_NOTIFICATIONS = 200
COOLDOWN_PREFIX = "intel_report:cooldown:"


def _get_redis():
    """Get a Redis client."""
    import redis

    config = load_config("openclaw")
    broker = config.get("celery", {}).get("broker_url", "redis://redis:6379/0")
    return redis.from_url(broker, decode_responses=True)


def _load_config() -> dict[str, Any]:
    """Load intel_analysis config with defaults."""
    try:
        cfg = load_config("intel_analysis")
        return cfg.get("intel_analysis", {})
    except Exception:
        return {}


def _load_portfolio_symbols() -> dict[str, dict[str, Any]]:
    """Load tracked symbols from SQLite portfolio and watchlist.

    Returns dict mapping symbol -> {name, cost_price?, shares?}.
    """
    symbols: dict[str, dict[str, Any]] = {}

    # Portfolio positions (SQLite)
    try:
        from src.web.services.portfolio_store import PortfolioStore

        for pos in PortfolioStore(capital_service=None).list_positions():
            sym = pos.get("symbol", "")
            if sym:
                symbols[sym] = {
                    "name": pos.get("name", sym),
                    "cost_price": pos.get("cost_price"),
                    "shares": pos.get("shares"),
                }
    except Exception as exc:
        logger.warning("Failed to read portfolio: %s", exc)

    # Watchlist (SQLite)
    try:
        from src.web.services.watchlist_service import WatchlistService

        for item in WatchlistService().list_all():
            code = item.get("symbol", "")
            name = item.get("name", "")
            if code and code not in symbols:
                symbols[code] = {"name": name}
    except Exception:
        pass

    return symbols


def _get_stock_name(symbol: str, tracked: dict[str, dict[str, Any]]) -> str:
    """Get display name for a symbol."""
    info = tracked.get(symbol, {})
    return info.get("name", symbol)


def _build_position_section(symbol: str, tracked: dict[str, dict[str, Any]]) -> str:
    """Build position context text for prompt."""
    info = tracked.get(symbol, {})
    cost = info.get("cost_price")
    shares = info.get("shares")
    if cost is not None and shares is not None:
        return (
            f"- 成本价: {cost}\n"
            f"- 持仓数量: {shares}股\n"
            "\n请结合持仓成本给出个性化建议和关键价位。"
        )
    return "（无持仓数据，position_context 输出 null）"


def _format_intel_items(items: list[dict[str, Any]]) -> str:
    """Format intel items for the prompt."""
    lines = []
    for i, item in enumerate(items[:10], 1):
        title = item.get("title", "")
        summary = item.get("summary", "")[:200]
        source = item.get("source_name", "")
        published = item.get("published_at", "")
        category = item.get("category", "")
        lines.append(
            f"{i}. [{category}] [{source}] {title}\n"
            f"   发布: {published}\n"
            f"   摘要: {summary}"
        )
    return "\n\n".join(lines) if lines else "无匹配情报"


@app.task(
    name="openclaw.tasks.intel_analysis_pipeline.task_intel_portfolio_analysis",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def task_intel_portfolio_analysis(
    self,
    matched: dict[str, list[str]],
    refresh_cycle: str,
) -> dict[str, Any]:
    """Analyze intel items matched to portfolio symbols.

    Args:
        matched: Mapping of symbol -> list of item_ids.
        refresh_cycle: Identifier for this refresh cycle.

    Returns:
        Summary dict with reports_created count.
    """
    config = _load_config()
    if not config.get("enabled", True):
        return {"status": "disabled", "reports_created": 0}

    max_reports = config.get("max_reports_per_cycle", 5)
    cooldown_hours = config.get("cooldown_hours", 4)
    min_items = config.get("min_items_per_symbol", 1)
    llm_config = config.get("llm", {})

    from src.intelligence_hub.info_store import InfoStore
    from src.intelligence_hub.report_store import IntelReportStore

    store = InfoStore()
    report_store = IntelReportStore()

    r = _get_redis()
    tracked = _load_portfolio_symbols()
    reports_created = 0

    for symbol, item_ids in matched.items():
        if reports_created >= max_reports:
            break

        # Cooldown check
        cooldown_key = f"{COOLDOWN_PREFIX}{symbol}"
        if r.exists(cooldown_key):
            logger.debug("Skipping %s — cooldown active", symbol)
            continue

        if len(item_ids) < min_items:
            continue

        # Load intel items
        items = store.get_items_by_ids(item_ids)
        if len(items) < min_items:
            continue

        try:
            report = _analyze_symbol(
                symbol=symbol,
                items=items,
                tracked=tracked,
                refresh_cycle=refresh_cycle,
                llm_config=llm_config,
            )
            if report:
                # Enrich with v34.0 intelligence modules
                report = _enrich_report(report, items)
                report_store.store(report)
                # Set cooldown
                r.setex(cooldown_key, int(cooldown_hours * 3600), "1")
                # Push notification
                _push_notification(r, report)
                reports_created += 1
                logger.info(
                    "Created report for %s (%s): %s",
                    symbol,
                    report.get("stock_name", ""),
                    report.get("action", ""),
                )

                # Populate knowledge graph with entities + relationships (v50.0 SS 6.4)
                _populate_knowledge_graph(symbol, report, items)

                # Process through Impact Engine for causal chain signals (v50.0 Gap 4)
                _run_impact_engine(items, symbol, report)

                # Publish to Redis Streams event bus (v50.0)
                try:
                    from src.event_bus.producers import publish_intel_event

                    publish_intel_event(
                        event_type="intel_report",
                        title=report.get("summary", "")[:120],
                        severity=report.get("confidence", 0.5),
                        sectors=[],
                        data={
                            "symbol": symbol,
                            "stock_name": report.get("stock_name", ""),
                            "action": report.get("action", ""),
                            "signal": report.get("signal", ""),
                            "report_id": report.get("id", ""),
                        },
                    )
                except Exception:
                    pass  # Never break the caller
        except Exception as exc:
            logger.error("Analysis failed for %s: %s", symbol, exc)

    logger.info(
        "Intel portfolio analysis complete: %d reports created", reports_created
    )
    return {"status": "ok", "reports_created": reports_created}


def _build_snapshot(
    symbol: str,
    stock_name: str,
    tracked: dict[str, dict[str, Any]],
) -> str:
    """Build a rich MarketSnapshot and serialize for LLM injection.

    Uses ContextBuilder with whatever modules are available.
    Falls back to minimal snapshot if builder fails.
    """
    import asyncio

    try:
        from src.agent_loop.market_snapshot import ContextBuilder

        # Initialize builder with available dependencies
        builder_kwargs: dict[str, Any] = {}

        # Try to get realtime quotes
        try:
            from src.data.realtime import RealtimeQuoteManager

            builder_kwargs["realtime"] = RealtimeQuoteManager()
        except Exception:
            pass

        # Try to get minute bar fetcher
        try:
            from src.data.minute_bar import MinuteBarFetcher

            builder_kwargs["minute_bar_fetcher"] = MinuteBarFetcher()
        except Exception:
            pass

        # Try to get VPIN
        try:
            from src.quant.vpin import VpinCalculator

            builder_kwargs["vpin_calculator"] = VpinCalculator()
        except Exception:
            pass

        # Try to get VWAP
        try:
            from src.quant.vwap_trigger import VwapTriggerEngine

            builder_kwargs["vwap_engine"] = VwapTriggerEngine()
        except Exception:
            pass

        # Try to get MTF
        try:
            from src.quant.multi_timeframe import MultiTimeframeEngine

            builder_kwargs["mtf_engine"] = MultiTimeframeEngine()
        except Exception:
            pass

        # Try to get reflexivity
        try:
            from src.agent_loop.reflexivity_detector import ReflexivityDetector

            builder_kwargs["reflexivity_detector"] = ReflexivityDetector()
        except Exception:
            pass

        # Try to get intraday patterns
        try:
            from src.agent_loop.intraday_patterns import IntradayPatternDetector

            builder_kwargs["pattern_detector"] = IntradayPatternDetector()
        except Exception:
            pass

        # Try to get alpha engine
        try:
            from src.quant.qlib_alpha import QlibAlphaEngine

            builder_kwargs["alpha_engine"] = QlibAlphaEngine()
        except Exception:
            pass

        # Try to get macro flow
        try:
            from src.data.macro_flow_fetcher import MacroFlowFetcher

            builder_kwargs["macro_flow_fetcher"] = MacroFlowFetcher()
        except Exception:
            pass

        # Try to get info store
        try:
            from src.intelligence_hub.info_store import InfoStore

            builder_kwargs["info_store"] = InfoStore()
        except Exception:
            pass

        # Try to get sentiment cycle
        try:
            from src.agent_loop.sentiment_cycle import SentimentCycleDetector

            builder_kwargs["sentiment_detector"] = SentimentCycleDetector()
        except Exception:
            pass

        # Try to get portfolio store
        try:
            from src.web.services.portfolio_store import PortfolioStore

            builder_kwargs["portfolio_store"] = PortfolioStore(capital_service=None)
        except Exception:
            pass

        # Global intelligence context (GDELT tone, FRED macro, Polymarket risk)
        try:
            from src.data.gdelt_fetcher import GdeltFetcher

            builder_kwargs["gdelt_fetcher"] = GdeltFetcher()
        except Exception:
            pass

        try:
            from src.data.fred_fetcher import FredFetcher

            builder_kwargs["fred_fetcher"] = FredFetcher()
        except Exception:
            pass

        try:
            from src.data.polymarket_fetcher import PolymarketFetcher

            builder_kwargs["polymarket_fetcher"] = PolymarketFetcher()
        except Exception:
            pass

        # v54: Corporate event sources
        for kwarg_name, module_path, class_name in [
            ("cninfo_fetcher", "src.data.cninfo_announcement", "CninfoAnnouncementFetcher"),
            ("lockup_fetcher", "src.data.lockup_expiry", "LockupExpiryFetcher"),
            ("block_trade_fetcher", "src.data.block_trade", "BlockTradeFetcher"),
            ("insider_fetcher", "src.data.insider_activity", "InsiderActivityFetcher"),
            ("earnings_fetcher", "src.data.earnings_forecast", "EarningsForecastFetcher"),
        ]:
            try:
                mod = __import__(module_path, fromlist=[class_name])
                builder_kwargs[kwarg_name] = getattr(mod, class_name)()
            except Exception:
                pass

        builder = ContextBuilder(**builder_kwargs)

        # Run async builder in sync context (Celery tasks are synchronous)
        loop = asyncio.new_event_loop()
        try:
            snapshot = loop.run_until_complete(builder.build(symbol, stock_name))
            return snapshot.serialize_for_llm()
        finally:
            loop.close()

    except Exception as exc:
        logger.warning(
            "Failed to build full snapshot for %s: %s — using minimal",
            symbol,
            exc,
        )
        # Fallback: build minimal snapshot from tracked data
        return _build_minimal_snapshot(symbol, stock_name, tracked)


def _build_minimal_snapshot(
    symbol: str,
    stock_name: str,
    tracked: dict[str, dict[str, Any]],
) -> str:
    """Fallback minimal snapshot when ContextBuilder fails."""
    from src.agent_loop.market_snapshot import MarketSnapshot

    info = tracked.get(symbol, {})
    snap = MarketSnapshot(
        symbol=symbol,
        name=stock_name,
        snapshot_time=datetime.now(_CST),
        cost_price=info.get("cost_price"),
        position_shares=info.get("shares"),
    )
    return snap.serialize_for_llm()


def _analyze_symbol(
    *,
    symbol: str,
    items: list[dict[str, Any]],
    tracked: dict[str, dict[str, Any]],
    refresh_cycle: str,
    llm_config: dict[str, Any],
) -> dict[str, Any] | None:
    """Run LLM analysis for a single symbol and return a report dict."""
    from src.llm.base import LLMMessage
    from src.llm.router import RoutingStrategy
    from src.prediction.prompts import PromptBuilderV2
    from src.web.dependencies import get_llm_gateway

    stock_name = _get_stock_name(symbol, tracked)

    # Build rich market snapshot (v52)
    snapshot_text = _build_snapshot(symbol, stock_name, tracked)

    # Use v52 context-driven prompts
    messages_raw = PromptBuilderV2.build_decision_prompt(
        snapshot_text=snapshot_text,
        stock_name=stock_name,
        symbol=symbol,
    )
    messages = [LLMMessage(role=m["role"], content=m["content"]) for m in messages_raw]

    router = get_llm_gateway()
    response = router.complete(
        messages=messages,
        caller="intel_analysis_pipeline.analyze_symbol",
        strategy=RoutingStrategy.QUALITY,
        max_tokens=llm_config.get("max_tokens", 2048),
        temperature=llm_config.get("temperature", 0.3),
        symbol=symbol,
        analysis_type="intel_portfolio_analysis",
    )

    data = _parse_response(response.text)
    if not data:
        return None

    # Map v52 schema fields to report format
    action = data.get("action", "hold")
    if action in ("buy", "add"):
        signal = "bullish"
    elif action in ("sell", "reduce"):
        signal = "bearish"
    else:
        signal = "neutral"

    report_id = str(uuid.uuid4())
    return {
        "id": report_id,
        "symbol": symbol,
        "stock_name": stock_name,
        "intel_item_ids": [it.get("item_id", "") for it in items],
        "refresh_cycle": refresh_cycle,
        "action": action,
        "signal": signal,
        "confidence": data.get("confidence", 0.5),
        "summary": data.get("headline", ""),
        "factors": [
            {"category": "综合", "description": r} for r in data.get("why", [])
        ],
        "position_context": None,
        "risk_warnings": data.get("risk", []),
        "outlook": data.get("next_step", ""),
        "reasoning": data.get("why", []),
        "intel_summary": "",
        "signal_quality": data.get("signal_quality", ""),
        "stop_loss": data.get("stop_loss"),
        "target": data.get("target"),
        "model_used": response.model,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "is_read": False,
    }


def _parse_response(text: str) -> dict[str, Any] | None:
    """Parse LLM JSON response."""
    import re

    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    json_str = match.group(1).strip() if match else text.strip()
    if not json_str.startswith("{"):
        match2 = re.search(r"\{[\s\S]*\}", json_str)
        if match2:
            json_str = match2.group(0)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        logger.warning("Failed to parse intel analysis response")
        return None


@app.task(
    name="openclaw.tasks.intel_analysis_pipeline.task_intel_macro_analysis",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def task_intel_macro_analysis(
    self,
    macro_events: list[dict[str, Any]],
    cycle: str,
) -> dict[str, Any]:
    """Generate macro intel report — not tied to specific stock codes.

    Triggered when MacroRadarService detects significant macro events.

    Args:
        macro_events: List of macro event dicts (titles, summaries, categories).
        cycle: Identifier for this analysis cycle.

    Returns:
        Summary dict with report creation status.
    """
    if not macro_events:
        return {"status": "no_events", "reports_created": 0}

    from src.data.global_market import GlobalMarketFetcher
    from src.intelligence_hub.report_store import IntelReportStore
    from src.llm.base import LLMMessage
    from src.llm.router import RoutingStrategy
    from src.prediction.prompts import PromptBuilderV2
    from src.web.dependencies import get_llm_gateway

    report_store = IntelReportStore()

    # Format macro events as snapshot text
    events_text_lines = []
    for i, event in enumerate(macro_events[:10], 1):
        title = event.get("title", "")
        summary = event.get("summary", "")[:200]
        category = event.get("category", "")
        source = event.get("source_name", "")
        events_text_lines.append(f"{i}. [{category}] [{source}] {title}\n   {summary}")
    events_text = "\n\n".join(events_text_lines) if events_text_lines else "无宏观事件"

    # Fetch global market data
    global_data = "无全球市场数据"
    try:
        fetcher = GlobalMarketFetcher()
        snapshot = fetcher.fetch_global_snapshot()
        parts = []
        for idx in snapshot.get("indices", []):
            name = idx.get("name", "")
            pct = idx.get("pct_change")
            if name and pct is not None:
                parts.append(f"{name}: {pct:+.2f}%")
        for com in snapshot.get("commodities", []):
            name = com.get("name", "")
            pct = com.get("pct_change")
            if name and pct is not None:
                parts.append(f"{name}: {pct:+.2f}%")
        if parts:
            global_data = " | ".join(parts)
    except Exception:
        logger.warning("Failed to fetch global market data for macro analysis")

    # Use v52 context-driven prompts
    messages_raw = PromptBuilderV2.build_macro_prompt(
        macro_snapshot_text=events_text,
        global_data_text=global_data,
    )
    messages = [LLMMessage(role=m["role"], content=m["content"]) for m in messages_raw]

    try:
        router = get_llm_gateway()
        response = router.complete(
            messages=messages,
            caller="intel_analysis_pipeline.macro_analysis",
            strategy=RoutingStrategy.QUALITY,
            max_tokens=2048,
            temperature=0.3,
            analysis_type="macro_analysis",
        )

        data = _parse_response(response.text)
        if not data:
            return {"status": "parse_failed", "reports_created": 0}

        # Map v52 macro schema to report format
        action_raw = data.get("action", "watch")
        if isinstance(action_raw, str):
            action_val = action_raw[:10]
        else:
            action_val = "watch"

        report_id = str(uuid.uuid4())
        report = {
            "id": report_id,
            "symbol": "MACRO",
            "stock_name": "宏观事件分析",
            "intel_item_ids": [],
            "refresh_cycle": cycle,
            "action": action_val,
            "signal": data.get("signal", "neutral"),
            "confidence": data.get("confidence", 0.5),
            "summary": data.get("headline", ""),
            "factors": [],
            "position_context": None,
            "risk_warnings": data.get("risk", []),
            "outlook": data.get("transmission", ""),
            "reasoning": [],
            "intel_summary": "",
            "signal_quality": data.get("signal_quality", ""),
            "sectors_bullish": data.get("sectors_bullish", []),
            "sectors_bearish": data.get("sectors_bearish", []),
            "model_used": response.model,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "is_read": False,
        }

        report_store.store(report)

        # Process macro events through Impact Engine (v50.0 Gap 4)
        _run_impact_engine(macro_events, "MACRO", report)

        # Push notification
        r = _get_redis()
        _push_notification(r, report)

        logger.info("Macro analysis report created: %s", report_id)
        return {"status": "ok", "reports_created": 1, "report_id": report_id}

    except Exception as exc:
        logger.error("Macro analysis failed: %s", exc)
        return {"status": "error", "reports_created": 0, "error": str(exc)}


def _enrich_report(
    report: dict[str, Any], items: list[dict[str, Any]]
) -> dict[str, Any]:
    """Enrich a report with v34.0 intelligence module outputs.

    Adds impact chains, Munger checklist, constraint check, and
    relevance scores to the report without replacing LLM analysis.
    """
    symbol = report.get("symbol", "")
    if not symbol or symbol == "MACRO":
        return report

    # 1. Impact chain analysis from intel headlines
    try:
        from src.intelligence.impact_chain import ImpactChainEngine

        engine = ImpactChainEngine()
        combined_text = " ".join(it.get("title", "") for it in items[:5])
        chains = engine.build_chains_for_event(combined_text)
        if chains:
            impacts = engine.find_stock_impact(symbol, chains)
            if impacts:
                report["impact_chains"] = impacts[:3]
                # Inject impact direction into risk_warnings if negative
                for imp in impacts:
                    if imp["direction"] == "negative":
                        report.setdefault("risk_warnings", []).append(
                            f"影响链: {imp['cause']}→{imp['effect']} ({imp['magnitude']})"
                        )
    except Exception as exc:
        logger.debug("Impact chain enrichment failed for %s: %s", symbol, exc)

    # 2. Trading constraint check
    try:
        from src.trading.constraints import TradingConstraintsEngine

        constraint_engine = TradingConstraintsEngine()
        result = constraint_engine.check(symbol, report.get("stock_name", ""))
        if not result.passed:
            report["constraint_violations"] = [
                {"rule": v.rule, "severity": v.severity, "message": v.message}
                for v in result.violations
            ]
            if result.blocked:
                report["action"] = "hold"
                report.setdefault("risk_warnings", []).append(
                    "交易约束阻断: " + result.violations[0].message
                )
    except Exception as exc:
        logger.debug("Constraint check failed for %s: %s", symbol, exc)

    # 3. Munger checklist (lightweight, no LLM)
    try:
        from src.intelligence.munger_checklist import MungerChecklist

        checklist = MungerChecklist()
        cl_result = checklist.run_checklist(
            symbol=symbol,
            name=report.get("stock_name", ""),
        )
        if not cl_result.overall_passed:
            blockers = [c.finding for c in cl_result.checks if c.severity == "block"]
            if blockers:
                report["munger_blockers"] = blockers
                report.setdefault("risk_warnings", []).extend(
                    f"芒格检查: {b}" for b in blockers
                )
    except Exception as exc:
        logger.debug("Munger checklist failed for %s: %s", symbol, exc)

    return report


def _populate_knowledge_graph(
    symbol: str,
    report: dict[str, Any],
    items: list[dict[str, Any]],
) -> None:
    """Write entities and relationships to the knowledge graph.

    Adds the stock, any related events, and affected_by / belongs_to edges.
    Never raises — all errors are logged and swallowed.
    """
    try:
        from src.web.dependencies import get_knowledge_graph

        kg = get_knowledge_graph()
    except Exception:
        return

    stock_name = report.get("stock_name", symbol)

    try:
        # Upsert the stock node
        kg.add_stock(symbol, name=stock_name)

        # Add event nodes from intel items and link to the stock
        for item in items[:10]:
            item_id = item.get("item_id", "")
            if not item_id:
                continue
            title = item.get("title", "")
            category = item.get("category", "news")
            severity = report.get("confidence", 0.5)
            kg.add_event(
                event_id=item_id,
                title=title,
                event_type=category,
                severity=severity,
            )
            kg.add_edge(
                source=symbol,
                target=item_id,
                relation="affected_by",
                confidence=severity,
                decay_rate=0.05,
            )

        # If report includes sector info, add belongs_to edges
        sectors_bullish = report.get("sectors_bullish", [])
        sectors_bearish = report.get("sectors_bearish", [])
        for sector in sectors_bullish + sectors_bearish:
            if isinstance(sector, str) and sector:
                kg.add_sector(sector, name=sector)
                kg.add_edge(
                    source=symbol,
                    target=sector,
                    relation="belongs_to",
                    confidence=1.0,
                )

        logger.debug("KG updated for %s: %d events linked", symbol, len(items[:10]))
    except Exception as exc:
        logger.debug("Knowledge graph population failed for %s: %s", symbol, exc)


def _run_impact_engine(
    items: list[dict[str, Any]],
    symbol: str,
    report: dict[str, Any],
) -> None:
    """Process intel items through the EventImpactEngine and publish resulting signals.

    For each item, constructs a causal chain via template matching. Resulting
    signals with confidence > 0.3 are published to events:signal. Significant
    impact chains (max confidence > 0.5) also create a MessageStore entry.

    Never raises — all errors are logged and swallowed.
    """
    try:
        from src.web.dependencies import get_impact_engine
    except Exception:
        return

    try:
        engine = get_impact_engine()
    except Exception as exc:
        logger.debug("ImpactEngine unavailable: %s", exc)
        return

    all_signals: list[dict[str, Any]] = []
    for item in items[:5]:
        event = {
            "title": item.get("title", ""),
            "summary": item.get("summary", ""),
            "confidence": item.get("confidence", report.get("confidence", 0.6)),
            "sectors": item.get("sectors", []),
            "event_id": item.get("item_id", ""),
        }
        try:
            signals = engine.process_event(event)
            all_signals.extend(signals)
        except Exception as exc:
            logger.debug("ImpactEngine.process_event failed: %s", exc)

    if not all_signals:
        return

    # Publish tradeable signals to events:signal
    try:
        from src.event_bus.producers import publish_signal_detected

        for sig in all_signals:
            if sig.get("confidence", 0) < 0.3:
                continue
            publish_signal_detected(
                symbol=sig.get("symbol", symbol),
                direction=sig.get("direction", "neutral"),
                source=sig.get("source", "impact_chain"),
                confidence=sig.get("confidence", 0.5),
                reason=sig.get("metadata", {}).get("impact", ""),
            )
    except Exception as exc:
        logger.debug("Failed to publish impact signals: %s", exc)

    # Create MessageStore entry for significant impact chains
    max_conf = max((s.get("confidence", 0) for s in all_signals), default=0)
    if max_conf > 0.5:
        try:
            from src.web.services.message_store import MessageStore

            store = MessageStore()
            chain_summary = "; ".join(
                f"{s['metadata'].get('impact', '')}({s.get('direction', '')})"
                for s in all_signals[:5]
                if s.get("metadata")
            )
            stock_name = report.get("stock_name", symbol)
            store.create_message(
                symbol=symbol,
                msg_type="impact_chain",
                title=f"事件影响链：{stock_name}",
                summary=chain_summary[:200] if chain_summary else "多维度事件影响",
                action_advice=report.get("outlook", ""),
                priority="high" if max_conf > 0.7 else "medium",
            )
        except Exception as exc:
            logger.debug("Failed to store impact chain message: %s", exc)

    logger.info(
        "ImpactEngine processed %d items → %d signals for %s (max_conf=%.2f)",
        len(items[:5]),
        len(all_signals),
        symbol,
        max_conf,
    )


def _push_notification(r: Any, report: dict[str, Any]) -> None:
    """Push a notification for a new report."""
    try:
        signal_emoji = {"bullish": "📈", "bearish": "📉"}.get(
            report.get("signal", ""), "📊"
        )
        notification = {
            "id": str(uuid.uuid4()),
            "type": "intel_report",
            "title": f"{signal_emoji} {report.get('stock_name', '')}({report['symbol']}) 情报分析",
            "summary": report.get("summary", "")[:100],
            "symbol": report["symbol"],
            "timestamp": datetime.now(UTC).isoformat(),
            "read": False,
            "action": "/reports",
        }
        r.lpush(
            NOTIFICATIONS_KEY,
            json.dumps(notification, ensure_ascii=False),
        )
        r.ltrim(NOTIFICATIONS_KEY, 0, MAX_NOTIFICATIONS - 1)
    except Exception as exc:
        logger.warning("Failed to push intel report notification: %s", exc)

"""Always-on investment daemon — persistent asyncio process.

Replaces the 10-minute cron heartbeat with a continuous event loop that:
1. Listens to Redis Streams (events:market, events:signal, events:news) ~100ms polling
2. Runs quick_trade heartbeat every 3 minutes for portfolio status
3. Runs deep analysis hourly (portfolio_watch at :00, opportunity_hunt at :30)
4. Routes events by severity to appropriate HeartbeatAgent missions

Architecture:
    Three concurrent asyncio tasks form the daemon's spine:
    - _heartbeat_loop: 3-minute quick_trade + hourly deep missions
    - _event_loop: Redis Streams consumer with severity-based routing
    - _scheduler_loop: time-triggered missions (morning_plan, decision_window, close_review)

    All mission execution delegates to HeartbeatAgent (no reinvention).
    AgentState persists across heartbeats via Redis.
    KillSwitch checked before every action.
    Graceful shutdown on SIGTERM/SIGINT.
"""

from __future__ import annotations

import asyncio
import json
import signal
import threading
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.utils.logger import get_logger

logger = get_logger("openclaw.daemon.always_on_agent")

_CST = ZoneInfo("Asia/Shanghai")

# ---------------------------------------------------------------------------
# Timing constants
# ---------------------------------------------------------------------------
HEARTBEAT_INTERVAL_S = 180  # 3 minutes
EVENT_POLL_INTERVAL_S = 0.1  # 100ms
SCHEDULER_CHECK_INTERVAL_S = 30  # 30 seconds

# Trading hours window (CST) — daemon is active 08:00-15:55
ACTIVE_START_HOUR = 8
ACTIVE_START_MIN = 0
ACTIVE_END_HOUR = 15
ACTIVE_END_MIN = 55

# Event routing — severity thresholds
HELD_Z_THRESHOLD = 2.0
WATCHLIST_Z_THRESHOLD = 2.5
SCANNER_CONFIDENCE_THRESHOLD = 0.7

# Rate limiting
MAX_EVENT_SESSIONS_PER_HOUR = 15
RATE_LIMIT_KEY = "daemon:event_sessions:hourly"

# Streams to consume
EVENT_STREAMS = ["events:market", "events:signal", "events:news"]
CONSUMER_GROUP = "always_on_daemon"
CONSUMER_NAME = "daemon-main"


def _now_cst() -> datetime:
    """Return current time in Asia/Shanghai."""
    return datetime.now(_CST)


def _is_active_window(now: datetime | None = None) -> bool:
    """Check if we are within the daemon's active trading window.

    Active window: 08:00-15:55 CST on weekdays.
    """
    now = now or _now_cst()
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    start = ACTIVE_START_HOUR * 60 + ACTIVE_START_MIN
    end = ACTIVE_END_HOUR * 60 + ACTIVE_END_MIN
    return start <= t <= end


def _is_trading_day() -> bool:
    """Check if today is a trading day using TradingCalendar."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.is_trading_day()
    except Exception:
        now = _now_cst()
        return now.weekday() < 5


# ---------------------------------------------------------------------------
# Singleton agent + dependencies
# ---------------------------------------------------------------------------

_agent_singleton = None
_agent_lock = threading.Lock()


def _get_heartbeat_agent():
    """Lazy-build HeartbeatAgent with full dependency injection.

    Reuses the same pattern as openclaw/tasks/heartbeat.py — singleton
    with thread-safe double-check locking.
    """
    global _agent_singleton
    if _agent_singleton is not None:
        return _agent_singleton

    with _agent_lock:
        if _agent_singleton is not None:
            return _agent_singleton

        from src.agent_loop.heartbeat_agent import HeartbeatAgent
        from src.llm.gateway import LLMGateway
        from src.llm.router import LLMRouter
        from src.web.dependencies import (
            get_capital_service,
            get_global_market_fetcher,
            get_portfolio_store,
            get_realtime_quote_manager,
        )
        from src.web.services.message_store import MessageStore
        from src.web.services.tool_registry import ToolRegistry

        gateway = LLMGateway(LLMRouter())

        registry = ToolRegistry()
        deps: dict[str, Any] = {
            "realtime_quote_manager": get_realtime_quote_manager(),
            "global_market_fetcher": get_global_market_fetcher(),
            "capital_service": get_capital_service(),
        }
        # Optional deps — degrade gracefully
        optional = [
            ("stock_service", "get_stock_service"),
            ("stock_registry", "get_stock_registry"),
            ("trading_calendar", "get_trading_calendar"),
            ("trend_news_aggregator", "get_trend_news_aggregator"),
            ("concept_board_service", "get_concept_board_service"),
            ("concept_analyzer", "get_concept_analyzer"),
            ("cross_market_analyzer", "get_cross_market_analyzer"),
            ("portfolio_service", "get_portfolio_service"),
            ("trade_service", "get_trade_service"),
            ("prediction_service", "get_prediction_service"),
            ("advisor_service", "get_advisor_service"),
        ]
        for name, getter in optional:
            try:
                from src.web import dependencies

                deps[name] = getattr(dependencies, getter)()
            except Exception:
                logger.warning("Optional dep '%s' failed to load", name)
        registry.register_all(deps)

        # SAFETY: Remove trade execution tools from autonomous agent.
        # Agent must push decisions to Discord for user to execute manually.
        # It must NEVER execute trades directly.
        # NOTE: record_manual_trade is ALLOWED — it only syncs trades the
        # user has already executed. Without it, the agent can't track the
        # user's actual portfolio (v64 over-blocked this causing stale data).
        _BLOCKED_TOOLS = {"execute_trade"}
        for tool_name in _BLOCKED_TOOLS:
            if tool_name in registry._tools:
                del registry._tools[tool_name]
                logger.info("Blocked tool '%s' from autonomous agent", tool_name)

        _agent_singleton = HeartbeatAgent(
            gateway=gateway,
            tool_registry=registry,
            portfolio_store=get_portfolio_store(),
            capital_service=get_capital_service(),
            message_store=MessageStore(),
            quote_manager=get_realtime_quote_manager(),
            global_market_fetcher=get_global_market_fetcher(),
        )

        # Register decision expression tools (submit_buy/sell/hold)
        # These need DecisionHandler + HeartbeatAgent refs, so registered
        # here not in register_all()
        registry._register_decision_tools(
            decision_handler=_agent_singleton._decision_handler,
            agent=_agent_singleton,
        )

        # Seed thesis for existing positions that predate the thesis system
        try:
            _redis = _get_redis()
            if _redis and not _redis.exists("thesis:002688"):
                _redis.setex(
                    "thesis:002688",
                    30 * 86400,
                    json.dumps(
                        {
                            "entry_price": 6.14,
                            "stop_loss": 5.90,
                            "target_price": 6.48,
                            "summary": "趋势刚启动，TrendHunter 推荐 (2026-04-02)",
                            "created_at": "2026-04-02T06:21:00",
                        }
                    ),
                )
                logger.info("Seeded thesis for 002688 (pre-existing position)")
        except Exception:
            pass

        logger.info("HeartbeatAgent initialized with %d tools", len(deps))
        return _agent_singleton


def _get_redis():
    """Get a Redis client for direct operations."""
    try:
        from src.web.dependencies import get_redis

        return get_redis()
    except Exception:
        return None


def _get_kill_switch():
    """Get the KillSwitch instance."""
    try:
        from src.web.dependencies import get_kill_switch

        return get_kill_switch()
    except Exception:
        from src.trading.kill_switch import KillSwitch

        return KillSwitch(redis_client=_get_redis())


def _get_held_symbols() -> set[str]:
    """Get currently held stock symbols from portfolio."""
    try:
        from src.web.dependencies import get_portfolio_store

        ps = get_portfolio_store()
        if ps:
            positions = ps.list_positions()
            return {p.get("symbol", "") for p in positions if p.get("symbol")}
    except Exception:
        pass
    return set()


# ---------------------------------------------------------------------------
# AlwaysOnDaemon
# ---------------------------------------------------------------------------


class AlwaysOnDaemon:
    """Persistent asyncio daemon that replaces cron-based heartbeat.

    Three concurrent loops run inside a single asyncio event loop:
    - Heartbeat loop (3min quick_trade + hourly deep analysis)
    - Event loop (Redis Streams consumer, 100ms poll)
    - Scheduler loop (time-triggered missions: morning_plan, decision_window, close_review)

    Args:
        heartbeat_interval: Seconds between quick_trade heartbeats.
        event_poll_interval: Seconds between Redis Streams polls.
    """

    def __init__(
        self,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_S,
        event_poll_interval: float = EVENT_POLL_INTERVAL_S,
    ) -> None:
        self._heartbeat_interval = heartbeat_interval
        self._event_poll_interval = event_poll_interval
        self._shutdown_event = asyncio.Event()
        self._kill_switch = _get_kill_switch()
        self._redis = _get_redis()
        self._executed_today: set[str] = set()
        self._last_date: str = ""
        self._pnl_tracker: Any | None = None
        self._event_correlator: Any | None = None
        self._stats: dict[str, int] = {
            "heartbeats": 0,
            "events_processed": 0,
            "missions_run": 0,
            "pnl_updates": 0,
            "pnl_alerts": 0,
            "correlation_patterns": 0,
            "errors": 0,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the daemon — runs until SIGTERM or shutdown."""
        logger.info(
            "AlwaysOnDaemon starting — heartbeat=%ds, event_poll=%.1fs",
            self._heartbeat_interval,
            self._event_poll_interval,
        )

        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal, sig)

        tasks = [
            asyncio.create_task(self._heartbeat_loop(), name="heartbeat"),
            asyncio.create_task(self._event_loop(), name="events"),
            asyncio.create_task(self._scheduler_loop(), name="scheduler"),
        ]

        logger.info("Daemon running — 3 loops active")

        # Wait for shutdown signal
        await self._shutdown_event.wait()

        logger.info("Shutdown signal received — cancelling tasks")
        for task in tasks:
            task.cancel()

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for task, result in zip(tasks, results):
            if isinstance(result, Exception) and not isinstance(
                result, asyncio.CancelledError
            ):
                logger.error("Task %s failed: %s", task.get_name(), result)

        logger.info(
            "Daemon stopped — stats: %s",
            json.dumps(self._stats, default=str),
        )

    def _handle_signal(self, sig: signal.Signals) -> None:
        """Handle SIGTERM/SIGINT for graceful shutdown."""
        logger.info("Received %s — initiating graceful shutdown", sig.name)
        self._shutdown_event.set()

    # ------------------------------------------------------------------
    # Pre-action checks
    # ------------------------------------------------------------------

    def _preflight_ok(self) -> bool:
        """Check kill switch and trading day before any action.

        Returns:
            True if safe to proceed, False if blocked.
        """
        if self._kill_switch.is_active():
            logger.warning("KillSwitch active — skipping action")
            return False
        if not _is_trading_day():
            return False
        if not _is_active_window():
            return False
        return True

    def _reset_daily_state(self) -> None:
        """Reset once-per-day trackers at date boundary."""
        today = _now_cst().strftime("%Y%m%d")
        if today != self._last_date:
            self._executed_today.clear()
            self._last_date = today
            logger.info("New trading day %s — daily state reset", today)

    def _get_pnl_tracker(self):
        """Lazy-load PnLTracker singleton."""
        if self._pnl_tracker is None:
            try:
                from src.trading.pnl_tracker import PnLTracker

                self._pnl_tracker = PnLTracker(redis_client=self._redis)
            except Exception:
                logger.debug("PnLTracker unavailable", exc_info=True)
        return self._pnl_tracker

    def _get_event_correlator(self):
        """Lazy-load EventCorrelator singleton."""
        if self._event_correlator is None:
            try:
                from src.agent_loop.event_correlator import EventCorrelator

                self._event_correlator = EventCorrelator()
            except Exception:
                logger.debug("EventCorrelator unavailable", exc_info=True)
        return self._event_correlator

    # ------------------------------------------------------------------
    # Loop 1: Heartbeat (3-min quick_trade + hourly deep)
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Run quick_trade every 3 min. Multi-agent deep analysis at :30."""
        logger.info("Heartbeat loop started (interval=%ds)", self._heartbeat_interval)
        while not self._shutdown_event.is_set():
            try:
                self._reset_daily_state()
                if self._preflight_ok():
                    # IRON RULE: check stop-losses BEFORE any LLM call
                    # This is code-level execution, not LLM decision
                    await self._auto_stop_loss()

                    now = datetime.now(_CST)
                    # :30-:34 → multi-agent deep analysis (Analyst→PM→Risk)
                    if 30 <= now.minute < 35 and self._stats["heartbeats"] > 0:
                        await self._run_multi_agent_analysis("hourly_deep")
                    else:
                        # All other slots → fast HeartbeatAgent (quick_trade)
                        agent = _get_heartbeat_agent()
                        result = await agent.run_heartbeat()
                        self._stats["heartbeats"] += 1
                        mission = result.get("mission", "unknown")
                        logger.info(
                            "Heartbeat #%d [%s] — %d decisions, %.1fs, $%.4f",
                            self._stats["heartbeats"],
                            mission,
                            result.get("decisions", 0),
                            result.get("duration_seconds", 0),
                            result.get("cost", 0),
                        )

                    # P&L price update + alert check (piggybacks on 3-min heartbeat)
                    await self._update_pnl_and_alert()

                    # Thesis expiry/invalidation check → auto sell_signal
                    await self._check_thesis_invalidations()
            except Exception:
                self._stats["errors"] += 1
                logger.exception("Heartbeat loop error")

            # Sleep with shutdown awareness
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._heartbeat_interval,
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Normal timeout — continue loop

    async def _auto_stop_loss(self) -> None:
        """Code-level stop-loss enforcement — NO LLM involved.

        Checks each position against its original thesis stop_loss.
        If current price <= thesis stop → push CRITICAL sell_signal
        directly to Discord. This runs BEFORE any LLM heartbeat.

        Iron rule: 止损是代码执行，不是 LLM 决策。
        """
        if not self._redis:
            return
        try:
            from src.data.realtime import RealtimeQuoteManager
            from src.web.dependencies import get_portfolio_store
            from src.web.services.message_store import MessageStore

            ps = get_portfolio_store()
            if not ps:
                return
            positions = ps.list_positions()
            if not positions:
                return

            mgr = RealtimeQuoteManager()
            loop = asyncio.get_running_loop()

            for p in positions:
                sym = p.get("symbol", "")
                if not sym:
                    continue

                raw = self._redis.get(f"thesis:{sym}")
                if not raw:
                    continue

                thesis = json.loads(raw)
                thesis_sl = float(thesis.get("stop_loss") or 0)
                if not thesis_sl:
                    continue

                # Get live price (sync call → run in executor)
                q = await loop.run_in_executor(None, mgr.get_single_quote, sym)
                if not q:
                    continue

                current = float(q.get("price", 0) or 0)
                if not current or current > thesis_sl:
                    continue

                # STOP-LOSS TRIGGERED — push CRITICAL sell directly
                name = p.get("name", sym)
                entry = float(thesis.get("entry_price") or 0)
                pnl_pct = ((current - entry) / entry * 100) if entry else 0

                logger.warning(
                    "🚨 AUTO STOP-LOSS: %s (%s) current=%.2f <= "
                    "thesis_sl=%.2f (pnl=%.1f%%)",
                    sym,
                    name,
                    current,
                    thesis_sl,
                    pnl_pct,
                )

                # Push directly to MessageStore + Redis pub/sub
                ms = MessageStore()
                msg_id = ms.create_message(
                    symbol=sym,
                    msg_type="sell_signal",
                    title=f"🚨 止损自动执行 {name}",
                    summary=(
                        f"止损触发: {name} 现价{current:.2f} "
                        f"<= 止损{thesis_sl:.2f} "
                        f"(亏损{pnl_pct:.1f}%)。"
                        f"按原始计划执行止损，不犹豫。"
                    ),
                    content=(
                        f"原始买入价: {entry:.2f}\n"
                        f"原始止损价: {thesis_sl:.2f}\n"
                        f"当前价: {current:.2f}\n"
                        f"亏损: {pnl_pct:.1f}%"
                    ),
                    priority="critical",
                    action_advice=f"立即卖出 {name} 全部持仓",
                    risk_note="止损铁律：设了就执行",
                    stock_recommendations=json.dumps(
                        [
                            {
                                "action": "sell",
                                "symbol": sym,
                                "name": name,
                                "shares": p.get("shares", 0),
                                "stop_loss": thesis_sl,
                                "confidence": 0.95,
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    raw_data_ref={
                        "source": "auto_stop_loss",
                        "thesis_sl": thesis_sl,
                        "current": current,
                    },
                    data_freshness="realtime",
                    data_collected_at=datetime.now(_CST).isoformat(),
                )

                # Publish to Redis for Discord push
                self._redis.publish(
                    "assistant:messages",
                    json.dumps(
                        {
                            "type": "sell_signal",
                            "symbol": sym,
                            "name": name,
                            "action": "sell",
                            "shares": p.get("shares", 0),
                            "confidence": 0.95,
                            "title": f"🚨 止损自动执行 {name}",
                            "summary": (
                                f"止损触发: 现价{current:.2f} <= 止损{thesis_sl:.2f}"
                            ),
                            "priority": "critical",
                            "action_advice": "立即卖出全部持仓",
                            "risk_note": "止损铁律",
                            "message_id": msg_id,
                        },
                        ensure_ascii=False,
                    ),
                )

                # Remove thesis to avoid repeated alerts
                self._redis.delete(f"thesis:{sym}")
                logger.info("Auto stop-loss sell pushed for %s, thesis cleared", sym)

        except Exception:
            logger.exception("Auto stop-loss check failed")

    async def _update_pnl_and_alert(self) -> None:
        """Update P&L for tracked decisions and push alerts for breaches.

        Runs after each heartbeat (~3 min). Fetches current prices,
        recomputes P&L, and pushes CRITICAL alerts for stop-loss /
        target-price breaches via Discord.
        """
        tracker = self._get_pnl_tracker()
        if tracker is None:
            return

        try:
            # update_prices() is synchronous (network I/O) — run in thread pool
            loop = asyncio.get_running_loop()
            updated = await loop.run_in_executor(None, tracker.update_prices)
            if updated:
                self._stats["pnl_updates"] += 1
                logger.debug("P&L updated for %d tracked decisions", len(updated))

            # Check for breaches
            alerts = await loop.run_in_executor(None, tracker.check_alerts)
            if not alerts:
                return

            self._stats["pnl_alerts"] += len(alerts)
            from src.agent_loop.decision_handler import DecisionHandler
            from src.web.services.message_store import MessageStore

            handler = DecisionHandler(
                message_store=MessageStore(),
                redis_client=self._redis,
            )

            for alert in alerts:
                alert_type_label = (
                    "🚨 止损触发" if alert.alert_type == "stop_loss" else "🎯 止盈触发"
                )
                msg_type = (
                    "sell_signal" if alert.alert_type == "stop_loss" else "hold_update"
                )
                decision_dict = {
                    "type": msg_type,
                    "action": "sell" if alert.alert_type == "stop_loss" else "hold",
                    "symbol": alert.symbol,
                    "name": alert.symbol,
                    "confidence": 0.95,
                    "summary": (
                        f"{alert_type_label}: {alert.symbol} "
                        f"入场 ¥{alert.entry_price:.2f} → "
                        f"现价 ¥{alert.current_price:.2f} "
                        f"({alert.pnl_pct:+.1f}%)"
                    ),
                }

                from src.agent_loop.agent_state import AgentState

                state = (
                    AgentState.load(self._redis)
                    if self._redis
                    else AgentState(date=_now_cst().strftime("%Y%m%d"))
                )
                await handler.push_decisions([decision_dict], state, "pnl_tracker")

                # Remove the track after alert to avoid repeated alerts
                tracker.remove_track(alert.decision_id)

                logger.info(
                    "P&L alert pushed: %s %s @ %.2f (was %.2f, %+.1f%%)",
                    alert.alert_type,
                    alert.symbol,
                    alert.current_price,
                    alert.entry_price,
                    alert.pnl_pct,
                )
        except Exception:
            self._stats["errors"] += 1
            logger.exception("P&L update/alert failed")

    async def _check_thesis_invalidations(self) -> None:
        """Check for expired/invalidated theses and push sell signals.

        Every 3 minutes (with heartbeat), scans active theses for:
        - Expiry: past expires_at date
        - Invalidation: confidence < 0.20

        Generates CRITICAL sell_signal for each, then resolves the thesis.
        """
        try:
            from src.agent_loop.thesis_tracker import ThesisTracker

            tracker = ThesisTracker()
            loop = asyncio.get_running_loop()

            # Apply daily decay (idempotent, safe to call multiple times)
            await loop.run_in_executor(None, tracker.apply_daily_decay)

            # Check for expired/invalidated
            actionable = await loop.run_in_executor(
                None, tracker.check_expired_and_invalid
            )
            if not actionable:
                return

            from src.agent_loop.agent_state import AgentState
            from src.agent_loop.decision_handler import DecisionHandler
            from src.web.services.message_store import MessageStore

            handler = DecisionHandler(
                message_store=MessageStore(),
                redis_client=self._redis,
            )
            state = (
                AgentState.load(self._redis)
                if self._redis
                else AgentState(date=_now_cst().strftime("%Y%m%d"))
            )

            for thesis in actionable:
                reason = (
                    "论点到期"
                    if thesis.expires_at
                    and datetime.now(thesis.expires_at.tzinfo or None)
                    >= thesis.expires_at
                    else f"论点信心衰减至 {thesis.current_confidence:.0%}"
                )
                decision_dict = {
                    "type": "sell_signal",
                    "action": "sell",
                    "symbol": thesis.symbol,
                    "name": thesis.symbol,
                    "confidence": 0.90,
                    "summary": (
                        f"[论点失效] {thesis.symbol}: {reason}。"
                        f"原论点: {thesis.narrative[:80]}"
                    ),
                    "risk_note": reason,
                }
                await handler.push_decisions([decision_dict], state, "thesis_tracker")

                # Resolve the thesis
                tracker.resolve_thesis(thesis.id, reason)

                logger.info(
                    "Thesis auto-sell pushed: %s %s — %s",
                    thesis.symbol,
                    thesis.id[:8],
                    reason,
                )

            if self._redis:
                state.save(self._redis)

        except ImportError:
            logger.debug("ThesisTracker not available")
        except Exception:
            self._stats["errors"] += 1
            logger.exception("Thesis invalidation check failed")

    # ------------------------------------------------------------------
    # Loop 2: Redis Streams event consumer (100ms poll)
    # ------------------------------------------------------------------

    async def _event_loop(self) -> None:
        """Poll Redis Streams for market/signal/news events."""
        logger.info("Event loop started (streams=%s)", EVENT_STREAMS)

        # Lazy import — EventBus uses synchronous Redis
        bus = self._get_event_bus()
        if bus is None:
            logger.error("EventBus unavailable — event loop disabled")
            await self._shutdown_event.wait()
            return

        # Ensure consumer groups exist
        for stream in EVENT_STREAMS:
            bus.ensure_consumer_group(stream, CONSUMER_GROUP, start_id="$")

        while not self._shutdown_event.is_set():
            try:
                if not self._preflight_ok():
                    await asyncio.sleep(30)
                    continue

                # Non-blocking read from Redis Streams via thread pool
                events = await asyncio.get_running_loop().run_in_executor(
                    None,
                    self._poll_events,
                    bus,
                )

                for stream_name, entry_id, parsed in events:
                    await self._route_event(stream_name, entry_id, parsed)
                    # ACK after processing
                    bus._redis.xack(stream_name, CONSUMER_GROUP, entry_id)

            except Exception:
                self._stats["errors"] += 1
                logger.exception("Event loop error")
                await asyncio.sleep(5)  # Back off on error

            # Short sleep between polls
            await asyncio.sleep(self._event_poll_interval)

    def _get_event_bus(self):
        """Create an EventBus instance, or None on failure."""
        try:
            from src.event_bus.bus import EventBus

            return EventBus()
        except Exception:
            logger.exception("Failed to create EventBus")
            return None

    def _poll_events(self, bus) -> list[tuple[str, str, dict[str, Any]]]:
        """Synchronous Redis Streams read — runs in thread pool.

        Args:
            bus: EventBus instance.

        Returns:
            List of (stream_name, entry_id, parsed_data) tuples.
        """
        results: list[tuple[str, str, dict[str, Any]]] = []
        try:
            stream_ids = {s: ">" for s in EVENT_STREAMS}
            raw = bus._redis.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                stream_ids,
                count=10,
                block=100,  # 100ms block
            )
            if raw:
                for stream_name, messages in raw:
                    for entry_id, raw_fields in messages:
                        parsed = bus._deserialize(raw_fields)
                        results.append((stream_name, entry_id, parsed))
        except Exception:
            logger.debug("Event poll error", exc_info=True)
        return results

    async def _route_event(
        self,
        stream_name: str,
        entry_id: str,
        parsed: dict[str, Any],
    ) -> None:
        """Route an event to HeartbeatAgent based on severity.

        Routing logic:
        - events:market with z_score > threshold → event_response
        - events:signal with confidence >= 0.7 → event_response
        - events:news with impact >= "high" → event_response
        - Low severity events → log and skip

        Args:
            stream_name: Redis stream key.
            entry_id: Stream entry ID.
            parsed: Deserialized event data.
        """
        self._stats["events_processed"] += 1
        data = parsed.get("data", parsed)
        event_type = parsed.get("type", "unknown")
        symbol = data.get("symbol", "")
        sector = data.get("sector", "")

        # Feed event into correlator for cross-event pattern detection
        correlator = self._get_event_correlator()
        if correlator is not None:
            from src.agent_loop.event_correlator import Event as CorrelatorEvent

            correlator.add_event(
                CorrelatorEvent(
                    event_type=event_type,
                    symbol=symbol,
                    sector=sector,
                    severity=float(data.get("severity", data.get("confidence", 0.5))),
                    data=data,
                )
            )

        # Rate limit check
        if not self._check_rate_limit():
            logger.debug(
                "Rate limit reached — dropping event %s %s", event_type, symbol
            )
            return

        held = _get_held_symbols()
        should_trigger = False
        event_data: dict[str, Any] = {
            "symbol": symbol,
            "event_type": event_type,
            "stream": stream_name,
            **data,
        }

        if stream_name == "events:market":
            z_score = float(data.get("z_score", 0))
            # Apply severity boost from cross-event correlation
            boost = correlator.get_severity_boost(symbol) if correlator else 0.0
            if boost > 0:
                logger.info(
                    "Correlation boost +%.2f for %s (z=%.2f)", boost, symbol, z_score
                )
            threshold = HELD_Z_THRESHOLD if symbol in held else WATCHLIST_Z_THRESHOLD
            # Boost effectively lowers the threshold for correlated events
            should_trigger = z_score >= (threshold - boost * 2)

        elif stream_name == "events:signal":
            confidence = float(data.get("confidence", 0))
            boost = correlator.get_severity_boost(symbol) if correlator else 0.0
            should_trigger = (confidence + boost) >= SCANNER_CONFIDENCE_THRESHOLD

        elif stream_name == "events:news":
            impact = data.get("impact", "").lower()
            should_trigger = impact in ("high", "critical")

        # Check for correlation patterns (triple resonance, sector cascade, etc.)
        if correlator is not None:
            patterns = correlator.detect_patterns()
            for pattern in patterns:
                self._stats["correlation_patterns"] += 1
                logger.info(
                    "Correlation pattern: %s — %s",
                    pattern.pattern_type,
                    pattern.description,
                )
                # Patterns with high severity auto-trigger regardless of threshold
                if pattern.severity >= 0.7 and pattern.symbols:
                    should_trigger = True
                    event_data["correlation_pattern"] = pattern.pattern_type
                    event_data["correlation_desc"] = pattern.description

        if not should_trigger:
            logger.debug(
                "Event below threshold: %s %s from %s",
                event_type,
                symbol,
                stream_name,
            )
            return

        logger.info(
            "Event qualifies — dispatching: %s %s from %s",
            event_type,
            symbol,
            stream_name,
        )

        try:
            agent = _get_heartbeat_agent()
            result = await agent.run_event_response(event_data)
            self._stats["missions_run"] += 1
            logger.info(
                "Event response [%s %s]: %d decisions, %.1fs",
                event_type,
                symbol,
                result.get("decisions", 0),
                result.get("duration_seconds", 0),
            )
        except Exception:
            self._stats["errors"] += 1
            logger.exception("Event response failed for %s %s", event_type, symbol)

    async def _run_multi_agent_analysis(self, context: str = "scheduled") -> None:
        """Run the Analyst → PM → Risk multi-agent pipeline.

        Used for deep analysis (hourly opportunity_hunt). Quick decisions
        still go through HeartbeatAgent directly for speed.

        Flow:
            1. Analyst researches market + candidates → proposals
            2. PM evaluates proposals + portfolio → decisions
            3. Risk checks each buy/add decision → approve/veto
            4. Approved decisions → Discord push
        """
        try:
            from src.agent_loop.multi_agent_analyst import AnalystAgent
            from src.agent_loop.multi_agent_pm import PMAgent
            from src.agent_loop.multi_agent_risk import RiskAgent

            logger.info("Multi-agent analysis starting (%s)", context)

            # Step 1: Analyst researches
            from src.web.dependencies import get_llm_gateway, get_tool_registry

            _gw = get_llm_gateway()
            _tr = get_tool_registry()

            analyst = AnalystAgent(gateway=_gw, tool_registry=_tr)
            proposals = await analyst.research()
            logger.info(
                "Analyst: %d proposals generated",
                len(proposals) if proposals else 0,
            )

            if not proposals:
                return

            # Step 2: PM evaluates each proposal
            pm = PMAgent(gateway=_gw, tool_registry=_tr)
            decisions = await pm.decide(proposals)
            logger.info(
                "PM: %d decisions from %d proposals",
                len(decisions) if decisions else 0,
                len(proposals),
            )

            if not decisions:
                return

            # Step 3: Risk vets each buy/add decision
            from src.web.dependencies import get_kill_switch as _get_ks

            risk = RiskAgent(gateway=_gw, tool_registry=_tr, kill_switch=_get_ks())
            verdicts = await risk.review(decisions)
            for decision, verdict in zip(decisions, verdicts):
                if decision.action in ("buy", "add"):
                    if not verdict.approved:
                        logger.warning(
                            "Risk VETO: %s %s — %s",
                            decision.action,
                            decision.symbol,
                            verdict.veto_reason,
                        )
                        decision.action = "watch"
                        decision.risk_note = f"[风控否决] {verdict.veto_reason}"
                    else:
                        logger.info(
                            "Risk APPROVED: %s %s (risk=%s)",
                            decision.action,
                            decision.symbol,
                            verdict.risk_level,
                        )

            # Step 4: Push approved decisions to Discord
            from src.agent_loop.decision_handler import DecisionHandler
            from src.web.services.message_store import MessageStore

            handler = DecisionHandler(
                message_store=MessageStore(),
                redis_client=self._redis,
            )
            from src.agent_loop.agent_state import AgentState

            state = (
                AgentState.load(self._redis)
                if self._redis
                else AgentState(date=datetime.now(_CST).strftime("%Y%m%d"))
            )

            decision_dicts = [
                {
                    "type": "buy_signal"
                    if d.action in ("buy", "add")
                    else "sell_signal"
                    if d.action in ("sell", "reduce")
                    else "hold_update",
                    "action": d.action,
                    "symbol": d.symbol,
                    "name": getattr(d, "name", d.symbol),
                    "shares": getattr(d, "shares", 0),
                    "entry_price": getattr(d, "entry_price", None),
                    "stop_loss": getattr(d, "stop_loss", None),
                    "target_price": getattr(d, "target_price", None),
                    "confidence": d.confidence,
                    "summary": d.reasoning,
                    "risk_note": getattr(d, "risk_note", ""),
                }
                for d in decisions
                if d.action != "watch"
            ]

            if decision_dicts:
                pushed = await handler.push_decisions(
                    decision_dicts, state, "multi_agent"
                )
                if self._redis:
                    state.save(self._redis)
                logger.info("Multi-agent: %d decisions pushed to Discord", pushed)
                self._stats["missions_run"] += 1

        except ImportError:
            logger.debug("Multi-agent modules not available, using HeartbeatAgent")
            agent = _get_heartbeat_agent()
            await agent.run_heartbeat()
        except Exception:
            self._stats["errors"] += 1
            logger.exception("Multi-agent analysis failed")

    def _check_rate_limit(self) -> bool:
        """Check hourly rate limit for event-triggered sessions.

        Returns:
            True if under the limit, False if exceeded.
        """
        if self._redis is None:
            return True
        try:
            count = self._redis.incr(RATE_LIMIT_KEY)
            if count == 1:
                self._redis.expire(RATE_LIMIT_KEY, 3600)
            return count <= MAX_EVENT_SESSIONS_PER_HOUR
        except Exception:
            return True

    # ------------------------------------------------------------------
    # Loop 3: Time-triggered mission scheduler
    # ------------------------------------------------------------------

    async def _scheduler_loop(self) -> None:
        """Trigger time-specific missions (morning_plan, decision_window, close_review).

        These are once-per-day missions that HeartbeatAgent's _select_mission
        handles internally, but the scheduler ensures they fire at the right
        time even if the heartbeat loop is busy with a long-running mission.
        """
        logger.info(
            "Scheduler loop started (check every %ds)", SCHEDULER_CHECK_INTERVAL_S
        )
        while not self._shutdown_event.is_set():
            try:
                self._reset_daily_state()
                if self._preflight_ok():
                    await self._check_scheduled_missions()
            except Exception:
                self._stats["errors"] += 1
                logger.exception("Scheduler loop error")

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=SCHEDULER_CHECK_INTERVAL_S,
                )
                break
            except asyncio.TimeoutError:
                pass

    async def _check_scheduled_missions(self) -> None:
        """Check if any time-triggered mission should fire now.

        Missions:
            08:00-08:10 → morning_plan (once per day)
            14:30-14:35 → decision_window (once per day)
            15:05-15:10 → close_review (once per day)

        Deduplication: each mission fires at most once per day, tracked
        in _executed_today. HeartbeatAgent's own _select_mission provides
        a second layer via AgentState.executed_missions.
        """
        now = _now_cst()
        h, m = now.hour, now.minute
        t = h * 60 + m

        schedule: list[tuple[str, int, int]] = [
            ("morning_plan", 8 * 60, 8 * 60 + 10),
            ("decision_window", 14 * 60 + 30, 14 * 60 + 35),
            ("close_review", 15 * 60 + 5, 15 * 60 + 10),
            ("auto_dream", 15 * 60 + 30, 15 * 60 + 40),
        ]

        for mission_key, start_t, end_t in schedule:
            if start_t <= t <= end_t and mission_key not in self._executed_today:
                self._executed_today.add(mission_key)
                logger.info("Scheduler triggering mission: %s", mission_key)

                if mission_key == "auto_dream":
                    await self._run_auto_dream()
                    continue

                try:
                    agent = _get_heartbeat_agent()
                    # HeartbeatAgent._select_mission will pick the right mission
                    # based on time, so we just invoke run_heartbeat
                    result = await agent.run_heartbeat()
                    self._stats["missions_run"] += 1
                    logger.info(
                        "Scheduled mission [%s] done: %d decisions, %.1fs",
                        result.get("mission", mission_key),
                        result.get("decisions", 0),
                        result.get("duration_seconds", 0),
                    )
                except Exception:
                    self._stats["errors"] += 1
                    logger.exception("Scheduled mission %s failed", mission_key)

    async def _run_auto_dream(self) -> None:
        """Run post-market autoDream distillation at 15:30.

        Reads today's decisions from decisions.db, evaluates direction
        correctness, and distills lessons via LLM. Lessons are stored
        in Redis (agent:distilled_lessons, 48h TTL) for injection into
        the next trading day's agent prompt.
        """
        try:
            from src.agent_loop.auto_dream import AutoDream

            today = _now_cst().strftime("%Y-%m-%d")
            logger.info("AutoDream starting for %s", today)

            dream = AutoDream()
            # distill_daily() is synchronous (DB + LLM) — run in thread pool
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, dream.distill_daily, today)

            self._stats["missions_run"] += 1
            logger.info(
                "AutoDream complete: %d decisions, %d wins, %d losses, %d lessons",
                result.total_decisions,
                result.wins,
                result.losses,
                len(result.lessons),
            )

            # Also store in MemoryStore for long-term retrieval
            if result.lessons:
                try:
                    from src.intelligence.memory_store import MemoryStore

                    ms = MemoryStore()
                    for lesson in result.lessons:
                        ms.store(
                            content=lesson,
                            category="insight",
                            source="auto_dream",
                            metadata={"date": today},
                        )
                    logger.info(
                        "AutoDream: %d lessons saved to MemoryStore",
                        len(result.lessons),
                    )
                except Exception:
                    logger.debug("MemoryStore save failed", exc_info=True)

        except ImportError:
            logger.debug("AutoDream module not available")
        except Exception:
            self._stats["errors"] += 1
            logger.exception("AutoDream failed")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Launch the always-on investment daemon."""
    logger.info("=" * 60)
    logger.info("KAIROS Always-On Investment Daemon")
    logger.info("=" * 60)

    daemon = AlwaysOnDaemon()
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        logger.info("Daemon interrupted by user")
    finally:
        logger.info("Daemon process exiting")

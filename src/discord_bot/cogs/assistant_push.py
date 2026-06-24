"""Redis pub/sub listener — pushes assistant inbox messages to Discord.

Subscribes to ``assistant:messages`` and forwards **only actionable**
plain-language messages as formatted embeds to the configured Discord channel.

Architecture: This is the SINGLE push channel for all automated notifications.
PushNotificationsCog is DEPRECATED — its dashboard-type notifications
(market_overview, sentiment_update, intel_refresh) belong in the web UI
message center, not in Discord.

Discord = 交易执行入口, not 仪表盘.  Only push what requires human action.

Push tiers:
    CRITICAL  — buy_signal, sell_signal, risk_alert → always push
    SCHEDULED — pre_market, late_session, post_market, holiday_intel → push
    SIGNAL    — call_auction, intraday_signal → push if quality threshold met

Filtered out (web-only):
    hold_reminder, market_watch (LOW/MEDIUM)

Rate limiting:
    - Max 2 messages per symbol per day
    - Max 15 total messages per day (global limit)
    - Quiet hours (21:00-08:30 CST): only CRITICAL messages
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Callable

import discord
from discord.ext import commands

from src.discord_bot.embeds.assistant_message_card import (
    build_assistant_message_embed,
)
from src.discord_bot.embeds.quant_schedule_card import (
    build_call_auction_embed,
    build_holiday_intel_embed,
    build_intraday_signal_embed,
    build_late_session_embed,
    build_review_embed,
)
from src.discord_bot.views import FollowUpView
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.assistant_push")

# Channel name in Redis
_REDIS_CHANNEL = "assistant:messages"

# Rate limits (v53.0: raised for InvestorAgent — fewer but higher quality messages)
_MAX_PER_SYMBOL_PER_DAY = 8
_MAX_TOTAL_PER_DAY = 30

# China Standard Time
_CST = ZoneInfo("Asia/Shanghai")

# Quiet hours: 21:00 - 08:30 CST — only CRITICAL messages
_QUIET_START_HOUR = 21
_QUIET_END_HOUR = 8
_QUIET_END_MINUTE = 30


# ---------------------------------------------------------------------------
# Push priority tiers
# ---------------------------------------------------------------------------


class _PushTier:
    CRITICAL = "critical"  # Must push, even in quiet hours
    SCHEDULED = "scheduled"  # Regular scheduled pushes (not in quiet hours)
    SIGNAL = "signal"  # Push if quality threshold met
    NEVER = "never"  # Never push to Discord


def _check_high_impact(payload: dict[str, Any]) -> bool:
    """Return True only if market_watch impact is HIGH."""
    return str(payload.get("impact", "")).upper() == "HIGH"


def _check_signal_quality(payload: dict[str, Any]) -> bool:
    """Check if signal has sufficient quality to push.

    Threshold adapts: 0.3 when portfolio empty (need buy signals),
    0.6 when holding (need high conviction for new buys).
    """
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)):
        return bool(payload.get("summary") or payload.get("action_advice"))

    # Adaptive threshold — calibration reduces confidence heavily,
    # so thresholds must account for post-calibration values
    threshold = 0.4  # Default: post-calibration buy signals are ~0.35-0.55
    try:
        from src.web.dependencies import get_portfolio_store

        ps = get_portfolio_store()
        positions = ps.list_positions()
        if not positions:
            threshold = 0.25  # Empty portfolio → even lower bar
    except Exception:
        pass

    if confidence < threshold:
        return False
    return bool(payload.get("summary") or payload.get("action_advice"))


def _check_has_content(payload: dict[str, Any]) -> bool:
    """Reject messages with no meaningful content (empty summary AND action_advice)."""
    summary = str(payload.get("summary", "")).strip()
    action_advice = str(payload.get("action_advice", "")).strip()
    return bool(summary) or bool(action_advice)


# (tier, optional_condition)
_PUSH_RULES: dict[str, tuple[str, Callable[[dict[str, Any]], bool] | None]] = {
    # CRITICAL — always push
    "buy_signal": (_PushTier.CRITICAL, _check_signal_quality),
    "sell_signal": (_PushTier.CRITICAL, None),
    "risk_alert": (_PushTier.CRITICAL, _check_has_content),
    # SCHEDULED — regular briefings
    "pre_market": (_PushTier.SCHEDULED, None),
    "late_session": (_PushTier.SCHEDULED, None),  # highest priority schedule
    "post_market": (_PushTier.SCHEDULED, None),
    "holiday_intel": (_PushTier.SCHEDULED, None),
    # SIGNAL — conditional push
    "call_auction": (_PushTier.SIGNAL, _check_signal_quality),
    "intraday_signal": (_PushTier.SIGNAL, _check_signal_quality),
    "market_watch": (_PushTier.SIGNAL, _check_high_impact),
    "market_pulse": (
        _PushTier.NEVER,
        None,
    ),  # v53.0: disabled, replaced by InvestorAgent
    # Event bus types (from notification_consumer)
    "trading_signal": (_PushTier.SIGNAL, _check_signal_quality),
    "regime_change": (_PushTier.SCHEDULED, None),
    # Global intelligence (from PlainLanguageWriter)
    "global_intelligence": (_PushTier.SIGNAL, None),
    # v53.0: InvestorAgent output types
    "market_insight": (
        _PushTier.SCHEDULED,
        _check_has_content,
    ),  # Agent session briefings
    "hold_update": (
        _PushTier.SCHEDULED,
        _check_has_content,
    ),  # Agent holding updates — always push (user needs to see portfolio status)
    # NEVER — web-only (no Discord push)
    "hold_reminder": (_PushTier.NEVER, None),
}


class _RateLimiter:
    """Rate limiter with per-symbol AND global daily limits."""

    def __init__(
        self,
        max_per_symbol: int = _MAX_PER_SYMBOL_PER_DAY,
        max_total: int = _MAX_TOTAL_PER_DAY,
    ) -> None:
        self._max_per_symbol = max_per_symbol
        self._max_total = max_total
        # symbol -> list of unix timestamps
        self._symbol_counts: dict[str, list[float]] = defaultdict(list)
        self._global_counts: list[float] = []
        self._last_cleanup = time.time()

    def allow(self, symbol: str = "", tier: str = _PushTier.SIGNAL) -> bool:
        """Return True if a push is allowed.

        CRITICAL tier bypasses global limit (but still respects per-symbol).
        """
        now = time.time()
        # Cleanup stale entries every 6 hours
        if now - self._last_cleanup > 21600:
            self._cleanup(now)

        day_start = self._day_start(now)

        # Global limit check (CRITICAL bypasses this)
        if tier != _PushTier.CRITICAL:
            self._global_counts[:] = [t for t in self._global_counts if t >= day_start]
            if len(self._global_counts) >= self._max_total:
                return False

        # Per-symbol limit check
        if symbol:
            timestamps = self._symbol_counts[symbol]
            timestamps[:] = [t for t in timestamps if t >= day_start]
            if len(timestamps) >= self._max_per_symbol:
                return False
            timestamps.append(now)

        self._global_counts.append(now)
        return True

    @staticmethod
    def _day_start(ts: float) -> float:
        """Return unix timestamp for start of the day containing *ts* (CST)."""
        dt = datetime.fromtimestamp(ts, tz=_CST)
        start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp()

    def _cleanup(self, now: float) -> None:
        """Remove entries older than today."""
        day_start = self._day_start(now)
        stale = [
            k for k, v in self._symbol_counts.items() if all(t < day_start for t in v)
        ]
        for k in stale:
            del self._symbol_counts[k]
        self._global_counts[:] = [t for t in self._global_counts if t >= day_start]
        self._last_cleanup = now


def _is_quiet_hours() -> bool:
    """Check if current time (CST) is in quiet hours (21:00 - 08:30)."""
    now = datetime.now(_CST)
    hour, minute = now.hour, now.minute

    if hour >= _QUIET_START_HOUR:
        return True
    if hour < _QUIET_END_HOUR:
        return True
    if hour == _QUIET_END_HOUR and minute < _QUIET_END_MINUTE:
        return True
    return False


class AssistantPushCog(commands.Cog):
    """Subscribe to Redis ``assistant:messages`` and push to Discord.

    This is the SINGLE source of automated Discord push notifications.
    Only actionable messages are forwarded — dashboard/info content
    stays in the web message center.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task[None] | None = None
        self._limiter = _RateLimiter()

    async def cog_load(self) -> None:
        self._task = self.bot.loop.create_task(self._redis_listener())

    async def cog_unload(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    # ------------------------------------------------------------------
    # Redis listener
    # ------------------------------------------------------------------

    async def _redis_listener(self) -> None:
        from src.web.dependencies import get_redis

        redis_client = get_redis()
        if redis_client is None:
            logger.warning("Redis unavailable — assistant push disabled")
            return

        pubsub = redis_client.pubsub()
        pubsub.subscribe(_REDIS_CHANNEL)
        logger.info("Subscribed to %s", _REDIS_CHANNEL)

        try:
            while True:
                msg = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                if msg and msg["type"] == "message":
                    try:
                        payload = json.loads(msg["data"])
                        await self._handle(payload)
                    except Exception:
                        logger.warning(
                            "Failed to handle assistant message", exc_info=True
                        )
                else:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("Assistant push listener cancelled")
        finally:
            try:
                pubsub.unsubscribe(_REDIS_CHANNEL)
                pubsub.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Push logic
    # ------------------------------------------------------------------

    def _should_push(self, payload: dict[str, Any]) -> tuple[bool, str]:
        """Check push rules for *payload*.

        Returns (should_push, tier).
        """
        msg_type = payload.get("type", "")

        rule = _PUSH_RULES.get(msg_type)
        if rule is None:
            logger.debug("Unknown message type: %s — skipping", msg_type)
            return False, _PushTier.NEVER

        tier, condition = rule

        if tier == _PushTier.NEVER:
            return False, tier

        # Check condition if present
        if condition is not None and not condition(payload):
            confidence = payload.get("confidence", "N/A")
            symbol = payload.get("symbol", "N/A")
            logger.info(
                "Filtered %s for %s — quality check failed (confidence=%s, needs>=0.6)",
                msg_type,
                symbol,
                confidence,
            )
            return False, tier

        # Quiet hours: only CRITICAL pushes through
        if _is_quiet_hours() and tier != _PushTier.CRITICAL:
            logger.debug("Skipping %s — quiet hours (21:00-08:30 CST)", msg_type)
            return False, tier

        return True, tier

    def _build_embed(self, payload: dict[str, Any]) -> discord.Embed:
        """Route payload to the correct embed builder based on type."""
        msg_type = payload.get("type", "")

        if msg_type in ("pre_market", "call_auction"):
            return build_call_auction_embed(payload)
        elif msg_type == "late_session":
            return build_late_session_embed(payload)
        elif msg_type == "post_market":
            return build_review_embed(payload)
        elif msg_type == "holiday_intel":
            return build_holiday_intel_embed(payload)
        elif msg_type == "intraday_signal":
            return build_intraday_signal_embed(payload)
        elif payload.get("action") and payload.get("action") != "no_trade":
            # Structured card for any decision with an action (buy/sell/hold/watch)
            from src.discord_bot.embeds.trading_signal_embed import (
                build_trading_signal_embed,
            )

            return build_trading_signal_embed(payload)
        else:
            # Fallback for risk_alert, market_watch, no_trade, etc.
            return build_assistant_message_embed(payload)

    def _build_context(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Build follow-up context from the push payload."""
        from src.discord_bot.context_builders import build_scheduled_push_context

        context_summary = build_scheduled_push_context(payload, payload.get("type", ""))
        kwargs: dict[str, Any] = {"mode": "market"}
        # Pass symbol if present for stock-specific context
        symbol = payload.get("symbol")
        if symbol:
            kwargs["symbol"] = symbol
        return context_summary, kwargs

    async def _handle(self, payload: dict[str, Any]) -> None:
        """Check push rules, rate limit, build embed, and send."""
        msg_type = payload.get("type", "")

        should_push, tier = self._should_push(payload)
        if not should_push:
            return

        # Rate limit per symbol + global
        symbol = payload.get("symbol", "")
        if not self._limiter.allow(symbol=symbol, tier=tier):
            logger.info(
                "Rate limited: %s for %s (max %d/symbol, %d/day global)",
                msg_type,
                symbol or "N/A",
                _MAX_PER_SYMBOL_PER_DAY,
                _MAX_TOTAL_PER_DAY,
            )
            return

        # Resolve channel
        from src.discord_bot.bot import AShareAnalystBot

        bot: AShareAnalystBot = self.bot  # type: ignore[assignment]
        channel = await bot.get_push_channel()
        if channel is None:
            logger.warning("No push channel available")
            return

        # Build embed
        embed = self._build_embed(payload)

        # Build follow-up view with context
        ctx_summary, ctx_kwargs = self._build_context(payload)
        view = FollowUpView(
            source_command=f"push:{msg_type}",
            context_summary=ctx_summary,
            thread_context_kwargs=ctx_kwargs,
            bot=self.bot,
        )

        await channel.send(embed=embed, view=view)
        logger.info(
            "Pushed [%s] %s for %s to Discord (tier=%s)",
            msg_type,
            payload.get("title", "")[:30],
            symbol or "N/A",
            tier,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AssistantPushCog(bot))

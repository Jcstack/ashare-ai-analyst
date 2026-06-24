"""Redis pub/sub listener — forwards ``notifications:push`` to Discord.

Routes channel-aware notification types through ChannelRouter when available,
falls back to the legacy single-channel dispatch for other types.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import discord
from discord.ext import commands

from src.discord_bot.embeds.capital_flow_card import build_capital_flow_embed
from src.discord_bot.embeds.intel_card import build_intel_embed
from src.discord_bot.embeds.market_card import build_market_embed
from src.discord_bot.embeds.risk_card import build_risk_embed
from src.discord_bot.embeds.sentiment_card import build_sentiment_embed
from src.discord_bot.embeds.trade_signal_card import (
    build_evening_review_embed,
    build_morning_briefing_embed,
    build_trade_signal_embed,
)
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.push")

# Notification types that should be routed through ChannelRouter
_ROUTED_TYPES = frozenset(
    {
        "trade_signal",
        "intraday_signal",
        "risk_alert",
        "thesis_invalidation",
        "regime_change",
        "morning_briefing",
        "close_briefing",
        "evening_review",
        "system_health",
    }
)


class PushNotificationsCog(commands.Cog):
    """Subscribe to Redis ``notifications:push`` and dispatch to channels."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task[None] | None = None

    async def cog_load(self) -> None:
        self._task = self.bot.loop.create_task(self._redis_listener())

    async def cog_unload(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    # ------------------------------------------------------------------
    # Redis listener loop
    # ------------------------------------------------------------------

    async def _redis_listener(self) -> None:
        from src.web.dependencies import get_redis

        redis_client = get_redis()
        if redis_client is None:
            logger.warning("Redis unavailable — push notifications disabled")
            return

        pubsub = redis_client.pubsub()
        pubsub.subscribe("notifications:push")
        logger.info("Subscribed to notifications:push")

        try:
            while True:
                msg = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                if msg and msg["type"] == "message":
                    try:
                        payload = json.loads(msg["data"])
                        await self._dispatch(payload)
                    except Exception:
                        logger.warning("Failed to dispatch push", exc_info=True)
                else:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("Push listener cancelled")
        finally:
            try:
                pubsub.unsubscribe("notifications:push")
                pubsub.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Channel router helper
    # ------------------------------------------------------------------

    def _get_router(self):
        """Get the ChannelRouter cog if loaded."""
        from src.discord_bot.cogs.channel_router import ChannelRouter

        return self.bot.get_cog(ChannelRouter.__qualname__)

    # ------------------------------------------------------------------
    # Dispatch logic
    # ------------------------------------------------------------------

    async def _dispatch(self, payload: dict[str, Any]) -> None:
        """Route a notification payload to the appropriate channel/embed."""
        from src.discord_bot.bot import AShareAnalystBot

        bot: AShareAnalystBot = self.bot  # type: ignore[assignment]

        push_types: list[str] = bot.cfg.get("push_types", [])
        notif_type = payload.get("type", "")
        if notif_type not in push_types:
            logger.debug("Ignoring push type: %s", notif_type)
            return

        data = payload.get("data", payload)

        # Try routing through ChannelRouter for supported types
        if notif_type in _ROUTED_TYPES:
            try:
                routed = await self._dispatch_routed(notif_type, data)
                if routed:
                    return
            except Exception:
                logger.warning(
                    "Routed dispatch failed for %s, falling back to legacy",
                    notif_type,
                    exc_info=True,
                )
            # Fall through to legacy dispatch if router unavailable or failed

        # Legacy single-channel dispatch
        channel = await bot.get_push_channel()
        if channel is None:
            logger.warning("No push channel available")
            return

        embed = self._build_embed(notif_type, payload)
        if embed is None:
            logger.debug("No embed builder for type: %s", notif_type)
            return

        try:
            await channel.send(embed=embed)
            logger.info("Pushed %s notification to channel", notif_type)
        except Exception:
            logger.warning(
                "Failed to send %s to legacy channel", notif_type, exc_info=True
            )

    async def _dispatch_routed(self, notif_type: str, data: dict[str, Any]) -> bool:
        """Dispatch through ChannelRouter. Returns True if handled."""
        router = self._get_router()
        if router is None:
            logger.debug("ChannelRouter not available, falling back to legacy")
            return False

        if notif_type in ("trade_signal", "intraday_signal"):
            return await router.push_trading_signal(data)

        if notif_type == "thesis_invalidation":
            return await router.push_risk_alert("thesis_invalidation", data)

        if notif_type == "regime_change":
            return await router.push_risk_alert("regime_change", data)

        if notif_type == "risk_alert":
            return await router.push_risk_alert("generic", data)

        if notif_type == "morning_briefing":
            return await router.push_morning_brief(data)

        if notif_type in ("close_briefing", "evening_review"):
            return await router.push_close_review(data)

        if notif_type == "system_health":
            return await router.push_system_health(data)

        return False

    @staticmethod
    def _build_embed(notif_type: str, payload: dict[str, Any]) -> discord.Embed | None:
        """Build embed for legacy single-channel dispatch."""
        data = payload.get("data", payload)

        if notif_type == "market_overview":
            indices = data.get("indices", [])
            return build_market_embed(indices)

        if notif_type in ("intelligence_hub_refresh", "intel_alert"):
            items = data.get("items", [data]) if isinstance(data, dict) else [data]
            return build_intel_embed(items)

        if notif_type in ("capital_flow_anomaly", "capital_flow_update"):
            return build_capital_flow_embed(data)

        if notif_type == "risk_alert":
            return build_risk_embed(data)

        if notif_type == "sentiment_update":
            return build_sentiment_embed(data)

        if notif_type == "trade_signal":
            return build_trade_signal_embed(data)

        if notif_type == "morning_briefing":
            return build_morning_briefing_embed(data)

        if notif_type in ("close_briefing", "evening_review"):
            return build_evening_review_embed(data)

        return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PushNotificationsCog(bot))

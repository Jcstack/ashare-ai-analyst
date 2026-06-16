"""Redis pub/sub listener — forwards ``notifications:push`` to Discord."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import discord
from discord.ext import commands

from src.discord_bot.embeds.capital_flow_card import build_capital_flow_embed
from src.discord_bot.embeds.intel_card import build_intel_embed
from src.discord_bot.embeds.market_card import build_market_embed
from src.discord_bot.embeds.recommendation_card import build_recommendation_embed
from src.discord_bot.embeds.risk_card import build_risk_embed
from src.discord_bot.embeds.sentiment_card import build_sentiment_embed
from src.discord_bot.embeds.trade_signal_card import (
    build_evening_review_embed,
    build_morning_briefing_embed,
    build_trade_signal_embed,
)
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.push")


class PushNotificationsCog(commands.Cog):
    """Subscribe to Redis ``notifications:push`` and dispatch to the channel."""

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
    # Dispatch logic
    # ------------------------------------------------------------------

    async def _dispatch(self, payload: dict[str, Any]) -> None:
        """Route a notification payload to the appropriate embed builder."""
        from src.discord_bot.bot import AShareAnalystBot

        bot: AShareAnalystBot = self.bot  # type: ignore[assignment]

        push_types: list[str] = bot.cfg.get("push_types", [])
        notif_type = payload.get("type", "")
        if notif_type not in push_types:
            logger.debug("Ignoring push type: %s", notif_type)
            return

        channel = await bot.get_push_channel()
        if channel is None:
            logger.warning("No push channel available")
            return

        embed = self._build_embed(notif_type, payload)
        if embed is None:
            logger.debug("No embed builder for type: %s", notif_type)
            return

        await channel.send(embed=embed)
        logger.info("Pushed %s notification to channel", notif_type)

    @staticmethod
    def _build_embed(notif_type: str, payload: dict[str, Any]) -> discord.Embed | None:
        data = payload.get("data", payload)

        if notif_type == "recommendation":
            recs = (
                data.get("recommendations", [data])
                if isinstance(data, dict)
                else [data]
            )
            return build_recommendation_embed(recs)

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

        if notif_type == "evening_review":
            return build_evening_review_embed(data)

        return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PushNotificationsCog(bot))

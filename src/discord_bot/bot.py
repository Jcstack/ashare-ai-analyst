"""Core bot class — lifecycle, channel resolution, cog loading."""

from __future__ import annotations

import asyncio
import os
import traceback
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from src.discord_bot.config import load_discord_config
from src.discord_bot.services import init_services
from src.utils.logger import get_logger

logger = get_logger("discord.bot")

_COG_DIR = Path(__file__).parent / "cogs"

# Cog modules that will be loaded in setup_hook (order matters for NL last)
_COG_MODULES = [
    "src.discord_bot.cogs.stock_commands",
    "src.discord_bot.cogs.market_commands",
    "src.discord_bot.cogs.portfolio_commands",
    "src.discord_bot.cogs.intel_commands",
    "src.discord_bot.cogs.sentiment_commands",
    "src.discord_bot.cogs.global_market_commands",
    "src.discord_bot.cogs.concept_commands",
    "src.discord_bot.cogs.agent_commands",
    "src.discord_bot.cogs.channel_router",
    "src.discord_bot.cogs.push_notifications",
    "src.discord_bot.cogs.assistant_push",
    "src.discord_bot.cogs.natural_language",
]


class AShareAnalystBot(commands.Bot):
    """A-share analyst Discord bot.

    Directly imports DI singletons from ``src/web/dependencies.py`` and
    shares Redis + SQLite with FastAPI / Celery.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.cfg = config or load_discord_config()
        self._resolved = self.cfg["_resolved"]

        intents = discord.Intents.default()
        intents.guilds = True
        intents.message_content = True

        # Proxy support — discord.py passes this to aiohttp
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

        kwargs: dict[str, Any] = {
            "command_prefix": "!",
            "intents": intents,
        }
        if proxy:
            kwargs["proxy"] = proxy
            logger.info("Using proxy: %s", proxy)

        super().__init__(**kwargs)

        self._channel: discord.TextChannel | None = None
        self._guild_id: int = self._resolved["guild_id"]
        self._channel_id: int = self._resolved["channel_id"]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        """Called once before the bot starts receiving events."""
        logger.info("setup_hook: initialising services …")
        await asyncio.to_thread(init_services)

        for module in _COG_MODULES:
            try:
                await self.load_extension(module)
                logger.info("Loaded cog: %s", module)
            except Exception:
                logger.error("Failed to load cog: %s", module, exc_info=True)

        self.tree.on_error = self._on_tree_error

        guild_obj = discord.Object(id=self._guild_id)
        self.tree.copy_global_to(guild=guild_obj)
        await self.tree.sync(guild=guild_obj)
        logger.info("Slash commands synced to guild %s", self._guild_id)

    async def on_ready(self) -> None:
        logger.info(
            "Bot ready: %s (id=%s)", self.user, self.user.id if self.user else "?"
        )

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        logger.error("Command error: %s", error, exc_info=error)

    async def _on_tree_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        logger.error(
            "Slash command error in /%s: %s",
            interaction.command.name if interaction.command else "?",
            error,
            exc_info=error,
        )
        tb = traceback.format_exception(type(error), error, error.__traceback__)
        logger.error("".join(tb))
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"⚠️ 命令异常: {error}", ephemeral=True)
            else:
                await interaction.response.send_message(
                    f"⚠️ 命令异常: {error}", ephemeral=True
                )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Channel helper
    # ------------------------------------------------------------------

    async def get_push_channel(self) -> discord.TextChannel | None:
        """Resolve and cache the single push channel."""
        if self._channel is not None:
            return self._channel
        ch = self.get_channel(self._channel_id)
        if ch is None:
            try:
                ch = await self.fetch_channel(self._channel_id)
            except Exception:
                logger.error("Cannot fetch channel %s", self._channel_id)
                return None
        if isinstance(ch, discord.TextChannel):
            self._channel = ch
            return ch
        logger.error("Channel %s is not a TextChannel", self._channel_id)
        return None

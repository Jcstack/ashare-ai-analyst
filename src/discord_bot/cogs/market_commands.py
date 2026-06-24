"""Slash commands: /market, /flow."""

from __future__ import annotations

import asyncio
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from src.discord_bot.embeds.capital_flow_card import build_capital_flow_embed
from src.discord_bot.embeds.market_card import build_market_embed
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.market")


class MarketCommandsCog(commands.Cog):
    """Market-wide commands: indices, capital flow."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_indices() -> list[dict[str, Any]]:
        from src.web.dependencies import get_market_service

        return get_market_service().get_market_indices()

    @staticmethod
    def _get_macro_flow() -> dict[str, Any]:
        from src.web.dependencies import get_capital_flow_service

        return get_capital_flow_service().get_macro_overview()

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    @app_commands.command(name="market", description="A股大盘概览")
    async def market(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        indices = await asyncio.to_thread(self._get_indices)
        embed = build_market_embed(indices)

        from src.discord_bot.context_builders import market_context
        from src.discord_bot.views import FollowUpView

        ctx_summary, ctx_kwargs = market_context(indices)
        view = FollowUpView(
            source_command="market",
            context_summary=ctx_summary,
            thread_context_kwargs=ctx_kwargs,
            bot=self.bot,
        )
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="flow", description="资金面宏观概览")
    async def flow(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        data = await asyncio.to_thread(self._get_macro_flow)
        embed = build_capital_flow_embed(data)

        from src.discord_bot.context_builders import flow_context
        from src.discord_bot.views import FollowUpView

        ctx_summary, ctx_kwargs = flow_context(data)
        view = FollowUpView(
            source_command="flow",
            context_summary=ctx_summary,
            thread_context_kwargs=ctx_kwargs,
            bot=self.bot,
        )
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketCommandsCog(bot))

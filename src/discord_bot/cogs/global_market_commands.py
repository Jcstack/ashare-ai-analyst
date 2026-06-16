"""Slash command: /global — global market overview."""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from src.discord_bot.config import get_timeout
from src.discord_bot.embeds.global_market_card import build_global_market_embed
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.global_market")


class GlobalMarketCommandsCog(commands.Cog):
    """Global market overview command."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="global", description="全球市场概览 — 指数/商品/汇率")
    async def global_market(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            from src.web.dependencies import get_global_market_fetcher
            from src.discord_bot.context_builders import global_market_context
            from src.discord_bot.views import FollowUpView

            fetcher = get_global_market_fetcher()
            snapshot = await asyncio.wait_for(
                asyncio.to_thread(fetcher.fetch_global_snapshot),
                timeout=get_timeout("analysis_timeout", 300),
            )
            embed = build_global_market_embed(snapshot)
            ctx_summary, ctx_kwargs = global_market_context(snapshot)
            view = FollowUpView(
                source_command="global",
                context_summary=ctx_summary,
                thread_context_kwargs=ctx_kwargs,
                bot=self.bot,
            )
            await interaction.followup.send(embed=embed, view=view)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏳ 全球市场数据获取超时，请稍后重试")
        except Exception as exc:
            logger.error("Global market command failed: %s", exc, exc_info=True)
            await interaction.followup.send("⚠️ 全球市场数据异常，请稍后重试")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GlobalMarketCommandsCog(bot))

"""Slash command: /concept — concept board hot rankings."""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from src.discord_bot.config import get_timeout
from src.discord_bot.embeds.concept_card import build_concept_embed
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.concept")


class ConceptCommandsCog(commands.Cog):
    """Concept board commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="concept", description="概念板块热度排行")
    @app_commands.describe(limit="显示数量 (默认10)")
    async def concept(self, interaction: discord.Interaction, limit: int = 10) -> None:
        await interaction.response.defer()
        limit = max(1, min(limit, 20))
        try:
            from src.web.dependencies import get_concept_board_service
            from src.discord_bot.context_builders import concept_context
            from src.discord_bot.views import FollowUpView

            svc = get_concept_board_service()
            boards = await asyncio.wait_for(
                asyncio.to_thread(svc.fetch_concept_list),
                timeout=get_timeout("analysis_timeout", 300),
            )
            embed = build_concept_embed(boards, limit=limit)
            ctx_summary, ctx_kwargs = concept_context(boards, limit)
            view = FollowUpView(
                source_command="concept",
                context_summary=ctx_summary,
                thread_context_kwargs=ctx_kwargs,
                bot=self.bot,
            )
            await interaction.followup.send(embed=embed, view=view)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏳ 概念板块数据获取超时，请稍后重试")
        except Exception as exc:
            logger.error("Concept command failed: %s", exc, exc_info=True)
            await interaction.followup.send("⚠️ 概念板块数据异常，请稍后重试")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ConceptCommandsCog(bot))

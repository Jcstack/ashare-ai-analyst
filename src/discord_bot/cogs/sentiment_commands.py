"""Slash commands: /sentiment, /pulse."""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from src.discord_bot.config import get_timeout
from src.discord_bot.embeds.sentiment_card import (
    build_pulse_embed,
    build_sentiment_embed,
)
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.sentiment")


class SentimentCommandsCog(commands.Cog):
    """Sentiment analysis and market pulse commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="sentiment", description="市场舆情分析报告")
    async def sentiment(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            from src.web.dependencies import get_sentiment_service
            from src.discord_bot.context_builders import sentiment_context
            from src.discord_bot.views import FollowUpView

            svc = get_sentiment_service()
            report = await asyncio.wait_for(
                asyncio.to_thread(svc.get_sentiment_report),
                timeout=get_timeout("analysis_timeout", 300),
            )
            embed = build_sentiment_embed(report)
            ctx_summary, ctx_kwargs = sentiment_context(report)
            view = FollowUpView(
                source_command="sentiment",
                context_summary=ctx_summary,
                thread_context_kwargs=ctx_kwargs,
                bot=self.bot,
            )
            await interaction.followup.send(embed=embed, view=view)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏳ 舆情分析超时，请稍后重试")
        except Exception as exc:
            logger.error("Sentiment command failed: %s", exc, exc_info=True)
            await interaction.followup.send("⚠️ 舆情分析异常，请稍后重试")

    @app_commands.command(name="pulse", description="市场脉搏 — 热点+持仓相关新闻")
    async def pulse(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            from src.web.dependencies import get_sentiment_service
            from src.discord_bot.context_builders import sentiment_context
            from src.discord_bot.views import FollowUpView

            svc = get_sentiment_service()
            pulse_data = await asyncio.wait_for(
                asyncio.to_thread(svc.get_market_pulse),
                timeout=get_timeout("analysis_timeout", 300),
            )
            embed = build_pulse_embed(pulse_data)
            ctx_summary, ctx_kwargs = sentiment_context(pulse_data)
            view = FollowUpView(
                source_command="pulse",
                context_summary=ctx_summary,
                thread_context_kwargs=ctx_kwargs,
                bot=self.bot,
            )
            await interaction.followup.send(embed=embed, view=view)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏳ 市场脉搏超时，请稍后重试")
        except Exception as exc:
            logger.error("Pulse command failed: %s", exc, exc_info=True)
            await interaction.followup.send("⚠️ 市场脉搏异常，请稍后重试")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SentimentCommandsCog(bot))

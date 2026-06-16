"""Slash command: /portfolio."""

from __future__ import annotations

import asyncio
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from src.discord_bot.embeds.portfolio_card import build_portfolio_embed
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.portfolio")


class PortfolioCommandsCog(commands.Cog):
    """Portfolio diagnosis command."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @staticmethod
    def _diagnose() -> dict[str, Any]:
        from src.web.dependencies import get_portfolio_service, get_portfolio_store

        store = get_portfolio_store()
        portfolio_data = store.get_portfolio_data()
        positions = portfolio_data.get("positions", [])

        if not positions:
            return {
                "status": "empty",
                "message": "当前没有持仓记录，请先在前端添加持仓",
            }

        svc = get_portfolio_service()
        return svc.diagnose_portfolio(positions)

    @app_commands.command(name="portfolio", description="持仓诊断")
    async def portfolio(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            data = await asyncio.to_thread(self._diagnose)
        except Exception as exc:
            logger.error("Portfolio diagnosis failed: %s", exc, exc_info=True)
            await interaction.followup.send("❌ 持仓诊断失败，请稍后重试")
            return

        if data.get("status") == "empty":
            await interaction.followup.send(f"📂 {data['message']}")
            return
        if data.get("status") == "error":
            await interaction.followup.send(f"❌ {data.get('message', '诊断失败')}")
            return

        embed = build_portfolio_embed(data)

        from src.discord_bot.context_builders import portfolio_context
        from src.discord_bot.views import FollowUpView

        ctx_summary, ctx_kwargs = portfolio_context(data)
        view = FollowUpView(
            source_command="portfolio",
            context_summary=ctx_summary,
            thread_context_kwargs=ctx_kwargs,
            bot=self.bot,
        )
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PortfolioCommandsCog(bot))

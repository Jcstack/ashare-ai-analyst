"""Slash commands: /intel, /report — intelligence hub & analysis reports."""

from __future__ import annotations

import asyncio
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from src.discord_bot.embeds.intel_card import (
    build_intel_clusters_embed,
    build_intel_embed,
    build_intel_overview_embed,
    build_report_embed,
    build_report_list_embed,
)
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.intel")

_CATEGORY_CHOICES = [
    app_commands.Choice(name="全部", value="all"),
    app_commands.Choice(name="政策", value="policy"),
    app_commands.Choice(name="宏观", value="macro"),
    app_commands.Choice(name="行业", value="industry"),
    app_commands.Choice(name="公司", value="company"),
    app_commands.Choice(name="市场", value="market"),
    app_commands.Choice(name="全球", value="global"),
    app_commands.Choice(name="社交", value="social"),
    app_commands.Choice(name="社区", value="community"),
]

_SORT_CHOICES = [
    app_commands.Choice(name="最新", value="time"),
    app_commands.Choice(name="评分最高", value="score"),
]


class IntelCommandsCog(commands.Cog):
    """Intelligence hub feed, overview, clusters, and analysis report commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_feed(
        category: str | None,
        query: str | None,
        sort_by: str,
        limit: int,
    ) -> dict[str, Any]:
        from src.web.dependencies import get_intelligence_hub_service

        svc = get_intelligence_hub_service()
        return svc.get_feed(
            category=category,
            search=query,
            sort_by=sort_by,
            limit=limit,
        )

    @staticmethod
    def _get_overview() -> dict[str, Any]:
        from src.web.dependencies import get_intelligence_hub_service

        return get_intelligence_hub_service().get_overview()

    @staticmethod
    def _get_clusters() -> list[dict[str, Any]]:
        from src.web.dependencies import get_intelligence_hub_service

        result = get_intelligence_hub_service().get_event_clusters(
            days=7, min_sources=2
        )
        return result.get("clusters", [])

    @staticmethod
    def _get_reports(symbol: str | None, limit: int) -> dict[str, Any]:
        from src.web.dependencies import get_intel_report_service

        return get_intel_report_service().get_reports(symbol=symbol, limit=limit)

    @staticmethod
    def _get_report(report_id: str) -> dict[str, Any] | None:
        from src.web.dependencies import get_intel_report_service

        return get_intel_report_service().get_report(report_id)

    # ------------------------------------------------------------------
    # /intel — 情报 Feed
    # ------------------------------------------------------------------

    @app_commands.command(name="intel", description="情报中心 — 查看最新情报")
    @app_commands.describe(
        category="情报分类 (可选)",
        query="搜索关键词 (可选)",
        sort="排序方式 (可选)",
    )
    @app_commands.choices(category=_CATEGORY_CHOICES, sort=_SORT_CHOICES)
    async def intel(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str] | None = None,
        query: str | None = None,
        sort: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer()
        cat_val = category.value if category else None
        if cat_val == "all":
            cat_val = None
        sort_val = sort.value if sort else "time"

        try:
            result = await asyncio.to_thread(
                self._get_feed,
                cat_val,
                query,
                sort_val,
                12,
            )
        except Exception as exc:
            logger.error("Intel feed failed: %s", exc, exc_info=True)
            await interaction.followup.send("❌ 获取情报失败，请稍后重试")
            return

        items = result.get("items", [])
        total = result.get("total", len(items))
        embed = build_intel_embed(
            items,
            category=cat_val,
            query=query,
            total=total,
        )

        from src.discord_bot.context_builders import intel_context
        from src.discord_bot.views import FollowUpView

        ctx_summary, ctx_kwargs = intel_context(items, query)
        view = FollowUpView(
            source_command="intel",
            context_summary=ctx_summary,
            thread_context_kwargs=ctx_kwargs,
            bot=self.bot,
        )
        await interaction.followup.send(embed=embed, view=view)

    # ------------------------------------------------------------------
    # /intel-overview — 分类概览
    # ------------------------------------------------------------------

    @app_commands.command(name="intel-overview", description="情报中心 — 分类概览统计")
    async def intel_overview(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            overview = await asyncio.to_thread(self._get_overview)
        except Exception as exc:
            logger.error("Intel overview failed: %s", exc, exc_info=True)
            await interaction.followup.send("❌ 获取概览失败，请稍后重试")
            return

        embed = build_intel_overview_embed(overview)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /intel-hot — 热点事件聚合 (多源交叉验证)
    # ------------------------------------------------------------------

    @app_commands.command(name="intel-hot", description="情报中心 — 热点事件聚合")
    async def intel_hot(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            clusters = await asyncio.to_thread(self._get_clusters)
        except Exception as exc:
            logger.error("Intel clusters failed: %s", exc, exc_info=True)
            await interaction.followup.send("❌ 获取热点聚合失败，请稍后重试")
            return

        embed = build_intel_clusters_embed(clusters)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /report — 情报分析报告
    # ------------------------------------------------------------------

    @app_commands.command(name="report", description="情报分析报告 — 查看AI情报分析")
    @app_commands.describe(symbol="股票代码 (可选，筛选特定股票的报告)")
    async def report(
        self,
        interaction: discord.Interaction,
        symbol: str | None = None,
    ) -> None:
        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(self._get_reports, symbol, 10)
        except Exception as exc:
            logger.error("Intel reports failed: %s", exc, exc_info=True)
            await interaction.followup.send("❌ 获取分析报告失败，请稍后重试")
            return

        reports = result.get("reports", [])
        total = result.get("total", len(reports))

        if not reports:
            msg = "暂无情报分析报告"
            if symbol:
                msg = f"暂无 {symbol} 的情报分析报告"
            await interaction.followup.send(f"📋 {msg}")
            return

        # If only 1 report, show full detail; otherwise show list
        if len(reports) == 1:
            embed = build_report_embed(reports[0])
        else:
            embed = build_report_list_embed(reports, total=total)

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(IntelCommandsCog(bot))

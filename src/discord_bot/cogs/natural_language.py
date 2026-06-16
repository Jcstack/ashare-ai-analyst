"""Natural language message handler for #analyst-chat channel."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import discord
from discord.ext import commands

from src.discord_bot import split_message
from src.discord_bot.config import get_timeout
from src.discord_bot.embeds.capital_flow_card import build_capital_flow_embed
from src.discord_bot.embeds.intel_card import build_intel_embed
from src.discord_bot.embeds.market_card import build_market_embed
from src.discord_bot.embeds.recommendation_card import build_recommendation_embed
from src.discord_bot.embeds.stock_card import build_stock_embed
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.nl")

# Trade-intent keywords
_TRADE_KEYWORDS = re.compile(r"买入|卖出|加仓|减仓|清仓|止损|建仓")

# Market-overview keywords
_MARKET_KEYWORDS = re.compile(r"大盘|市场|行情|指数|走势|盘面|趋势|概况|涨跌|龙虎榜")

# Recommendation keywords
_RECOMMEND_KEYWORDS = re.compile(
    r"推荐|选股|荐股|牛股|好股|股票推荐|今日推荐|有什么好股"
)

# Intel / news keywords
_INTEL_KEYWORDS = re.compile(r"情报|新闻|资讯|消息|政策")

# Capital flow keywords
_FLOW_KEYWORDS = re.compile(r"资金|北向|南向|主力|流入|流出|融资|融券")

# Portfolio keywords
_PORTFOLIO_KEYWORDS = re.compile(r"持仓|仓位|诊断|组合|我的股票")

# Sentiment keywords
_SENTIMENT_KEYWORDS = re.compile(r"舆情|情绪|市场情绪|看涨|看跌|恐慌|贪婪|脉搏")

# Global market keywords
_GLOBAL_KEYWORDS = re.compile(r"全球|美股|港股|欧股|纳指|标普|恒生|黄金|原油|VIX")

# Concept board keywords
_CONCEPT_KEYWORDS = re.compile(r"概念|板块|题材|热点板块|板块轮动|热度")


def classify_message(text: str) -> tuple[str, dict[str, Any]]:
    """Classify a natural-language message into an intent.

    Returns:
        Tuple of (intent, context_dict).
        Intents: ``trade_intent``, ``stock_analysis``, ``market_overview``,
        ``recommend``, ``intel``, ``flow``, ``portfolio``, ``agent_qa``.
    """
    from src.web.dependencies import get_symbol_extractor

    extractor = get_symbol_extractor()
    symbols = extractor.extract(text)

    if symbols:
        symbol = symbols[0]
        if _TRADE_KEYWORDS.search(text):
            return ("trade_intent", {"symbol": symbol, "text": text})
        return ("stock_analysis", {"symbol": symbol})

    # Fast-path intents (no Agent needed)
    if _RECOMMEND_KEYWORDS.search(text):
        return ("recommend", {})

    if _SENTIMENT_KEYWORDS.search(text):
        return ("sentiment", {})

    if _GLOBAL_KEYWORDS.search(text):
        return ("global_market", {})

    if _CONCEPT_KEYWORDS.search(text):
        return ("concept", {})

    if _MARKET_KEYWORDS.search(text):
        return ("market_overview", {})

    if _INTEL_KEYWORDS.search(text):
        return ("intel", {"query": text})

    if _FLOW_KEYWORDS.search(text):
        return ("flow", {})

    if _PORTFOLIO_KEYWORDS.search(text):
        return ("portfolio", {})

    return ("agent_qa", {"question": text})


class NaturalLanguageCog(commands.Cog):
    """Parse free-form messages in the designated channel and route them."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore bots and thread messages (handled by AgentCommandsCog)
        if message.author.bot:
            return
        if isinstance(message.channel, discord.Thread):
            return

        from src.discord_bot.bot import AShareAnalystBot

        bot: AShareAnalystBot = self.bot  # type: ignore[assignment]

        # Only respond in the designated channel
        if message.channel.id != bot._channel_id:
            return

        text = message.content.strip()
        if not text:
            return

        intent, ctx = await asyncio.to_thread(classify_message, text)
        logger.info("NL classify: %r → %s", text[:50], intent)

        if intent == "stock_analysis":
            await self._handle_stock(message, ctx["symbol"])
        elif intent == "trade_intent":
            await self._handle_agent(message, text)
        elif intent == "market_overview":
            await self._handle_market(message)
        elif intent == "recommend":
            await self._handle_recommend(message)
        elif intent == "intel":
            await self._handle_intel(message, ctx.get("query"))
        elif intent == "flow":
            await self._handle_flow(message)
        elif intent == "portfolio":
            await self._handle_portfolio(message)
        elif intent == "sentiment":
            await self._handle_sentiment(message)
        elif intent == "global_market":
            await self._handle_global(message)
        elif intent == "concept":
            await self._handle_concept(message)
        else:
            await self._handle_agent(message, text)

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_stock(self, message: discord.Message, symbol: str) -> None:
        async with message.channel.typing():
            from src.discord_bot.cogs.stock_commands import StockCommandsCog
            from src.discord_bot.context_builders import stock_context
            from src.discord_bot.views import FollowUpView

            result = await asyncio.to_thread(StockCommandsCog._analyze, symbol)
            embed = build_stock_embed(result["analysis"], result.get("quote"))
            ctx_summary, ctx_kwargs = stock_context(
                symbol, result["analysis"], result.get("quote")
            )
            view = FollowUpView(
                source_command="stock",
                context_summary=ctx_summary,
                thread_context_kwargs=ctx_kwargs,
                bot=self.bot,
            )
            await message.reply(embed=embed, view=view)

    async def _handle_market(self, message: discord.Message) -> None:
        async with message.channel.typing():
            from src.web.dependencies import get_market_service
            from src.discord_bot.context_builders import market_context
            from src.discord_bot.views import FollowUpView

            indices = await asyncio.to_thread(get_market_service().get_market_indices)
            embed = build_market_embed(indices)
            ctx_summary, ctx_kwargs = market_context(indices)
            view = FollowUpView(
                source_command="market",
                context_summary=ctx_summary,
                thread_context_kwargs=ctx_kwargs,
                bot=self.bot,
            )
            await message.reply(embed=embed, view=view)

    async def _handle_recommend(self, message: discord.Message) -> None:
        async with message.channel.typing():
            from src.web.dependencies import get_recommendation_service
            from src.discord_bot.context_builders import recommend_context
            from src.discord_bot.views import FollowUpView

            svc = get_recommendation_service()
            recs = await asyncio.to_thread(svc.get_recommendations, style=None, limit=8)
            embed = build_recommendation_embed(recs)
            ctx_summary, ctx_kwargs = recommend_context(recs, None)
            view = FollowUpView(
                source_command="recommend",
                context_summary=ctx_summary,
                thread_context_kwargs=ctx_kwargs,
                bot=self.bot,
            )
            await message.reply(embed=embed, view=view)

    async def _handle_intel(self, message: discord.Message, query: str | None) -> None:
        async with message.channel.typing():
            from src.web.dependencies import get_intelligence_hub_service
            from src.discord_bot.context_builders import intel_context
            from src.discord_bot.views import FollowUpView

            svc = get_intelligence_hub_service()
            result = await asyncio.to_thread(
                svc.get_feed,
                search=query,
                limit=8,
            )
            items = result.get("items", [])
            embed = build_intel_embed(items, query=query, total=result.get("total"))
            ctx_summary, ctx_kwargs = intel_context(items, query)
            view = FollowUpView(
                source_command="intel",
                context_summary=ctx_summary,
                thread_context_kwargs=ctx_kwargs,
                bot=self.bot,
            )
            await message.reply(embed=embed, view=view)

    async def _handle_flow(self, message: discord.Message) -> None:
        async with message.channel.typing():
            from src.web.dependencies import get_capital_flow_service
            from src.discord_bot.context_builders import flow_context
            from src.discord_bot.views import FollowUpView

            data = await asyncio.to_thread(
                get_capital_flow_service().get_macro_overview
            )
            embed = build_capital_flow_embed(data)
            ctx_summary, ctx_kwargs = flow_context(data)
            view = FollowUpView(
                source_command="flow",
                context_summary=ctx_summary,
                thread_context_kwargs=ctx_kwargs,
                bot=self.bot,
            )
            await message.reply(embed=embed, view=view)

    async def _handle_portfolio(self, message: discord.Message) -> None:
        async with message.channel.typing():
            from src.discord_bot.cogs.portfolio_commands import PortfolioCommandsCog
            from src.discord_bot.context_builders import portfolio_context
            from src.discord_bot.embeds.portfolio_card import build_portfolio_embed
            from src.discord_bot.views import FollowUpView

            data = await asyncio.to_thread(PortfolioCommandsCog._diagnose)
            if data.get("status") in ("empty", "error"):
                await message.reply(
                    f"\U0001f4c2 {data.get('message', '持仓诊断不可用')}"
                )
                return
            embed = build_portfolio_embed(data)
            ctx_summary, ctx_kwargs = portfolio_context(data)
            view = FollowUpView(
                source_command="portfolio",
                context_summary=ctx_summary,
                thread_context_kwargs=ctx_kwargs,
                bot=self.bot,
            )
            await message.reply(embed=embed, view=view)

    async def _handle_sentiment(self, message: discord.Message) -> None:
        async with message.channel.typing():
            from src.web.dependencies import get_sentiment_service
            from src.discord_bot.context_builders import sentiment_context
            from src.discord_bot.embeds.sentiment_card import build_sentiment_embed
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
            await message.reply(embed=embed, view=view)

    async def _handle_global(self, message: discord.Message) -> None:
        async with message.channel.typing():
            from src.web.dependencies import get_global_market_fetcher
            from src.discord_bot.context_builders import global_market_context
            from src.discord_bot.embeds.global_market_card import (
                build_global_market_embed,
            )
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
            await message.reply(embed=embed, view=view)

    async def _handle_concept(self, message: discord.Message) -> None:
        async with message.channel.typing():
            from src.web.dependencies import get_concept_board_service
            from src.discord_bot.context_builders import concept_context
            from src.discord_bot.embeds.concept_card import build_concept_embed
            from src.discord_bot.views import FollowUpView

            svc = get_concept_board_service()
            boards = await asyncio.wait_for(
                asyncio.to_thread(svc.fetch_concept_list),
                timeout=get_timeout("analysis_timeout", 300),
            )
            embed = build_concept_embed(boards)
            ctx_summary, ctx_kwargs = concept_context(boards)
            view = FollowUpView(
                source_command="concept",
                context_summary=ctx_summary,
                thread_context_kwargs=ctx_kwargs,
                bot=self.bot,
            )
            await message.reply(embed=embed, view=view)

    async def _handle_agent(self, message: discord.Message, text: str) -> None:
        # Send placeholder immediately so user knows we're working
        placeholder = await message.reply("\U0001f914 正在分析中，请稍候\u2026")

        import time

        from src.discord_bot.views import FollowUpView

        t0 = time.monotonic()
        try:
            from src.web.dependencies import get_agent_service
            from src.web.schemas.chat import ThreadContext

            svc = get_agent_service()
            _, reply = await asyncio.wait_for(
                svc.create_thread(text, ThreadContext(mode="general")),
                timeout=get_timeout("agent_timeout", 600),
            )
            reply_text = reply.content
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            logger.warning("Agent NL timed out after %.0fs for: %s", elapsed, text[:50])
            await placeholder.edit(
                content="\u23f3 Agent 超时（等待超过5分钟），请稍后重试"
            )
            return
        except Exception as exc:
            logger.error("Agent NL handler failed: %s", exc, exc_info=True)
            await placeholder.edit(content="\u26a0\ufe0f Agent 异常，请稍后重试")
            return

        elapsed = time.monotonic() - t0
        logger.info(
            "Agent NL completed in %.1fs, reply_len=%d for: %s",
            elapsed,
            len(reply_text),
            text[:50],
        )

        ctx_summary = f"自由问答: {text[:200]}"
        view = FollowUpView(
            source_command="ask",
            context_summary=ctx_summary,
            thread_context_kwargs={"mode": "general"},
            bot=self.bot,
        )
        chunks = split_message(reply_text)
        await placeholder.edit(content=chunks[0], view=view)
        for chunk in chunks[1:]:
            await message.channel.send(chunk)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NaturalLanguageCog(bot))

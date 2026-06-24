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
from src.discord_bot.embeds.stock_card import build_stock_embed
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.nl")

# Trade-intent keywords
_TRADE_KEYWORDS = re.compile(r"买入|卖出|加仓|减仓|清仓|止损|建仓")

# Quick buy/sell check: simple yes/no questions about a specific stock
_QUICK_CHECK = re.compile(
    r"能买|可以买|值得买|要买|能追|要追|能入手|可以入|该买|买不买|能卖|该卖|要卖"
)
_DEEP_OVERRIDE = re.compile(r"详细|深度|全面|仔细|完整")

# Execution feedback: user reports a completed trade
# Matches: "买了3000股平安银行 12.50" / "已买入 000001 3000股 @12.50" / "卖了500股茅台"
_EXECUTION_PATTERN = re.compile(
    r"(?:已|我)?(?P<action>买了|卖了|已买入|已卖出|成交|已成交|已执行)"
    r"\s*(?P<shares>\d+)\s*股\s*"
    r"(?P<name_or_code>\S+)"
    r"(?:\s*[@＠]?\s*(?P<price>\d+\.?\d*))?",
)

# Market-overview keywords
_MARKET_KEYWORDS = re.compile(r"大盘|市场|行情|指数|走势|盘面|趋势|概况|涨跌|龙虎榜")

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
        ``intel``, ``flow``, ``portfolio``, ``agent_qa``.
    """
    from src.web.dependencies import get_symbol_extractor

    extractor = get_symbol_extractor()
    symbols = extractor.extract(text)

    # Execution feedback: "买了3000股平安银行 12.50"
    exec_match = _EXECUTION_PATTERN.search(text)
    if exec_match:
        action_raw = exec_match.group("action")
        action = "buy" if "买" in action_raw else "sell"
        shares = int(exec_match.group("shares"))
        name_or_code = exec_match.group("name_or_code")
        price_str = exec_match.group("price")
        price = float(price_str) if price_str else None
        # Try to resolve symbol from name
        resolved = extractor.extract(name_or_code)
        symbol = resolved[0] if resolved else name_or_code
        return (
            "execution_feedback",
            {
                "symbol": symbol,
                "action": action,
                "shares": shares,
                "price": price,
                "name": name_or_code,
            },
        )

    if symbols:
        symbol = symbols[0]
        # Quick trade check: "能买X吗" → fast path (<30s)
        if _QUICK_CHECK.search(text) and not _DEEP_OVERRIDE.search(text):
            return ("quick_trade_check", {"symbol": symbol, "question": text})
        if _TRADE_KEYWORDS.search(text):
            return ("trade_intent", {"symbol": symbol, "text": text})
        return ("stock_analysis", {"symbol": symbol})

    # Fast-path intents (no Agent needed)
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

        if intent == "execution_feedback":
            await self._handle_execution_feedback(message, ctx)
        elif intent == "quick_trade_check":
            await self._handle_quick_trade_check(
                message, ctx["symbol"], ctx["question"]
            )
        elif intent == "stock_analysis":
            await self._handle_stock(message, ctx["symbol"])
        elif intent == "trade_intent":
            await self._handle_agent(message, text)
        elif intent == "market_overview":
            await self._handle_market(message)
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

    async def _handle_quick_trade_check(
        self,
        message: discord.Message,
        symbol: str,
        question: str,
    ) -> None:
        """Fast path: answer 'can I buy X?' in <30s without deep_analyze.

        Parallel-fetches realtime quote + fund flow timeline + portfolio,
        then makes a single LLM call with pre-built context.
        Falls back to full agent path on failure.
        """
        import time

        placeholder = await message.reply("\u26a1 快速检查中...")
        t0 = time.monotonic()

        try:
            from src.web.dependencies import (
                get_capital_service,
                get_llm_gateway,
                get_realtime_quote_manager,
                get_stock_service,
            )

            quote_mgr = get_realtime_quote_manager()
            stock_svc = get_stock_service()
            capital_svc = get_capital_service()

            # Parallel data fetch (~3s)
            quote_task = asyncio.to_thread(quote_mgr.get_single_quote, symbol)
            flow_task = asyncio.to_thread(
                stock_svc.fetcher.fetch_intraday_fund_flow_series, symbol
            )
            cash_task = asyncio.to_thread(capital_svc.get_overview)

            quote, flow, cash_info = await asyncio.wait_for(
                asyncio.gather(quote_task, flow_task, cash_task),
                timeout=15,
            )

            # Build compact context
            ctx_lines = []
            if quote:
                ctx_lines.append(
                    f"现价{quote.get('price', '-')} "
                    f"涨跌{quote.get('pct_change', '-')}% "
                    f"成交额{quote.get('amount', 0) / 1e8:.1f}亿"
                )
            if flow and isinstance(flow, list) and flow:
                last = flow[-1]
                main = last.get("main_net", 0)
                direction = "净流入" if main > 0 else "净流出"
                ctx_lines.append(
                    f"今日主力{direction}{abs(main) / 1e4:.0f}万 "
                    f"(共{len(flow)}个采样点)"
                )
            if cash_info and isinstance(cash_info, dict):
                cash = cash_info.get("available_cash", cash_info.get("cash", 0))
                ctx_lines.append(f"可用资金: {cash:.0f}元")
            context = "\n".join(ctx_lines) if ctx_lines else "数据获取中"

            # Single LLM call (~5-10s)
            from src.llm.base import LLMMessage

            gateway = get_llm_gateway()
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    gateway.complete,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "你是A股投资顾问。用大白话30秒内回答。必须包含:\n"
                                "1. 能否买入(明确结论)\n"
                                "2. 如果能买: 建议价位、数量(100股整数倍)、止损价\n"
                                "3. 如果不能: 原因\n"
                                "4. 主要风险\n"
                                "控制在200字内。"
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=f"{question}\n\n实时数据:\n{context}",
                        ),
                    ],
                    caller="quick_trade_check",
                    max_tokens=512,
                    temperature=0.2,
                    symbol=symbol,
                ),
                timeout=20,
            )

            elapsed = time.monotonic() - t0
            reply_text = response.text or "分析失败"
            reply_text += (
                f"\n\n_\u26a1 快速检查 {elapsed:.1f}s"
                f" | 如需详细分析请说「详细分析{symbol}」_"
            )

            await placeholder.edit(content=reply_text)
            logger.info(
                "Quick trade check %s completed in %.1fs",
                symbol,
                elapsed,
            )

        except Exception as exc:
            elapsed = time.monotonic() - t0
            logger.warning(
                "Quick trade check failed for %s after %.1fs: %s",
                symbol,
                elapsed,
                exc,
            )
            await placeholder.edit(content="\u26a1 快速检查失败，切换到深度分析...")
            await self._handle_agent(message, question)

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

    async def _handle_execution_feedback(
        self, message: discord.Message, ctx: dict[str, Any]
    ) -> None:
        """Handle user reporting a completed trade execution."""
        symbol = ctx["symbol"]
        action = ctx["action"]
        shares = ctx["shares"]
        price = ctx.get("price")
        name = ctx.get("name", symbol)

        if not price:
            await message.reply(
                f"\u2753 收到你{action}了{shares}股{name}，"
                f"请补充成交价格，例如：「买了{shares}股{name} 12.50」"
            )
            return

        action_cn = "买入" if action == "buy" else "卖出"
        try:
            from src.web.dependencies import get_trade_service

            trade_svc = get_trade_service()
            trade = await asyncio.to_thread(
                trade_svc.execute_trade,
                symbol=symbol,
                stock_name=name,
                action=action,
                shares=shares,
                price=price,
                reasoning=f"Discord反馈: 用户{action_cn}{shares}股@{price}",
            )
            await message.reply(
                f"\u2705 已记录: **{action_cn} {name}({symbol})** "
                f"{shares}股 @ \u00a5{price:.2f}\n"
                f"组合已更新 | 交易ID: `{trade.id[:8]}`"
            )
            logger.info(
                "Discord execution feedback: %s %s %d @ %.2f → trade %s",
                action,
                symbol,
                shares,
                price,
                trade.id,
            )
        except Exception as exc:
            logger.error("Failed to record execution from Discord: %s", exc)
            await message.reply(f"\u274c 记录失败: {exc}\n请通过Web端手动录入")

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

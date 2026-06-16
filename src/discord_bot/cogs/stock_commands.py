"""Slash commands: /stock, /quote."""

from __future__ import annotations

import asyncio
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from src.discord_bot.embeds.quote_card import build_quote_embed
from src.discord_bot.embeds.stock_card import build_stock_embed
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.stock")


class StockCommandsCog(commands.Cog):
    """Individual stock analysis and quote commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Helpers (sync — run via asyncio.to_thread)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_symbol(code: str) -> str:
        """Normalise user input to a 6-digit symbol."""
        code = code.strip().upper()
        # Strip common prefixes
        for prefix in ("SH", "SZ", "BJ"):
            if code.startswith(prefix):
                code = code[len(prefix) :]
        return code.zfill(6)

    @staticmethod
    def _get_quote(symbol: str) -> dict[str, Any]:
        from src.web.dependencies import get_realtime_quote_manager

        mgr = get_realtime_quote_manager()
        df = mgr.get_quotes([symbol])
        if df is not None and not df.empty:
            return df.iloc[0].to_dict()
        return {}

    @staticmethod
    def _analyze(symbol: str) -> dict[str, Any]:
        """Run comprehensive analysis (mirrors stocks.py route logic).

        Gathers all 10 data sources synchronously (this runs inside
        asyncio.to_thread so blocking is fine) and passes them to
        analyze_comprehensive_realtime for a full AI summary.
        """
        from src.data.registry import StockRegistry
        from src.web.dependencies import (
            get_realtime_analyzer,
            get_realtime_quote_manager,
            get_stock_service,
            get_strategy_context_service,
        )

        svc = get_stock_service()
        analyzer = get_realtime_analyzer()

        # 1. Quote (DI singleton)
        quote = None
        try:
            mgr = get_realtime_quote_manager()
            df = mgr.get_quotes([symbol])
            if df is not None and not df.empty:
                quote = df.iloc[0].to_dict()
        except Exception:
            pass

        # 2. Indicators
        indicators: dict = {}
        try:
            indicators = svc.get_indicators_summary(symbol) or {}
        except Exception:
            pass

        # 3. Fund flow (intraday)
        fund_flow: list[dict] = []
        try:
            df = svc.fetcher.fetch_intraday_fund_flow(symbol)
            if not df.empty:
                fund_flow = df.to_dict(orient="records")
        except Exception:
            pass

        # 4. Dragon tiger (last 7 days)
        dragon_tiger: list[dict] = []
        try:
            from datetime import datetime, timedelta

            end = datetime.now()
            start = end - timedelta(days=7)
            df = svc.fetcher.fetch_dragon_tiger(
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            if not df.empty:
                sym_col = (
                    "代码"
                    if "代码" in df.columns
                    else "symbol"
                    if "symbol" in df.columns
                    else None
                )
                if sym_col:
                    df = df[df[sym_col].astype(str).str.strip() == symbol.strip()]
                dragon_tiger = df.to_dict(orient="records")
        except Exception:
            pass

        # 5. Valuation
        valuation: dict = {}
        try:
            valuation = svc.fetcher.fetch_valuation_indicator(symbol)
        except Exception:
            pass

        # 6. Strategy signals
        strategy_signals: dict = {}
        try:
            strategy_ctx_svc = get_strategy_context_service()
            strategy_signals = strategy_ctx_svc.get_strategy_context(symbol)
        except Exception:
            pass

        # 7. Bayesian analysis
        bayesian: dict = {}
        try:
            strategy_ctx_svc = get_strategy_context_service()
            bayesian = strategy_ctx_svc.get_bayesian_context(symbol)
        except Exception:
            pass

        # 8. Fund flow detail
        fund_flow_detail: dict = {}
        try:
            df = svc.fetcher.fetch_fund_flow_detail(symbol)
            if not df.empty:
                fund_flow_detail = df.iloc[0].to_dict()
        except Exception:
            pass

        # 9. Board type & price limit
        board = StockRegistry.get_board(symbol)
        _BOARD_LABEL = {"star": "科创板", "chinext": "创业板", "main": "主板"}
        _PRICE_LIMIT = {"star": "±20%", "chinext": "±20%", "main": "±10%"}
        board_type = _BOARD_LABEL.get(board, "主板")
        price_limit = _PRICE_LIMIT.get(board, "±10%")

        # 10. Comprehensive analysis with all data sources
        try:
            result = analyzer.analyze_comprehensive_realtime(
                symbol,
                quote,
                fund_flow,
                dragon_tiger,
                indicators,
                strategy_signals=strategy_signals,
                bayesian_analysis=bayesian,
                board_type=board_type,
                price_limit=price_limit,
                valuation=valuation,
                fund_flow_detail=fund_flow_detail,
            )
            return {"analysis": result, "quote": quote}
        except Exception as exc:
            logger.warning("Analysis failed for %s: %s", symbol, exc)
            return {
                "analysis": {
                    "symbol": symbol,
                    "signal": "neutral",
                    "summary": "分析暂不可用",
                    "points": [],
                    "risks": [],
                },
                "quote": quote,
            }

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    @app_commands.command(name="stock", description="个股AI综合分析")
    @app_commands.describe(code="股票代码 (如 600519)")
    async def stock(self, interaction: discord.Interaction, code: str) -> None:
        await interaction.response.defer()
        symbol = self._resolve_symbol(code)
        result = await asyncio.to_thread(self._analyze, symbol)
        embed = build_stock_embed(result["analysis"], result.get("quote"))

        from src.discord_bot.context_builders import stock_context
        from src.discord_bot.views import FollowUpView

        ctx_summary, ctx_kwargs = stock_context(
            symbol, result["analysis"], result.get("quote")
        )
        view = FollowUpView(
            source_command="stock",
            context_summary=ctx_summary,
            thread_context_kwargs=ctx_kwargs,
            bot=self.bot,
        )
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="quote", description="实时行情快照")
    @app_commands.describe(code="股票代码 (如 600519)")
    async def quote(self, interaction: discord.Interaction, code: str) -> None:
        await interaction.response.defer()
        symbol = self._resolve_symbol(code)
        data = await asyncio.to_thread(self._get_quote, symbol)
        if not data or data.get("price") is None:
            await interaction.followup.send(f"⚠️ 无法获取 {symbol} 行情")
            return
        embed = build_quote_embed(data)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StockCommandsCog(bot))

"""Agent tool registry — wraps existing services as Anthropic tool_use tools.

Each tool is a thin wrapper around an existing service method, converting
its inputs/outputs to JSON-serializable formats suitable for the
Anthropic Messages API tool_use protocol.
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from src.utils.logger import get_logger

logger = get_logger("web.tool_registry")


def _load_prediction_from_redis(symbol: str) -> dict[str, Any]:
    """Load the latest prediction pipeline result from Redis."""
    try:
        from src.web.dependencies import get_redis

        r = get_redis()
        if not r:
            return {"error": "Redis unavailable"}
        raw = r.get(f"prediction:{symbol}")
        if not raw:
            return {"error": f"No prediction found for {symbol}"}
        return json.loads(raw)
    except Exception as exc:
        return {"error": str(exc)}


def _get_trend_candidates(min_score: int = 50, top_n: int = 10) -> list[dict]:
    """Get early-stage trend candidates from TrendHunter."""
    try:
        from src.quant.trend_hunter import TrendHunter

        hunter = TrendHunter()
        candidates = hunter.scan(top_n=max(top_n, 5))
        return [
            {
                "symbol": c.symbol,
                "name": c.name,
                "score": c.score,
                "pct_change": c.pct_change,
                "volume_ratio": c.volume_ratio,
                "price": c.price,
                "signals": c.signals,
                "sector": c.sector,
                "near_breakout": c.near_breakout,
            }
            for c in candidates
            if c.score >= min_score
        ][:top_n]
    except Exception as exc:
        return [{"error": str(exc)}]


_TOOL_TIMEOUT_SECONDS = 30
# LLM-backed tools (analyze_stock_detailed, get_stock_advice) need more time
_LLM_TOOL_TIMEOUT_SECONDS = 60
# deep_analyze builds full MarketSnapshot (15 parallel fetches) — needs more headroom
_DEEP_TOOL_TIMEOUT_SECONDS = 90


@dataclass
class ToolDefinition:
    """Internal registration entry for a tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]
    is_async: bool = False
    llm_backed: bool = False  # True for Tier 3+ tools that make inner LLM calls
    deep: bool = False  # True for heavy data tools (deep_analyze) needing 90s timeout
    tier: str = "extended"  # "core" = always loaded, "extended" = on-demand


# Tools always loaded with full schema (used in every heartbeat)
_CORE_TOOL_NAMES: set[str] = {
    "get_portfolio",
    "get_realtime_quote",
    "get_capital_balance",
    "get_market_pulse",
    "get_limit_up_pool",
    "get_sector_leaders",
    "get_trend_candidates",
    "get_opportunity_candidates",
    "evaluate_signals",
    "deep_analyze",
    "detect_sentiment_phase",
    "get_active_theses",
    "capital_flow_tool",
    "search_stocks",
    "get_trending_news",
    "record_manual_trade",
    "submit_buy_signal",
    "submit_sell_signal",
    "submit_hold_update",
    "load_tool_schema",
}


class ToolRegistry:
    """Registry of agent tools backed by existing domain services.

    Initialised with the FastAPI dependency-injected service singletons.
    Provides Anthropic-format tool definitions and a unified execute method.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return all tools in Anthropic tool_use JSON schema format."""
        return [
            {
                "name": td.name,
                "description": td.description,
                "input_schema": td.input_schema,
            }
            for td in self._tools.values()
        ]

    def get_core_definitions(self) -> list[dict[str, Any]]:
        """Return only core-tier tools with full schema.

        Extended tools are available via the load_tool_schema meta-tool.
        Saves ~75% of token overhead vs get_tool_definitions().
        """
        return [
            {
                "name": td.name,
                "description": td.description,
                "input_schema": td.input_schema,
            }
            for td in self._tools.values()
            if td.tier == "core"
        ]

    def get_extended_catalog(self) -> str:
        """Return a compact catalog of extended tools (name + description only).

        Injected into system prompt so the agent knows what's available
        and can call load_tool_schema(name) to load full schema on demand.
        """
        lines = []
        for td in self._tools.values():
            if td.tier != "core":
                lines.append(f"- {td.name}: {td.description[:80]}")
        if not lines:
            return ""
        return (
            "## 扩展工具（按需加载）\n"
            "以下工具可用但未加载。需要时调用 load_tool_schema(name) 加载后使用。\n"
            + "\n".join(lines)
        )

    def get_tool_schema(self, name: str) -> dict[str, Any] | None:
        """Return full schema for a single tool (used by load_tool_schema)."""
        td = self._tools.get(name)
        if td is None:
            return None
        return {
            "name": td.name,
            "description": td.description,
            "input_schema": td.input_schema,
        }

    async def execute(self, name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool by name and return JSON result string.

        Args:
            name: Registered tool name.
            tool_input: Input parameters (from Claude tool_use block).

        Returns:
            JSON-encoded result string.
        """
        td = self._tools.get(name)
        if td is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        if td.deep:
            timeout = _DEEP_TOOL_TIMEOUT_SECONDS
        elif td.llm_backed:
            timeout = _LLM_TOOL_TIMEOUT_SECONDS
        else:
            timeout = _TOOL_TIMEOUT_SECONDS
        start = time.perf_counter()
        try:
            if td.is_async:
                result = await asyncio.wait_for(
                    td.handler(**tool_input), timeout=timeout
                )
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(td.handler, **tool_input),
                    timeout=timeout,
                )

            elapsed = (time.perf_counter() - start) * 1000
            logger.info(
                "Tool %s executed in %.0fms",
                name,
                elapsed,
            )

            return _serialize(result)
        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning("Tool %s timed out after %ds", name, timeout)
            return json.dumps(
                {
                    "error": f"工具 {name} 执行超时 ({timeout}s)",
                    "tool": name,
                }
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                "Tool %s failed after %.0fms: %s",
                name,
                elapsed,
                exc,
            )
            logger.debug("Tool %s traceback:\n%s", name, traceback.format_exc(limit=3))
            return json.dumps(
                {
                    "error": str(exc),
                    "tool": name,
                }
            )

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[..., Any],
        *,
        is_async: bool = False,
        llm_backed: bool = False,
        deep: bool = False,
    ) -> None:
        """Register a tool.

        Args:
            name: Unique tool name.
            description: Human-readable description for Claude.
            input_schema: JSON Schema describing the tool input.
            handler: Callable implementing the tool logic.
            is_async: Whether the handler is an async coroutine.
            llm_backed: Whether this tool makes inner LLM calls (Tier 3+).
        """
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            is_async=is_async,
            llm_backed=llm_backed,
            deep=deep,
            tier="core" if name in _CORE_TOOL_NAMES else "extended",
        )

    def is_llm_backed(self, name: str) -> bool:
        """Check if a tool makes inner LLM calls."""
        td = self._tools.get(name)
        return td.llm_backed if td else False

    async def execute_parallel(
        self, calls: list[tuple[str, dict[str, Any]]]
    ) -> list[str]:
        """Execute multiple tool calls concurrently.

        Args:
            calls: List of (tool_name, tool_input) tuples.

        Returns:
            List of JSON result strings in the same order as calls.
        """
        if len(calls) == 1:
            return [await self.execute(calls[0][0], calls[0][1])]
        return list(
            await asyncio.gather(*(self.execute(name, inp) for name, inp in calls))
        )

    def register_all(self, deps: dict[str, Any]) -> None:
        """Register all agent tools using injected service singletons.

        Args:
            deps: Dict of service name → service instance from
                  ``dependencies.py`` getters.
        """
        self._register_data_tools(deps)
        self._register_analysis_tools(deps)
        self._register_portfolio_tools(deps)
        self._register_trade_tools(deps)
        self._register_capital_tools(deps)
        self._register_prediction_tools(deps)
        self._register_risk_tools(deps)
        self._register_quant_tools(deps)
        self._register_intel_tools(deps)
        self._register_fusion_tools(deps)
        self._register_intelligence_tools(deps)
        self._register_deep_analysis_tool(deps)
        self._register_intraday_tools(deps)
        self._register_advanced_tools(deps)
        self._register_agent_loop_tools(deps)

    # ------------------------------------------------------------------
    # Tier 1 — Data tools
    # ------------------------------------------------------------------

    def _register_data_tools(self, deps: dict[str, Any]) -> None:
        quote_manager = deps.get("realtime_quote_manager")
        if quote_manager:
            self.register(
                name="get_realtime_quote",
                description=(
                    "获取A股股票的实时行情数据，包括当前价格、涨跌幅、成交量、成交额等。"
                    "用于了解股票的最新市场表现。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "股票代码列表，如 ['600519', '300750']",
                        }
                    },
                    "required": ["symbols"],
                },
                handler=lambda symbols: quote_manager.get_quotes(symbols),
            )

        registry = deps.get("stock_registry")
        if registry:
            self.register(
                name="search_stocks",
                description=(
                    "搜索A股股票，支持按代码或名称模糊匹配。"
                    "返回匹配的股票列表（代码+名称+行业）。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词，如 '茅台' 或 '600519'",
                        }
                    },
                    "required": ["query"],
                },
                handler=lambda query: registry.search(query),
            )

        global_fetcher = deps.get("global_market_fetcher")
        if global_fetcher:
            self.register(
                name="get_global_markets",
                description=(
                    "获取全球市场概览，包括美股主要指数、港股、欧洲、"
                    "大宗商品、汇率等最新数据。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {},
                },
                handler=lambda: global_fetcher.fetch_global_snapshot(),
            )

        calendar = deps.get("trading_calendar")
        if calendar:
            self.register(
                name="check_trading_day",
                description=(
                    "检查指定日期是否为A股交易日，并返回下一个交易日。"
                    "不传日期则检查今天。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "日期字符串 YYYY-MM-DD，不传则为今天",
                        }
                    },
                },
                handler=lambda date=None: _check_trading_day(calendar, date),
            )

        news_aggregator = deps.get("trend_news_aggregator")
        if news_aggregator:
            self.register(
                name="get_trending_news",
                description=(
                    "获取最新的A股市场热点新闻和财经资讯。"
                    "返回热门新闻列表，按热度排序。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {},
                },
                handler=lambda: news_aggregator.fetch_all(),
            )

    # ------------------------------------------------------------------
    # Tier 2 — Analysis tools
    # ------------------------------------------------------------------

    def _register_analysis_tools(self, deps: dict[str, Any]) -> None:
        stock_service = deps.get("stock_service")
        if stock_service:
            self.register(
                name="get_technical_indicators",
                description=(
                    "获取个股技术指标汇总，包括均线(MA)、MACD、RSI、KDJ、"
                    "布林带等指标的当前值和信号。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码，如 '600519'",
                        }
                    },
                    "required": ["symbol"],
                },
                handler=lambda symbol: stock_service.get_indicators_summary(symbol),
            )

        concept_service = deps.get("concept_board_service")
        if concept_service:
            self.register(
                name="get_stock_concepts",
                description=(
                    "获取个股所属的概念板块列表，包括板块名称、涨跌幅、热度等。"
                    "用于分析个股的概念联动和板块共振。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码，如 '600519'",
                        }
                    },
                    "required": ["symbol"],
                },
                handler=lambda symbol: concept_service.fetch_stock_concepts(symbol),
            )

        concept_analyzer = deps.get("concept_analyzer")
        if concept_analyzer:
            self.register(
                name="get_concept_heat",
                description="获取当前概念板块热度排行，返回涨幅最大或关注度最高的概念。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "top_n": {
                            "type": "integer",
                            "description": "返回前 N 个概念，默认 10",
                            "default": 10,
                        }
                    },
                },
                handler=lambda top_n=10: concept_analyzer.rank_concepts(
                    top_n=int(top_n)
                ),
            )

        cross_market = deps.get("cross_market_analyzer")
        if cross_market:
            self.register(
                name="analyze_cross_market",
                description=(
                    "分析个股的跨市场关联影响，包括对应的美股/港股/大宗商品"
                    "标的表现及其对A股个股的潜在影响。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码，如 '600519'",
                        }
                    },
                    "required": ["symbol"],
                },
                handler=lambda symbol: cross_market.assess_cross_market_impact(symbol),
            )

    # ------------------------------------------------------------------
    # Tier 4 — Portfolio / watchlist tools
    # ------------------------------------------------------------------

    def _register_portfolio_tools(self, deps: dict[str, Any]) -> None:
        self.register(
            name="get_portfolio",
            description="获取用户当前的模拟持仓列表，包括持仓股票、数量、成本价、盈亏等。",
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=_read_portfolio,
        )

        stock_service = deps.get("stock_service")
        if stock_service:
            self.register(
                name="get_watchlist",
                description="获取用户的自选股列表。",
                input_schema={
                    "type": "object",
                    "properties": {},
                },
                handler=lambda: stock_service.get_watchlist(),
            )

    # ------------------------------------------------------------------
    # Tier 4 — Trade tools (stateful, side effects)
    # ------------------------------------------------------------------

    def _register_trade_tools(self, deps: dict[str, Any]) -> None:
        trade_service = deps.get("trade_service")
        if not trade_service:
            return

        execution_bridge = deps.get("execution_bridge")

        def _execute_trade_handler(
            symbol, stock_name, action, shares, price, reasoning=""
        ):
            """Route through execution bridge when available, else simulation."""
            if execution_bridge and execution_bridge.is_live_mode():
                result = execution_bridge.process_proposal(
                    symbol=symbol,
                    action=action,
                    shares=int(shares),
                    price=float(price),
                    stock_name=stock_name,
                    reasoning=reasoning,
                )
                return {
                    "status": result.status,
                    "gate_request_id": result.gate_request_id,
                    "broker_order_id": result.broker_order_id,
                    "reason": result.reason,
                    "message": (
                        f"{result.status}: {action} {symbol} {shares}股 @ {price}元"
                    ),
                }
            return trade_service.execute_trade(
                symbol=symbol,
                stock_name=stock_name,
                action=action,
                shares=shares,
                price=price,
                reasoning=reasoning,
            )

        is_live = execution_bridge and execution_bridge.is_live_mode()
        trade_desc = (
            "执行交易（买入/卖出/加仓/减仓）。订单将通过风控预检后提交至券商。"
            if is_live
            else "执行一笔模拟交易（买入/卖出/加仓/减仓）。"
            "交易将记录到用户的模拟持仓中。"
        )

        self.register(
            name="execute_trade",
            description=trade_desc,
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码，如 '600519'",
                    },
                    "stock_name": {
                        "type": "string",
                        "description": "股票名称，如 '贵州茅台'",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["buy", "sell", "add", "reduce"],
                        "description": "交易类型: buy(买入), sell(卖出), add(加仓), reduce(减仓)",
                    },
                    "shares": {
                        "type": "integer",
                        "description": "交易股数（100的整数倍）",
                    },
                    "price": {
                        "type": "number",
                        "description": "交易价格（元）",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "交易理由",
                    },
                },
                "required": ["symbol", "stock_name", "action", "shares", "price"],
            },
            handler=_execute_trade_handler,
        )

        self.register(
            name="record_manual_trade",
            description=(
                "记录用户手动同步的交易。当用户告知已在券商完成实际交易时，"
                "调用此工具记录到系统中以保持持仓同步。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码",
                    },
                    "stock_name": {
                        "type": "string",
                        "description": "股票名称",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["buy", "sell", "add", "reduce"],
                        "description": "交易类型",
                    },
                    "shares": {
                        "type": "integer",
                        "description": "交易股数",
                    },
                    "price": {
                        "type": "number",
                        "description": "交易价格（元）",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "交易理由或备注",
                    },
                },
                "required": ["symbol", "stock_name", "action", "shares", "price"],
            },
            handler=lambda symbol, stock_name, action, shares, price, reasoning="": (
                trade_service.record_manual_trade(
                    symbol=symbol,
                    stock_name=stock_name,
                    action=action,
                    shares=shares,
                    price=price,
                    reasoning=reasoning,
                )
            ),
        )

        self.register(
            name="get_trade_history",
            description=(
                "查询交易历史记录。可按股票代码筛选。返回最近的交易记录列表。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "可选：按股票代码筛选",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回记录数量，默认 20",
                        "default": 20,
                    },
                },
            },
            handler=lambda symbol=None, limit=20: trade_service.get_trade_history(
                symbol=symbol, limit=limit
            ),
        )

    # ------------------------------------------------------------------
    # Tier 4 — Capital tools
    # ------------------------------------------------------------------

    def _register_capital_tools(self, deps: dict[str, Any]) -> None:
        capital_service = deps.get("capital_service")
        if capital_service:
            self.register(
                name="get_capital_balance",
                description=(
                    "查询用户的资金账户状态，包括可用现金、持仓市值、总资产、"
                    "资金使用率。用于在给出买入建议前确认用户可用资金。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {},
                },
                handler=lambda: capital_service.get_breakdown(),
            )

        capital_flow_service = deps.get("capital_flow_service")
        if capital_flow_service:
            self.register(
                name="capital_flow_tool",
                description=(
                    "查询资金流向数据，包括宏观资金面评分、板块资金流排行、个股资金流。"
                    "query_type='macro' 返回宏观资金面概览（北向、南向、融资、ETF净流入及综合评分）；"
                    "query_type='sector' 返回行业/概念板块资金流排行；"
                    "query_type='stock' 返回个股资金流详情（需提供 symbol）。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query_type": {
                            "type": "string",
                            "enum": ["macro", "sector", "stock"],
                            "description": "查询类型: macro(宏观资金面), sector(板块排行), stock(个股资金流)",
                        },
                        "symbol": {
                            "type": "string",
                            "description": "股票代码（query_type='stock' 时必填），如 '600519'",
                        },
                        "period": {
                            "type": "string",
                            "enum": ["today", "3d", "5d"],
                            "description": "时间范围，默认 'today'",
                        },
                    },
                    "required": ["query_type"],
                },
                handler=lambda query_type, symbol=None, period="today": (
                    _handle_capital_flow(
                        capital_flow_service, query_type, symbol, period
                    )
                ),
            )

    # ------------------------------------------------------------------
    # Tier 3 — Prediction / advisor tools (LLM-backed, higher latency)
    # ------------------------------------------------------------------

    def _register_prediction_tools(self, deps: dict[str, Any]) -> None:
        advisor_service = deps.get("advisor_service")
        if advisor_service:
            self.register(
                name="get_stock_advice",
                description=(
                    "获取个股的专业买卖建议，包括操作方向、止损位、仓位建议、"
                    "核心理由和风险提示。基于技术面+资金面+消息面综合研判。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码，如 '600519'",
                        }
                    },
                    "required": ["symbol"],
                },
                handler=lambda symbol: advisor_service.get_stock_advice(symbol),
                llm_backed=True,
            )

            self.register(
                name="get_portfolio_advice",
                description=(
                    "诊断用户的持仓组合，评估组合健康度，给出加仓/减仓/调仓建议。"
                    "传入持仓列表，每个持仓包含 symbol、shares、cost_price 字段。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "positions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "symbol": {"type": "string"},
                                    "shares": {"type": "integer"},
                                    "cost_price": {"type": "number"},
                                },
                            },
                            "description": "持仓列表",
                        }
                    },
                    "required": ["positions"],
                },
                handler=lambda positions: advisor_service.get_portfolio_advice(
                    positions
                ),
                llm_backed=True,
            )

            self.register(
                name="get_holiday_impact",
                description=(
                    "评估假期对个股的潜在影响，包括全球市场联动、"
                    "假期消息面分析、开盘预判。适合长假前后使用。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码，如 '600519'",
                        }
                    },
                    "required": ["symbol"],
                },
                handler=lambda symbol: advisor_service.get_holiday_impact(symbol),
                llm_backed=True,
            )

        # Prediction pipeline results (stored in Redis by task_predict_all)
        self.register(
            name="get_prediction_summary",
            description=(
                "获取最近一次AI量化预测结果（每天17:00自动生成）。"
                "包含趋势判断、信号方向、置信度、关键因素和风险警告。"
                "用于在交易决策前参考量化分析的结论。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码，如 '600519'",
                    }
                },
                "required": ["symbol"],
            },
            handler=lambda symbol: _load_prediction_from_redis(symbol),
        )

        # Early trend detection (v61.0 Hunter Mode)
        self.register(
            name="get_trend_candidates",
            description=(
                "扫描全市场寻找趋势刚启动的股票（不是已涨停的）。"
                "找的是：底部放量+板块聚集+即将突破的票，涨幅<7%还能买入。"
                "比涨停池更有价值——发现猎物在它起飞前。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "min_score": {
                        "type": "integer",
                        "description": "最低评分（默认50）",
                        "default": 50,
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "返回数量（默认10）",
                        "default": 10,
                    },
                },
            },
            handler=lambda min_score=50, top_n=10: _get_trend_candidates(
                int(min_score), int(top_n)
            ),
        )

        sentiment_service = deps.get("sentiment_service")
        if sentiment_service:
            self.register(
                name="get_sentiment_report",
                description=(
                    "获取市场情绪脉搏报告，包括舆情热度、多空力量对比、"
                    "热点事件、板块情绪等。可选传入自选股筛选相关舆情。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "watchlist": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选的股票代码列表，筛选相关舆情",
                        }
                    },
                },
                handler=lambda watchlist=None: sentiment_service.get_market_pulse(
                    watchlist=watchlist
                ),
                llm_backed=True,
            )

        prediction_service = deps.get("prediction_service")
        if prediction_service:
            self.register(
                name="analyze_stock_detailed",
                description=(
                    "对个股进行深度分析，包含技术面、资金面、基本面等多维度研判。"
                    "返回结构化的分析结果和趋势预测。比 get_stock_advice 更详细，"
                    "适合用户需要深度了解个股时使用。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码，如 '600519'",
                        }
                    },
                    "required": ["symbol"],
                },
                handler=lambda symbol: prediction_service.predict(symbol),
                llm_backed=True,
            )

        backtest_service = deps.get("backtest_service")
        if backtest_service:
            self.register(
                name="backtest_strategy",
                description=(
                    "对个股运行策略回测，评估历史表现。"
                    "支持 trend_following（趋势跟踪）、mean_reversion（均值回归）、"
                    "momentum（动量策略）三种策略。"
                    "返回年化收益、最大回撤、胜率等指标。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码，如 '600519'",
                        },
                        "strategy_key": {
                            "type": "string",
                            "enum": [
                                "trend_following",
                                "mean_reversion",
                                "momentum",
                            ],
                            "description": "策略类型",
                        },
                    },
                    "required": ["symbol", "strategy_key"],
                },
                handler=lambda symbol, strategy_key: backtest_service.run_backtest(
                    symbol=symbol, strategy_key=strategy_key
                ),
            )

    # ------------------------------------------------------------------
    # Tier 5 — Risk tools (v17.0)
    # ------------------------------------------------------------------

    def _register_risk_tools(self, deps: dict[str, Any]) -> None:
        var_calc = deps.get("var_calculator")
        if var_calc:
            self.register(
                name="calculate_var",
                description=(
                    "计算投资组合的 VaR（风险价值）和 CVaR（条件风险价值），"
                    "支持历史模拟法、参数法和蒙特卡洛法。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "returns": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "日收益率序列",
                        },
                        "portfolio_value": {
                            "type": "number",
                            "description": "投资组合总市值",
                        },
                        "confidence_level": {
                            "type": "number",
                            "description": "置信水平，默认 0.95",
                        },
                    },
                    "required": ["returns", "portfolio_value"],
                },
                handler=lambda returns, portfolio_value, confidence_level=0.95: (
                    {"error": "returns array is empty, need at least 5 data points"}
                    if not returns or len(returns) < 5
                    else _serialize_risk_results(
                        var_calc.calculate_all(
                            returns, portfolio_value, confidence_level
                        )
                    )
                ),
            )

        stress_tester = deps.get("stress_tester")
        if stress_tester:
            self.register(
                name="run_stress_test",
                description=(
                    "对持仓进行压力测试。支持 3 个预设场景: "
                    "crash_2015(2015股灾), covid_2020(新冠疫情), "
                    "realestate_2022(地产危机)，以及自定义冲击。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "scenario_id": {
                            "type": "string",
                            "description": "场景ID: crash_2015/covid_2020/realestate_2022",
                        },
                        "positions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "symbol": {"type": "string"},
                                    "stock_name": {"type": "string"},
                                    "current_value": {"type": "number"},
                                    "sector": {"type": "string"},
                                },
                            },
                            "description": "持仓列表",
                        },
                    },
                    "required": ["scenario_id", "positions"],
                },
                handler=lambda scenario_id, positions: stress_tester.run_scenario(
                    scenario_id, positions
                ),
            )

            self.register(
                name="list_stress_scenarios",
                description="列出所有可用的压力测试场景。",
                input_schema={"type": "object", "properties": {}},
                handler=lambda: stress_tester.list_scenarios(),
            )

        position_sizer = deps.get("position_sizer")
        if position_sizer:
            self.register(
                name="calculate_position_size",
                description=(
                    "计算个股建议仓位大小，基于 Kelly 公式 + 波动率缩放，"
                    "自动按 A 股 100 股整数手调整，单仓不超过 30%。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码",
                        },
                        "portfolio_value": {
                            "type": "number",
                            "description": "总资金",
                        },
                        "current_price": {
                            "type": "number",
                            "description": "当前股价",
                        },
                        "win_rate": {
                            "type": "number",
                            "description": "胜率 (0-1)",
                        },
                        "avg_win": {
                            "type": "number",
                            "description": "平均盈利幅度",
                        },
                        "avg_loss": {
                            "type": "number",
                            "description": "平均亏损幅度",
                        },
                    },
                    "required": ["symbol", "portfolio_value", "current_price"],
                },
                handler=lambda symbol, portfolio_value, current_price, win_rate=0.5, avg_win=0.05, avg_loss=0.03: (
                    position_sizer.calculate_size(
                        symbol,
                        portfolio_value,
                        current_price,
                        win_rate,
                        avg_win,
                        avg_loss,
                    )
                ),
            )

        circuit_breaker = deps.get("circuit_breaker")
        if circuit_breaker:
            self.register(
                name="check_circuit_breaker",
                description=(
                    "检查组合熔断状态。日亏损超 15% 触发日熔断，"
                    "周亏损超 25% 触发周暂停。返回当前状态和是否可以交易。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "daily_pnl_pct": {
                            "type": "number",
                            "description": "今日组合收益率",
                        },
                        "weekly_pnl_pct": {
                            "type": "number",
                            "description": "本周累计收益率",
                        },
                    },
                    "required": ["daily_pnl_pct", "weekly_pnl_pct"],
                },
                handler=lambda daily_pnl_pct, weekly_pnl_pct: circuit_breaker.check(
                    daily_pnl_pct, weekly_pnl_pct
                ),
            )

    # ------------------------------------------------------------------
    # Tier 6 — Quant tools (v18.0 Phase 4)
    # ------------------------------------------------------------------

    def _register_quant_tools(self, deps: dict[str, Any]) -> None:
        signal_lib = deps.get("signal_library")
        if signal_lib:
            self.register(
                name="evaluate_signals",
                description=(
                    "对个股进行技术信号评估，使用内置信号库（MA交叉、RSI极值、"
                    "布林带突破、放量突破、MACD背离）。返回多空共识和综合评分。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "closes": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "收盘价序列（至少30个数据点）",
                        },
                        "volumes": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "成交量序列（可选，与 closes 等长）",
                        },
                        "signal_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要评估的信号名称列表，不传则评估全部",
                        },
                    },
                    "required": ["closes"],
                },
                handler=lambda closes, volumes=None, signal_names=None: (
                    signal_lib.evaluate(closes, volumes, signal_names)
                ),
            )

        regime_detector = deps.get("regime_detector")
        if regime_detector:
            self.register(
                name="detect_regime",
                description=(
                    "检测当前市场所处的 regime（低波动/中波动/高波动），"
                    "基于滚动波动率分位数方法。返回 regime 历史、转移矩阵和分布。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "daily_returns": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "日收益率序列（至少60个数据点）",
                        },
                        "dates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "日期序列（YYYY-MM-DD），与 daily_returns 等长",
                        },
                    },
                    "required": ["daily_returns"],
                },
                handler=lambda daily_returns, dates=None: regime_detector.detect(
                    daily_returns, dates
                ),
            )

        walk_forward = deps.get("walk_forward_validator")
        if walk_forward:
            self.register(
                name="run_walk_forward",
                description=(
                    "运行滚动窗口验证（Walk-Forward Validation），"
                    "检测策略过拟合和样本外降级。返回各窗口的 Sharpe 比率"
                    "和整体稳健性评估。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "daily_returns": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "日收益率序列",
                        },
                        "trade_dates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "交易日期列表（YYYY-MM-DD），可选",
                        },
                        "dates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "日期序列（YYYY-MM-DD），与 daily_returns 等长",
                        },
                    },
                    "required": ["daily_returns"],
                },
                handler=lambda daily_returns, trade_dates=None, dates=None: (
                    walk_forward.validate(daily_returns, trade_dates, dates)
                ),
            )

        feature_store = deps.get("feature_store")
        if feature_store:
            self.register(
                name="get_features",
                description=(
                    "获取指定股票的全部已缓存特征值（动量、波动率、均值回归等）。"
                    "返回特征列表及其计算时间和有效期。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码，如 '600519'",
                        },
                    },
                    "required": ["symbol"],
                },
                handler=lambda symbol: feature_store.get_all(symbol),
            )
            self.register(
                name="put_feature",
                description=(
                    "缓存一个计算好的特征值（如 RSI、波动率等）。"
                    "支持设置有效期（TTL）。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码，如 '600519'",
                        },
                        "name": {
                            "type": "string",
                            "description": "特征名称，如 'rsi_14'",
                        },
                        "category": {
                            "type": "string",
                            "description": "特征分类：momentum, volatility, mean_reversion 等",
                        },
                        "value": {
                            "description": "特征计算结果（数值或对象）",
                        },
                        "ttl": {
                            "type": "integer",
                            "description": "缓存有效期（秒），不填则使用默认值",
                        },
                    },
                    "required": ["symbol", "name", "category", "value"],
                },
                handler=lambda symbol, name, category, value, ttl=None: (
                    feature_store.put(
                        symbol,
                        _make_feature_def(name, category),
                        value,
                        ttl,
                    )
                ),
            )

    # ------------------------------------------------------------------
    # Tier 7 — Intelligence Hub tools
    # ------------------------------------------------------------------

    def _register_intel_tools(self, deps: dict[str, Any]) -> None:
        intel_hub = deps.get("intelligence_hub_service")
        if not intel_hub:
            return

        self.register(
            name="search_intel",
            description=(
                "搜索情报中心的最新资讯。可按关键词搜索、按分类筛选、"
                "按关联股票筛选。返回匹配的情报列表（标题、摘要、分类、关联标的、来源）。"
                "**分析个股时必须调用此工具获取该股票相关情报**。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "搜索关键词，如 '锂电池' 或 '降息'",
                    },
                    "symbol": {
                        "type": "string",
                        "description": "按关联股票代码筛选，如 '600519'",
                    },
                    "category": {
                        "type": "string",
                        "description": "按分类筛选，如 'policy'、'market'、'industry'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数，默认 10，最多 30",
                        "default": 10,
                    },
                },
            },
            handler=lambda search=None, symbol=None, category=None, limit=10: (
                _search_intel(intel_hub, search, symbol, category, min(int(limit), 30))
            ),
        )

        # Web search tool (联网搜索)
        web_search_svc = deps.get("web_search_service")
        if web_search_svc:
            self.register(
                name="web_search",
                description=(
                    "联网搜索工具 — 通过 DuckDuckGo 搜索最新的新闻、公告、研报等信息。"
                    "当本地情报库（search_intel）没有找到足够的相关信息时，"
                    "使用此工具联网获取最新资讯。支持搜索新闻（news）和网页（text）。"
                    "\n⚠️ 调用限制：5 分钟内最多 10 次。请合并多个关键词为一次搜索，"
                    "避免对每只股票单独搜索。触发限流后请勿重试，改用已有数据分析。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词，如 '博纳影业 票房' 或 '宁德时代 最新消息'",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "返回条数，默认 5，最多 10",
                            "default": 5,
                        },
                        "search_type": {
                            "type": "string",
                            "enum": ["text", "news"],
                            "description": "搜索类型: text(网页搜索), news(新闻搜索)",
                            "default": "text",
                        },
                    },
                    "required": ["query"],
                },
                handler=lambda query, max_results=5, search_type="text": (
                    web_search_svc.search(
                        query,
                        max_results=int(max_results),
                        search_type=search_type,
                    )
                ),
            )

    # ------------------------------------------------------------------
    # Tier 8 — Signal Fusion tools (Phase 4)
    # ------------------------------------------------------------------

    def _register_fusion_tools(self, deps: dict[str, Any]) -> None:
        fusion_engine = deps.get("fusion_engine")
        if not fusion_engine:
            return

        self.register(
            name="get_fusion_signal",
            description=(
                "获取指定股票的多源融合信号（量化+情报+技术面+宏观）。"
                "返回各信号源评分、加权融合置信度和综合信号判断。"
                "用于综合评估个股的多维度信号强度。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码，如 '600519'",
                    },
                },
                "required": ["symbol"],
            },
            handler=lambda symbol: fusion_engine.fuse(symbol),
        )

        self.register(
            name="get_alpha_factors",
            description=(
                "获取Qlib量化alpha因子值（动量、波动率、换手率等）。"
                "当Qlib不可用时返回 null。用于量化维度的个股评估。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码，如 '600519'",
                    },
                },
                "required": ["symbol"],
            },
            handler=lambda symbol: fusion_engine.get_alpha_factors(symbol),
        )

    def _register_intelligence_tools(self, deps: dict[str, Any]) -> None:
        """Register v34.0 intelligent investment agent tools."""

        # --- Impact Chain ---
        self.register(
            name="analyze_impact_chain",
            description=(
                "分析宏观事件的影响链传导路径。输入事件描述（如'中东战争'、'美元走强'），"
                "返回从事件到受影响板块和个股的传导链，包括方向、强度和时滞。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "event_text": {
                        "type": "string",
                        "description": "事件描述，如 '中东战争导致原油价格飙升'",
                    },
                },
                "required": ["event_text"],
            },
            handler=lambda event_text: _handle_impact_chain(event_text),
        )

        # --- Position Macro Analysis ---
        self.register(
            name="analyze_position_macro",
            description=(
                "分析持仓标的在当前宏观环境下的敏感度和轮动信号。"
                "返回宏观评分、轮动建议（hold/reduce/exit/add）及主要影响因素。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码，如 '002155'",
                    },
                    "name": {
                        "type": "string",
                        "description": "股票名称",
                        "default": "",
                    },
                },
                "required": ["symbol"],
            },
            handler=lambda symbol, name="": _handle_position_macro(symbol, name),
        )

        # --- Portfolio Rotation Scan ---
        self.register(
            name="scan_portfolio_rotation",
            description=(
                "扫描全部持仓的宏观敏感度，生成轮动建议。"
                "当持仓受宏观压力时，推荐受益板块的替代标的（仅主板）。"
                "返回包含卖出建议和买入候选的完整轮动方案。"
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=lambda: _handle_rotation_scan(),
        )

        # --- Munger Checklist ---
        self.register(
            name="run_munger_checklist",
            description=(
                "对指定股票运行芒格心理模型检查清单（6项检查）："
                "安全边际、能力圈、逆向思维、激励偏差、锚定效应、可得性偏差。"
                "返回每项检查结果和阻断/警告标记。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码",
                    },
                    "name": {
                        "type": "string",
                        "description": "股票名称",
                        "default": "",
                    },
                    "current_price": {
                        "type": "number",
                        "description": "当前价格（可选）",
                    },
                    "fair_value": {
                        "type": "number",
                        "description": "合理估值（可选）",
                    },
                    "recent_gain_pct": {
                        "type": "number",
                        "description": "近5日涨幅%（可选）",
                    },
                    "news_count_24h": {
                        "type": "integer",
                        "description": "24小时新闻数量（可选）",
                        "default": 0,
                    },
                },
                "required": ["symbol"],
            },
            handler=lambda **kwargs: _handle_munger_checklist(**kwargs),
        )

        # --- Bull/Bear Debate ---
        self.register(
            name="run_debate",
            description=(
                "对指定股票运行多空辩论分析。收集做多和做空论据，"
                "裁决给出行动建议（buy/sell/hold）、胜率估计和风险收益比。"
                "包含风控否决和芒格检查清单集成。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码",
                    },
                    "name": {
                        "type": "string",
                        "description": "股票名称",
                        "default": "",
                    },
                    "trigger": {
                        "type": "string",
                        "description": "触发辩论的原因",
                        "default": "agent request",
                    },
                },
                "required": ["symbol"],
            },
            handler=lambda **kwargs: _handle_debate(**kwargs),
        )

        # --- Trading Constraint Check ---
        self.register(
            name="check_trading_constraints",
            description=(
                "检查股票是否满足交易约束（板块权限、追涨限制、流动性等）。"
                "返回通过/阻断状态和具体违规项。仅主板可交易。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码",
                    },
                    "name": {
                        "type": "string",
                        "description": "股票名称",
                        "default": "",
                    },
                },
                "required": ["symbol"],
            },
            handler=lambda symbol, name="", stock_name="", **_kw: (
                _handle_constraint_check(symbol, name or stock_name)
            ),
        )

        logger.info("Registered 6 intelligence tools (v34.0)")

    # ------------------------------------------------------------------
    # Tier 9 — Deep Analysis (trading-loop grade context)
    # ------------------------------------------------------------------

    def _register_deep_analysis_tool(self, deps: dict[str, Any]) -> None:
        """Register deep analysis tool that uses ContextBuilder + DecisionPipeline.

        This gives agent chat the same analytical depth as the trading loop:
        MarketSnapshot with 8 dimension blocks (quant, funds, intel, regime,
        portfolio, risk, macro, thesis) built in parallel via ContextBuilder.
        """
        self.register(
            name="deep_analyze",
            description=(
                "Deep-analyze a stock using the same engine as the autonomous trading loop. "
                "Builds a full MarketSnapshot in parallel across 15+ dimensions: "
                "realtime quotes, capital flow, intelligence/news, quant signals (VWAP/VPIN), "
                "multi-timeframe confirmation, reflexivity state, sentiment cycle phase, "
                "portfolio position, risk state, macro indicators, geopolitical tone, "
                "and active thesis. Returns the complete snapshot text plus a structured "
                "investment decision (action, confidence, entry range, stop-loss, target, "
                "position size, holding period, invalidation trigger).\n\n"
                "PREFER this tool over calling get_realtime_quote + search_intel separately. "
                "One call gives you all the context you need for professional-grade analysis."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "6-digit A-share stock code, e.g. '600519'",
                    },
                    "stock_name": {
                        "type": "string",
                        "description": "Stock name (optional, auto-resolved if omitted)",
                        "default": "",
                    },
                },
                "required": ["symbol"],
            },
            handler=lambda symbol, stock_name="": _handle_deep_analyze(
                symbol, stock_name
            ),
            is_async=False,
            deep=True,
        )
        logger.info("Registered deep_analyze tool (trading-loop grade)")

    # ------------------------------------------------------------------
    # Tier 1.5 — Intraday tools (v55.0)
    # ------------------------------------------------------------------

    def _register_intraday_tools(self, deps: dict[str, Any]) -> None:
        """Register real-time intraday data tools for trading-hour sessions.

        These give InvestorAgent the same intraday visibility that Agent Chat
        has via MCP tools — minute-level fund flow, patterns, bars, etc.
        """
        stock_service = deps.get("stock_service")
        minute_bar_fetcher = deps.get("minute_bar_fetcher")

        # --- Tool 1: Intraday fund flow timeline (30-min samples) ---
        if stock_service:
            self.register(
                name="get_intraday_fund_flow_timeline",
                description=(
                    "获取个股盘中资金流时间线（30分钟采样），"
                    "含主力/超大单/大单/中单/小单净流入时序。"
                    "用于判断资金日内流向趋势（如持续流入/流出/反转）。"
                    "返回约8-10个采样点覆盖全天交易时段。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码，如 '600519'",
                        }
                    },
                    "required": ["symbol"],
                },
                handler=lambda symbol: (
                    stock_service.fetcher.fetch_intraday_fund_flow_series(symbol)
                ),
            )

        # --- Tool 2: Intraday pattern detection (8 A-share patterns) ---
        if stock_service and minute_bar_fetcher:

            def _detect_intraday_patterns(symbol: str) -> list[dict]:
                from src.agent_loop.intraday_patterns import IntradayPatternDetector
                from src.data.realtime import RealtimeQuoteManager

                detector = IntradayPatternDetector()
                bars_df = minute_bar_fetcher.fetch(symbol, period="5", days=1)
                if bars_df is None or bars_df.empty:
                    return [{"info": "无分钟K线数据，盘中模式检测不可用"}]

                quote_mgr = RealtimeQuoteManager()
                quote = quote_mgr.get_single_quote(symbol) or {}

                patterns = detector.detect_all(
                    symbol=symbol, minute_bars=bars_df, quote=quote
                )
                return [p.to_dict() if hasattr(p, "to_dict") else p for p in patterns]

            self.register(
                name="get_intraday_patterns",
                description=(
                    "检测个股盘中8种异动模式：冲高回落、低开高走、尾盘拉升、"
                    "尾盘跳水、量价背离、VWAP压制/支撑、缩量、开盘冲击。"
                    "返回结构化模式列表含severity(严重度)和direction(方向)。"
                    "仅在交易时段有数据。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码",
                        }
                    },
                    "required": ["symbol"],
                },
                handler=_detect_intraday_patterns,
            )

        # --- Tool 3: Minute bars (5/15/30/60 min OHLCV) ---
        if minute_bar_fetcher:
            self.register(
                name="get_minute_bars",
                description=(
                    "获取个股分钟K线数据（OHLCV）。支持5/15/30/60分钟级别。"
                    "用于分时级别的量价分析。默认5分钟线、最近1天。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码",
                        },
                        "period": {
                            "type": "string",
                            "description": "K线周期: '5'(默认)/'15'/'30'/'60'",
                        },
                    },
                    "required": ["symbol"],
                },
                handler=lambda symbol, period="5": minute_bar_fetcher.fetch(
                    symbol, period=period, days=1
                ),
            )

        # --- Tool 4: Dragon tiger data (龙虎榜) ---
        if stock_service:
            self.register(
                name="get_dragon_tiger",
                description=(
                    "获取个股龙虎榜统计数据（近三月汇总），"
                    "含买入/卖出总额、净买入额、上榜次数等。"
                    "用于判断机构和游资的动向。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码",
                        }
                    },
                    "required": ["symbol"],
                },
                handler=lambda symbol: (
                    stock_service.fetcher.fetch_dragon_tiger_stock_stats(symbol)
                ),
            )

        # --- Tool 5: Support and resistance levels ---
        if stock_service:
            self.register(
                name="get_support_resistance",
                description=(
                    "获取个股关键支撑位和阻力位（基于历史价格分析），"
                    "含价位、类型(support/resistance)和触碰次数。"
                    "用于判断入场价位、止损位和目标位。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "股票代码",
                        }
                    },
                    "required": ["symbol"],
                },
                handler=lambda symbol: stock_service.get_support_resistance(symbol),
            )

        logger.info("Registered 5 intraday tools (v55.0)")

        # --- Tool: Call-auction signals (集合竞价弱转强) ---
        def _get_call_auction_signals() -> list[dict]:
            from src.data.call_auction import CallAuctionCollector

            try:
                from src.web.dependencies import get_redis

                collector = CallAuctionCollector(redis_client=get_redis())
            except Exception:
                collector = CallAuctionCollector()

            candidates = collector.get_auction_candidates(min_volume=50000)
            if not candidates:
                return [{"info": "暂无集合竞价候选（9:25后可用）"}]

            # Return top 10
            return candidates[:10]

        self.register(
            name="get_call_auction_signals",
            description=(
                "获取今日集合竞价（9:15-9:25）弱转强信号。"
                "返回价格由低走高、放量的候选股列表。"
                "最佳使用时机：9:25-10:00 早盘开始前选股。"
            ),
            input_schema={"type": "object", "properties": {}},
            handler=lambda: _get_call_auction_signals(),
        )

    # ------------------------------------------------------------------
    # Agent loop domain tools
    # ------------------------------------------------------------------
    # Advanced tools — sub-agent, dry-run, sentiment metrics (v55.0 Sprint 4)
    # ------------------------------------------------------------------

    def _register_advanced_tools(self, deps: dict[str, Any]) -> None:
        """Register advanced agent capabilities: sub-agent, dry-run, sentiment."""
        gateway = deps.get("gateway")
        stock_service = deps.get("stock_service")

        # --- Sub-agent: spawn research agent ---
        if gateway:

            async def _spawn_research(task: str, symbol: str = "") -> str:
                from src.agent_loop.sub_agent import SubAgentRunner
                from src.web.dependencies import get_tool_registry

                runner = SubAgentRunner(
                    gateway=gateway,
                    tool_registry=get_tool_registry(),
                    max_cost_usd=0.05,
                    max_turns=5,
                )
                return await runner.run(task, symbol)

            self.register(
                name="spawn_research_agent",
                description=(
                    "启动子Agent深度研究一个问题。子Agent有独立工具集和成本预算，"
                    "不会干扰当前分析。用于需要深入调查的问题，如'分析该股龙虎榜机构行为'。"
                    "返回研究结论（500字内）。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "研究任务描述，如'分析600498龙虎榜机构行为'",
                        },
                        "symbol": {
                            "type": "string",
                            "description": "相关股票代码（可选）",
                        },
                    },
                    "required": ["task"],
                },
                handler=_spawn_research,
                is_async=True,
            )

        # --- Dry-run: simulate trade impact ---
        self.register(
            name="simulate_trade",
            description=(
                "模拟交易对组合的影响。在推荐买入前调用此工具，"
                "检查仓位集中度、板块暴露、现金余额和隔夜风险。"
                "返回通过/未通过的检查项。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码"},
                    "action": {
                        "type": "string",
                        "description": "buy/sell/add/reduce",
                    },
                    "shares": {"type": "integer", "description": "股数"},
                    "price": {"type": "number", "description": "价格"},
                    "stop_loss": {
                        "type": "number",
                        "description": "止损价（可选）",
                    },
                },
                "required": ["symbol", "action", "shares", "price"],
            },
            handler=lambda symbol, action, shares, price, stop_loss=None: (
                self._run_dry_run(symbol, action, int(shares), float(price), stop_loss)
            ),
        )

        # --- Consecutive board promotion rate ---
        if stock_service:
            self.register(
                name="get_consecutive_board_rate",
                description=(
                    "获取连板晋级率数据 — 情绪周期关键拐点信号。"
                    "包含涨停总数、首板/二板/三板+数量、最高连板数、"
                    "晋级率(1→2板、2→3板)、趋势和信号判断。"
                    "晋级率下降=情绪见顶，晋级率上升=情绪加速。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "日期YYYYMMDD格式（可选，默认今天）",
                        }
                    },
                    "required": [],
                },
                handler=lambda date="": self._get_board_rate(
                    stock_service.fetcher, date
                ),
            )

        # --- Decision pipeline: debate + sizing + risk gate ---
        self.register(
            name="run_decision_pipeline",
            description=(
                "对买入/卖出信号运行完整决策流水线（辩论引擎+贝叶斯推理+仓位计算+风控检查）。"
                "输入: symbol, action(buy/sell/add/reduce), confidence(0-1), reason。"
                "返回: approved + TradeProposal(含shares/entry_price/stop_loss) 或 rejected + 原因。"
                "买入信号建议先通过此工具验证。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码"},
                    "name": {"type": "string", "description": "股票名称"},
                    "action": {
                        "type": "string",
                        "description": "buy/sell/add/reduce",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "信号置信度 0-1",
                    },
                    "reason": {"type": "string", "description": "触发原因"},
                },
                "required": ["symbol", "action", "confidence", "reason"],
            },
            handler=lambda **kw: ToolRegistry._run_decision_pipeline(**kw),
            llm_backed=True,
        )

        logger.info("Registered 4 advanced tools (v55.0+v56.0)")

    @staticmethod
    def _run_dry_run(
        symbol: str,
        action: str,
        shares: int,
        price: float,
        stop_loss: float | None = None,
    ) -> dict:
        from src.agent_loop.dry_run import DryRunHarness
        from src.web.dependencies import get_trade_service

        harness = DryRunHarness()
        trade_svc = get_trade_service()
        try:
            broker = trade_svc.broker if trade_svc else None
            raw_positions = broker.get_positions() if broker else []
            positions = [
                {
                    "symbol": p.symbol,
                    "shares": p.shares,
                    "costPrice": p.cost_price,
                    "currentPrice": getattr(p, "current_price", p.cost_price),
                }
                for p in raw_positions
            ]
            cash = broker.get_cash() if broker else 100000
        except Exception:
            positions = []
            cash = 100000

        proposal = {
            "symbol": symbol,
            "action": action,
            "shares": shares,
            "entry_price": price,
            "stop_loss": stop_loss,
        }
        report = harness.simulate(proposal, positions, cash)
        return {
            "summary": report.to_summary(),
            "all_passed": report.all_passed,
            "checks_passed": report.checks_passed,
            "checks_failed": report.checks_failed,
            "new_position_pct": report.new_position_pct,
            "overnight_risk_pct": report.overnight_risk_pct,
        }

    @staticmethod
    def _get_board_rate(fetcher: Any, date: str = "") -> dict:
        from src.data.consecutive_board import ConsecutiveBoardTracker

        tracker = ConsecutiveBoardTracker(fetcher=fetcher)
        snapshot = tracker.compute_snapshot(date=date)
        if snapshot:
            return snapshot.to_dict()
        return {"error": "连板数据不可用"}

    # ------------------------------------------------------------------
    # Decision pipeline handler (v56.0 Sprint 4)
    # ------------------------------------------------------------------

    @staticmethod
    def _run_decision_pipeline(
        symbol: str,
        action: str,
        confidence: float,
        reason: str,
        name: str = "",
    ) -> dict:
        """Bridge agent tool call to DecisionPipeline.evaluate()."""
        try:
            from src.web.dependencies import get_decision_pipeline

            pipeline = get_decision_pipeline()

            from src.agent_loop.models import (
                AggregatedSignal,
                SignalDirection,
                UrgencyTier,
            )

            direction_map = {
                "buy": SignalDirection.BUY,
                "sell": SignalDirection.SELL,
                "add": SignalDirection.BUY,
                "reduce": SignalDirection.SELL,
            }
            signal = AggregatedSignal(
                symbol=symbol,
                name=name or symbol,
                direction=direction_map.get(action, SignalDirection.BUY),
                source="investor_agent",
                confidence=confidence,
                urgency=UrgencyTier.NORMAL,
                reason=reason,
            )

            # Get portfolio context
            from src.web.dependencies import get_capital_service, get_trade_service

            portfolio: list[dict] = []
            cash = 100000.0
            try:
                trade_svc = get_trade_service()
                if trade_svc and hasattr(trade_svc, "broker"):
                    positions = trade_svc.broker.get_positions()
                    portfolio = [
                        {
                            "symbol": p.symbol,
                            "shares": p.shares,
                            "costPrice": p.cost_price,
                        }
                        for p in positions
                    ]
                cap_svc = get_capital_service()
                overview = cap_svc.get_overview() if cap_svc else {}
                cash = float(
                    overview.get("available_cash", overview.get("cash", 100000))
                )
            except Exception:
                pass

            import asyncio

            loop = asyncio.new_event_loop()
            try:
                proposal = loop.run_until_complete(
                    pipeline.evaluate(
                        signal=signal,
                        portfolio=portfolio,
                        available_cash=cash,
                    )
                )
            finally:
                loop.close()

            if proposal is None:
                return {
                    "status": "rejected",
                    "reason": "决策管线拒绝（风控/置信度/辩论否决）",
                }
            return {
                "status": "approved",
                "proposal": proposal.to_dict()
                if hasattr(proposal, "to_dict")
                else str(proposal),
            }
        except Exception as exc:
            return {"status": "error", "reason": str(exc)}

    # ------------------------------------------------------------------

    def _register_agent_loop_tools(self, _deps: dict[str, Any]) -> None:
        """Register domain-specific tools for the InvestorAgent loop.

        These expose the system's core analytical modules (sentiment cycle,
        leader detection, thesis tracker, etc.) as tools the LLM can call.
        """

        # --- load_tool_schema: progressive disclosure meta-tool ---
        def _load_tool_schema(name: str) -> dict[str, Any]:
            schema = self.get_tool_schema(name)
            if schema is None:
                available = [n for n, t in self._tools.items() if t.tier == "extended"]
                return {
                    "error": f"Tool '{name}' not found",
                    "available_extended_tools": available[:20],
                }
            return {
                "status": "loaded",
                "tool_name": name,
                "description": schema["description"],
                "input_schema": schema["input_schema"],
                "hint": f"Tool '{name}' is now available. Call it directly.",
            }

        self.register(
            name="load_tool_schema",
            description=(
                "加载一个扩展工具的完整参数定义。"
                "当你需要使用扩展工具列表中的工具时，先调用此工具加载它的schema，"
                "然后就可以直接调用该工具。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要加载的工具名称",
                    },
                },
                "required": ["name"],
            },
            handler=_load_tool_schema,
        )

        # --- load_skill: on-demand trading knowledge ---
        self.register(
            name="load_skill",
            description=(
                "Load a trading knowledge skill file on demand. "
                "Available skills: sentiment_framework, risk_rules, "
                "leader_detection, a_share_rules, thesis_management, "
                "decision_process, stock_selection, overnight_analysis. "
                "Call this when you need specific domain knowledge for your analysis."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Skill file name (without .md extension)",
                    },
                },
                "required": ["skill_name"],
            },
            handler=lambda skill_name: _load_skill(skill_name),
        )

        # --- get_belief_state: market regime snapshot ---
        self.register(
            name="get_belief_state",
            description=(
                "Get the current market regime state: sentiment phase "
                "(freezing/ignition/acceleration/climax/ebb), HMM regime "
                "(bull/bear/consolidation), risk budget remaining, "
                "position limits, and cash strategy."
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=lambda: _get_belief_state(),
        )

        # --- detect_sentiment_phase: emotion cycle detection ---
        self.register(
            name="detect_sentiment_phase",
            description=(
                "Detect the current A-share market sentiment phase and "
                "get position sizing guidance. Returns phase name, "
                "max_position_pct, max_single_stock_pct, stop_loss_pct."
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=lambda: _detect_sentiment_phase(),
        )

        # --- get_active_theses: list investment theses ---
        self.register(
            name="get_active_theses",
            description=(
                "List all active investment theses. Each thesis tracks "
                "why a position was opened, its entry/exit conditions, "
                "current confidence, and expiry date."
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=lambda: _get_active_theses(),
        )

        # --- get_outcome_stats: signal accuracy statistics ---
        self.register(
            name="get_outcome_stats",
            description=(
                "Get historical signal accuracy statistics: per-source "
                "win rate, per-action accuracy, and calibration data. "
                "Useful for assessing confidence in current signals."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "lookback_days": {
                        "type": "integer",
                        "description": "Days of history to analyze (default 30)",
                        "default": 30,
                    },
                },
            },
            handler=lambda lookback_days=30: _get_outcome_stats(lookback_days),
        )

        # --- get_opportunity_candidates: market scanner results (v57.0) ---
        self.register(
            name="get_opportunity_candidates",
            description=(
                "获取今日全市场扫描结果 — 按龙头评分排序的候选标的列表。"
                "数据来自每15分钟运行的市场扫描器（零LLM成本）。"
                "返回: symbol, name, sector, total_score, reason, scores。"
                "在午后扫描和尾盘决策时必须先调用此工具了解全市场机会。"
                "配合 load_skill('stock_selection') 使用游资选股方法论。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "min_score": {
                        "type": "number",
                        "description": "最低分数过滤（默认50）",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "返回前N个候选（默认10）",
                    },
                },
            },
            handler=lambda min_score=50, top_n=10: _get_scanner_candidates(
                float(min_score), int(top_n)
            ),
        )

        # --- get_overnight_transmission: cross-market sector impact (I-113) ---
        self.register(
            name="get_overnight_transmission",
            description=(
                "获取隔夜跨市场传导分析 — 美股/大宗商品/汇率变动对A股各板块的影响。"
                "基于传导敏感度映射自动计算每个板块的'顺风/逆风'评分。"
                "在盘前分析(pre_market)时必须调用此工具了解隔夜全球市场对A股的影响。"
                "返回: 板块影响列表(排序) + 综合场景判断 + 敏感度系数。"
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=lambda: _compute_overnight_transmission(),
        )

        # --- get_market_pulse: lightweight "what's happening NOW" (heartbeat) ---
        self.register(
            name="get_market_pulse",
            description=(
                "获取当前市场脉搏 — 大盘指数、涨跌家数、板块异动、持仓盈亏变化。"
                "这是心跳Agent的第一个工具调用，了解当前状况后决定下一步。"
                "返回: 指数(上证/深成/创业板)、涨跌停数、北向资金、板块轮动、"
                "持仓实时盈亏(如有)。轻量级，<2s。"
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=lambda: _get_market_pulse(),
        )

        # --- get_limit_up_pool: today's limit-up stocks (Phase 3: discovery) ---
        self.register(
            name="get_limit_up_pool",
            description=(
                "获取今日涨停池 — 所有涨停股票列表，含封板金额、连板数、首封时间、"
                "炸板次数、所属行业。用于发现龙头股和市场主线。"
                "返回: symbol, name, pct_change, price, seal_amount, first_seal_time, "
                "break_count, consecutive, industry。"
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=lambda: _get_limit_up_pool(),
        )

        # --- get_sector_leaders: top sectors by capital inflow (Phase 3) ---
        self.register(
            name="get_sector_leaders",
            description=(
                "获取板块资金龙头 — 按净流入排序的行业板块，每个板块返回领涨股。"
                "用于判断市场主线方向和资金偏好。"
                "返回: sector, net_inflow, change_pct, leader_stocks。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "top_n": {
                        "type": "integer",
                        "description": "返回前N个板块（默认5）",
                    },
                },
            },
            handler=lambda top_n=5: _get_sector_leaders(int(top_n)),
        )

        logger.info("Registered %d agent loop tools", 10)

    # ------------------------------------------------------------------
    # Decision expression tools (Phase 2 — Claude Code alignment)
    # ------------------------------------------------------------------

    def _register_decision_tools(
        self,
        decision_handler: Any,
        agent: Any,
    ) -> None:
        """Register submit_buy/sell/hold tools for autonomous decision expression.

        These tools are called by the LLM during its agent loop to express
        trading decisions. The handler pushes decisions through the same
        pipeline as JSON-parsed decisions (validation, calibration, risk gate).

        NOT registered in ``register_all()`` because they need DecisionHandler
        and HeartbeatAgent references that only exist after construction.

        Args:
            decision_handler: DecisionHandler instance for push_single_decision.
            agent: HeartbeatAgent instance (for _current_state access).
        """
        from src.agent_loop.agent_state import AgentState

        async def _handle_submit_buy(
            symbol: str,
            name: str,
            shares: int,
            entry_price: float,
            stop_loss: float,
            target_price: float,
            confidence: float,
            summary: str,
            hold_days: int = 0,
            risk_note: str = "",
        ) -> dict[str, Any]:
            # --- Hard buyability check: reject limit-up stocks ---
            try:
                from src.data.realtime import RealtimeQuoteManager

                rqm = RealtimeQuoteManager()
                q = rqm.get_single_quote(symbol)
                if q:
                    pct = float(q.get("pct_change", q.get("change_pct", 0)) or 0)
                    # Detect board type for correct limit
                    is_chinext_star = symbol.startswith(("3", "68"))
                    limit_pct = 20.0 if is_chinext_star else 10.0
                    if pct >= limit_pct - 0.1:
                        logger.warning(
                            "submit_buy_signal REJECTED: %s %s at %.1f%% "
                            "(已涨停，无法买入)",
                            symbol,
                            name,
                            pct,
                        )
                        return {
                            "status": "rejected",
                            "reason": (
                                f"{name}({symbol})当前涨幅{pct:+.1f}%，"
                                f"已涨停封板，散户排队也买不到。"
                                f"建议：看同板块涨幅3-7%的票，"
                                f"用 get_trend_candidates 找可买替代标的。"
                            ),
                            "symbol": symbol,
                        }
            except Exception:
                pass  # Fail open — can't check quote, allow through

            # --- Cash sufficiency check ---
            try:
                from src.web.dependencies import get_capital_service

                cs = get_capital_service()
                cash = cs.get_balance()
                order_amt = shares * entry_price
                if isinstance(cash, (int, float)) and order_amt > cash:
                    return {
                        "status": "rejected",
                        "reason": (
                            f"资金不足：买入需要¥{order_amt:,.0f}，"
                            f"可用资金仅¥{cash:,.0f}。"
                        ),
                        "symbol": symbol,
                    }
            except Exception:
                pass

            state = agent._current_state
            if state is None:
                state = AgentState(
                    date=datetime.now(UTC).strftime("%Y%m%d"),
                )
            decision_dict: dict[str, Any] = {
                "type": "buy_signal",
                "action": "buy",
                "symbol": symbol,
                "name": name,
                "shares": shares,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "target_price": target_price,
                "confidence": confidence,
                "summary": summary,
                "risk_note": risk_note,
            }
            if hold_days:
                decision_dict["hold_days"] = hold_days
            try:
                ok = await decision_handler.push_single_decision(
                    decision_dict, state, "tool_call"
                )
                if ok:
                    return {
                        "status": "accepted",
                        "symbol": symbol,
                        "action": "buy",
                        "reflection": (
                            f"买入信号已提交。在确认前反思一下：\n"
                            f"1. 如果这笔交易亏了，最可能的原因是什么？\n"
                            f"2. {name}的基本面是否支撑当前价格？\n"
                            f"3. 你的置信度({confidence:.0%})是否过度自信？"
                        ),
                    }
                return {
                    "status": "rejected",
                    "reason": "decision pipeline filtered this signal",
                    "symbol": symbol,
                }
            except Exception as exc:
                return {
                    "status": "rejected",
                    "reason": str(exc),
                    "symbol": symbol,
                }

        self.register(
            name="submit_buy_signal",
            description=(
                "提交买入信号。当你决定买入某只股票时调用此工具。"
                "信号将经过风控校验（止损/目标/集中度/熔断器）后推送。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码，如 '600519'",
                    },
                    "name": {
                        "type": "string",
                        "description": "股票名称，如 '贵州茅台'",
                    },
                    "shares": {
                        "type": "integer",
                        "description": "买入股数（100的整数倍）",
                    },
                    "entry_price": {
                        "type": "number",
                        "description": "建议买入价格（元）",
                    },
                    "stop_loss": {
                        "type": "number",
                        "description": "止损价格（元）",
                    },
                    "target_price": {
                        "type": "number",
                        "description": "目标价格（元）",
                    },
                    "hold_days": {
                        "type": "integer",
                        "description": "预计持有天数",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "置信度 0-1",
                    },
                    "summary": {
                        "type": "string",
                        "description": "买入理由（大白话）",
                    },
                    "risk_note": {
                        "type": "string",
                        "description": "主要风险提示",
                    },
                },
                "required": [
                    "symbol",
                    "name",
                    "shares",
                    "entry_price",
                    "stop_loss",
                    "target_price",
                    "confidence",
                    "summary",
                ],
            },
            handler=_handle_submit_buy,
            is_async=True,
        )

        async def _handle_submit_sell(
            symbol: str,
            name: str,
            shares: int,
            confidence: float,
            summary: str,
            risk_note: str = "",
        ) -> dict[str, Any]:
            state = agent._current_state
            if state is None:
                state = AgentState(
                    date=datetime.now(UTC).strftime("%Y%m%d"),
                )
            decision_dict: dict[str, Any] = {
                "type": "sell_signal",
                "action": "sell",
                "symbol": symbol,
                "name": name,
                "shares": shares,
                "confidence": confidence,
                "summary": summary,
                "risk_note": risk_note,
            }
            try:
                ok = await decision_handler.push_single_decision(
                    decision_dict, state, "tool_call"
                )
                if ok:
                    return {
                        "status": "accepted",
                        "symbol": symbol,
                        "action": "sell",
                    }
                return {
                    "status": "rejected",
                    "reason": "decision pipeline filtered this signal",
                    "symbol": symbol,
                }
            except Exception as exc:
                return {
                    "status": "rejected",
                    "reason": str(exc),
                    "symbol": symbol,
                }

        self.register(
            name="submit_sell_signal",
            description=(
                "提交卖出信号。当你决定卖出某只股票时调用此工具。信号将经过校验后推送。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码，如 '600519'",
                    },
                    "name": {
                        "type": "string",
                        "description": "股票名称，如 '贵州茅台'",
                    },
                    "shares": {
                        "type": "integer",
                        "description": "卖出股数（100的整数倍）",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "置信度 0-1",
                    },
                    "summary": {
                        "type": "string",
                        "description": "卖出理由（大白话）",
                    },
                    "risk_note": {
                        "type": "string",
                        "description": "风险提示",
                    },
                },
                "required": [
                    "symbol",
                    "name",
                    "shares",
                    "confidence",
                    "summary",
                ],
            },
            handler=_handle_submit_sell,
            is_async=True,
        )

        async def _handle_submit_hold(
            symbol: str,
            name: str,
            confidence: float,
            summary: str,
            stop_loss: float | None = None,
            target_price: float | None = None,
            risk_note: str = "",
        ) -> dict[str, Any]:
            state = agent._current_state
            if state is None:
                state = AgentState(
                    date=datetime.now(UTC).strftime("%Y%m%d"),
                )
            decision_dict: dict[str, Any] = {
                "type": "hold_update",
                "action": "hold",
                "symbol": symbol,
                "name": name,
                "confidence": confidence,
                "summary": summary,
                "risk_note": risk_note,
            }
            if stop_loss is not None:
                decision_dict["stop_loss"] = stop_loss
            if target_price is not None:
                decision_dict["target_price"] = target_price

            # Thesis drift warning — alert LLM when target_price drops
            # significantly vs. the original buy thesis
            result_extra = ""
            try:
                from src.web.dependencies import get_redis

                r = get_redis()
                if r and symbol:
                    raw = r.get(f"thesis:{symbol}")
                    if raw:
                        thesis = json.loads(raw)
                        orig_tp = thesis.get("target_price")
                        new_tp = decision_dict.get("target_price")
                        if orig_tp and new_tp and float(new_tp) < float(orig_tp):
                            result_extra = (
                                f" ⚠️ 目标价从{orig_tp}降到{new_tp}，大幅偏离原始计划"
                            )
            except Exception:
                pass

            try:
                ok = await decision_handler.push_single_decision(
                    decision_dict, state, "tool_call"
                )
                if ok:
                    result: dict[str, Any] = {
                        "status": "accepted",
                        "symbol": symbol,
                        "action": "hold",
                    }
                    if result_extra:
                        result["warning"] = result_extra
                    return result
                return {
                    "status": "rejected",
                    "reason": "decision pipeline filtered this signal",
                    "symbol": symbol,
                }
            except Exception as exc:
                return {
                    "status": "rejected",
                    "reason": str(exc),
                    "symbol": symbol,
                }

        self.register(
            name="submit_hold_update",
            description=(
                "提交持有更新。当你判断继续持有时调用此工具，可以更新止损/目标价。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码，如 '600519'",
                    },
                    "name": {
                        "type": "string",
                        "description": "股票名称，如 '贵州茅台'",
                    },
                    "stop_loss": {
                        "type": "number",
                        "description": "更新后的止损价格（元）",
                    },
                    "target_price": {
                        "type": "number",
                        "description": "更新后的目标价格（元）",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "置信度 0-1",
                    },
                    "summary": {
                        "type": "string",
                        "description": "持有理由（大白话）",
                    },
                    "risk_note": {
                        "type": "string",
                        "description": "风险提示",
                    },
                },
                "required": [
                    "symbol",
                    "name",
                    "confidence",
                    "summary",
                ],
            },
            handler=_handle_submit_hold,
            is_async=True,
        )

        logger.info("Registered 3 decision expression tools (submit_buy/sell/hold)")


def _load_skill(skill_name: str) -> str:
    """Load a trading skill markdown file."""
    from pathlib import Path

    skills_dir = Path(__file__).parent.parent.parent / "agent_loop" / "skills"
    path = skills_dir / f"{skill_name}.md"
    if not path.exists():
        available = (
            [p.stem for p in skills_dir.glob("*.md")] if skills_dir.exists() else []
        )
        return json.dumps(
            {"error": f"Unknown skill: {skill_name}", "available": available},
            ensure_ascii=False,
        )
    return path.read_text(encoding="utf-8")


def _get_belief_state() -> dict[str, Any]:
    """Get SharedBeliefState as a dict."""
    try:
        from src.agent_loop.shared_belief_state import SharedBeliefState

        state = SharedBeliefState()
        return state.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


def _detect_sentiment_phase() -> dict[str, Any]:
    """Detect current sentiment cycle phase with full 7-dimension quantified data."""
    try:
        from src.agent_loop.sentiment_cycle import (
            SentimentCycleDetector,
            SentimentSignals,
        )

        signals = SentimentSignals()

        # --- Signal 1: Limit-up pool (涨停池) ---
        try:
            from src.data.fetcher import StockDataFetcher

            fetcher = StockDataFetcher()
            pool = fetcher.fetch_limit_up_pool()
            if pool is not None and not pool.empty:
                signals.limit_up_count = len(pool)
                # Signal 2: Max consecutive board (最高连板)
                if "consecutive" in pool.columns:
                    signals.max_consecutive_board = int(pool["consecutive"].max())
                # Signal 6: Board break rate (炸板率)
                if "break_count" in pool.columns:
                    # 炸板率 = 有过开板的股票数 / 总涨停数（不是break_count总和）
                    stocks_with_breaks = int((pool["break_count"] > 0).sum())
                    signals.board_break_rate = float(stocks_with_breaks / len(pool))
        except Exception:
            pass

        # --- Signal 3: Limit-down pool (跌停池) ---
        try:
            down_pool = fetcher.fetch_limit_down_pool()
            if down_pool is not None and not down_pool.empty:
                signals.limit_down_count = len(down_pool)
        except Exception:
            pass

        # --- Signal 7: Promotion rate (晋级率) ---
        try:
            from src.data.consecutive_board import ConsecutiveBoardTracker

            cbt = ConsecutiveBoardTracker()
            snapshot = cbt.compute_snapshot()
            if snapshot:
                signals.promotion_1to2 = getattr(snapshot, "promotion_1to2", None)
                signals.promotion_2to3 = getattr(snapshot, "promotion_2to3", None)
        except Exception:
            pass

        # --- Signal 4: Volume change (成交量变化) ---
        try:
            idx_df = fetcher.fetch_index("000001")  # 上证综指
            if idx_df is not None and not idx_df.empty and "volume" in idx_df.columns:
                recent_vol = idx_df["volume"].iloc[-1]
                avg_vol = idx_df["volume"].iloc[-20:].mean()
                if avg_vol > 0:
                    signals.volume_change_pct = float(
                        (recent_vol - avg_vol) / avg_vol * 100
                    )
        except Exception:
            pass

        # --- Signal 5: Northbound flow (北向资金) ---
        try:
            from src.data.macro_flow_fetcher import MacroFlowFetcher

            mf = MacroFlowFetcher()
            nb = mf.fetch_northbound_today()
            if nb and isinstance(nb, dict):
                flow = nb.get("net_flow") or nb.get("net") or nb.get("net_buy_amount")
                if flow is not None:
                    signals.northbound_net_flow = float(flow)
        except Exception:
            pass

        detector = SentimentCycleDetector()
        phase = detector.detect(signals)
        if hasattr(phase, "__dict__"):
            return {k: v for k, v in phase.__dict__.items() if not k.startswith("_")}
        return {"phase": str(phase)}
    except Exception as exc:
        return {"error": str(exc), "note": "Sentiment detection unavailable"}


def _get_active_theses() -> list[dict[str, Any]]:
    """Get all active investment theses."""
    try:
        from src.agent_loop.thesis_tracker import ThesisTracker

        tracker = ThesisTracker()
        theses = tracker.get_active()
        if not theses:
            return []
        result = []
        for t in theses:
            if hasattr(t, "to_dict"):
                result.append(t.to_dict())
            elif isinstance(t, dict):
                result.append(t)
            else:
                result.append({"data": str(t)})
        return result
    except Exception as exc:
        return [{"error": str(exc)}]


def _compute_overnight_transmission() -> dict[str, Any]:
    """Compute overnight cross-market transmission scores for A-share sectors."""
    try:
        import yaml
        from pathlib import Path

        # Load transmission map — /app/config/ is 4 levels up from this file
        config_path = (
            Path(__file__).parent.parent.parent.parent
            / "config"
            / "sector_transmission_map.yaml"
        )
        if not config_path.exists():
            return {"error": "sector_transmission_map.yaml not found"}

        with open(config_path, encoding="utf-8") as f:
            tmap = yaml.safe_load(f)

        # Fetch global market data
        from src.web.dependencies import get_global_market_fetcher

        fetcher = get_global_market_fetcher()
        snapshot = fetcher.fetch_snapshot()
        if not snapshot:
            return {"error": "Global market data unavailable"}

        # Extract key index moves
        indices = {
            i.get("name", ""): i.get("pct_change", 0) or 0
            for i in snapshot.get("indices", [])
        }
        commodities = {
            c.get("name", ""): c.get("pct_change", 0) or 0
            for c in snapshot.get("commodities", [])
        }
        currencies = {
            c.get("name", ""): c.get("pct_change", 0) or 0
            for c in snapshot.get("currencies", [])
        }

        nasdaq_pct = indices.get("纳斯达克", 0)
        sp500_pct = indices.get("标普500", 0)
        dow_pct = indices.get("道琼斯", 0)
        oil_pct = commodities.get("原油(WTI)", 0)
        gold_pct = commodities.get("黄金", 0)
        copper_pct = commodities.get("铜", 0)
        dxy_pct = currencies.get("美元指数(DXY)", 0)

        # Compute sector impact scores
        sector_impacts: dict[str, float] = {}

        # US equity transmission
        us_eq = tmap.get("us_equity", {})
        for index_name, index_pct, sectors in [
            ("nasdaq", nasdaq_pct, us_eq.get("nasdaq", {})),
            ("sp500", sp500_pct, us_eq.get("sp500", {})),
            ("dowjones", dow_pct, us_eq.get("dowjones", {})),
        ]:
            for sector, cfg in sectors.items():
                sens = cfg.get("sensitivity", 0)
                direction = 1 if cfg.get("direction", "positive") == "positive" else -1
                impact = index_pct * sens * direction
                sector_impacts[sector] = sector_impacts.get(sector, 0) + impact

        # Commodity transmission
        comm = tmap.get("commodity", {})
        for comm_name, comm_pct, sectors in [
            ("原油", oil_pct, comm.get("原油", {})),
            ("黄金", gold_pct, comm.get("黄金", {})),
            ("铜", copper_pct, comm.get("铜", {})),
        ]:
            for sector, cfg in sectors.items():
                sens = cfg.get("sensitivity", 0)
                direction = 1 if cfg.get("direction", "positive") == "positive" else -1
                impact = comm_pct * sens * direction
                sector_impacts[sector] = sector_impacts.get(sector, 0) + impact

        # Currency transmission
        curr = tmap.get("currency", {})
        for curr_name, curr_pct, sectors in [
            ("美元指数", dxy_pct, curr.get("美元指数", {})),
        ]:
            for sector, cfg in sectors.items():
                sens = cfg.get("sensitivity", 0)
                direction = 1 if cfg.get("direction", "positive") == "positive" else -1
                impact = curr_pct * sens * direction
                sector_impacts[sector] = sector_impacts.get(sector, 0) + impact

        # Sort by absolute impact
        sorted_sectors = sorted(
            sector_impacts.items(), key=lambda x: abs(x[1]), reverse=True
        )

        # Determine scenario
        scenarios = tmap.get("scenarios", {})
        scenario = "unknown"
        us_avg = (nasdaq_pct + sp500_pct + dow_pct) / 3
        if us_avg > 0.5 and oil_pct < -0.5 and dxy_pct < 0:
            scenario = "risk_on"
        elif us_avg < -0.5 and gold_pct > 0.5 and dxy_pct > 0:
            scenario = "risk_off"
        elif us_avg < -0.5 and oil_pct > 1 and gold_pct > 0:
            scenario = "stagflation"
        elif abs(us_avg) < 0.5 and abs(oil_pct) < 1:
            scenario = "goldilocks"

        scenario_info = scenarios.get(scenario, {})

        result = {
            "overnight_summary": {
                "纳斯达克": f"{nasdaq_pct:+.2f}%",
                "标普500": f"{sp500_pct:+.2f}%",
                "道琼斯": f"{dow_pct:+.2f}%",
                "原油WTI": f"{oil_pct:+.2f}%",
                "黄金": f"{gold_pct:+.2f}%",
                "美元指数": f"{dxy_pct:+.2f}%",
            },
            "scenario": scenario,
            "scenario_description": scenario_info.get("description", ""),
            "beneficiaries": scenario_info.get("beneficiaries", []),
            "pressured": scenario_info.get("pressured", []),
            "sector_impacts": [
                {
                    "sector": sector,
                    "impact_score": round(impact, 2),
                    "direction": "顺风" if impact > 0 else "逆风",
                    "expected_move": f"{impact:+.1f}%",
                }
                for sector, impact in sorted_sectors
                if abs(impact) > 0.1
            ],
        }
        return result
    except Exception as exc:
        return {"error": f"Transmission analysis failed: {exc}"}


def _get_outcome_stats(lookback_days: int = 30) -> dict[str, Any]:
    """Get signal outcome accuracy statistics."""
    try:
        from src.agent_loop.outcome_tracker import OutcomeTracker

        tracker = OutcomeTracker()
        stats = tracker.get_accuracy_stats(lookback_days=lookback_days)
        if isinstance(stats, dict):
            return stats
        return {"data": str(stats)}
    except Exception as exc:
        return {"error": str(exc)}


def _get_scanner_candidates(min_score: float = 50, top_n: int = 10) -> dict[str, Any]:
    """Retrieve scored opportunity candidates from Redis (v57.0)."""
    try:
        import redis
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        r = redis.Redis(host="redis", port=6379, db=0, decode_responses=True)
        date = _dt.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        key = f"scanner:candidates:{date}"

        raw = r.zrevrangebyscore(
            key, "+inf", str(min_score), withscores=True, start=0, num=top_n
        )

        candidates = []
        for member, score in raw:
            data = json.loads(member)
            data["total_score"] = round(score, 1)
            candidates.append(data)

        if not candidates:
            return {
                "message": "今日暂无扫描结果（可能市场未开盘或涨停数过少）",
                "candidates": [],
            }

        return {"count": len(candidates), "candidates": candidates}
    except Exception as exc:
        return {"error": f"获取扫描结果失败: {exc}", "candidates": []}


def _handle_deep_analyze(symbol: str, stock_name: str = "") -> dict[str, Any]:
    """Build full MarketSnapshot + run LLM decision for a symbol.

    Returns the same quality of analysis as InvestmentDirector.coordinate_cycle().

    Runs ContextBuilder.build() in a separate thread to avoid event loop
    conflicts (this function is called from the sync tool executor which
    itself runs inside an async context).
    """
    import concurrent.futures

    from src.agent_loop.market_snapshot import ContextBuilder

    # Resolve stock name if not provided
    if not stock_name:
        try:
            from src.web.dependencies import get_stock_service

            info = get_stock_service().get_stock_info(symbol)
            stock_name = info.get("name", symbol) if info else symbol
        except Exception:
            stock_name = symbol

    # Use FastAPI DI singletons instead of creating fresh instances.
    # This ensures shared caches, state, and correct portfolio context.
    builder_kwargs: dict[str, Any] = {}
    _di_getters = [
        ("realtime", "get_realtime_quote_manager"),
        ("minute_bar_fetcher", "get_minute_bar_fetcher"),
        ("mtf_engine", "get_mtf_engine"),
        ("reflexivity_detector", "get_reflexivity_detector"),
        ("alpha_engine", "get_qlib_alpha_engine"),
        ("macro_flow_fetcher", "get_macro_flow_fetcher"),
        ("info_store", "get_info_store"),
        ("sentiment_detector", "get_sentiment_cycle_detector"),
        ("portfolio_store", "get_portfolio_store"),
        ("convergence_engine", "get_convergence_engine"),
        ("thesis_tracker", "get_thesis_tracker"),
    ]
    from src.web import dependencies as _deps

    for kwarg_name, getter_name in _di_getters:
        try:
            getter = getattr(_deps, getter_name, None)
            if getter:
                builder_kwargs[kwarg_name] = getter()
        except Exception:
            pass

    # Bayesian engine from DecisionPipeline DI
    try:
        pipeline = _deps.get_decision_pipeline()
        builder_kwargs["bayesian_engine"] = pipeline._bayesian
    except Exception:
        pass

    # Non-DI sources (no singleton getter — create fresh instances)
    for kwarg_name, module_path, class_name in [
        ("vpin_calculator", "src.quant.vpin", "VpinCalculator"),
        ("vwap_engine", "src.quant.vwap_trigger", "VwapTriggerEngine"),
        (
            "pattern_detector",
            "src.agent_loop.intraday_patterns",
            "IntradayPatternDetector",
        ),
        ("gdelt_fetcher", "src.data.gdelt_fetcher", "GdeltFetcher"),
        ("fred_fetcher", "src.data.fred_fetcher", "FredFetcher"),
        ("polymarket_fetcher", "src.data.polymarket_fetcher", "PolymarketFetcher"),
        ("cninfo_fetcher", "src.data.cninfo_announcement", "CninfoAnnouncementFetcher"),
        ("lockup_fetcher", "src.data.lockup_expiry", "LockupExpiryFetcher"),
        ("block_trade_fetcher", "src.data.block_trade", "BlockTradeFetcher"),
        ("insider_fetcher", "src.data.insider_activity", "InsiderActivityFetcher"),
        ("earnings_fetcher", "src.data.earnings_forecast", "EarningsForecastFetcher"),
    ]:
        try:
            mod = __import__(module_path, fromlist=[class_name])
            builder_kwargs[kwarg_name] = getattr(mod, class_name)()
        except Exception:
            pass

    # Run async ContextBuilder.build() in a fresh thread with its own event loop
    import asyncio as _aio

    async def _build_snapshot():
        builder = ContextBuilder(**builder_kwargs)
        return await builder.build(symbol, stock_name)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            snapshot = pool.submit(_aio.run, _build_snapshot()).result(timeout=80)
    except Exception as exc:
        logger.error("deep_analyze ContextBuilder failed for %s: %s", symbol, exc)
        return {
            "symbol": symbol,
            "error": f"Snapshot build failed: {exc}",
            "snapshot_text": "",
        }

    snapshot_text = snapshot.serialize_for_llm()

    # No inner LLM call — the outer agent LLM receives snapshot_text
    # and does its own reasoning. This avoids:
    # 1. Redundant LLM call (60s timeout, doubles latency)
    # 2. Google API 'dict has no attribute role' format mismatch
    # 3. Double token cost for the same analysis

    result: dict[str, Any] = {
        "symbol": symbol,
        "name": stock_name,
        "snapshot_text": snapshot_text,
    }

    # Attach key numeric fields for quick access
    if snapshot.current_price is not None:
        result["current_price"] = snapshot.current_price
    if snapshot.price_change_pct is not None:
        result["change_pct"] = snapshot.price_change_pct
    if snapshot.bayesian_posterior is not None:
        result["bayesian_posterior"] = snapshot.bayesian_posterior
    if snapshot.convergence_score is not None:
        result["convergence_score"] = snapshot.convergence_score

    return result


def _handle_impact_chain(event_text: str) -> dict[str, Any]:
    """Handle impact chain analysis tool call."""
    from src.intelligence.impact_chain import ImpactChainEngine

    engine = ImpactChainEngine()
    chains = engine.build_chains_for_event(event_text)
    if not chains:
        return {"event": event_text, "chains": [], "message": "未匹配到影响链模板"}
    return {
        "event": event_text,
        "chains": [c.to_dict() for c in chains],
        "affected_sectors": chains[0].all_affected_sectors if chains else [],
    }


def _handle_position_macro(symbol: str, name: str = "") -> dict[str, Any]:
    """Handle position macro analysis tool call."""
    from src.intelligence.position_macro_mapper import (
        MacroEnvironment,
        PositionMacroMapper,
    )

    mapper = PositionMacroMapper()
    # Use neutral environment as default (real data should be injected)
    env = MacroEnvironment()
    profile = mapper.analyze_position(symbol, name, env)
    return profile.to_dict()


def _handle_rotation_scan() -> dict[str, Any]:
    """Handle portfolio rotation scan tool call."""
    from src.intelligence.position_macro_mapper import MacroEnvironment
    from src.intelligence.rotation_engine import RotationEngine
    from src.web.services.portfolio_store import PortfolioStore

    try:
        store = PortfolioStore()
        data = store.get_portfolio_data()
        positions = [
            {"symbol": p["symbol"], "name": p.get("name", p["symbol"])}
            for p in data.get("positions", [])
        ]
    except Exception:
        return {"error": "无法读取持仓数据", "plans": []}

    if not positions:
        return {"message": "持仓为空，无需轮动分析", "plans": []}

    engine = RotationEngine()
    env = MacroEnvironment()  # neutral default
    plans = engine.scan_portfolio(positions, env)

    return {
        "position_count": len(positions),
        "rotation_plans": [p.to_dict() for p in plans],
        "plans_count": len(plans),
    }


def _handle_munger_checklist(**kwargs: Any) -> dict[str, Any]:
    """Handle Munger checklist tool call."""
    from src.intelligence.munger_checklist import MungerChecklist

    checklist = MungerChecklist()
    result = checklist.run_checklist(
        symbol=kwargs["symbol"],
        name=kwargs.get("name", ""),
        current_price=kwargs.get("current_price"),
        fair_value=kwargs.get("fair_value"),
        recent_gain_pct=kwargs.get("recent_gain_pct"),
        news_count_24h=kwargs.get("news_count_24h", 0),
    )
    return result.to_dict()


def _handle_debate(**kwargs: Any) -> dict[str, Any]:
    """Handle bull/bear debate tool call."""
    from src.intelligence.debate_engine import DebateEngine

    engine = DebateEngine()
    record = engine.run_debate(
        symbol=kwargs["symbol"],
        name=kwargs.get("name", ""),
        trigger=kwargs.get("trigger", "agent request"),
        market_data=kwargs.get("market_data", {}),
    )
    return record.to_dict()


def _handle_constraint_check(symbol: str, name: str = "") -> dict[str, Any]:
    """Handle trading constraint check tool call."""
    from src.trading.constraints import TradingConstraintsEngine

    engine = TradingConstraintsEngine()
    result = engine.check(symbol, name)
    return {
        "symbol": symbol,
        "name": name,
        "board": engine.get_board(symbol),
        "passed": result.passed,
        "blocked": result.blocked,
        "violations": [
            {"rule": v.rule, "severity": v.severity, "message": v.message}
            for v in result.violations
        ],
    }


def _handle_capital_flow(
    capital_flow_service: Any,
    query_type: str,
    symbol: str | None,
    period: str,
) -> dict[str, Any]:
    """Execute a capital flow query and return results for the agent."""
    if query_type == "macro":
        return capital_flow_service.get_macro_overview()
    elif query_type == "sector":
        return capital_flow_service.get_sector_ranking(
            sector_type="industry", period=period
        )
    elif query_type == "stock":
        if not symbol:
            return {"error": "query_type='stock' 需要提供 symbol 参数"}
        # Use AKShare individual stock fund flow via StockDataFetcher
        try:
            import akshare as ak

            from src.data.fetcher import _bypass_proxy

            with _bypass_proxy():
                raw = ak.stock_individual_fund_flow(stock=symbol, market="sh")
            if raw is None or raw.empty:
                # Try SZ market
                with _bypass_proxy():
                    raw = ak.stock_individual_fund_flow(stock=symbol, market="sz")
            if raw is None or raw.empty:
                return {
                    "symbol": symbol,
                    "fund_flow": [],
                    "message": "无个股资金流数据",
                }

            # Return last few rows as records
            period_limit = {"today": 1, "3d": 3, "5d": 5}.get(period, 1)
            rows = raw.tail(period_limit)
            try:
                records = rows.fillna(0).to_dict(orient="records")
            except Exception:
                # Fallback: manual row-by-row conversion
                records = []
                for _, row in rows.iterrows():
                    rec = {}
                    for col in rows.columns:
                        val = row[col]
                        if val is None or (isinstance(val, float) and val != val):
                            rec[col] = 0
                        else:
                            rec[col] = val
                    records.append(rec)
            return {"symbol": symbol, "period": period, "fund_flow": records}
        except Exception as exc:
            return {"symbol": symbol, "error": str(exc)}
    else:
        return {"error": f"Unknown query_type: {query_type}"}


def _search_intel(
    intel_hub: Any,
    search: str | None,
    symbol: str | None,
    category: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Execute an intel hub search and return slim results for the agent."""
    result = intel_hub.get_feed(
        search=search,
        symbol=symbol,
        category=category,
        limit=limit,
        days=7,
    )
    items = result.get("items", [])
    # Return only the fields the agent needs — skip large blobs
    return [
        {
            "title": it.get("title", ""),
            "summary": it.get("summary", ""),
            "category": it.get("category", ""),
            "source_name": it.get("source_name", ""),
            "related_symbols": it.get("related_symbols", []),
            "tags": it.get("tags", []),
            "published_at": it.get("published_at", ""),
        }
        for it in items
    ]


def _make_feature_def(name: str, category: str):
    """Create a FeatureDefinition for put_feature tool."""
    from src.quant.feature_store import FeatureDefinition

    return FeatureDefinition(name=name, category=category)


def _serialize_risk_results(results: list) -> str:
    """Serialize VaR results to JSON string."""
    items = []
    for r in results:
        items.append(
            {
                "method": r.method,
                "confidence_level": r.confidence_level,
                "var_pct": r.var_pct,
                "var_amount": r.var_amount,
                "cvar_pct": r.cvar_pct,
                "cvar_amount": r.cvar_amount,
                "warnings": r.warnings,
            }
        )
    return json.dumps(items, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _read_portfolio() -> dict[str, Any]:
    """Read portfolio positions from SQLite (single source of truth)."""
    from src.web.services.portfolio_store import PortfolioStore

    try:
        store = PortfolioStore()
        return store.get_portfolio_data()
    except Exception:
        return {"positions": []}


def _check_trading_day(calendar: Any, date: str | None) -> dict[str, Any]:
    """Check if a date is a trading day."""
    from datetime import date as date_type, datetime

    if date:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        d = date_type.today()

    is_trading = calendar.is_trading_day(d)
    next_trading = calendar.next_trading_day(d)

    return {
        "date": d.isoformat(),
        "is_trading_day": is_trading,
        "next_trading_day": next_trading.isoformat() if next_trading else None,
    }


def _serialize(obj: Any) -> str:
    """Serialize a tool result to JSON string, handling common types."""
    if isinstance(obj, str):
        return obj

    try:
        import pandas as pd

        if isinstance(obj, pd.DataFrame):
            # Limit to prevent token explosion
            if len(obj) > 50:
                obj = obj.head(50)
            return obj.to_json(orient="records", date_format="iso", force_ascii=False)
        if isinstance(obj, pd.Series):
            return obj.to_json(force_ascii=False)
    except ImportError:
        pass

    if isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False, default=str)
    if isinstance(obj, (list, tuple)):
        return json.dumps(obj, ensure_ascii=False, default=str)
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), ensure_ascii=False, default=str)
    if hasattr(obj, "dict"):
        return json.dumps(obj.dict(), ensure_ascii=False, default=str)

    return json.dumps({"result": str(obj)}, ensure_ascii=False)


def _get_market_pulse() -> dict[str, Any]:
    """Lightweight market snapshot for heartbeat agent.

    Returns indices, portfolio P&L, capital, sector rotation, scanner candidates.
    Uses StockDataFetcher (reliable) instead of RealtimeQuoteManager.
    Cached in Redis for 120s to avoid redundant fetches within a heartbeat.
    """
    from datetime import datetime as _dt

    # Check Redis cache first (120s TTL)
    _cache_key = "market_pulse:cache"
    try:
        from src.web.dependencies import get_redis as _get_redis

        _r = _get_redis()
        if _r:
            cached = _r.get(_cache_key)
            if cached:
                return json.loads(cached)
    except Exception:
        _r = None

    pulse: dict[str, Any] = {"timestamp": _dt.now().isoformat()}

    # 1. Major indices + held stock quotes via EastMoneyClient (fast batch API)
    try:
        from src.data.eastmoney_client import EastMoneyClient

        em = EastMoneyClient()
        # Indices use special codes: 000001(上证), 399001(深成), 399006(创业板)
        index_quotes = em.fetch_batch_quotes(["000001", "399001", "399006"])
        if index_quotes:
            indices = {}
            for q in index_quotes:
                indices[q.get("name", q.get("symbol", "?"))] = {
                    "price": q.get("price"),
                    "change_pct": q.get("pct_change"),
                }
            pulse["indices"] = indices
        else:
            pulse["indices"] = {"error": "数据暂不可用"}
    except Exception as exc:
        pulse["indices"] = {"error": str(exc)}

    # 2. Portfolio positions with LIVE P&L
    try:
        from src.web.dependencies import get_capital_service, get_portfolio_store

        ps = get_portfolio_store()
        if ps:
            positions = ps.list_positions()
            if positions:
                # Fetch live quotes for held stocks
                held_symbols = [p.get("symbol") for p in positions if p.get("symbol")]
                live_quotes = {}
                if held_symbols:
                    try:
                        from src.data.eastmoney_client import EastMoneyClient

                        em = EastMoneyClient()
                        batch = em.fetch_batch_quotes(held_symbols)
                        for q in batch or []:
                            sym = q.get("symbol", "")
                            live_quotes[sym] = {
                                "price": q.get("price"),
                                "pct_change": q.get("pct_change"),
                            }
                    except Exception:
                        pass

                portfolio_items = []
                total_pnl = 0.0
                total_value = 0.0
                for p in positions:
                    sym = p.get("symbol", "")
                    cost = p.get("cost_price", 0) or 0
                    shares = p.get("shares", 0) or 0
                    live = live_quotes.get(sym, {})
                    current_price = live.get("price") or cost
                    today_change = live.get("pct_change")
                    pnl_pct = ((current_price - cost) / cost * 100) if cost > 0 else 0
                    pnl_amount = (current_price - cost) * shares

                    total_pnl += pnl_amount
                    total_value += current_price * shares

                    portfolio_items.append(
                        {
                            "symbol": sym,
                            "name": p.get("name", ""),
                            "shares": shares,
                            "cost": round(cost, 2),
                            "current_price": round(current_price, 2),
                            "today_change_pct": round(today_change, 2)
                            if today_change
                            else None,
                            "pnl_pct": round(pnl_pct, 2),
                            "pnl_amount": round(pnl_amount, 0),
                        }
                    )

                pulse["portfolio"] = {
                    "position_count": len(positions),
                    "total_value": round(total_value, 0),
                    "total_pnl": round(total_pnl, 0),
                    "positions": portfolio_items,
                }
            else:
                pulse["portfolio"] = {"position_count": 0, "positions": []}

        # 2b. Capital
        cs = get_capital_service()
        if cs:
            try:
                balance = cs.get_balance()
                cash = float(balance) if isinstance(balance, (int, float)) else 0
                pulse["capital"] = {
                    "available_cash": round(cash, 2),
                    "total_assets": round(cash + total_value, 2),
                }
            except Exception:
                pass
    except Exception as exc:
        pulse["portfolio"] = {"error": str(exc)}

    # 3. Sector rotation from cache
    try:
        from src.web.dependencies import get_redis

        r = get_redis()
        if r:
            cached = r.get("sector_flow:rotation")
            if cached:
                rotation = json.loads(cached)
                pulse["sector_rotation"] = {
                    "top_in": [
                        s.get("sector", "") for s in rotation.get("rotating_in", [])[:5]
                    ],
                    "top_out": [
                        s.get("sector", "")
                        for s in rotation.get("rotating_out", [])[:3]
                    ],
                }
    except Exception:
        pass

    # 4. Recent scanner candidates (top 5)
    try:
        from src.web.dependencies import get_redis

        r = get_redis()
        if r:
            date_key = _dt.now().strftime("%Y%m%d")
            candidates = r.zrevrange(
                f"scanner:candidates:{date_key}", 0, 4, withscores=True
            )
            if candidates:
                pulse["top_candidates"] = []
                for raw, score in candidates:
                    try:
                        c = json.loads(raw)
                        pulse["top_candidates"].append(
                            {
                                "symbol": c.get("symbol"),
                                "name": c.get("name"),
                                "score": round(score, 1),
                                "reason": c.get("reason", "")[:80],
                            }
                        )
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception:
        pass

    # Cache result in Redis (120s TTL)
    try:
        if _r:
            _r.set(
                _cache_key, json.dumps(pulse, ensure_ascii=False, default=str), ex=120
            )
    except Exception:
        pass

    return pulse


def _get_limit_up_pool() -> dict[str, Any]:
    """Get today's limit-up (涨停) stock pool."""
    try:
        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        df = fetcher.fetch_limit_up_pool()
        if df is None or df.empty:
            return {"stocks": [], "count": 0}

        stocks = []
        for _, row in df.head(30).iterrows():
            stocks.append(
                {
                    "symbol": row.get("symbol", ""),
                    "name": row.get("name", ""),
                    "pct_change": row.get("pct_change"),
                    "price": row.get("price"),
                    "seal_amount": row.get("seal_amount"),
                    "first_seal_time": str(row.get("first_seal_time", "")),
                    "break_count": row.get("break_count", 0),
                    "consecutive": row.get("consecutive", 1),
                    "industry": row.get("industry", ""),
                }
            )
        return {"stocks": stocks, "count": len(df)}
    except Exception as exc:
        return {"error": str(exc)}


def _get_sector_leaders(top_n: int = 5) -> dict[str, Any]:
    """Get top sectors by capital inflow with leader stocks."""
    try:
        from src.data.intraday_sector_flow import IntradaySectorFlowTracker

        tracker = IntradaySectorFlowTracker()
        flow_list = tracker.fetch_current_flow()
        if not flow_list:
            return {"sectors": [], "error": "no_data"}

        # Already sorted by net_inflow descending from fetch_current_flow
        sectors = []
        for s in flow_list[:top_n]:
            sectors.append(
                {
                    "sector": s.get("sector", ""),
                    "net_inflow": s.get("net_inflow"),
                    "change_pct": s.get("change_pct"),
                    "leader_stock": s.get("leader_stock", ""),
                    "leader_change": s.get("leader_change"),
                }
            )
        return {"sectors": sectors}
    except Exception as exc:
        return {"error": str(exc)}

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
from typing import Any, Callable

from src.utils.logger import get_logger

logger = get_logger("web.tool_registry")

_TOOL_TIMEOUT_SECONDS = 120


@dataclass
class ToolDefinition:
    """Internal registration entry for a tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]
    is_async: bool = False


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

        start = time.perf_counter()
        try:
            if td.is_async:
                result = await asyncio.wait_for(
                    td.handler(**tool_input), timeout=_TOOL_TIMEOUT_SECONDS
                )
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(td.handler, **tool_input),
                    timeout=_TOOL_TIMEOUT_SECONDS,
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
            logger.warning("Tool %s timed out after %ds", name, _TOOL_TIMEOUT_SECONDS)
            return json.dumps(
                {
                    "error": f"工具 {name} 执行超时 ({_TOOL_TIMEOUT_SECONDS}s)",
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
    ) -> None:
        """Register a tool.

        Args:
            name: Unique tool name.
            description: Human-readable description for Claude.
            input_schema: JSON Schema describing the tool input.
            handler: Callable implementing the tool logic.
            is_async: Whether the handler is an async coroutine.
        """
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            is_async=is_async,
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

        self.register(
            name="execute_trade",
            description=(
                "执行一笔模拟交易（买入/卖出/加仓/减仓）。"
                "交易将记录到用户的模拟持仓中。"
                "在给出交易建议并获得用户确认后调用此工具。"
            ),
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
            handler=lambda symbol, stock_name, action, shares, price, reasoning="": (
                trade_service.execute_trade(
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
                    _serialize_risk_results(
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
            handler=lambda symbol, name="": _handle_constraint_check(symbol, name),
        )

        logger.info("Registered 6 intelligence tools (v34.0)")


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

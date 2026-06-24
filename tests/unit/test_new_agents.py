"""Tests for Phase 3 specialist agents (9 new agents).

Covers:
- DataQAAgent (rule-based)
- BacktestAgent (rule-based)
- CorrelationAgent (rule-based)
- ExecPlanAgent (rule-based)
- PredictionMonitorAgent (rule-based)
- SentimentAgent (LLM-backed)
- RegimeAgent (LLM-backed)
- PortfolioAgent (LLM-backed)
- ReportAgent (LLM-backed)

Part of v18.0 Agent Spec Compliance — Phase 3.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

from src.agents.base import AgentCapability, AgentMessage


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


class MockToolRegistry:
    """Fake tool registry returning preconfigured results per tool name."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self._results = results or {}
        self.calls: list[tuple[str, dict]] = []

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [{"name": n} for n in self._results]

    async def execute(self, name: str, tool_input: dict[str, Any]) -> str:
        self.calls.append((name, tool_input))
        val = self._results.get(name, '{"error": "unknown tool"}')
        if isinstance(val, dict):
            return json.dumps(val, ensure_ascii=False)
        if isinstance(val, Exception):
            raise val
        return val


class ErrorToolRegistry(MockToolRegistry):
    """Tool registry that raises on every execute call."""

    async def execute(self, name: str, tool_input: dict[str, Any]) -> str:
        self.calls.append((name, tool_input))
        raise RuntimeError(f"Tool {name} unavailable")


def _cap(name: str, tools: list[str] | None = None, **kw: Any) -> AgentCapability:
    return AgentCapability(
        name=name,
        tool_whitelist=tools or [],
        **kw,
    )


def _msg(
    task: str = "分析",
    symbol: str = "600519",
    ctx: dict[str, Any] | None = None,
    budget: int = 10000,
) -> AgentMessage:
    context: dict[str, Any] = {"symbol": symbol}
    if ctx:
        context.update(ctx)
    return AgentMessage(
        from_agent="master",
        to_agent="test_agent",
        task=task,
        context=context,
        budget_remaining=budget,
    )


@dataclass
class FakeToolCall:
    id: str = "tc_1"
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class FakeLLMResponse:
    text: str = ""
    tool_calls: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    input_tokens: int = 100
    output_tokens: int = 200
    raw_assistant_content: Any = None


# ═══════════════════════════════════════════════════════════════════════════
# DataQAAgent
# ═══════════════════════════════════════════════════════════════════════════


class TestDataQAAgent:
    def _make(self, tool_results: dict | None = None) -> Any:
        from src.agents.data_qa_agent import DataQAAgent

        tools = MockToolRegistry(
            tool_results
            or {
                "get_realtime_quote": {"price": 1800.0},
                "get_technical_indicators": {"macd": 0.5},
                "check_trading_day": {"is_trading_day": True},
            }
        )
        cap = _cap(
            "data_qa",
            ["get_realtime_quote", "get_technical_indicators", "check_trading_day"],
        )
        return DataQAAgent(capability=cap, tool_registry=tools), tools

    def test_all_checks_pass(self):
        agent, tools = self._make()
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert data["is_sufficient"] is True
        assert data["data_quality_score"] == 100
        assert data["confidence_score"] == 1.0
        assert len(data["data_gaps"]) == 0
        assert len(tools.calls) == 3

    def test_non_trading_day_deducts(self):
        agent, _ = self._make(
            {
                "get_realtime_quote": {"price": 100},
                "get_technical_indicators": {"rsi": 50},
                "check_trading_day": {"is_trading_day": False},
            }
        )
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert data["data_quality_score"] == 90
        assert data["is_sufficient"] is True
        assert any("非交易日" in g for g in data["data_gaps"])

    def test_quote_error_deducts_30(self):
        agent, _ = self._make(
            {
                "get_realtime_quote": {"error": "timeout"},
                "get_technical_indicators": {"rsi": 50},
                "check_trading_day": {"is_trading_day": True},
            }
        )
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert data["data_quality_score"] == 70
        assert data["is_sufficient"] is True

    def test_all_tools_fail_score_drops(self):
        agent, _ = self._make()
        # Use error-throwing tools — quote(-30) + indicators(-20) = score 50
        agent._tools = ErrorToolRegistry()
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert data["data_quality_score"] == 50
        assert data["is_sufficient"] is True  # 50 >= 40 threshold
        assert len(data["data_gaps"]) >= 2

    def test_no_symbol_skips_checks(self):
        agent, tools = self._make()
        msg = _msg(symbol="")
        result = asyncio.run(agent._execute_impl(msg))
        data = json.loads(result.result)
        # Only trading_day check should run
        assert data["data_quality_score"] == 100
        assert len(tools.calls) == 1  # just check_trading_day

    def test_delegation_chain(self):
        agent, _ = self._make()
        result = asyncio.run(agent._execute_impl(_msg()))
        assert "data_qa" in result.delegation_chain

    def test_tokens_zero_for_rule_engine(self):
        agent, _ = self._make()
        result = asyncio.run(agent._execute_impl(_msg()))
        assert result.tokens_used == 0


# ═══════════════════════════════════════════════════════════════════════════
# BacktestAgent
# ═══════════════════════════════════════════════════════════════════════════


class TestBacktestAgent:
    def _make(self, bt_result: dict | None = None) -> Any:
        from src.agents.backtest_agent import BacktestAgent

        tools = MockToolRegistry(
            {
                "backtest_strategy": bt_result
                or {
                    "win_rate": 0.55,
                    "total_trades": 120,
                    "annual_return": 0.15,
                    "max_drawdown": -0.12,
                },
            }
        )
        cap = _cap("backtest", ["backtest_strategy"])
        return BacktestAgent(capability=cap, tool_registry=tools), tools

    def test_normal_backtest(self):
        agent, _ = self._make()
        msg = _msg(ctx={"signal": "trend_following"})
        result = asyncio.run(agent._execute_impl(msg))
        data = json.loads(result.result)
        assert data["overfit_warning"] is False
        assert data["confidence_score"] == 0.7
        assert len(data["walk_forward_report"]) > 0

    def test_overfit_high_winrate_low_trades(self):
        agent, _ = self._make(
            {
                "win_rate": 0.90,
                "total_trades": 10,
                "annual_return": 0.3,
                "max_drawdown": -0.1,
            }
        )
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert data["overfit_warning"] is True
        assert data["confidence_score"] == 0.4

    def test_overfit_suspicious_drawdown(self):
        agent, _ = self._make(
            {
                "win_rate": 0.6,
                "total_trades": 50,
                "annual_return": 0.6,
                "max_drawdown": -0.03,
            }
        )
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert data["overfit_warning"] is True

    def test_no_symbol(self):
        agent, tools = self._make()
        result = asyncio.run(agent._execute_impl(_msg(symbol="")))
        data = json.loads(result.result)
        assert any("未提供股票代码" in g for g in data["data_gaps"])
        assert len(tools.calls) == 0

    def test_signal_mapping_trend(self):
        from src.agents.backtest_agent import BacktestAgent

        assert BacktestAgent._map_signal_to_strategy("趋势突破") == "trend_following"
        assert (
            BacktestAgent._map_signal_to_strategy("breakout signal")
            == "trend_following"
        )

    def test_signal_mapping_mean_reversion(self):
        from src.agents.backtest_agent import BacktestAgent

        assert BacktestAgent._map_signal_to_strategy("均值回归") == "mean_reversion"
        assert (
            BacktestAgent._map_signal_to_strategy("oversold bounce") == "mean_reversion"
        )

    def test_signal_mapping_default(self):
        from src.agents.backtest_agent import BacktestAgent

        assert BacktestAgent._map_signal_to_strategy("") == "momentum"
        assert BacktestAgent._map_signal_to_strategy("some unknown") == "momentum"

    def test_tool_error_graceful(self):
        from src.agents.backtest_agent import BacktestAgent

        tools = ErrorToolRegistry()
        cap = _cap("backtest", ["backtest_strategy"])
        agent = BacktestAgent(capability=cap, tool_registry=tools)
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert any("回测执行失败" in g for g in data["data_gaps"])
        assert data["confidence_score"] == 0.4


# ═══════════════════════════════════════════════════════════════════════════
# CorrelationAgent
# ═══════════════════════════════════════════════════════════════════════════


class TestCorrelationAgent:
    def _make(self, portfolio: list | None = None) -> Any:
        from src.agents.correlation_agent import CorrelationAgent

        tools = MockToolRegistry(
            {
                "get_portfolio": {
                    "positions": portfolio
                    or [
                        {"symbol": "600519", "shares": 100},
                        {"symbol": "000858", "shares": 200},
                        {"symbol": "601318", "shares": 300},
                    ],
                },
            }
        )
        cap = _cap("correlation", ["get_portfolio"])
        return CorrelationAgent(capability=cap, tool_registry=tools), tools

    def test_multi_position_diversification(self):
        agent, _ = self._make()
        result = asyncio.run(
            agent._execute_impl(
                _msg(
                    ctx={
                        "portfolio": [
                            {"symbol": "600519"},
                            {"symbol": "000858"},
                            {"symbol": "601318"},
                        ]
                    }
                )
            )
        )
        data = json.loads(result.result)
        assert 0 < data["diversification_score"] <= 1.0
        assert len(data["symbols_analyzed"]) == 3

    def test_single_position_zero_diversification(self):
        agent, _ = self._make()
        result = asyncio.run(
            agent._execute_impl(
                _msg(
                    ctx={
                        "portfolio": [
                            {"symbol": "600519"},
                        ]
                    }
                )
            )
        )
        data = json.loads(result.result)
        assert data["diversification_score"] == 0.0
        assert any("单只股票" in g for g in data["data_gaps"])

    def test_no_portfolio_fetches_from_tool(self):
        agent, tools = self._make()
        # Don't pass portfolio in context — agent should call get_portfolio
        msg = _msg()
        msg.context.pop("portfolio", None)
        result = asyncio.run(agent._execute_impl(msg))
        assert any(c[0] == "get_portfolio" for c in tools.calls)
        data = json.loads(result.result)
        assert len(data["symbols_analyzed"]) == 3

    def test_empty_portfolio_fetches_from_tool(self):
        from src.agents.correlation_agent import CorrelationAgent

        # Empty portfolio ([]) is falsy → agent tries get_portfolio tool
        # Mock returns empty positions too
        tools = MockToolRegistry(
            {
                "get_portfolio": {"positions": []},
            }
        )
        cap = _cap("correlation", ["get_portfolio"])
        agent = CorrelationAgent(capability=cap, tool_registry=tools)
        result = asyncio.run(agent._execute_impl(_msg(ctx={"portfolio": []})))
        data = json.loads(result.result)
        assert any("无持仓数据" in g for g in data["data_gaps"])
        assert any(c[0] == "get_portfolio" for c in tools.calls)

    def test_returns_matrix_boosts_confidence(self):
        agent, _ = self._make()
        result = asyncio.run(
            agent._execute_impl(
                _msg(
                    ctx={
                        "portfolio": [{"symbol": "A"}, {"symbol": "B"}],
                        "returns_matrix": {"A": [0.01, -0.02], "B": [0.02, -0.01]},
                    }
                )
            )
        )
        data = json.loads(result.result)
        assert data["confidence_score"] == 0.8


# ═══════════════════════════════════════════════════════════════════════════
# ExecPlanAgent
# ═══════════════════════════════════════════════════════════════════════════


class TestExecPlanAgent:
    def _make(self, cb_result: dict | None = None) -> Any:
        from src.agents.exec_plan_agent import ExecPlanAgent

        tools = MockToolRegistry(
            {
                "check_circuit_breaker": cb_result or {"can_trade": True},
            }
        )
        cap = _cap(
            "exec_plan", ["check_circuit_breaker", "get_portfolio", "get_trade_history"]
        )
        return ExecPlanAgent(capability=cap, tool_registry=tools), tools

    def test_risk_approved_circuit_ok(self):
        agent, _ = self._make()
        result = asyncio.run(
            agent._execute_impl(
                _msg(
                    ctx={
                        "action": "buy",
                        "suggested_shares": 100,
                        "risk_approved": True,
                        "risk_level": "low",
                    }
                )
            )
        )
        data = json.loads(result.result)
        assert data["execution_plan"]["status"] == "ready"
        assert data["execution_plan"]["gate_stage"] == "RISK_APPROVED"
        assert data["confidence_score"] == 0.95
        assert data["gate_request_id"].startswith("gate-")

    def test_risk_not_approved_blocks(self):
        agent, _ = self._make()
        result = asyncio.run(
            agent._execute_impl(
                _msg(
                    ctx={
                        "action": "buy",
                        "risk_approved": False,
                    }
                )
            )
        )
        data = json.loads(result.result)
        assert data["execution_plan"]["status"] == "blocked"
        assert data["execution_plan"]["gate_stage"] == "PENDING"
        assert data["confidence_score"] == 0.3

    def test_circuit_breaker_triggered(self):
        agent, _ = self._make({"can_trade": False, "reason": "daily_loss_limit"})
        result = asyncio.run(
            agent._execute_impl(
                _msg(
                    ctx={
                        "action": "sell",
                        "risk_approved": True,
                    }
                )
            )
        )
        data = json.loads(result.result)
        assert data["execution_plan"]["status"] == "blocked"
        assert data["execution_plan"]["gate_stage"] == "REJECTED"

    def test_simulation_record_always_present(self):
        agent, _ = self._make()
        result = asyncio.run(agent._execute_impl(_msg(ctx={"action": "buy"})))
        data = json.loads(result.result)
        sim = data["simulation_record"]
        assert "gate_request_id" in sim
        assert sim["proposed_trade"]["symbol"] == "600519"

    def test_circuit_check_error_defaults_ok(self):
        from src.agents.exec_plan_agent import ExecPlanAgent

        tools = ErrorToolRegistry()
        cap = _cap("exec_plan", ["check_circuit_breaker"])
        agent = ExecPlanAgent(capability=cap, tool_registry=tools)
        result = asyncio.run(agent._execute_impl(_msg(ctx={"risk_approved": True})))
        data = json.loads(result.result)
        # Defaults to circuit_ok=True when check fails
        assert data["execution_plan"]["status"] == "ready"
        assert any("熔断检查不可用" in g for g in data["data_gaps"])


# ═══════════════════════════════════════════════════════════════════════════
# PredictionMonitorAgent
# ═══════════════════════════════════════════════════════════════════════════


class TestPredictionMonitorAgent:
    def _make(self) -> Any:
        from src.agents.prediction_monitor_agent import PredictionMonitorAgent

        tools = MockToolRegistry()
        cap = _cap("monitor", [])
        return PredictionMonitorAgent(capability=cap, tool_registry=tools)

    def test_graceful_without_model_monitor(self):
        agent = self._make()
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        # ModelMonitor likely not importable in test env
        assert "data_gaps" in data
        assert data["confidence_score"] <= 0.5
        assert data["window_days"] == 30

    def test_custom_window_days(self):
        agent = self._make()
        result = asyncio.run(agent._execute_impl(_msg(ctx={"window_days": 60})))
        data = json.loads(result.result)
        assert data["window_days"] == 60

    def test_tokens_zero(self):
        agent = self._make()
        result = asyncio.run(agent._execute_impl(_msg()))
        assert result.tokens_used == 0

    def test_delegation_chain(self):
        agent = self._make()
        result = asyncio.run(agent._execute_impl(_msg()))
        assert "monitor" in result.delegation_chain


# ═══════════════════════════════════════════════════════════════════════════
# SentimentAgent (LLM-backed)
# ═══════════════════════════════════════════════════════════════════════════


class TestSentimentAgent:
    def _make(self, llm_text: str = "", tool_calls: list | None = None) -> Any:
        from src.agents.sentiment_agent import SentimentAgent

        tools = MockToolRegistry(
            {
                "get_trending_news": {"articles": [{"title": "test news"}]},
                "get_sentiment_report": {"sentiment": 0.3},
            }
        )
        llm = MagicMock()
        resp = FakeLLMResponse(
            text=llm_text or '{"sentiment_score": 0.3, "sentiment_signal": "bullish"}',
            tool_calls=tool_calls or [],
        )
        llm.complete_with_tools.return_value = resp
        cap = _cap(
            "sentiment", ["get_trending_news", "get_sentiment_report"], max_tokens=2048
        )
        return (
            SentimentAgent(capability=cap, tool_registry=tools, llm_router=llm),
            tools,
            llm,
        )

    def test_direct_response_no_tools(self):
        agent, _, llm = self._make()
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert data["sentiment_score"] == 0.3
        assert data["sentiment_signal"] == "bullish"
        assert result.tokens_used == 300  # 100 + 200

    def test_tool_use_round(self):
        from src.agents.sentiment_agent import SentimentAgent

        tools = MockToolRegistry(
            {
                "get_trending_news": '{"articles": []}',
            }
        )
        llm = MagicMock()
        # First call: request tool use
        resp1 = FakeLLMResponse(
            text="",
            tool_calls=[FakeToolCall(id="tc_1", name="get_trending_news", input={})],
            stop_reason="tool_use",
        )
        # Second call: final answer
        resp2 = FakeLLMResponse(
            text='{"sentiment_score": -0.2, "sentiment_signal": "bearish"}',
        )
        llm.complete_with_tools.side_effect = [resp1, resp2]

        cap = _cap("sentiment", ["get_trending_news"], max_tokens=2048)
        agent = SentimentAgent(capability=cap, tool_registry=tools, llm_router=llm)
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert data["sentiment_signal"] == "bearish"
        assert result.tool_calls_made == 1
        assert llm.complete_with_tools.call_count == 2

    def test_budget_exhausted(self):
        agent, _, _ = self._make()
        msg = _msg(budget=100)
        result = asyncio.run(agent._execute_impl(msg))
        # Budget < 500 threshold → early exit
        assert "预算不足" in result.result

    def test_forbidden_tool_rejected(self):
        from src.agents.sentiment_agent import SentimentAgent

        tools = MockToolRegistry({"execute_trade": '{"ok": true}'})
        llm = MagicMock()
        resp1 = FakeLLMResponse(
            text="",
            tool_calls=[FakeToolCall(id="tc_1", name="execute_trade", input={})],
            stop_reason="tool_use",
        )
        resp2 = FakeLLMResponse(text='{"sentiment_score": 0}')
        llm.complete_with_tools.side_effect = [resp1, resp2]

        cap = _cap("sentiment", ["get_trending_news"], max_tokens=2048)
        agent = SentimentAgent(capability=cap, tool_registry=tools, llm_router=llm)
        result = asyncio.run(agent._execute_impl(_msg()))
        # Tool should be rejected because execute_trade is not in whitelist
        assert result.tool_calls_made == 0


# ═══════════════════════════════════════════════════════════════════════════
# RegimeAgent (LLM-backed)
# ═══════════════════════════════════════════════════════════════════════════


class TestRegimeAgent:
    def _make(self, llm_text: str = "") -> Any:
        from src.agents.regime_agent import RegimeAgent

        tools = MockToolRegistry(
            {
                "get_global_markets": {"us": {"sp500": 4500}},
                "analyze_cross_market": {"correlation": 0.7},
            }
        )
        llm = MagicMock()
        resp = FakeLLMResponse(
            text=llm_text or '{"current_regime": "sideways", "regime_confidence": 0.6}',
        )
        llm.complete_with_tools.return_value = resp
        cap = _cap(
            "regime", ["get_global_markets", "analyze_cross_market"], max_tokens=2048
        )
        return RegimeAgent(capability=cap, tool_registry=tools, llm_router=llm), llm

    def test_direct_regime_detection(self):
        agent, _ = self._make()
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert data["current_regime"] == "sideways"
        assert data["regime_confidence"] == 0.6
        assert result.tokens_used == 300

    def test_budget_exhausted_fallback(self):
        agent, _ = self._make()
        result = asyncio.run(agent._execute_impl(_msg(budget=100)))
        data = json.loads(result.result)
        assert data["current_regime"] == "unknown"

    def test_prompt_includes_output_spec(self):
        agent, _ = self._make()
        prompt = agent._build_prompt(_msg())
        assert "current_regime" in prompt
        assert "regime_confidence" in prompt
        assert "transition_matrix" in prompt


# ═══════════════════════════════════════════════════════════════════════════
# PortfolioAgent (LLM-backed)
# ═══════════════════════════════════════════════════════════════════════════


class TestPortfolioAgent:
    def _make(self, llm_text: str = "") -> Any:
        from src.agents.portfolio_agent import PortfolioAgent

        tools = MockToolRegistry(
            {
                "get_portfolio": '{"positions": []}',
                "get_capital_balance": '{"available": 100000}',
                "calculate_position_size": '{"shares": 200}',
            }
        )
        llm = MagicMock()
        resp = FakeLLMResponse(
            text=llm_text or '{"adjustments": [], "suggested_shares": 200}',
        )
        llm.complete_with_tools.return_value = resp
        cap = _cap(
            "portfolio",
            [
                "get_portfolio",
                "get_capital_balance",
                "calculate_position_size",
                "calculate_var",
            ],
            max_tokens=2048,
        )
        return PortfolioAgent(capability=cap, tool_registry=tools, llm_router=llm), llm

    def test_direct_recommendation(self):
        agent, _ = self._make()
        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert "adjustments" in data
        assert result.tokens_used == 300

    def test_budget_exhausted(self):
        agent, _ = self._make()
        result = asyncio.run(agent._execute_impl(_msg(budget=100)))
        data = json.loads(result.result)
        assert "预算不足" in json.dumps(data, ensure_ascii=False)

    def test_prompt_includes_symbol(self):
        agent, _ = self._make()
        prompt = agent._build_prompt(_msg(symbol="000858"))
        assert "000858" in prompt
        assert "Target Stock" in prompt

    def test_prompt_no_symbol(self):
        agent, _ = self._make()
        prompt = agent._build_prompt(_msg(symbol=""))
        assert "Target Stock" not in prompt


# ═══════════════════════════════════════════════════════════════════════════
# ReportAgent (LLM-backed)
# ═══════════════════════════════════════════════════════════════════════════


class TestReportAgent:
    def _make(self, llm_text: str = "") -> Any:
        from src.agents.report_agent import ReportAgent

        tools = MockToolRegistry()
        llm = MagicMock()
        resp = FakeLLMResponse(
            text=llm_text
            or json.dumps(
                {
                    "report_markdown": "# Report",
                    "executive_summary": "Summary",
                    "scenarios": [
                        {"name": "乐观", "probability": 0.3, "risk_level": "low"},
                        {"name": "中性", "probability": 0.5, "risk_level": "medium"},
                        {"name": "悲观", "probability": 0.2, "risk_level": "high"},
                    ],
                    "confidence_score": 0.7,
                },
                ensure_ascii=False,
            ),
        )
        llm.complete_with_tools.return_value = resp
        cap = _cap("report", [], max_tokens=4096)
        return ReportAgent(capability=cap, tool_registry=tools, llm_router=llm), llm

    def test_report_synthesis(self):
        agent, _ = self._make()
        result = asyncio.run(
            agent._execute_impl(
                _msg(
                    ctx={
                        "signal": "bullish",
                        "confidence_score": 0.7,
                        "sentiment_score": 0.3,
                    }
                )
            )
        )
        data = json.loads(result.result)
        assert "report_markdown" in data
        assert len(data["scenarios"]) == 3

    def test_fallback_on_llm_failure(self):
        from src.agents.report_agent import ReportAgent

        tools = MockToolRegistry()
        llm = MagicMock()
        llm.complete_with_tools.side_effect = RuntimeError("LLM down")
        cap = _cap("report", [], max_tokens=4096)
        agent = ReportAgent(capability=cap, tool_registry=tools, llm_router=llm)

        result = asyncio.run(agent._execute_impl(_msg()))
        data = json.loads(result.result)
        assert "报告生成失败" in data["executive_summary"]
        assert data["confidence_score"] == 0.2
        assert result.tokens_used == 0

    def test_context_summary_extraction(self):
        from src.agents.report_agent import ReportAgent

        ctx = {
            "signal": "bullish",
            "confidence_score": 0.8,
            "data_quality_score": 90,
            "sentiment_score": 0.5,
            "current_regime": "bull",
        }
        summary = ReportAgent._summarize_context(ctx)
        assert "signal" in summary
        assert "confidence_score" in summary
        assert "bullish" in summary

    def test_context_summary_empty(self):
        from src.agents.report_agent import ReportAgent

        summary = ReportAgent._summarize_context({})
        assert "(No analysis data available)" in summary

    def test_prompt_includes_symbol(self):
        agent, _ = self._make()
        prompt = agent._build_prompt(_msg(symbol="600519"))
        assert "600519" in prompt
        assert "Analysis Target" in prompt

    def test_prompt_includes_rules(self):
        agent, _ = self._make()
        prompt = agent._build_prompt(_msg())
        assert "The three scenario probabilities must sum to 1.0" in prompt
        assert "written in Chinese" in prompt

    def test_no_tool_calls(self):
        agent, _ = self._make()
        result = asyncio.run(agent._execute_impl(_msg()))
        assert result.tool_calls_made == 0

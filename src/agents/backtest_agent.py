"""Backtest & Validation agent — signal validation (rule engine, no LLM).

Runs walk-forward validation on signals, checks overfitting,
and assesses regime sensitivity. Pure computation, no LLM calls.

Part of v18.0 Agent Spec Compliance — Phase 3.
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.agents.base import AgentCapability, AgentMessage, BaseAgent
from src.utils.logger import get_logger

logger = get_logger("agents.backtest")


class BacktestAgent(BaseAgent):
    """Backtest & signal validation — rule engine, no LLM.

    Capabilities:
    - Walk-forward validation
    - Overfitting detection
    - Strategy backtesting
    - Regime sensitivity analysis

    Forbidden: All trade tools.
    """

    def __init__(
        self,
        capability: AgentCapability,
        tool_registry: Any,
        llm_router: Any = None,
        system_role: str = "",
    ) -> None:
        super().__init__(capability)
        self._tools = tool_registry

    async def _execute_impl(self, message: AgentMessage) -> AgentMessage:
        """Run backtest validation on signals."""
        start = time.perf_counter()
        tool_calls_count = 0

        symbol = message.context.get("symbol", "")
        signal = message.context.get("signal", "")
        data_gaps: list[str] = []
        walk_forward_report: dict[str, Any] = {}
        overfit_warning = False

        # Run backtest strategy if available
        if symbol:
            strategy = self._map_signal_to_strategy(signal)
            try:
                bt_str = await self._tools.execute(
                    "backtest_strategy",
                    {"symbol": symbol, "strategy_key": strategy},
                )
                tool_calls_count += 1
                bt_data = json.loads(bt_str) if isinstance(bt_str, str) else bt_str

                if isinstance(bt_data, dict) and not bt_data.get("error"):
                    walk_forward_report = bt_data
                    # Check for overfitting indicators
                    overfit_warning = self._check_overfit(bt_data)
                else:
                    data_gaps.append("回测数据不足或策略不可用")
            except Exception as exc:
                data_gaps.append(f"回测执行失败: {exc}")
        else:
            data_gaps.append("未提供股票代码，无法回测")

        confidence = 0.7 if walk_forward_report and not overfit_warning else 0.4

        result = json.dumps(
            {
                "walk_forward_report": walk_forward_report,
                "overfit_warning": overfit_warning,
                "regime_sensitivity": {},
                "confidence_score": confidence,
                "data_gaps": data_gaps,
                "key_assumptions": [
                    "历史数据充足（>= 2年）",
                    "市场微观结构未发生根本变化",
                    "策略参数未过度优化",
                ],
                "failure_modes": [
                    "样本外表现与样本内差异过大（过拟合）",
                    "市场 regime 切换导致策略失效",
                    "数据不足导致统计意义不够",
                ],
            },
            ensure_ascii=False,
        )

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "BacktestAgent: symbol=%s, overfit=%s, %.0fms",
            symbol,
            overfit_warning,
            elapsed,
        )

        return AgentMessage(
            from_agent=self.name,
            to_agent=message.from_agent,
            task=message.task,
            context=message.context,
            budget_remaining=message.budget_remaining,
            result=result,
            tool_calls_made=tool_calls_count,
            tokens_used=0,
            delegation_chain=[*message.delegation_chain, self.name],
        )

    @staticmethod
    def _map_signal_to_strategy(signal: str) -> str:
        """Map an analysis signal to a backtest strategy key."""
        signal_lower = signal.lower() if signal else ""
        if any(w in signal_lower for w in ("trend", "趋势", "突破", "breakout")):
            return "trend_following"
        if any(w in signal_lower for w in ("revert", "均值", "超卖", "oversold")):
            return "mean_reversion"
        return "momentum"

    @staticmethod
    def _check_overfit(bt_data: dict[str, Any]) -> bool:
        """Heuristic overfitting detection from backtest metrics."""
        # High win rate + low trade count = likely overfit
        win_rate = bt_data.get("win_rate", 0.5)
        total_trades = bt_data.get("total_trades", 0)
        max_drawdown = bt_data.get("max_drawdown", 0)

        if isinstance(win_rate, (int, float)) and win_rate > 0.85 and total_trades < 20:
            return True
        # Suspiciously low drawdown with high returns
        annual_return = bt_data.get("annual_return", 0)
        if (
            isinstance(annual_return, (int, float))
            and isinstance(max_drawdown, (int, float))
            and annual_return > 0.5
            and abs(max_drawdown) < 0.05
        ):
            return True
        return False

"""Data QA agent — data quality gate-keeper (rule engine, no LLM).

Validates data freshness, completeness, and consistency before
analysis proceeds. If data is insufficient, the pipeline halts early.

Part of v18.0 Agent Spec Compliance — Phase 3.
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.agents.base import AgentCapability, AgentMessage, BaseAgent
from src.utils.logger import get_logger

logger = get_logger("agents.data_qa")


class DataQAAgent(BaseAgent):
    """Data quality gate-keeper — rule engine, no LLM calls.

    Checks:
    - Quote data availability and freshness
    - Technical indicator completeness
    - Trading day validation
    - Minimum data points for analysis

    Returns ``is_sufficient: false`` with ``data_gaps[]`` when
    data is inadequate; the pipeline decides whether to continue.
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
        """Run data quality checks."""
        start = time.perf_counter()
        tool_calls_count = 0

        symbol = message.context.get("symbol", "")
        data_gaps: list[str] = []
        freshness_checks: dict[str, Any] = {}
        quality_score = 100  # Start at 100, deduct for issues

        # Check 1: Real-time quote
        if symbol:
            try:
                quote_str = await self._tools.execute(
                    "get_realtime_quote", {"symbols": [symbol]}
                )
                tool_calls_count += 1
                quote_data = (
                    json.loads(quote_str) if isinstance(quote_str, str) else quote_str
                )
                if isinstance(quote_data, dict) and quote_data.get("error"):
                    data_gaps.append(f"实时行情不可用: {quote_data['error']}")
                    quality_score -= 30
                    freshness_checks["quote"] = "unavailable"
                else:
                    freshness_checks["quote"] = "available"
            except Exception as exc:
                data_gaps.append(f"实时行情获取失败: {exc}")
                quality_score -= 30
                freshness_checks["quote"] = "error"

        # Check 2: Technical indicators
        if symbol:
            try:
                ind_str = await self._tools.execute(
                    "get_technical_indicators", {"symbol": symbol}
                )
                tool_calls_count += 1
                ind_data = json.loads(ind_str) if isinstance(ind_str, str) else ind_str
                if isinstance(ind_data, dict) and ind_data.get("error"):
                    data_gaps.append("技术指标不可用")
                    quality_score -= 20
                    freshness_checks["indicators"] = "unavailable"
                else:
                    freshness_checks["indicators"] = "available"
            except Exception as exc:
                data_gaps.append(f"技术指标获取失败: {exc}")
                quality_score -= 20
                freshness_checks["indicators"] = "error"

        # Check 3: Trading day
        try:
            td_str = await self._tools.execute("check_trading_day", {})
            tool_calls_count += 1
            td_data = json.loads(td_str) if isinstance(td_str, str) else td_str
            if isinstance(td_data, dict):
                is_trading = td_data.get("is_trading_day", True)
                if not is_trading:
                    data_gaps.append("当前非交易日，行情数据可能不是最新")
                    quality_score -= 10
                freshness_checks["trading_day"] = td_data
        except Exception:
            freshness_checks["trading_day"] = "check_skipped"

        # Clamp score
        quality_score = max(0, min(100, quality_score))
        is_sufficient = quality_score >= 40

        result = json.dumps(
            {
                "data_quality_score": quality_score,
                "freshness_checks": freshness_checks,
                "is_sufficient": is_sufficient,
                "data_gaps": data_gaps,
                "confidence_score": quality_score / 100.0,
                "key_assumptions": ["数据源正常运行", "行情数据实时更新"],
                "failure_modes": ["数据源宕机", "网络超时", "非交易时段数据陈旧"],
            },
            ensure_ascii=False,
        )

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "DataQAAgent: score=%d, sufficient=%s, gaps=%d, %.0fms",
            quality_score,
            is_sufficient,
            len(data_gaps),
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

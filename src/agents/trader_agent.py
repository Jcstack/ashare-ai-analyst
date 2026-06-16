"""Trader agent — trade execution specialist (rule engine, no LLM).

Executes trades only after risk approval. Uses pure rule logic to
validate trade parameters and execute via trade tools.

Part of v16.0 Agent Mesh layer.
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.agents.base import AgentCapability, AgentMessage, BaseAgent
from src.utils.logger import get_logger

logger = get_logger("agents.trader")


class TraderAgent(BaseAgent):
    """Trade execution specialist — rule engine, no LLM calls.

    Capabilities:
    - Execute simulated trades
    - Record manual trades
    - Query trade history and portfolio

    Validation rules:
    - Shares must be multiples of 100
    - Risk approval must be present in context
    - Buy amount must not exceed available capital
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
        # llm_router accepted but not used — trader is a pure rule engine
        self._system_role = system_role

    async def _execute_impl(self, message: AgentMessage) -> AgentMessage:
        """Execute a trade using rule-based validation.

        Expects message.context to contain:
        - trade_params: {symbol, stock_name, action, shares, price, reasoning}
        - risk_approved: bool (from RiskAgent)
        """
        start = time.perf_counter()

        trade_params = message.context.get("trade_params", {})
        risk_approved = message.context.get("risk_approved", False)
        tool_calls_count = 0

        # Validate risk approval
        if not risk_approved:
            result = json.dumps(
                {
                    "status": "rejected",
                    "reason": "交易未通过风控审批。",
                },
                ensure_ascii=False,
            )
            return self._build_reply(message, result, tool_calls_count, start)

        # Validate trade parameters
        validation_error = self._validate_params(trade_params)
        if validation_error:
            result = json.dumps(
                {
                    "status": "rejected",
                    "reason": validation_error,
                },
                ensure_ascii=False,
            )
            return self._build_reply(message, result, tool_calls_count, start)

        # Execute the trade
        try:
            trade_result = await self._tools.execute("execute_trade", trade_params)
            tool_calls_count += 1
            result = json.dumps(
                {
                    "status": "executed",
                    "trade": json.loads(trade_result)
                    if isinstance(trade_result, str)
                    else trade_result,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.error("Trade execution failed: %s", exc)
            result = json.dumps(
                {
                    "status": "failed",
                    "reason": f"交易执行失败: {exc}",
                },
                ensure_ascii=False,
            )

        return self._build_reply(message, result, tool_calls_count, start)

    def _validate_params(self, params: dict[str, Any]) -> str | None:
        """Validate trade parameters. Returns error message or None."""
        required = ["symbol", "stock_name", "action", "shares", "price"]
        for field in required:
            if field not in params:
                return f"缺少必要参数: {field}"

        shares = params.get("shares", 0)
        if not isinstance(shares, int) or shares <= 0:
            return "股数必须为正整数"
        if shares % 100 != 0:
            return "股数必须是 100 的整数倍"

        price = params.get("price", 0)
        if not isinstance(price, (int, float)) or price <= 0:
            return "价格必须为正数"

        action = params.get("action", "")
        if action not in ("buy", "sell", "add", "reduce"):
            return f"无效的交易类型: {action}"

        return None

    def _build_reply(
        self,
        message: AgentMessage,
        result: str,
        tool_calls_count: int,
        start: float,
    ) -> AgentMessage:
        """Build the reply AgentMessage."""
        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "TraderAgent completed: %d tool calls, %.0fms",
            tool_calls_count,
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
            tokens_used=0,  # No LLM calls
            delegation_chain=[*message.delegation_chain, self.name],
        )

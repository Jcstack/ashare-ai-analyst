"""Execution Planning agent — gate request creation (rule engine, no LLM).

Creates simulation records and gate requests for proposed trades.
Never executes directly — must go through ConfirmationGate.

Part of v18.0 Agent Spec Compliance — Phase 3.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from src.agents.base import AgentCapability, AgentMessage, BaseAgent
from src.utils.logger import get_logger

logger = get_logger("agents.exec_plan")


class ExecPlanAgent(BaseAgent):
    """Execution planning specialist — rule engine, no LLM.

    Creates gate requests and simulation records for proposed trades.
    Replaces direct trade execution with simulation-first flow.

    Capabilities:
    - Gate request creation
    - Circuit breaker check
    - Portfolio state query
    - Trade history query

    Forbidden: Direct ``execute_trade`` — must go through gate.
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
        """Create execution plan and gate request."""
        start = time.perf_counter()
        tool_calls_count = 0
        data_gaps: list[str] = []

        ctx = message.context
        symbol = ctx.get("symbol", "")
        action = ctx.get("action", "")
        suggested_shares = ctx.get("suggested_shares", 0)
        risk_approved = ctx.get("risk_approved", False)
        risk_level = ctx.get("risk_level", "medium")

        # Check circuit breaker
        circuit_ok = True
        try:
            cb_str = await self._tools.execute(
                "check_circuit_breaker",
                {"daily_pnl_pct": 0.0, "weekly_pnl_pct": 0.0},
            )
            tool_calls_count += 1
            cb_data = json.loads(cb_str) if isinstance(cb_str, str) else cb_str
            if isinstance(cb_data, dict):
                circuit_ok = cb_data.get("can_trade", True)
                if not circuit_ok:
                    data_gaps.append(f"熔断触发: {cb_data.get('reason', 'unknown')}")
        except Exception:
            data_gaps.append("熔断检查不可用，默认放行")

        # Build execution plan
        gate_request_id = f"gate-{uuid.uuid4().hex[:12]}"

        if not risk_approved:
            execution_plan = {
                "status": "blocked",
                "reason": "风控未审批",
                "gate_stage": "PENDING",
            }
        elif not circuit_ok:
            execution_plan = {
                "status": "blocked",
                "reason": "熔断触发，暂停交易",
                "gate_stage": "REJECTED",
            }
        else:
            execution_plan = {
                "status": "ready",
                "gate_stage": "RISK_APPROVED",
                "symbol": symbol,
                "action": action,
                "shares": suggested_shares,
                "risk_level": risk_level,
                "next_step": "等待用户确认",
            }

        simulation_record = {
            "gate_request_id": gate_request_id,
            "proposed_trade": {
                "symbol": symbol,
                "action": action,
                "shares": suggested_shares,
            },
            "risk_approved": risk_approved,
            "circuit_breaker_ok": circuit_ok,
        }

        result = json.dumps(
            {
                "gate_request_id": gate_request_id,
                "execution_plan": execution_plan,
                "simulation_record": simulation_record,
                "confidence_score": 0.95 if risk_approved and circuit_ok else 0.3,
                "data_gaps": data_gaps,
                "key_assumptions": [
                    "风控审批结果准确",
                    "熔断状态实时更新",
                    "用户将在确认门中最终决策",
                ],
                "failure_modes": [
                    "风控系统不可用",
                    "市场闪崩导致价格剧烈偏离",
                    "用户确认延迟超过行情有效期",
                ],
            },
            ensure_ascii=False,
        )

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "ExecPlanAgent: gate=%s, status=%s, %.0fms",
            gate_request_id,
            execution_plan["status"],
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

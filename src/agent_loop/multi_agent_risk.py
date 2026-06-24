"""Multi-agent Risk Manager — independent veto power over trading decisions.

The risk manager receives PMDecisions and evaluates each one against
hard risk constraints. It has VETO power: any buy/add decision can
be rejected if risk checks fail. The risk manager operates independently
from the PM and cannot be overridden.

Uses existing risk infrastructure:
- KillSwitch (emergency halt)
- CircuitBreaker (daily/weekly loss limits)
- PreflightRiskCheck (aggregated pre-order validation)

Part of the Analyst -> PM -> Risk multi-agent pipeline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.agent_loop.multi_agent_pm import PMDecision
from src.utils.logger import get_logger

logger = get_logger("agent_loop.multi_agent_risk")

# Risk manager only needs portfolio visibility + quotes
_RISK_TOOL_ALLOWLIST: set[str] = {
    "get_portfolio",
    "get_realtime_quote",
    "get_capital_balance",
}

_RISK_SYSTEM_PROMPT = (
    "你是独立风控官。你的职责是保护资金安全，有一票否决权。"
    "当风险不可接受时必须否决。\n\n"
    "## 你的权力\n"
    "- 你可以否决任何买入/加仓决策\n"
    "- 你可以缩减仓位（建议200股但你批准100股）\n"
    "- 你不能发起交易——只能批准或否决PM的决策\n"
    "- 卖出/减仓决策默认批准（减少风险敞口是好事）\n\n"
    "## 风控检查清单\n"
    "1. 杀手开关（kill switch）是否激活？激活则否决一切\n"
    "2. 熔断器状态——日亏≥15%或周亏≥25%则否决买入\n"
    "3. 单只持仓集中度——新买后单只占比是否超过总资产50%\n"
    "4. 每日亏损限额——今日已亏多少？再买入能承受吗\n"
    "5. 资金充足性——可用资金是否足够下单\n"
    "6. 历史准确率——PM的买入准确率低于30%时缩减仓位\n\n"
    "## 判断原则\n"
    "- 宁可错过机会，不可失控亏损\n"
    "- PM信心高不等于风险低——高信心买入历史上只有27%准确\n"
    "- 单日最大新增仓位不超过总资产的40%\n"
    "- 如果否决，必须给出具体原因和替代建议\n\n"
    "## 输出格式\n"
    "对PM的每个决策给出裁定：\n"
    "```json\n"
    '{"verdicts": [{"symbol": "600XXX", "approved": true, '
    '"risk_level": "medium", "veto_reason": "", '
    '"adjusted_shares": null}]}\n'
    "```\n\n"
    "approved=false 时必须填写 veto_reason。\n"
    "adjusted_shares 可选——当你认为仓位过大时给出缩减后的数量。"
)


@dataclass
class RiskVerdict:
    """Risk manager's verdict on a PM decision.

    Attributes:
        symbol: Stock code this verdict applies to.
        approved: Whether the decision is approved.
        veto_reason: Why the decision was vetoed (empty if approved).
        risk_level: "low", "medium", "high", or "critical".
        adjusted_shares: If set, risk manager recommends fewer shares.
    """

    symbol: str
    approved: bool
    veto_reason: str = ""
    risk_level: str = "medium"
    adjusted_shares: int | None = None


class RiskAgent:
    """Independent risk manager with veto power over trading decisions.

    Evaluates PM decisions using both rule-based checks (kill switch,
    circuit breaker, concentration) and LLM-based risk assessment.
    Can reject any buy/add decision or reduce position sizes.

    Args:
        gateway: LLMGateway or LLMRouter instance.
        tool_registry: ToolRegistry with all tools registered.
        kill_switch: KillSwitch instance for emergency halt check.
        circuit_breaker: CircuitBreaker instance for loss limit check.
        max_turns: Maximum LLM round-trips for risk analysis.
        max_cost_usd: Cost budget for a single risk review.
    """

    def __init__(
        self,
        gateway: Any,
        tool_registry: Any,
        kill_switch: Any | None = None,
        circuit_breaker: Any | None = None,
        max_turns: int = 5,
        max_cost_usd: float = 0.10,
    ) -> None:
        self._gateway = gateway
        self._tool_registry = tool_registry
        self._kill_switch = kill_switch
        self._circuit_breaker = circuit_breaker
        self._max_turns = max_turns
        self._max_cost_usd = max_cost_usd

    async def review(
        self,
        decisions: list[PMDecision],
        portfolio_summary: str = "",
        available_cash: float = 0.0,
        daily_pnl_pct: float = 0.0,
        weekly_pnl_pct: float = 0.0,
        calibration_accuracy: float | None = None,
    ) -> list[RiskVerdict]:
        """Review PM decisions and issue verdicts.

        Args:
            decisions: PMDecision list from the portfolio manager.
            portfolio_summary: Current portfolio text summary.
            available_cash: Available cash for new positions (CNY).
            daily_pnl_pct: Today's portfolio P&L percentage.
            weekly_pnl_pct: This week's cumulative P&L percentage.
            calibration_accuracy: PM's historical accuracy (0.0-1.0).

        Returns:
            List of RiskVerdict, one per decision. Sell/reduce
            decisions are auto-approved. Buy/add decisions go
            through both rule-based and LLM-based review.
        """
        if not decisions:
            return []

        verdicts: list[RiskVerdict] = []

        # Phase 1: Rule-based hard checks (fast, no LLM cost)
        hard_block = self._check_hard_constraints(daily_pnl_pct, weekly_pnl_pct)

        for decision in decisions:
            # Sells and reduces are always approved (reducing risk)
            if decision.action in ("sell", "reduce"):
                verdicts.append(
                    RiskVerdict(
                        symbol=decision.symbol,
                        approved=True,
                        risk_level="low",
                    )
                )
                continue

            # Hold decisions pass through
            if decision.action == "hold":
                verdicts.append(
                    RiskVerdict(
                        symbol=decision.symbol,
                        approved=True,
                        risk_level="low",
                    )
                )
                continue

            # Buy/add decisions — check hard constraints first
            if hard_block:
                verdicts.append(
                    RiskVerdict(
                        symbol=decision.symbol,
                        approved=False,
                        veto_reason=hard_block,
                        risk_level="critical",
                    )
                )
                continue

            # Concentration check
            conc_result = self._check_concentration(decision, available_cash)
            if conc_result:
                verdicts.append(conc_result)
                continue

            # Cash sufficiency
            order_amount = decision.shares * decision.entry_price
            if order_amount > 0 and order_amount > available_cash:
                verdicts.append(
                    RiskVerdict(
                        symbol=decision.symbol,
                        approved=False,
                        veto_reason=(
                            f"资金不足: 需要¥{order_amount:,.0f}, "
                            f"可用¥{available_cash:,.0f}"
                        ),
                        risk_level="critical",
                    )
                )
                continue

            # Calibration-based position reduction
            adjusted = self._apply_calibration_adjustment(
                decision, calibration_accuracy
            )

            # Mark for LLM review (passed hard checks)
            verdicts.append(
                RiskVerdict(
                    symbol=decision.symbol,
                    approved=True,
                    risk_level="medium",
                    adjusted_shares=adjusted,
                )
            )

        # Phase 2: LLM-based soft review for approved buy/add decisions
        buy_decisions = [
            (d, v)
            for d, v in zip(decisions, verdicts)
            if d.action in ("buy", "add") and v.approved
        ]

        if buy_decisions:
            llm_verdicts = await self._llm_risk_review(
                [d for d, _ in buy_decisions],
                portfolio_summary,
                available_cash,
                daily_pnl_pct,
            )

            # Merge LLM verdicts back — LLM can veto or adjust
            llm_map = {v.symbol: v for v in llm_verdicts}
            for i, (decision, verdict) in enumerate(zip(decisions, verdicts)):
                if decision.symbol in llm_map and verdict.approved:
                    llm_v = llm_map[decision.symbol]
                    if not llm_v.approved:
                        # LLM vetoed — override
                        verdicts[i] = llm_v
                    elif llm_v.adjusted_shares is not None:
                        # LLM reduced position
                        verdicts[i].adjusted_shares = llm_v.adjusted_shares
                        verdicts[i].risk_level = llm_v.risk_level

        # Log summary
        approved = sum(1 for v in verdicts if v.approved)
        vetoed = sum(1 for v in verdicts if not v.approved)
        logger.info(
            "Risk review: %d approved, %d vetoed out of %d decisions",
            approved,
            vetoed,
            len(verdicts),
        )

        return verdicts

    def _check_hard_constraints(
        self,
        daily_pnl_pct: float,
        weekly_pnl_pct: float,
    ) -> str:
        """Check kill switch and circuit breaker.

        Args:
            daily_pnl_pct: Today's P&L percentage.
            weekly_pnl_pct: This week's P&L percentage.

        Returns:
            Block reason string, or empty string if all clear.
        """
        # Kill switch
        if self._kill_switch and self._kill_switch.is_active():
            status = self._kill_switch.status()
            return f"杀手开关已激活: {status.reason}"

        # Circuit breaker
        if self._circuit_breaker:
            from src.risk.circuit_breaker import BreakerState

            breaker_status = self._circuit_breaker.check(daily_pnl_pct, weekly_pnl_pct)
            if breaker_status.state != BreakerState.NORMAL:
                return (
                    f"熔断器触发 ({breaker_status.state.value}): "
                    f"{breaker_status.trigger_reason}"
                )

        return ""

    def _check_concentration(
        self,
        decision: PMDecision,
        available_cash: float,
    ) -> RiskVerdict | None:
        """Check if a buy would create excessive concentration.

        Args:
            decision: The buy/add decision to check.
            available_cash: Available cash (CNY).

        Returns:
            RiskVerdict with veto if concentration too high, else None.
        """
        if decision.entry_price <= 0 or decision.shares <= 0:
            return None

        order_amount = decision.shares * decision.entry_price

        # Single-day new position cap: 40% of available cash
        if order_amount > available_cash * 0.4:
            suggested_shares = int((available_cash * 0.4) / decision.entry_price)
            # Round down to lot size (100 shares)
            suggested_shares = (suggested_shares // 100) * 100
            if suggested_shares <= 0:
                return RiskVerdict(
                    symbol=decision.symbol,
                    approved=False,
                    veto_reason=(
                        f"单笔下单¥{order_amount:,.0f}超过可用资金40%限额"
                        f"(¥{available_cash * 0.4:,.0f})"
                    ),
                    risk_level="high",
                )
            return RiskVerdict(
                symbol=decision.symbol,
                approved=True,
                risk_level="high",
                adjusted_shares=suggested_shares,
            )

        return None

    def _apply_calibration_adjustment(
        self,
        decision: PMDecision,
        calibration_accuracy: float | None,
    ) -> int | None:
        """Reduce position if PM's historical accuracy is poor.

        Args:
            decision: The buy/add decision.
            calibration_accuracy: PM accuracy (0.0-1.0), or None.

        Returns:
            Adjusted share count, or None if no adjustment needed.
        """
        if calibration_accuracy is None or calibration_accuracy >= 0.30:
            return None

        # Below 30% accuracy — cut position by half
        adjusted = (decision.shares // 2 // 100) * 100
        if adjusted <= 0:
            adjusted = 100  # minimum lot
        logger.info(
            "Calibration adjustment for %s: %d -> %d shares (accuracy %.0f%%)",
            decision.symbol,
            decision.shares,
            adjusted,
            calibration_accuracy * 100,
        )
        return adjusted

    async def _llm_risk_review(
        self,
        decisions: list[PMDecision],
        portfolio_summary: str,
        available_cash: float,
        daily_pnl_pct: float,
    ) -> list[RiskVerdict]:
        """LLM-based risk assessment for buy/add decisions.

        Args:
            decisions: Buy/add decisions that passed hard checks.
            portfolio_summary: Current portfolio text.
            available_cash: Available cash (CNY).
            daily_pnl_pct: Today's P&L percentage.

        Returns:
            LLM-generated verdicts for each decision.
        """
        from src.agent_loop.llm_agent import AgentLoop
        from src.llm.base import LLMMessage

        # Filter tools to risk-only subset
        all_tools = self._tool_registry.get_tool_definitions()
        risk_tools = [t for t in all_tools if t["name"] in _RISK_TOOL_ALLOWLIST]

        loop = AgentLoop(
            gateway=self._gateway,
            tool_executor=self._tool_registry.execute,
            tool_definitions=risk_tools,
            max_turns=self._max_turns,
            max_cost_usd=self._max_cost_usd,
        )

        # Build decision summary for LLM
        decision_lines: list[str] = []
        for d in decisions:
            decision_lines.append(
                f"- {d.action.upper()} {d.symbol}: "
                f"{d.shares}股 @ ¥{d.entry_price:.2f} "
                f"(止损¥{d.stop_loss:.2f}, 目标¥{d.target_price:.2f}, "
                f"信心{d.confidence:.0%})\n"
                f"  理由: {d.reasoning}\n"
                f"  PM风险备注: {d.risk_note}"
            )

        user_message = (
            "## 待审批的交易决策\n"
            + "\n".join(decision_lines)
            + f"\n\n## 当前持仓\n{portfolio_summary}"
            + f"\n可用资金: ¥{available_cash:,.2f}"
            + f"\n今日盈亏: {daily_pnl_pct:+.1%}"
            + "\n\n请用 get_portfolio 和 get_realtime_quote 验证数据，"
            "然后对每个决策给出 verdicts JSON。"
        )

        messages = [
            LLMMessage(role="system", content=_RISK_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_message),
        ]

        try:
            result = await loop.run(
                messages,
                caller="trading_advisor",
                max_tokens=2048,
                temperature=0.2,
            )

            logger.info(
                "Risk LLM review completed: %d turns, $%.4f",
                result.turns,
                result.total_cost_usd,
            )

            return self._parse_verdicts(result.text or "")

        except Exception as exc:
            logger.error(
                "Risk LLM review failed: %s — defaulting to approve",
                exc,
            )
            # Fail-open for LLM errors (hard checks already passed)
            return [
                RiskVerdict(symbol=d.symbol, approved=True, risk_level="medium")
                for d in decisions
            ]

    def _parse_verdicts(self, text: str) -> list[RiskVerdict]:
        """Extract RiskVerdict list from LLM JSON output.

        Args:
            text: Raw LLM response text containing JSON.

        Returns:
            Parsed verdicts, or empty list if parsing fails.
        """
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not json_match:
            json_match = re.search(r'\{"verdicts"\s*:\s*\[.*?\]\s*\}', text, re.DOTALL)

        if not json_match:
            logger.warning("Risk response contained no parseable JSON")
            return []

        try:
            raw = json_match.group(1) if json_match.lastindex else json_match.group(0)
            data = json.loads(raw)
        except (json.JSONDecodeError, IndexError) as exc:
            logger.warning("Failed to parse risk JSON: %s", exc)
            return []

        verdicts: list[RiskVerdict] = []
        for item in data.get("verdicts", []):
            symbol = item.get("symbol", "")
            if not symbol:
                continue

            adj_shares = item.get("adjusted_shares")
            if adj_shares is not None:
                adj_shares = int(adj_shares)

            verdict = RiskVerdict(
                symbol=symbol,
                approved=bool(item.get("approved", True)),
                veto_reason=item.get("veto_reason", ""),
                risk_level=item.get("risk_level", "medium"),
                adjusted_shares=adj_shares,
            )
            verdicts.append(verdict)

        return verdicts

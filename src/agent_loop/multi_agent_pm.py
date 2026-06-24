"""Multi-agent Portfolio Manager — the decision maker.

Receives AnalystProposals, evaluates them against portfolio context
and calibration history, then makes final buy/sell/hold decisions
with position sizing. Has FULL tool access including execute_trade.

Part of the Analyst -> PM -> Risk multi-agent pipeline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.agent_loop.multi_agent_analyst import AnalystProposal
from src.utils.logger import get_logger

logger = get_logger("agent_loop.multi_agent_pm")


@dataclass
class PMDecision:
    """Final trading decision from the Portfolio Manager.

    Attributes:
        action: "buy", "sell", "add", "reduce", or "hold".
        symbol: Stock code (e.g. "600498").
        shares: Number of shares to trade (multiple of 100).
        entry_price: Target entry price for buy/add.
        stop_loss: Hard stop-loss price (mandatory).
        target_price: Profit target price.
        confidence: PM's conviction level (0.0-1.0).
        reasoning: Decision rationale in plain Chinese.
        risk_note: Key risk the PM is accepting.
    """

    action: str  # buy / sell / add / reduce / hold
    symbol: str
    shares: int = 0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_price: float = 0.0
    confidence: float = 0.5
    reasoning: str = ""
    risk_note: str = ""


# The PM gets the full conviction philosophy from heartbeat_agent's
# _SYSTEM_PROMPT, plus calibration self-awareness.
_PM_SYSTEM_PROMPT = (
    "你是投资总监（Portfolio Manager），拥有最终决策权。\n"
    "研究分析师已经完成初步筛选，现在由你做最终判断。\n\n"
    "## 身份\n"
    "- 你是决策者，不是顾问。直接说'买'、'卖'、'持有'\n"
    "- 你对真金白银的结果负责\n"
    "- 分析师的建议只是参考，你可以否决、修改或追加研究\n\n"
    "## 仓位哲学（核心原则）\n"
    "- Druckenmiller: '有巨大信心时，要全力出击——要有勇气做猪'\n"
    "- 赵老哥: '五成仓常规，龙头强势可重仓，越不顺越控制仓位'\n"
    "- 没有'单只最多30%'这种死规则——仓位跟着信心走\n"
    "- 信心90%+且逻辑完美 → 可以全仓一只\n"
    "- 信心70% → 半仓\n"
    "- 信心50% → 轻仓试探或不买\n"
    "- 但是：不对就走，亏损的票不讲道理。止损线一旦设定，触及必须执行\n\n"
    "## 从历史错误中学到的5条经验（必须遵守）\n"
    "1. 你的 hold 信号只有27%准确——说'持有'大概率是错的。"
    "要么买要么卖，别含糊\n"
    "2. 你的高信心（80%+）只有27%准确——越自信越危险。"
    "高信心通常出现在趋势末端，恰好是反转点\n"
    "3. 连续同方向判断3天以上要警惕——你追趋势总是迟到，"
    "等你全面看多时可能已经是顶部\n"
    "4. 概念股/事件驱动的票不要用纯技术面判断——"
    "必须结合消息催化和资金流向\n"
    "5. 趋势明确的票可以信，但震荡票和反转票要靠资金流+板块轮动判断\n\n"
    "## 决策格式\n"
    "对每个分析师提案逐一评判，然后输出 decisions JSON：\n"
    "```json\n"
    '{"decisions": [{"action": "buy", "symbol": "600XXX", '
    '"shares": 200, "entry_price": 0.00, "stop_loss": 0.00, '
    '"target_price": 0.00, "confidence": 0.75, '
    '"reasoning": "...", "risk_note": "..."}]}\n'
    "```\n\n"
    "每个决策必须填写所有字段。不操作也要说明原因。"
)


class PMAgent:
    """Portfolio Manager agent — makes final trading decisions.

    Receives analyst proposals and evaluates them in the context of
    current portfolio, available capital, and calibration history.
    Has full tool access to verify analyst findings and execute trades.

    Args:
        gateway: LLMGateway or LLMRouter instance.
        tool_registry: ToolRegistry with all tools registered.
        max_turns: Maximum LLM round-trips.
        max_cost_usd: Cost budget for a single decision session.
    """

    def __init__(
        self,
        gateway: Any,
        tool_registry: Any,
        max_turns: int = 10,
        max_cost_usd: float = 0.25,
    ) -> None:
        self._gateway = gateway
        self._tool_registry = tool_registry
        self._max_turns = max_turns
        self._max_cost_usd = max_cost_usd

    async def decide(
        self,
        proposals: list[AnalystProposal],
        portfolio_summary: str = "",
        available_cash: float = 0.0,
        calibration_report: str = "",
    ) -> list[PMDecision]:
        """Evaluate analyst proposals and produce trading decisions.

        Args:
            proposals: AnalystProposal list from the research analyst.
            portfolio_summary: Current portfolio text summary.
            available_cash: Available cash for new positions (CNY).
            calibration_report: Historical accuracy context string.

        Returns:
            List of PMDecision dataclasses. May be empty if the PM
            rejects all proposals.
        """
        from src.agent_loop.llm_agent import AgentLoop
        from src.llm.base import LLMMessage

        if not proposals:
            logger.info("PM received no proposals — nothing to decide")
            return []

        # PM gets full tool access
        all_tools = self._tool_registry.get_tool_definitions()

        loop = AgentLoop(
            gateway=self._gateway,
            tool_executor=self._tool_registry.execute,
            tool_definitions=all_tools,
            max_turns=self._max_turns,
            max_cost_usd=self._max_cost_usd,
        )

        user_message = self._build_user_message(
            proposals, portfolio_summary, available_cash, calibration_report
        )

        messages = [
            LLMMessage(role="system", content=_PM_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_message),
        ]

        try:
            result = await loop.run(
                messages,
                caller="final_decision",
                max_tokens=4096,
                temperature=0.3,
            )

            logger.info(
                "PM decision completed: %d turns, %d tools, $%.4f",
                result.turns,
                result.tool_calls_made,
                result.total_cost_usd,
            )

            decisions = self._parse_decisions(result.text or "")
            logger.info(
                "PM produced %d decisions: %s",
                len(decisions),
                ", ".join(f"{d.action} {d.symbol}" for d in decisions),
            )
            return decisions

        except Exception as exc:
            logger.error("PM decision failed: %s", exc, exc_info=True)
            return []

    def _build_user_message(
        self,
        proposals: list[AnalystProposal],
        portfolio_summary: str,
        available_cash: float,
        calibration_report: str,
    ) -> str:
        """Build the user prompt with all context for PM evaluation.

        Args:
            proposals: Analyst proposals to evaluate.
            portfolio_summary: Current portfolio text.
            available_cash: Cash available (CNY).
            calibration_report: Historical accuracy context.

        Returns:
            Formatted user message string.
        """
        parts: list[str] = []

        # Proposals section
        parts.append("## 分析师提案（需要你逐一评判）")
        for i, p in enumerate(proposals, 1):
            evidence_text = ""
            if p.evidence:
                evidence_text = "  证据: " + "; ".join(
                    f"{name}" for name, _ in p.evidence[:5]
                )
            parts.append(
                f"\n### 提案 {i}: {p.action.upper()} {p.name}({p.symbol})\n"
                f"- 信心: {p.confidence:.0%}\n"
                f"- 理由: {p.reasoning}\n"
                f"- 止损: ¥{p.stop_loss:.2f} | 目标: ¥{p.target_price:.2f}\n"
                f"{evidence_text}"
            )

        # Portfolio context
        if portfolio_summary:
            parts.append(f"\n## 当前持仓\n{portfolio_summary}")
        parts.append(f"\n可用资金: ¥{available_cash:,.2f}")

        # Calibration context
        if calibration_report:
            parts.append(f"\n## 你的历史成绩单（32%基准线）\n{calibration_report}")

        # Instructions
        parts.append(
            "\n## 你的任务\n"
            "1. 对每个提案：用工具验证关键数据（get_realtime_quote等）\n"
            "2. 结合持仓、资金、历史准确率做最终判断\n"
            "3. 确定仓位大小（信心→仓位，参考仓位哲学）\n"
            "4. 输出 decisions JSON（每个提案都要有结论）"
        )

        return "\n".join(parts)

    def _parse_decisions(self, text: str) -> list[PMDecision]:
        """Extract PMDecision list from LLM JSON output.

        Args:
            text: Raw LLM response text containing JSON.

        Returns:
            Parsed decisions, or empty list if parsing fails.
        """
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not json_match:
            json_match = re.search(r'\{"decisions"\s*:\s*\[.*?\]\s*\}', text, re.DOTALL)

        if not json_match:
            logger.warning("PM response contained no parseable JSON")
            return []

        try:
            raw = json_match.group(1) if json_match.lastindex else json_match.group(0)
            data = json.loads(raw)
        except (json.JSONDecodeError, IndexError) as exc:
            logger.warning("Failed to parse PM JSON: %s", exc)
            return []

        decisions: list[PMDecision] = []
        for item in data.get("decisions", []):
            symbol = item.get("symbol", "")
            if not symbol:
                continue

            decision = PMDecision(
                action=item.get("action", "hold"),
                symbol=symbol,
                shares=int(item.get("shares", 0)),
                entry_price=float(item.get("entry_price", 0.0)),
                stop_loss=float(item.get("stop_loss", 0.0)),
                target_price=float(item.get("target_price", 0.0)),
                confidence=float(item.get("confidence", 0.5)),
                reasoning=item.get("reasoning", ""),
                risk_note=item.get("risk_note", ""),
            )
            decisions.append(decision)

        return decisions

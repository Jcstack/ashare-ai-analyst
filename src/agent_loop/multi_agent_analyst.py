"""Multi-agent Research Analyst — discovers opportunities with evidence.

The analyst is a READ-ONLY agent: it can scan markets, analyze data,
and research stocks, but it cannot execute trades. Its job is to
produce AnalystProposals backed by tool evidence for the Portfolio
Manager to evaluate.

Part of the Analyst -> PM -> Risk multi-agent pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("agent_loop.multi_agent_analyst")

# Read-only tools — no execute_trade, no portfolio mutations
_ANALYST_TOOL_ALLOWLIST: set[str] = {
    "get_market_pulse",
    "get_global_markets",
    "get_sector_leaders",
    "get_concept_heat",
    "get_limit_up_pool",
    "get_opportunity_candidates",
    "get_trending_news",
    "search_intel",
    "detect_sentiment_phase",
    "deep_analyze",
    "get_prediction_summary",
    "get_realtime_quote",
    "get_intraday_fund_flow_timeline",
    "get_trend_candidates",
}

_ANALYST_SYSTEM_PROMPT = (
    "你是研究分析师，不是决策者。你的工作是发现机会并提供证据，"
    "最终决策由投资总监做。\n\n"
    "## 你的职责\n"
    "1. 扫描全市场，找到值得关注的标的\n"
    "2. 对每个候选做多维度验证（板块+资金+消息+技术面）\n"
    "3. 给出明确的结论：买入/卖出/观察，附带证据链\n"
    "4. 你不做最终决策——你提供研究报告，由PM决定\n\n"
    "## 输出要求\n"
    "对每个发现的机会，必须包含：\n"
    "- 代码和名称\n"
    "- 推荐动作（buy/sell/watch）\n"
    "- 信心分数（0.0-1.0）\n"
    "- 详细理由（引用工具返回的具体数据）\n"
    "- 止损价和目标价（buy/sell必填）\n"
    "- 风险因素\n\n"
    "## 原则\n"
    "- 不要推荐没有证据支撑的标的\n"
    "- 板块+资金+消息三维共振才是强信号\n"
    "- 宁可漏掉机会，不推荐垃圾——PM信任你的筛选质量\n"
    "- 用大白话，不要堆砌技术指标术语\n\n"
    "在回复末尾输出 JSON：\n"
    '```json\n{"proposals": [{"symbol": "600XXX", "name": "XX", '
    '"action": "buy", "confidence": 0.75, "reasoning": "...", '
    '"stop_loss": 0.00, "target_price": 0.00, '
    '"evidence_summary": "..."}]}\n```'
)


@dataclass
class AnalystProposal:
    """A research proposal from the analyst agent.

    Attributes:
        symbol: Stock code (e.g. "600498").
        name: Stock name (e.g. "烽火通信").
        action: Recommended action — "buy", "sell", or "watch".
        confidence: Analyst's confidence score (0.0-1.0).
        reasoning: Human-readable explanation with data references.
        evidence: List of (tool_name, result_summary) from tool calls.
        stop_loss: Suggested stop-loss price (0.0 if watch).
        target_price: Suggested target price (0.0 if watch).
    """

    symbol: str
    name: str
    action: str  # buy / sell / watch
    confidence: float
    reasoning: str
    evidence: list[tuple[str, str]] = field(default_factory=list)
    stop_loss: float = 0.0
    target_price: float = 0.0


class AnalystAgent:
    """Read-only research analyst that discovers opportunities.

    Uses a filtered tool set (data + analysis only, no trading) to
    scan the market and produce AnalystProposals backed by evidence.

    Args:
        gateway: LLMGateway or LLMRouter instance.
        tool_registry: ToolRegistry with all tools registered.
        max_turns: Maximum LLM round-trips for research.
        max_cost_usd: Cost budget for a single research session.
    """

    def __init__(
        self,
        gateway: Any,
        tool_registry: Any,
        max_turns: int = 15,
        max_cost_usd: float = 0.30,
    ) -> None:
        self._gateway = gateway
        self._tool_registry = tool_registry
        self._max_turns = max_turns
        self._max_cost_usd = max_cost_usd

    async def research(
        self,
        task: str = "",
        portfolio_context: str = "",
    ) -> list[AnalystProposal]:
        """Run a research session and return proposals.

        Args:
            task: Optional specific research task. If empty, defaults
                to a full market scan.
            portfolio_context: Current portfolio summary for context
                (analyst should avoid recommending what we already hold).

        Returns:
            List of AnalystProposal dataclasses, possibly empty if
            the analyst found nothing worth proposing.
        """
        from src.agent_loop.llm_agent import AgentLoop
        from src.llm.base import LLMMessage

        # Filter tools to read-only subset
        all_tools = self._tool_registry.get_tool_definitions()
        analyst_tools = [t for t in all_tools if t["name"] in _ANALYST_TOOL_ALLOWLIST]

        if not analyst_tools:
            logger.warning("No analyst tools available — skipping research")
            return []

        loop = AgentLoop(
            gateway=self._gateway,
            tool_executor=self._tool_registry.execute,
            tool_definitions=analyst_tools,
            max_turns=self._max_turns,
            max_cost_usd=self._max_cost_usd,
        )

        user_message = task or (
            "执行全市场扫描：\n"
            "1. get_market_pulse — 大盘环境\n"
            "2. get_concept_heat + get_sector_leaders — 今日最强板块\n"
            "3. get_opportunity_candidates — 高分候选\n"
            "4. get_limit_up_pool — 涨停板块聚集\n"
            "5. get_trending_news — 消息催化\n"
            "6. 从以上选出最值得研究的1-3只\n"
            "7. 对候选做 deep_analyze + get_intraday_fund_flow_timeline\n"
            "8. 输出 proposals JSON"
        )

        if portfolio_context:
            user_message += f"\n\n当前持仓（避免重复推荐）:\n{portfolio_context}"

        messages = [
            LLMMessage(role="system", content=_ANALYST_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_message),
        ]

        try:
            result = await loop.run(
                messages,
                caller="trading_advisor",
                max_tokens=4096,
                temperature=0.3,
            )

            logger.info(
                "Analyst research completed: %d turns, %d tools, $%.4f",
                result.turns,
                result.tool_calls_made,
                result.total_cost_usd,
            )

            proposals = self._parse_proposals(result.text or "", result.tool_history)
            logger.info("Analyst produced %d proposals", len(proposals))
            return proposals

        except Exception as exc:
            logger.error("Analyst research failed: %s", exc, exc_info=True)
            return []

    def _parse_proposals(
        self,
        text: str,
        tool_history: list[tuple[str, dict, str]],
    ) -> list[AnalystProposal]:
        """Extract AnalystProposal list from LLM JSON output.

        Args:
            text: Raw LLM response text containing JSON.
            tool_history: Tool call history for evidence extraction.

        Returns:
            Parsed proposals, or empty list if parsing fails.
        """
        import json
        import re

        # Build evidence index from tool history
        evidence_map: dict[str, list[tuple[str, str]]] = {}
        for tool_name, tool_input, tool_result in tool_history:
            symbol = (
                tool_input.get("symbol", "") if isinstance(tool_input, dict) else ""
            )
            summary = str(tool_result)[:200]
            if symbol:
                evidence_map.setdefault(symbol, []).append((tool_name, summary))

        # Extract JSON from response
        proposals: list[AnalystProposal] = []
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not json_match:
            # Try bare JSON
            json_match = re.search(r'\{"proposals"\s*:\s*\[.*?\]\s*\}', text, re.DOTALL)

        if not json_match:
            logger.warning("Analyst response contained no parseable JSON")
            return []

        try:
            raw = json_match.group(1) if json_match.lastindex else json_match.group(0)
            data = json.loads(raw)
        except (json.JSONDecodeError, IndexError) as exc:
            logger.warning("Failed to parse analyst JSON: %s", exc)
            return []

        for item in data.get("proposals", []):
            symbol = item.get("symbol", "")
            if not symbol:
                continue

            proposal = AnalystProposal(
                symbol=symbol,
                name=item.get("name", ""),
                action=item.get("action", "watch"),
                confidence=float(item.get("confidence", 0.5)),
                reasoning=item.get("reasoning", ""),
                evidence=evidence_map.get(symbol, []),
                stop_loss=float(item.get("stop_loss", 0.0)),
                target_price=float(item.get("target_price", 0.0)),
            )
            proposals.append(proposal)

        return proposals

"""Report agent — synthesis and scenario generation specialist.

Synthesizes multi-agent results into structured Chinese reports
with three-scenario analysis (bullish/base/bearish).

Part of v18.0 Agent Spec Compliance — Phase 3.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.agents.base import AgentCapability, AgentMessage, BaseAgent
from src.llm.base import LLMMessage, LLMToolResponse
from src.utils.logger import get_logger

logger = get_logger("agents.report")


class ReportAgent(BaseAgent):
    """Report synthesis specialist — LLM-backed.

    Receives pre-computed data from all prior pipeline steps
    and synthesizes a comprehensive report with:
    - Executive summary
    - Three scenarios (bullish/base/bearish) with probabilities
    - Risk level per scenario
    - Full report markdown

    Tools: None (receives pre-computed data via context).
    """

    def __init__(
        self,
        capability: AgentCapability,
        tool_registry: Any,
        llm_router: Any,
        system_role: str = "",
    ) -> None:
        super().__init__(capability)
        self._tools = tool_registry
        self._llm = llm_router
        self._system_role = system_role or (
            "You are a senior investment report writing specialist. "
            "Synthesize multi-dimensional analysis results (technicals, sentiment, "
            "regime, risk control, backtesting) into a comprehensive report. "
            "Must include three scenario analyses (bullish/neutral/bearish), "
            "each labeled with probability and risk level. "
            "Be concise, state conclusions clearly, and ensure risk warnings are thorough. "
            "Write all output text in Chinese."
        )

    async def _execute_impl(self, message: AgentMessage) -> AgentMessage:
        """Synthesize multi-agent results into a structured report."""
        start = time.perf_counter()

        system_prompt = self._build_prompt(message)

        # Prepare context summary for the LLM
        context_summary = self._summarize_context(message.context)

        llm_messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="user",
                content=f"{message.task}\n\n## Analysis Data Summary\n{context_summary}",
            ),
        ]

        total_tokens = 0
        final_text = ""

        try:
            response: LLMToolResponse = await asyncio.to_thread(
                self._llm.complete_with_tools,
                messages=llm_messages,
                tools=[],  # Report agent uses no tools
                caller=f"agent.{self.name}",
                max_tokens=self._capability.max_tokens,
                temperature=self._capability.temperature,
                analysis_type="agent_report",
            )
            total_tokens = response.input_tokens + response.output_tokens
            final_text = response.text or ""
        except Exception as exc:
            logger.error("ReportAgent LLM call failed: %s", exc)
            final_text = self._build_fallback_report(message.context)

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "ReportAgent: %d tokens, %.0fms",
            total_tokens,
            elapsed,
        )

        return AgentMessage(
            from_agent=self.name,
            to_agent=message.from_agent,
            task=message.task,
            context=message.context,
            budget_remaining=message.budget_remaining - total_tokens,
            result=final_text,
            tool_calls_made=0,
            tokens_used=total_tokens,
            delegation_chain=[*message.delegation_chain, self.name],
        )

    def _build_prompt(self, message: AgentMessage) -> str:
        """Build report-specific system prompt."""
        parts = [
            self._system_role,
            "",
            "## Output Format (JSON)",
            "{",
            '  "report_markdown": "完整的 Markdown 报告文本",',
            '  "executive_summary": "一句话核心结论",',
            '  "scenarios": [',
            '    {"name": "乐观", "probability": 0.3, "risk_level": "low", "description": "..."},',
            '    {"name": "中性", "probability": 0.5, "risk_level": "medium", "description": "..."},',
            '    {"name": "悲观", "probability": 0.2, "risk_level": "high", "description": "..."}',
            "  ],",
            '  "confidence_score": 0.7,',
            '  "key_assumptions": ["..."],',
            '  "failure_modes": ["..."],',
            '  "data_gaps": ["..."]',
            "}",
            "",
            "## Rules",
            "- The three scenario probabilities must sum to 1.0",
            "- Each scenario must include specific trigger conditions and impact analysis",
            "- The report must be written in Chinese",
            "- Do not give specific buy/sell instructions — only present analysis and scenarios",
        ]
        symbol = message.context.get("symbol")
        if symbol:
            parts.append(f"\n## Analysis Target: {symbol}")
        return "\n".join(parts)

    @staticmethod
    def _summarize_context(ctx: dict[str, Any]) -> str:
        """Create a text summary of pipeline context for the LLM."""
        import json

        parts: list[str] = []

        for key in [
            "signal",
            "confidence_score",
            "data_quality_score",
            "sentiment_score",
            "sentiment_signal",
            "current_regime",
            "risk_level",
            "risk_assessment",
            "overfit_warning",
            "walk_forward_report",
            "position_suggestion",
            "diversification_score",
            "data_gaps",
        ]:
            if key in ctx:
                val = ctx[key]
                if isinstance(val, (dict, list)):
                    val = json.dumps(val, ensure_ascii=False)
                parts.append(f"- **{key}**: {val}")

        return "\n".join(parts) if parts else "(No analysis data available)"

    @staticmethod
    def _build_fallback_report(ctx: dict[str, Any]) -> str:
        """Build a minimal report when LLM fails."""
        import json

        return json.dumps(
            {
                "report_markdown": "# 分析报告\n\n由于系统限制，无法生成完整报告。请参考各维度的独立分析结果。",
                "executive_summary": "报告生成失败，建议查看各维度独立分析。",
                "scenarios": [
                    {
                        "name": "中性",
                        "probability": 1.0,
                        "risk_level": "medium",
                        "description": "数据不足以进行情景分析",
                    },
                ],
                "confidence_score": 0.2,
                "key_assumptions": [],
                "failure_modes": ["LLM 调用失败"],
                "data_gaps": ["报告合成失败"],
            },
            ensure_ascii=False,
        )

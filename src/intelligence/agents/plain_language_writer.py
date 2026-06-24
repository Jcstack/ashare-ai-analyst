"""Plain Language Writer — converts technical analysis to human-readable Chinese.

Core principle: Users don't know MACD/RSI. Every message must include:
结论 + 原因 + 风险 + 下一步
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.plain_language_writer")

# Message templates for different event types
TEMPLATES: dict[str, dict[str, str]] = {
    "geopolitical_escalation": {
        "title_prefix": "🌍 国际局势",
        "priority": "high",
    },
    "ceasefire": {
        "title_prefix": "🕊️ 和平信号",
        "priority": "normal",
    },
    "tech_revolution": {
        "title_prefix": "🚀 科技突破",
        "priority": "high",
    },
    "policy_change": {
        "title_prefix": "📋 政策变化",
        "priority": "high",
    },
    "commodity_shock": {
        "title_prefix": "⛽ 大宗商品",
        "priority": "normal",
    },
    "monetary_tightening": {
        "title_prefix": "🏦 货币政策",
        "priority": "normal",
    },
    "trade_conflict": {
        "title_prefix": "⚔️ 贸易摩擦",
        "priority": "high",
    },
    "default": {
        "title_prefix": "📰 全球动态",
        "priority": "normal",
    },
}


class PlainLanguageWriter:
    """Messenger team: writes human-readable messages from intelligence analysis.

    Converts structured intelligence outputs (event understanding, scenarios,
    signals, risk assessments) into plain Chinese messages that retail
    investors can understand without financial background.
    """

    def __init__(self, llm_router: Any) -> None:
        self._llm_router = llm_router

    async def write_message(
        self,
        event: dict[str, Any],
        scenarios: dict[str, Any] | None = None,
        signals: list[dict[str, Any]] | None = None,
        risk: dict[str, Any] | None = None,
        analogies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Generate a plain-language message from intelligence analysis.

        Args:
            event: EventUnderstanding dict (event_type, certainty, etc.).
            scenarios: Scenario planner output with scenarios list.
            signals: Trade signal dicts from causal chain agent.
            risk: Risk assessment dict with risk_level and alert_message.
            analogies: Historical analogy dicts.

        Returns:
            Message dict ready for AlertPriorityRouter.
        """
        template = TEMPLATES.get(event.get("event_type", ""), TEMPLATES["default"])

        prompt = self._build_prompt(event, scenarios, signals, risk, analogies)

        try:
            response = self._llm_router.generate(
                model="gemini",  # Cost-effective for writing
                system=_SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=800,
            )
            parsed = json.loads(response) if isinstance(response, str) else response
        except Exception as exc:
            logger.warning("Plain language generation failed: %s", exc)
            parsed = self._fallback_message(event)

        # Determine priority
        priority = template["priority"]
        if risk and risk.get("risk_level") in ("high", "critical"):
            priority = "critical"
        elif (
            event.get("certainty", 0) > 0.8 and event.get("a_share_relevance", 0) > 0.7
        ):
            priority = "high"

        return {
            "type": "global_intelligence",
            "title": f"{template['title_prefix']} {parsed.get('title', event.get('one_line_summary', ''))}",
            "content": parsed.get("content", ""),
            "priority": priority,
            "stock_recommendations": self._format_stock_recs(signals)
            if signals
            else None,
            "metadata": {
                "event_type": event.get("event_type"),
                "certainty": event.get("certainty"),
                "reversal_risk": event.get("reversal_risk"),
                "scenarios": scenarios.get("scenarios", []) if scenarios else [],
                "risk_level": risk.get("risk_level") if risk else None,
            },
        }

    def _build_prompt(
        self,
        event: dict[str, Any],
        scenarios: dict[str, Any] | None,
        signals: list[dict[str, Any]] | None,
        risk: dict[str, Any] | None,
        analogies: list[dict[str, Any]] | None,
    ) -> str:
        """Build the LLM prompt from structured intelligence data."""
        parts = [f"事件：{event.get('one_line_summary', '')}"]
        parts.append(f"确定性：{event.get('certainty', 'N/A')}")
        parts.append(f"反转风险：{event.get('reversal_risk', 'N/A')}")

        if scenarios:
            parts.append("\n场景分析：")
            for s in scenarios.get("scenarios", []):
                parts.append(
                    f"- {s.get('name', '')}: {s.get('probability', 0):.0%}"
                    f" — {s.get('description', '')}"
                )
            parts.append(f"建议：{scenarios.get('recommended_action', '')}")

        if signals:
            parts.append("\n相关股票：")
            for sig in signals[:5]:
                direction = "看好" if sig.get("direction") == "long" else "谨慎"
                parts.append(
                    f"- {sig.get('stock_code', '')}: {direction}"
                    f" ({sig.get('causal_path', '')})"
                )

        if risk and risk.get("risk_level") in ("medium", "high", "critical"):
            parts.append(f"\n风险警告：{risk.get('alert_message', '')}")
            parts.append(f"对冲建议：{risk.get('recommended_hedge', '')}")

        if analogies:
            parts.append("\n历史参考：")
            for a in analogies[:2]:
                parts.append(
                    f"- {a.get('historical_event', '')}: {a.get('predicted_pattern', '')}"
                )

        parts.append(
            "\n请用普通人能看懂的语言写一条消息，输出 JSON：\n"
            "{\n"
            '  "title": "10字以内的标题",\n'
            '  "content": "消息正文，包含：\\n\\n**发生了什么**：...'
            "\\n\\n**对你的影响**：...\\n\\n**风险提醒**：..."
            '\\n\\n**建议操作**：..."\n'
            "}"
        )
        return "\n".join(parts)

    @staticmethod
    def _fallback_message(event: dict[str, Any]) -> dict[str, str]:
        """Generate a fallback message when LLM call fails."""
        return {
            "title": event.get("one_line_summary", "全球事件更新")[:20],
            "content": (
                f"**发生了什么**：{event.get('one_line_summary', '未知事件')}\n\n"
                f"**相关板块**：{', '.join(event.get('key_sectors', ['待分析']))}\n\n"
                f"**风险提醒**：反转风险{event.get('reversal_risk', '未知')}，请谨慎操作\n\n"
                f"**建议操作**：保持关注，等待进一步确认"
            ),
        }

    @staticmethod
    def _format_stock_recs(
        signals: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Format trade signals into stock recommendation dicts."""
        recs = []
        for sig in signals[:5]:
            if sig.get("strength", 0) >= 0.5:
                recs.append(
                    {
                        "stock_code": sig.get("stock_code", ""),
                        "direction": sig.get("direction", ""),
                        "reason": sig.get("causal_path", ""),
                        "confidence": sig.get("confidence", 0.5),
                        "time_horizon": sig.get("time_horizon", ""),
                    }
                )
        return recs if recs else None


_SYSTEM_PROMPT = """\
你是面向普通散户（没有金融背景）的消息撰写者。

## 写作规则
1. 用户不懂金融术语——绝不使用 MACD、RSI、PE、均线、量比等词汇
2. 每条消息必须包含四个部分：结论 + 原因 + 风险 + 下一步
3. 像朋友在微信上分享重要消息一样写——简洁、直接、有温度
4. 不要堆砌数据——用日常语言解释影响（如"大资金在买入"而非"主力净流入3.2亿元"）
5. 推荐股票时必须同时说明理由和风险，不能只报好消息
6. 不确定的事情用"可能""或许"，不要把推测写成事实

## 消息质量标准
- 好的消息：像一个懂投资的朋友发的微信语音转文字
- 差的消息：像证券公司的研究报告摘要
- 标题要抓人但不标题党，10字以内

输出 JSON。所有文本中文。"""


@lru_cache(maxsize=1)
def get_plain_language_writer() -> PlainLanguageWriter:
    """Singleton factory for PlainLanguageWriter."""
    from src.web.dependencies import get_llm_router

    return PlainLanguageWriter(llm_router=get_llm_router())

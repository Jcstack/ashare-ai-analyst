"""Event Digest Agent — generates periodic intelligence digests.

Creates morning pre-market, midday, and evening post-market digests
summarizing all intelligence activity, key events, and market outlook.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.event_digest")


class EventDigestAgent:
    """Messenger team: generates periodic intelligence digests.

    Produces morning (pre-market), midday, and evening (post-market)
    summaries of global intelligence events, writing plain Chinese
    for retail investors.
    """

    DIGEST_TYPES: dict[str, dict[str, str]] = {
        "morning": {
            "title": "📋 早盘情报简报",
            "description": "盘前全球事件梳理 + 今日关注",
            "priority": "high",
        },
        "midday": {
            "title": "📊 午间情报更新",
            "description": "上午关键变化 + 下午展望",
            "priority": "normal",
        },
        "evening": {
            "title": "🌙 收盘情报总结",
            "description": "今日复盘 + 夜间关注",
            "priority": "normal",
        },
    }

    def __init__(
        self,
        event_bus: Any,
        llm_router: Any,
        message_store: Any,
    ) -> None:
        self._event_bus = event_bus
        self._llm_router = llm_router
        self._message_store = message_store

    async def generate_digest(
        self,
        digest_type: str,
        events: list[dict[str, Any]],
        signals: list[dict[str, Any]] | None = None,
        risk: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a digest message for the given period.

        Args:
            digest_type: One of "morning", "midday", "evening".
            events: List of EventUnderstanding dicts from the period.
            signals: Optional trade signal dicts.
            risk: Optional composite risk assessment.

        Returns:
            Dict with generated flag, message_id, and event_count.
        """
        config = self.DIGEST_TYPES.get(digest_type, self.DIGEST_TYPES["morning"])

        if not events:
            logger.info("No events for %s digest, skipping", digest_type)
            return {"generated": False, "reason": "no_events"}

        prompt = self._build_digest_prompt(digest_type, events, signals, risk)

        try:
            response = self._llm_router.generate(
                model="deepseek-chat",
                system=_DIGEST_SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=1000,
            )
            content = (
                response
                if isinstance(response, str)
                else json.dumps(response, ensure_ascii=False)
            )
        except Exception as exc:
            logger.warning("Digest generation failed: %s", exc)
            content = self._fallback_digest(digest_type, events)

        # Store digest as message
        msg_id = self._message_store.create_message(
            msg_type="intelligence_digest",
            title=config["title"],
            summary=content[:200],
            content=content,
            priority=config["priority"],
        )

        # Publish to event bus for Discord routing
        await self._event_bus.publish(
            "messenger:push",
            {
                "type": "intelligence_digest",
                "title": config["title"],
                "content": content,
                "priority": config["priority"],
                "digest_type": digest_type,
                "message_id": msg_id,
            },
        )

        logger.info("Generated %s digest with %d events", digest_type, len(events))
        return {"generated": True, "message_id": msg_id, "event_count": len(events)}

    def _build_digest_prompt(
        self,
        digest_type: str,
        events: list[dict[str, Any]],
        signals: list[dict[str, Any]] | None,
        risk: dict[str, Any] | None,
    ) -> str:
        """Build the LLM prompt for digest generation."""
        time_label = {
            "morning": "盘前",
            "midday": "午间",
            "evening": "收盘",
        }.get(digest_type, "")

        parts = [f"请生成{time_label}情报简报。"]
        parts.append(f"\n当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

        parts.append(f"\n共 {len(events)} 个事件：")
        for i, e in enumerate(events[:15], 1):
            relevance = e.get("a_share_relevance", 0)
            marker = "⭐" if relevance > 0.7 else "•"
            parts.append(
                f"{marker} {i}. {e.get('one_line_summary', 'N/A')} "
                f"(确定性:{e.get('certainty', 'N/A')}, "
                f"A股相关性:{relevance:.1f})"
            )

        if signals:
            parts.append(f"\n{len(signals)} 个潜在机会：")
            for sig in signals[:5]:
                d = "看好" if sig.get("direction") == "long" else "谨慎"
                parts.append(
                    f"- {sig.get('stock_code', '')}: {d} ({sig.get('causal_path', '')})"
                )

        if risk and risk.get("risk_level") in ("medium", "high", "critical"):
            parts.append(
                f"\n⚠️ 复合风险等级：{risk.get('risk_level', '')}"
                f" ({risk.get('risk_score', 0):.0%})"
            )
            parts.append(f"原因：{risk.get('alert_message', '')}")

        parts.append(f"\n请输出完整的{time_label}简报文字，格式清晰易读。")
        return "\n".join(parts)

    @staticmethod
    def _fallback_digest(digest_type: str, events: list[dict[str, Any]]) -> str:
        """Generate a fallback digest when LLM call fails."""
        time_label = {
            "morning": "盘前",
            "midday": "午间",
            "evening": "收盘",
        }.get(digest_type, "")

        lines = [
            f"**{time_label}情报简报** ({datetime.now().strftime('%m/%d %H:%M')})\n"
        ]
        for i, e in enumerate(events[:10], 1):
            lines.append(f"{i}. {e.get('one_line_summary', 'N/A')}")
        lines.append(f"\n共追踪 {len(events)} 个事件，请关注高确定性事件的后续发展。")
        return "\n".join(lines)


_DIGEST_SYSTEM_PROMPT = """\
You are an investment intelligence briefing writer for retail investors with no financial background.

Requirements:
1. Write in concise Chinese
2. Focus on key points, do not try to cover everything
3. Summarize each event in one sentence + its impact
4. End with today's/tomorrow's watchlist

All output must be in Chinese."""


@lru_cache(maxsize=1)
def get_event_digest_agent() -> EventDigestAgent:
    """Singleton factory for EventDigestAgent."""
    from src.intelligence.event_bus import EventBus
    from src.web.dependencies import get_llm_router, get_message_store

    return EventDigestAgent(
        event_bus=EventBus(),
        llm_router=get_llm_router(),
        message_store=get_message_store(),
    )

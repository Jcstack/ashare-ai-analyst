"""Weekly self-review task — the agent audits its own decisions.

Runs Saturday 10:00 CST. Pulls all decisions + outcomes from the past week,
asks the LLM to identify patterns (not individual errors), and persists
actionable lessons to Redis for injection into future heartbeat context.

This closes the feedback loop: decisions → outcomes → pattern recognition
→ behavior adjustment → better decisions.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from openclaw.celery_app import app

logger = logging.getLogger(__name__)

_REVIEW_PROMPT = """你是一个交易复盘专家。以下是过去7天的所有交易决策及其实际结果。

{decisions_text}

请分析并回答：

1. **系统性错误**（不是个案，是模式）：你在哪类决策上反复犯错？
2. **信号可靠性**：哪些信号源表现好，哪些在衰减？
3. **仓位管理**：仓位大小是否合理？有没有该重仓的时候怯了？
4. **情绪判断**：对市场情绪的判断准确率如何？

输出格式：
- 3-5条可执行的行为调整建议（不要泛泛而谈）
- 每条建议格式：[领域] 具体行为变化（原因：具体数据支撑）
"""


@app.task(
    name="openclaw.tasks.weekly_self_review.task_weekly_self_review",
    soft_time_limit=180,
    time_limit=240,
)
def task_weekly_self_review() -> dict[str, Any]:
    """Weekly self-review: LLM audits its own past decisions.

    Returns:
        Summary with lessons extracted.
    """
    result: dict[str, Any] = {
        "decisions_reviewed": 0,
        "lessons_extracted": 0,
        "review_text": "",
    }

    try:
        from src.web.dependencies import get_decision_log

        decision_log = get_decision_log()
        completed = decision_log.get_completed(lookback_days=7)
        result["decisions_reviewed"] = len(completed)

        if len(completed) < 3:
            result["review_text"] = "决策不足3条，跳过周度复盘"
            logger.info("Weekly review: only %d decisions, skipping", len(completed))
            return result

        # Format decisions for LLM
        lines = []
        for d in completed:
            t1 = d.get("t1_return_pct")
            correct = d.get("direction_correct")
            lines.append(
                f"- {d.get('action', '?')} {d.get('symbol', '?')} "
                f"conf={d.get('confidence', 0):.0%} "
                f"T+1={f'{t1:+.1f}%' if t1 is not None else '?'} "
                f"{'✓' if correct else '✗' if correct is False else '?'}"
            )

        decisions_text = "\n".join(lines)
        prompt = _REVIEW_PROMPT.format(decisions_text=decisions_text)

        # Call LLM (DeepSeek = cheapest for Chinese text)
        from src.llm.router import LLMRouter
        from src.llm.base import LLMMessage

        router = LLMRouter()
        response = router.complete(
            messages=[LLMMessage(role="user", content=prompt)],
            model="deepseek-chat",
            max_tokens=1000,
        )

        review_text = response.text or ""
        result["review_text"] = review_text

        # Extract lessons and persist to Redis
        lessons = _extract_lessons(review_text)
        result["lessons_extracted"] = len(lessons)

        if lessons:
            _persist_lessons(lessons)

        # Save full review to disk
        now = datetime.now(UTC)
        review_path = f"data/weekly_reviews/{now.strftime('%Y%m%d')}.md"
        try:
            from pathlib import Path

            Path(review_path).parent.mkdir(parents=True, exist_ok=True)
            Path(review_path).write_text(
                f"# 周度自我复盘 {now.strftime('%Y-%m-%d')}\n\n"
                f"决策数: {len(completed)}\n\n"
                f"## LLM分析\n\n{review_text}\n",
                encoding="utf-8",
            )
        except Exception:
            pass

        logger.info(
            "Weekly review complete: %d decisions, %d lessons",
            len(completed),
            len(lessons),
        )

    except Exception as exc:
        logger.error("Weekly self-review failed: %s", exc, exc_info=True)
        result["error"] = str(exc)

    return result


def _extract_lessons(review_text: str) -> list[str]:
    """Extract actionable lessons from LLM review text."""
    lessons = []
    for line in review_text.split("\n"):
        line = line.strip()
        if line.startswith(("-", "•", "*")) and len(line) > 10:
            # Remove bullet marker
            lesson = line.lstrip("-•* ").strip()
            if lesson and "[" in lesson:
                lessons.append(lesson)
    return lessons[:5]  # Max 5 lessons


def _persist_lessons(lessons: list[str]) -> None:
    """Persist weekly lessons to Redis for heartbeat context injection."""
    try:
        from src.web.dependencies import get_redis

        r = get_redis()
        if r:
            r.set(
                "agent:weekly_lessons",
                json.dumps(lessons, ensure_ascii=False),
                ex=7 * 86400,  # 7-day TTL
            )
            logger.info("Persisted %d weekly lessons to Redis", len(lessons))
    except Exception as exc:
        logger.warning("Failed to persist weekly lessons: %s", exc)

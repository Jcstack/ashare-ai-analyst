"""Redis-backed session memory for cross-session context.

Stores compressed transcripts of each InvestorAgent session so that
later sessions (e.g., late_session) can see what happened earlier
(e.g., pre_market decisions, morning_check findings).

Storage: Redis list per trading day, LPUSH + LTRIM for bounded history.
TTL: 3 days (auto-cleanup).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
_CST = ZoneInfo("Asia/Shanghai")

_REDIS_KEY_PREFIX = "investor_agent:sessions:"
_MAX_SESSIONS = 12  # Full trading day + richer debate records
_TTL_SECONDS = 86400 * 3  # 3 days


class SessionMemory:
    """Stores and retrieves session transcripts from Redis."""

    def __init__(self, redis_client: Any = None) -> None:
        self._redis = redis_client
        if not self._redis:
            self._redis = self._connect()

    @staticmethod
    def _connect() -> Any:
        """Connect to Redis, return None on failure."""
        try:
            import redis

            return redis.Redis(host="redis", port=6379, db=0, decode_responses=True)
        except Exception:
            return None

    def save_transcript(
        self,
        session_type: str,
        summary: dict[str, Any],
        date: str | None = None,
    ) -> None:
        """Save a session summary to Redis.

        Args:
            session_type: e.g. "pre_market", "late_session"
            summary: Dict with keys like decisions, key_findings, turns, cost
            date: Trading date string (default: today CST)
        """
        if not self._redis:
            return

        if not date:
            date = datetime.now(_CST).strftime("%Y-%m-%d")

        key = f"{_REDIS_KEY_PREFIX}{date}"
        record = {
            "session_type": session_type,
            "time": datetime.now(_CST).strftime("%H:%M"),
            **summary,
        }

        try:
            self._redis.lpush(key, json.dumps(record, ensure_ascii=False))
            self._redis.ltrim(key, 0, _MAX_SESSIONS - 1)
            self._redis.expire(key, _TTL_SECONDS)
        except Exception as exc:
            logger.warning("SessionMemory save failed: %s", exc)

    def load_context(self, date: str | None = None) -> list[dict[str, Any]]:
        """Load previous session summaries for a trading day.

        Returns list of session dicts, most recent first.
        """
        if not self._redis:
            return []

        if not date:
            date = datetime.now(_CST).strftime("%Y-%m-%d")

        key = f"{_REDIS_KEY_PREFIX}{date}"
        try:
            raw = self._redis.lrange(key, 0, -1)
            return [json.loads(r) for r in raw if r]
        except Exception as exc:
            logger.warning("SessionMemory load failed: %s", exc)
            return []

    @staticmethod
    def format_for_prompt(sessions: list[dict[str, Any]]) -> str:
        """Format session history as a concise context block for the LLM."""
        if not sessions:
            return ""

        lines: list[str] = []
        # Show in chronological order (list is most-recent-first)
        for s in reversed(sessions):
            stype = s.get("session_type", "unknown")
            stime = s.get("time", "??:??")
            findings = s.get("key_findings", "")
            n_decisions = s.get("decisions_count", 0)
            tools_used = s.get("tools_used", 0)

            line = f"- [{stime}] {stype}"
            if n_decisions:
                line += f" — {n_decisions}个决策"
            if tools_used:
                line += f", {tools_used}次工具调用"
            lines.append(line)

            if findings:
                short = findings[:1500]
                if len(findings) > 1500:
                    short += "..."
                lines.append(f"  摘要: {short}")

            # Include debate summaries if present (v55.0)
            debates = s.get("debate_summaries", [])
            for d in debates[:3]:
                symbol = d.get("symbol", "")
                name = d.get("name", "")
                action = d.get("final_action", "")
                reasoning = d.get("reasoning", "")[:100]
                lines.append(f"  辩论: {name}({symbol}) → {action} — {reasoning}")

        return "\n".join(lines) + "\n"

    def save_debate_summary(
        self,
        session_type: str,
        debate_summary: dict[str, Any],
        date: str | None = None,
    ) -> None:
        """Append a debate summary to the current session's record.

        The debate summary is stored as part of the session record
        so that later sessions can reference earlier debates.
        """
        if not self._redis:
            return

        if not date:
            date = datetime.now(_CST).strftime("%Y-%m-%d")

        key = f"{_REDIS_KEY_PREFIX}{date}"
        try:
            # Read the most recent session record
            raw = self._redis.lindex(key, 0)
            if not raw:
                return
            record = json.loads(raw)
            debates = record.get("debate_summaries", [])
            debates.append(
                {
                    "symbol": debate_summary.get("symbol", ""),
                    "name": debate_summary.get("name", ""),
                    "final_action": debate_summary.get("final_action", ""),
                    "reasoning": (debate_summary.get("verdict", {}) or {}).get(
                        "reasoning", ""
                    )[:200],
                    "bull_count": len(debate_summary.get("bull_arguments", [])),
                    "bear_count": len(debate_summary.get("bear_arguments", [])),
                }
            )
            record["debate_summaries"] = debates

            # Replace the most recent record
            pipe = self._redis.pipeline()
            pipe.lset(key, 0, json.dumps(record, ensure_ascii=False))
            pipe.execute()
        except Exception as exc:
            logger.warning("SessionMemory save_debate_summary failed: %s", exc)

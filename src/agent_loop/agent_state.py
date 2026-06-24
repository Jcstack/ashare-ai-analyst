"""Persistent agent state across heartbeats — Redis-backed.

Tracks what the agent has decided, what needs follow-up, and what
it's currently researching. Survives process restarts and is
scoped to the current trading day.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("agent_loop.agent_state")

_KEY_PREFIX = "agent:state"


@dataclass
class AgentDecision:
    """A decision the agent made during a heartbeat."""

    timestamp: str
    action: str  # buy/sell/hold/watch/ignore
    symbol: str
    summary: str
    confidence: float = 0.5
    executed: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    """Cross-heartbeat persistent state for one trading day.

    Loaded from Redis at heartbeat start, saved after each heartbeat.
    Scoped to a single trading day (key includes date).
    """

    date: str  # YYYYMMDD
    heartbeat_count: int = 0
    last_heartbeat: str = ""

    # What the agent has decided today
    decisions: list[AgentDecision] = field(default_factory=list)

    # Stocks the agent wants to research further
    research_queue: list[dict[str, Any]] = field(default_factory=list)

    # Stocks the agent is watching (self-managed watchlist)
    watched_stocks: list[str] = field(default_factory=list)

    # Key findings from today's sessions (condensed)
    findings: list[str] = field(default_factory=list)

    # Current market assessment (updated each heartbeat)
    market_assessment: str = ""

    # What the agent plans to do next (set at end of each heartbeat)
    next_focus: str = ""

    # Conviction log: accumulating evidence per candidate (Phase 3)
    # Key: symbol, value: list of {"time", "signal", "direction", "weight"}
    conviction_log: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    # Yesterday's outcomes for morning reflection (Phase 4)
    yesterday_outcomes: list[dict[str, Any]] = field(default_factory=list)

    # Lessons learned from reflection
    lessons: list[str] = field(default_factory=list)

    # Missions executed today (for once-per-day dedup)
    executed_missions: set[str] = field(default_factory=set)

    # Last 10 compressed mission summaries
    rolling_context: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, redis_client: Any, date: str | None = None) -> AgentState:
        """Load state from Redis, or create fresh for today."""
        if date is None:
            date = datetime.now(UTC).strftime("%Y%m%d")

        key = f"{_KEY_PREFIX}:{date}"
        try:
            raw = redis_client.get(key)
            if raw:
                data = json.loads(raw)
                state = cls(date=date)
                state.heartbeat_count = data.get("heartbeat_count", 0)
                state.last_heartbeat = data.get("last_heartbeat", "")
                state.decisions = [
                    AgentDecision(**d) for d in data.get("decisions", [])
                ]
                state.research_queue = data.get("research_queue", [])
                state.watched_stocks = data.get("watched_stocks", [])
                state.findings = data.get("findings", [])
                state.market_assessment = data.get("market_assessment", "")
                state.next_focus = data.get("next_focus", "")
                state.conviction_log = data.get("conviction_log", {})
                state.yesterday_outcomes = data.get("yesterday_outcomes", [])
                state.lessons = data.get("lessons", [])
                state.executed_missions = set(data.get("executed_missions", []))
                state.rolling_context = data.get("rolling_context", [])
                return state
        except Exception as exc:
            logger.warning("Failed to load agent state: %s", exc)

        return cls(date=date)

    def save(self, redis_client: Any) -> None:
        """Persist state to Redis with 24h TTL."""
        key = f"{_KEY_PREFIX}:{self.date}"
        data = {
            "heartbeat_count": self.heartbeat_count,
            "last_heartbeat": self.last_heartbeat,
            "decisions": [
                {
                    "timestamp": d.timestamp,
                    "action": d.action,
                    "symbol": d.symbol,
                    "summary": d.summary,
                    "confidence": d.confidence,
                    "executed": d.executed,
                    "details": d.details,
                }
                for d in self.decisions
            ],
            "research_queue": self.research_queue[-20:],  # cap at 20
            "watched_stocks": self.watched_stocks[:30],  # cap at 30
            "findings": self.findings[-10:],  # keep last 10
            "market_assessment": self.market_assessment,
            "next_focus": self.next_focus,
            "conviction_log": {
                k: v[-10:] for k, v in self.conviction_log.items()
            },  # cap at 10 signals per symbol
            "yesterday_outcomes": self.yesterday_outcomes[-10:],
            "lessons": self.lessons[-5:],
            "executed_missions": list(self.executed_missions),
            "rolling_context": self.rolling_context[-10:],
        }
        try:
            redis_client.set(key, json.dumps(data, ensure_ascii=False), ex=86400)
        except Exception as exc:
            logger.warning("Failed to save agent state: %s", exc)

    def add_decision(self, decision: AgentDecision) -> None:
        """Record a new decision."""
        self.decisions.append(decision)

    def add_finding(self, finding: str) -> None:
        """Record a key finding (max 200 chars)."""
        self.findings.append(finding[:200])

    def add_context(self, summary: str) -> None:
        """Append a compressed mission summary. Keep last 10, skip duplicates."""
        # Skip if identical to the last entry (same heartbeat producing same output)
        if self.rolling_context and self.rolling_context[-1] == summary:
            return
        self.rolling_context.append(summary)
        if len(self.rolling_context) > 10:
            self.rolling_context = self.rolling_context[-10:]

    def get_decisions_summary(self) -> str:
        """Format today's decisions for the agent's context.

        Only shows the most recent decision per symbol (deduped) and caps
        at 8 entries to avoid flooding the prompt with stale context.
        """
        if not self.decisions:
            return "今日尚无决策"

        # Deduplicate: keep last decision per (symbol, action) pair
        seen: dict[tuple[str, str], "AgentDecision"] = {}
        for d in self.decisions:
            key = (d.symbol, d.action)
            seen[key] = d  # Later entries overwrite earlier ones

        # Sort by timestamp descending, cap at 8
        recent = sorted(seen.values(), key=lambda d: d.timestamp, reverse=True)[:8]

        lines = []
        for d in recent:
            status = "已执行" if d.executed else "待执行"
            lines.append(
                f"- [{d.timestamp}] {d.action} {d.symbol}: "
                f"{d.summary[:100]} (置信度{d.confidence:.0%}, {status})"
            )
        if len(self.decisions) > len(recent):
            lines.append(f"（今日共 {len(self.decisions)} 条决策，仅显示最近）")
        return "\n".join(lines)

    def get_pending_research(self) -> str:
        """Format research queue for agent context."""
        if not self.research_queue:
            return "无待研究标的"
        lines = []
        for item in self.research_queue[:5]:
            lines.append(
                f"- {item.get('symbol', '?')} {item.get('name', '')}: "
                f"{item.get('reason', '待研究')}"
            )
        return "\n".join(lines)

    def add_conviction(
        self, symbol: str, signal: str, direction: str, weight: float = 1.0
    ) -> None:
        """Accumulate conviction evidence for a candidate.

        Args:
            symbol: Stock symbol.
            signal: Signal description (e.g. "资金持续流入", "涨停封板坚固").
            direction: "bullish" or "bearish".
            weight: Signal weight (default 1.0).
        """
        if symbol not in self.conviction_log:
            self.conviction_log[symbol] = []
        self.conviction_log[symbol].append(
            {
                "time": datetime.now(UTC).strftime("%H:%M"),
                "signal": signal[:100],
                "direction": direction,
                "weight": weight,
            }
        )

    def get_conviction_score(self, symbol: str) -> float:
        """Compute net conviction score for a symbol.

        Returns positive for bullish, negative for bearish.
        """
        entries = self.conviction_log.get(symbol, [])
        if not entries:
            return 0.0
        score = 0.0
        for e in entries:
            w = e.get("weight", 1.0)
            if e.get("direction") == "bullish":
                score += w
            else:
                score -= w
        return score

    def get_conviction_summary(self) -> str:
        """Format conviction log for agent context."""
        if not self.conviction_log:
            return "无候选标的信号积累"
        lines = []
        for symbol, entries in self.conviction_log.items():
            score = self.get_conviction_score(symbol)
            direction = "看多" if score > 0 else "看空" if score < 0 else "中性"
            lines.append(
                f"- {symbol}: {direction}(净分{score:.1f}, {len(entries)}条信号)"
            )
        return "\n".join(lines[:10])

    def load_yesterday_outcomes(
        self,
        redis_client: Any,
        now_cst: datetime | None = None,
    ) -> None:
        """Load yesterday's decision outcomes from Redis.

        Args:
            redis_client: Redis connection.
            now_cst: Current time in Asia/Shanghai. If None, uses UTC
                (legacy fallback).
        """
        try:
            from datetime import timedelta

            if now_cst is not None:
                today = now_cst.date()
            else:
                today = datetime.now(UTC).date()

            # Try TradingCalendar for accurate previous trading day
            yesterday_date = None
            try:
                from src.data.trading_calendar import TradingCalendar

                cal = TradingCalendar()
                yesterday_date = cal.prev_trading_day(today)
            except Exception:
                yesterday_date = today - timedelta(days=1)

            yesterday = yesterday_date.strftime("%Y%m%d")
            key = f"agent:outcomes:{yesterday}"
            raw = redis_client.get(key)
            if raw:
                self.yesterday_outcomes = json.loads(raw)
        except Exception as exc:
            logger.debug("No yesterday outcomes: %s", exc)

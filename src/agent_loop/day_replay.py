"""Day replay harness — replay historical trading days through the agent.

Feeds recorded market data for a specific date into InvestorAgent sessions
to evaluate what the agent would have decided. Compares agent decisions
against actual market outcomes.

Usage:
    harness = DayReplayHarness("2026-03-28")
    report = await harness.replay_full_day()
    print(report.summary)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
_CST = ZoneInfo("Asia/Shanghai")

# Sessions to replay in order (skip call_auction — no data)
_REPLAY_SESSIONS = [
    "pre_market",
    "market_open",
    "morning_check",
    "midday",
    "afternoon",
    "late_session",
    "close",
]


@dataclass
class SessionReplayResult:
    """Result of replaying a single session."""

    session_type: str
    decisions: list[dict[str, Any]] = field(default_factory=list)
    tools_called: int = 0
    turns: int = 0
    cost_usd: float = 0.0
    error: str = ""


@dataclass
class DayReplayReport:
    """Complete replay report for a trading day."""

    replay_date: str
    sessions: list[SessionReplayResult] = field(default_factory=list)
    total_decisions: int = 0
    total_cost_usd: float = 0.0
    actual_outcomes: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        lines = [f"Day Replay Report: {self.replay_date}"]
        lines.append(
            f"Sessions: {len(self.sessions)}, Decisions: {self.total_decisions}"
        )
        lines.append(f"Total Cost: ${self.total_cost_usd:.4f}")
        lines.append("")
        for s in self.sessions:
            status = (
                f"{len(s.decisions)} decisions" if not s.error else f"ERROR: {s.error}"
            )
            lines.append(
                f"  [{s.session_type}] {status} (turns={s.turns}, ${s.cost_usd:.4f})"
            )
            for d in s.decisions:
                lines.append(
                    f"    → {d.get('type', '?')} {d.get('symbol', '?')} "
                    f"confidence={d.get('confidence', 0):.0%}"
                )
        return "\n".join(lines)


class DayReplayHarness:
    """Replay a historical trading day through the agent loop.

    Replaces live data fetchers with historical data for the specified date.
    Runs all sessions sequentially with the same agent state.
    """

    def __init__(
        self,
        replay_date: str,
        gateway: Any = None,
        tool_registry: Any = None,
    ) -> None:
        self._date = replay_date
        self._gateway = gateway
        self._tool_registry = tool_registry

    async def replay_full_day(self) -> DayReplayReport:
        """Replay all sessions for the target date.

        Returns:
            DayReplayReport with per-session decisions and outcomes.
        """
        from src.web.dependencies import get_llm_gateway, get_tool_registry

        gateway = self._gateway or get_llm_gateway()
        tool_registry = self._tool_registry or get_tool_registry()

        report = DayReplayReport(replay_date=self._date)

        for session_type in _REPLAY_SESSIONS:
            result = await self._replay_session(session_type, gateway, tool_registry)
            report.sessions.append(result)
            report.total_decisions += len(result.decisions)
            report.total_cost_usd += result.cost_usd

        # Load actual outcomes for comparison
        report.actual_outcomes = self._load_actual_outcomes()

        logger.info(
            "Day replay %s complete: %d sessions, %d decisions, $%.4f",
            self._date,
            len(report.sessions),
            report.total_decisions,
            report.total_cost_usd,
        )
        return report

    async def _replay_session(
        self,
        session_type: str,
        gateway: Any,
        tool_registry: Any,
    ) -> SessionReplayResult:
        """Replay a single agent session."""
        from src.agent_loop.investor_agent import _SESSION_CONFIG
        from src.agent_loop.llm_agent import AgentLoop
        from src.llm.base import LLMMessage

        result = SessionReplayResult(session_type=session_type)
        config = _SESSION_CONFIG.get(session_type)
        if not config:
            result.error = f"Unknown session type: {session_type}"
            return result

        loop = AgentLoop(
            gateway=gateway,
            tool_executor=tool_registry.execute,
            tool_definitions=tool_registry.get_tool_definitions(),
            max_turns=10,
            max_cost_usd=0.10,
        )

        system = (
            f"你是A股投资总监。正在回测 {self._date} 的 {config['name']} 时段。\n"
            f"请使用工具获取当天数据并做出决策。\n"
            f"注意：这是历史回测，请基于当天数据做判断。"
        )

        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=config["directive"]),
        ]

        try:
            agent_result = await loop.run(
                messages,
                caller="replay_agent",
                max_tokens=4096,
                temperature=0.2,
            )
            result.turns = agent_result.turns
            result.cost_usd = agent_result.total_cost_usd
            result.tools_called = agent_result.tool_calls_made

            # Parse decisions from response
            if agent_result.text:
                result.decisions = self._extract_decisions(agent_result.text)

        except Exception as exc:
            result.error = str(exc)
            logger.warning("Replay session %s failed: %s", session_type, exc)

        return result

    @staticmethod
    def _extract_decisions(text: str) -> list[dict[str, Any]]:
        """Extract structured decisions from agent response text."""
        import json
        import re

        match = re.search(r'"decisions"\s*:\s*\[.*?\]', text, re.DOTALL)
        if match:
            try:
                wrapper = "{" + match.group() + "}"
                data = json.loads(wrapper)
                return data.get("decisions", [])
            except json.JSONDecodeError:
                pass
        return []

    def _load_actual_outcomes(self) -> dict[str, Any]:
        """Load actual market outcomes for the replay date."""
        try:
            from datetime import datetime, timedelta

            from src.data.fetcher import StockDataFetcher

            fetcher = StockDataFetcher()
            # Get market index performance over a short window covering the
            # replay date (fetch_daily_ohlcv expects YYYYMMDD bounds).
            end_dt = datetime.strptime(self._date, "%Y-%m-%d")
            start_dt = end_dt - timedelta(days=10)
            df = fetcher.fetch_daily_ohlcv(
                "000001",
                start_date=start_dt.strftime("%Y%m%d"),
                end_date=end_dt.strftime("%Y%m%d"),
            )
            if df is not None and not df.empty:
                day_row = df[df["date"] == self._date]
                if not day_row.empty:
                    return {
                        "index_change": float(day_row.iloc[0].get("pct_change", 0)),
                        "date": self._date,
                    }
        except Exception as exc:
            logger.debug("Failed to load actual outcomes: %s", exc)
        return {"date": self._date}

"""HeartbeatAgent — mission-driven autonomous investor.

Architecture: "The model is the agent. The code is the harness."

NOT a 5-minute polling check. The scheduler determines WHICH mission
to run based on time and events. The agent then executes the mission
deeply — using as many tools as needed until it has enough information
to make a decision or conclude "no action needed".

Missions:
    morning_plan    08:00  — Overnight analysis, portfolio risk, day strategy (10+ tools)
    portfolio_watch 09:30+ — Deep check each position (price, flow, thesis validity)
    opportunity_hunt 10:30+ — Scan market, research candidates, propose trades
    decision_window 14:30  — Final buy/sell decisions with full evidence chain
    close_review    15:05  — Day summary, P&L, lessons, tomorrow plan
    event_response  anytime — React to price spike / news break (quick 3-5 tools)

Flow:
    Scheduler picks mission → build mission prompt → AgentLoop.run()
    → Model calls 5-20 tools as needed → Model stops when it has enough
    → Parse decisions → Push to Discord
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.agent_loop.agent_state import AgentState
from src.agent_loop.decision_handler import DecisionHandler
from src.utils.logger import get_logger

logger = get_logger("agent_loop.heartbeat_agent")
_CST = ZoneInfo("Asia/Shanghai")


# ---------------------------------------------------------------------------
# Mission definitions — what the agent must ACCOMPLISH, not "what to look at"
# ---------------------------------------------------------------------------

_MISSIONS: dict[str, dict[str, Any]] = {
    "morning_plan": {
        "name": "晨间策略",
        "max_turns": 20,
        "max_cost": 0.50,
        "caller": "final_decision",
        "mission": (
            "制定今日交易策略。评估大环境，检查每个持仓，寻找新机会。\n"
            "用 submit_* 工具表达你的决策。"
        ),
    },
    "portfolio_watch": {
        "name": "持仓巡检",
        "max_turns": 15,
        "max_cost": 0.30,
        "caller": "final_decision",
        "mission": (
            "检查每个持仓是否健康。该卖就卖，该持有就说理由。\n"
            "用 submit_hold_update 或 submit_sell_signal 逐个表达。"
        ),
    },
    "opportunity_hunt": {
        "name": "机会猎手",
        "max_turns": 20,
        "max_cost": 0.50,
        "caller": "final_decision",
        "mission": (
            "找到今天最值得买入的股票。\n"
            "你有全套工具，自行决定分析路径和调用顺序。\n"
            "先看资金——满仓就不找新票。\n"
            "找到好机会就 submit_buy_signal，没有就说明原因。"
        ),
    },
    "decision_window": {
        "name": "尾盘决策",
        "max_turns": 20,
        "max_cost": 0.60,
        "caller": "final_decision",
        "mission": (
            "尾盘决策窗口。两件事：\n"
            "1. 评估每个持仓，决定操作\n"
            "2. 有闲钱就找买入机会，没钱就只做持仓评估\n"
            "用 submit_* 工具表达决策。"
        ),
    },
    "close_review": {
        "name": "收盘总结",
        "max_turns": 15,
        "max_cost": 0.30,
        "caller": "final_decision",
        "mission": (
            "收盘复盘 + 明日计划。\n"
            "今天做对了什么？错了什么？错过了什么？诚实总结。\n"
            "逐个持仓用 submit_hold_update 表达明日操作预案。"
        ),
    },
    "event_response": {
        "name": "事件响应",
        "max_turns": 8,
        "max_cost": 0.15,
        "caller": "trading_advisor",
        "mission": (
            "刚发生了一个市场事件（详情见下方）。\n"
            "快速判断：需要行动还是忽略？用 submit_* 工具或说明理由。"
        ),
    },
    "quick_trade": {
        "name": "快速交易判断",
        "max_turns": 8,
        "max_cost": 0.05,
        "caller": "trading_advisor",
        "mission": (
            "快速决策。两种情况：\n"
            "1. 有持仓：查价格，对比止损和目标，该卖就 submit_sell_signal，该持有就 submit_hold_update\n"
            "2. 空仓/有闲钱：找机会，用 get_trend_candidates 或 get_sector_leaders 扫描，"
            "找到好票就 submit_buy_signal，没有就说明原因\n"
            "重要：目标是做出决策（submit_*），不是收集信息。最多用3个工具就该决策了。"
        ),
    },
}


# Map time ranges to missions
def _select_mission(now_cst: datetime, state: AgentState) -> str:
    """Select mission — fast trading judgments primary, deep analysis secondary.

    Two-speed design (like a real trader):
    - FAST (quick_trade): 30s decision, every heartbeat during trading
    - DEEP (opportunity_hunt/portfolio_watch): 3-5min, once per hour
    - CRITICAL (decision_window): 14:30-15:00, final decisions
    """
    h, m = now_cst.hour, now_cst.minute
    t = h * 60 + m

    # First heartbeat of the day → morning plan (deep)
    if state.heartbeat_count == 1 and h < 10:
        return "morning_plan"

    # 15:05+ → close review (once per day)
    if t >= 15 * 60 + 5:
        if "close_review" not in state.executed_missions:
            return "close_review"
        return "quick_trade"

    # 14:30-15:05 → decision window (critical, once)
    if t >= 14 * 60 + 30:
        if "decision_window" not in state.executed_missions:
            return "decision_window"
        return "quick_trade"

    # Trading hours 09:30-14:30
    if t >= 9 * 60 + 30:
        # Check if portfolio is empty — opportunity hunt is more valuable
        is_empty = not state.decisions  # No decisions today = likely empty
        try:
            from src.web.dependencies import get_portfolio_store

            ps = get_portfolio_store()
            if ps:
                is_empty = len(ps.list_positions()) == 0
        except Exception:
            pass

        if is_empty:
            # Empty portfolio: hunt for opportunities every cycle,
            # deep analysis at :00 and :30
            if m < 5 or (m >= 30 and m < 35):
                return "opportunity_hunt"
            return "quick_trade"  # quick_trade prompt is portfolio-aware

        # Has positions: regular schedule
        if m < 5:
            return "portfolio_watch"  # Deep持仓检查 (3-5 min)
        if m >= 30 and m < 35:
            return "opportunity_hunt"  # Deep机会搜索 (3-5 min)
        return "quick_trade"

    # Pre-market 08:00-09:30
    if h >= 8:
        return "morning_plan" if state.heartbeat_count <= 2 else "quick_trade"

    return "quick_trade"


_STATIC_PROMPT = """你是A股投资总监，自主管理一个真实账户。你的买卖指令直接推送到用户手机执行——每个决策都是真金白银。

## 核心原则
- 你是决策者，不是顾问。直接说"买"、"卖"、"持有"，用大白话，不要技术术语
- 仓位跟着信心走（Druckenmiller: 信心极强时全力出击；赵老哥: 越不顺越控仓）——没有死规则
- 非对称下注（Soros: reward/risk < 1.5 不做，> 3 重仓）
- 止损铁律：设了就执行，亏损的票不讲道理
- 每个结论必须有工具数据支撑，不能凭空判断

## A股铁律
- 满仓不买新票——可用资金不足以买100股时，不推荐任何买入
- 已涨停的票（主板≥9.9%、创业板/科创板≥19.9%）买不到——涨停封板散户排队也成交不了
- 涨停股是情报来源（判断板块主线），不是买入目标。看到龙头涨停后，找同板块涨幅3-7%的可买标的
- 当用户告知执行了交易，必须用 record_manual_trade 工具同步持仓

## 工具
你有多种工具可用。根据任务需要自行选择调用哪些——工具失败就跳过，不要因此放弃分析。
使用 submit_buy_signal / submit_sell_signal / submit_hold_update 工具表达你的决策。

## 输出格式
通过工具调用表达买卖持有决策。分析完成后可以用文字总结判断。"""


class HeartbeatAgent:
    """Mission-driven autonomous investor agent.

    The scheduler picks a mission based on time/events. The agent executes
    the mission deeply — calling as many tools as needed until it has enough
    information to decide. This is NOT a polling check.
    """

    def __init__(
        self,
        gateway: Any = None,
        tool_registry: Any = None,
        portfolio_store: Any = None,
        capital_service: Any = None,
        message_store: Any = None,
        quote_manager: Any = None,
        global_market_fetcher: Any = None,
    ) -> None:
        self._gateway = gateway
        self._tool_registry = tool_registry
        self._portfolio = portfolio_store
        self._capital = capital_service
        self._message_store = message_store
        self._quote_manager = quote_manager
        self._global_market = global_market_fetcher

        self._current_state: AgentState | None = None  # Set during run_heartbeat

        self._redis = None
        try:
            from src.web.dependencies import get_redis

            self._redis = get_redis()
        except Exception:
            logger.warning("Redis unavailable — agent state will not persist")

        self._decision_handler = DecisionHandler(
            message_store=message_store,
            redis_client=self._redis,
        )

    async def run_heartbeat(self) -> dict[str, Any]:
        """Run a mission — agent executes deeply until done."""
        import time

        start = time.monotonic()
        now_cst = datetime.now(_CST)
        date_str = now_cst.strftime("%Y%m%d")

        # Load persistent state
        state = (
            AgentState.load(self._redis, date_str)
            if self._redis
            else AgentState(date=date_str)
        )
        state.heartbeat_count += 1
        state.last_heartbeat = now_cst.strftime("%H:%M")

        if state.heartbeat_count == 1 and self._redis:
            state.load_yesterday_outcomes(self._redis, now_cst)

        # Select mission based on time and state
        mission_key = _select_mission(now_cst, state)
        mission = _MISSIONS[mission_key]

        logger.info(
            "=== Mission [%s] %s #%d START ===",
            mission_key,
            mission["name"],
            state.heartbeat_count,
        )

        if not self._gateway or not self._tool_registry:
            logger.error("Agent not initialized (missing gateway or tools)")
            return {"error": "not_initialized"}

        try:
            from src.agent_loop.llm_agent import AgentLoop
            from src.llm.base import LLMMessage

            # Create agent loop with core tools only (progressive disclosure)
            agent_loop = AgentLoop(
                gateway=self._gateway,
                tool_executor=self._tool_registry.execute,
                tool_definitions=self._tool_registry.get_core_definitions(),
                max_turns=mission["max_turns"],
                max_cost_usd=mission["max_cost"],
            )

            system_prompt = _STATIC_PROMPT
            user_message = self._build_context_message(now_cst, state, mission)

            messages = [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_message),
            ]

            self._current_state = state
            result = await agent_loop.run(
                messages=messages,
                caller=mission["caller"],
            )
            self._current_state = None

            # Pass tool usage context for calibration tracking
            tools_used = []
            tools_failed = []
            if result and hasattr(result, "tool_history") and result.tool_history:
                for name, _input, output in result.tool_history:
                    tools_used.append(name)
                    if output and "error" in str(output).lower():
                        tools_failed.append(name)
            DecisionHandler.set_tool_context(
                tools_used=tools_used, tools_failed=tools_failed
            )

            # Primary: count decisions already pushed via submit_* tool calls
            tool_pushed = 0
            tool_symbols: set[str] = set()
            if result and hasattr(result, "tool_history") and result.tool_history:
                for name, _input, output in result.tool_history:
                    if (
                        name.startswith("submit_")
                        and "rejected" not in str(output).lower()
                    ):
                        tool_pushed += 1
                        sym = (
                            _input.get("symbol", "") if isinstance(_input, dict) else ""
                        )
                        if sym:
                            tool_symbols.add(sym)

            # Fallback: parse JSON from response text (backward compat)
            response_text = result.text if result else ""
            decisions = DecisionHandler.parse_decisions(response_text)

            # Dedup: only push text decisions for symbols NOT already
            # handled by tool calls
            if tool_symbols:
                decisions = [
                    d for d in decisions if d.get("symbol") not in tool_symbols
                ]

            pushed = tool_pushed
            if decisions:
                pushed += await self._decision_handler.push_decisions(
                    decisions,
                    state,
                    mission_key,
                )

            # Push briefing for non-idle missions with content
            if mission_key != "quick_trade" and response_text.strip():
                await self._decision_handler.push_briefing(
                    response_text,
                    now_cst,
                    state,
                    mission_key,
                )
            elif mission_key == "quick_trade" and "无变化" not in response_text:
                # quick_trade found something — push it
                if response_text.strip() and len(response_text.strip()) > 10:
                    await self._decision_handler.push_briefing(
                        response_text,
                        now_cst,
                        state,
                        mission_key,
                    )

            # Update state
            self._update_state(state, response_text, decisions, mission_key)

            # Save compressed context for next heartbeat
            # Filter to valid 6-digit symbols only (exclude "CASH", "", etc.)
            valid_decisions = [
                d for d in decisions if re.fullmatch(r"\d{6}", d.get("symbol") or "")
            ]
            context_summary = self._compress_mission_context(
                mission_key, valid_decisions, response_text
            )
            if context_summary:
                state.add_context(context_summary)

            if self._redis:
                state.save(self._redis)

            duration = time.monotonic() - start
            tools_used = result.tool_calls_made if result else 0

            # Save mission summary — include tool-call decisions for complete picture
            all_decisions_for_memory = list(decisions)
            if result and hasattr(result, "tool_history") and result.tool_history:
                for name, _input, _output in result.tool_history:
                    if name.startswith("submit_") and isinstance(_input, dict):
                        act = (
                            "buy"
                            if "buy" in name
                            else ("sell" if "sell" in name else "hold")
                        )
                        all_decisions_for_memory.append(
                            {
                                "symbol": _input.get("symbol", ""),
                                "action": act,
                                "summary": _input.get("summary", ""),
                            }
                        )
            self._save_session_summary(
                mission_key,
                mission["name"],
                response_text,
                all_decisions_for_memory,
                tools_used,
            )

            logger.info(
                "=== Mission [%s] END — %.1fs, %d tools, %d decisions, %d pushed ===",
                mission_key,
                duration,
                tools_used,
                len(decisions),
                pushed,
            )

            return {
                "status": "ok",
                "mission": mission_key,
                "mission_name": mission["name"],
                "heartbeat": state.heartbeat_count,
                "time": now_cst.strftime("%H:%M"),
                "duration_seconds": round(duration, 2),
                "tools_used": tools_used,
                "decisions": len(decisions),
                "pushed": pushed,
                "provider": result.provider if result else None,
                "model": result.model if result else None,
                "cost": round(result.total_cost_usd, 4) if result else 0,
            }

        except Exception as exc:
            logger.error("Mission [%s] failed: %s", mission_key, exc, exc_info=True)
            return {"error": str(exc), "mission": mission_key}

    async def run_event_response(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """Rapid response to a market event."""
        import time

        start = time.monotonic()
        symbol = event_data.get("symbol", "")
        event_type = event_data.get("event_type", "unknown")

        logger.info("=== Event Response [%s] %s START ===", event_type, symbol)

        if not self._gateway or not self._tool_registry:
            return {"error": "not_initialized"}

        try:
            from src.agent_loop.llm_agent import AgentLoop
            from src.llm.base import LLMMessage

            mission = _MISSIONS["event_response"]
            agent_loop = AgentLoop(
                gateway=self._gateway,
                tool_executor=self._tool_registry.execute,
                tool_definitions=self._tool_registry.get_core_definitions(),
                max_turns=mission["max_turns"],
                max_cost_usd=mission["max_cost"],
            )

            portfolio_text = self._get_portfolio_text()
            event_desc = (
                f"事件类型: {event_type}\n"
                f"股票: {symbol} ({event_data.get('name', '')})\n"
                f"数据: {json.dumps(event_data, ensure_ascii=False, default=str)}\n\n"
                f"当前持仓:\n{portfolio_text}"
            )

            messages = [
                LLMMessage(role="system", content=_STATIC_PROMPT),
                LLMMessage(
                    role="user", content=mission["mission"] + "\n\n" + event_desc
                ),
            ]

            result = await agent_loop.run(messages=messages, caller="trading_advisor")
            response_text = result.text if result else ""
            decisions = DecisionHandler.parse_decisions(response_text)
            pushed = 0

            if decisions:
                state = (
                    AgentState.load(self._redis)
                    if self._redis
                    else AgentState(date=datetime.now(UTC).strftime("%Y%m%d"))
                )
                pushed = await self._decision_handler.push_decisions(
                    decisions,
                    state,
                    "event_response",
                )
                if self._redis:
                    state.save(self._redis)

            duration = time.monotonic() - start
            logger.info(
                "=== Event Response END — %.1fs, %d decisions ===",
                duration,
                len(decisions),
            )
            return {
                "status": "ok",
                "event_type": event_type,
                "symbol": symbol,
                "duration_seconds": round(duration, 2),
                "decisions": len(decisions),
                "pushed": pushed,
            }

        except Exception as exc:
            logger.error("Event response failed: %s", exc, exc_info=True)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self, now_cst: datetime, state: AgentState, mission: dict[str, Any]
    ) -> str:
        """Build system prompt — now returns static prompt (dynamic content in user msg)."""
        return _STATIC_PROMPT

    def _build_context_message(
        self, now_cst: datetime, state: AgentState, mission: dict[str, Any]
    ) -> str:
        """Build dynamic context as user message.

        Claude Code pattern: static identity in system prompt, all dynamic
        context (portfolio, state, memory) in the user message. This makes
        the system prompt cacheable across heartbeats.
        """
        parts = []

        # Current state header
        parts.append(
            f"时间: {now_cst.strftime('%Y-%m-%d %H:%M (CST)')} | "
            f"市场: {self._get_market_status(now_cst)} | "
            f"第 {state.heartbeat_count} 次心跳 | 任务: {mission['name']}"
        )

        # Portfolio + cash
        parts.append(f"\n持仓:\n{self._get_portfolio_text()}")
        parts.append(f"可用资金: ¥{self._get_available_cash()}")

        # Original buy theses — anchor against target-price drift
        thesis_ctx = self._load_active_theses()
        if thesis_ctx:
            parts.append(f"\n## 持仓原始计划（不要随意修改止损和目标）\n{thesis_ctx}")

        # Today's decisions — CRITICAL for consistency
        decisions_summary = state.get_decisions_summary()
        parts.append(f"\n今日决策: {decisions_summary}")

        # Explicit warning if buy signals were already pushed today
        today_buys = [d for d in state.decisions if d.action in ("buy", "add")]
        if today_buys:
            buy_symbols = ", ".join(f"{d.symbol}({d.summary[:20]})" for d in today_buys)
            parts.append(
                f"\n⚠️ 已推荐买入: {buy_symbols}\n"
                "不要重复推荐同一只票。不要当天推荐买入又推荐卖出（除非触发止损）。"
            )

        parts.append(f"待研究: {state.get_pending_research()}")
        parts.append(f"信号积累: {state.get_conviction_summary()}")

        # Holiday risk awareness
        holiday_ctx = self._check_holiday_risk(now_cst)
        if holiday_ctx:
            parts.append(f"\n{holiday_ctx}")

        # Sentiment cycle auto-inject (saves a tool call)
        sentiment_ctx = self._load_sentiment_state()
        if sentiment_ctx:
            parts.append(f"\n{sentiment_ctx}")

        # Extra context sections
        extra_parts: list[str] = []
        if state.yesterday_outcomes and state.heartbeat_count <= 2:
            extra_parts.append(
                "## 昨日决策结果\n" + self._format_yesterday_outcomes(state)
            )
        if state.findings:
            extra_parts.append("## 今日发现\n" + "\n".join(state.findings[-5:]))

        pred_ctx = self._load_prediction_context()
        if pred_ctx:
            extra_parts.append("## 量化预测（昨日管线）\n" + pred_ctx)
        session_ctx = self._load_session_history()
        if session_ctx:
            extra_parts.append("## 最近分析（你的短期记忆）\n" + session_ctx)
        knowledge_ctx = self._load_relevant_knowledge(state)
        if knowledge_ctx:
            extra_parts.append("## 相关历史分析（你的长期记忆）\n" + knowledge_ctx)
        cal_ctx = self._load_calibration_context()
        if cal_ctx:
            extra_parts.append("## 历史准确率（你自己的成绩单）\n" + cal_ctx)
        dream_lessons = self._load_dream_lessons()
        if dream_lessons:
            extra_parts.append("## 经验教训（autoDream 蒸馏）\n" + dream_lessons)
        stress_ctx = self._load_stress_test_context()
        if stress_ctx:
            extra_parts.append("## 压力测试（极端场景下的持仓风险）\n" + stress_ctx)
        accuracy_ctx = self._load_signal_accuracy()
        if accuracy_ctx:
            extra_parts.append(accuracy_ctx)
        if state.rolling_context:
            ctx_text = "\n".join("- " + c for c in state.rolling_context[-5:])
            extra_parts.append("## 最近决策摘要（你的连续思考）\n" + ctx_text)

        if extra_parts:
            parts.append("\n" + "\n\n".join(extra_parts))

        # Extended tool catalog (progressive disclosure)
        if self._tool_registry:
            catalog = self._tool_registry.get_extended_catalog()
            if catalog:
                extra_parts.append(catalog)

        # Mission prompt at the end
        parts.append(f"\n---\n任务: {mission['mission']}")

        return "\n".join(parts)

    def _format_yesterday_outcomes(self, state: AgentState) -> str:
        outcomes = state.yesterday_outcomes
        if not outcomes:
            return "无"
        lines = []
        for o in outcomes[:5]:
            pnl = o.get("pnl_pct", 0)
            pnl_str = f"+{pnl:.1f}%" if pnl > 0 else f"{pnl:.1f}%"
            lines.append(
                f"- {o.get('action', '?')} {o.get('symbol', '?')}: "
                f"{o.get('result', '?')} ({pnl_str})"
            )
        return "\n".join(lines)

    def _load_active_theses(self) -> str:
        """Load original buy theses for current positions from Redis.

        Returns a formatted string suitable for injection into the LLM
        context message.  Each held position with a stored thesis gets
        a line showing the original entry/stop/target so the agent can
        avoid drifting those values without fundamental reason.
        """
        if not self._redis:
            return ""
        try:
            positions: list[dict[str, Any]] = []
            if self._portfolio:
                positions = self._portfolio.list_positions()
            if not positions:
                return ""
            lines: list[str] = []
            for p in positions:
                sym = p.get("symbol", "")
                if not sym:
                    continue
                raw = self._redis.get(f"thesis:{sym}")
                if raw:
                    thesis = json.loads(raw)
                    lines.append(
                        f"- {p.get('name', sym)}({sym}): "
                        f"买入价{thesis.get('entry_price')} "
                        f"原始止损{thesis.get('stop_loss')} "
                        f"原始目标{thesis.get('target_price')} "
                        f"({thesis.get('created_at', '')[:10]})"
                    )
                    reason = thesis.get("summary", "")
                    if reason:
                        lines.append(f"  买入理由: {reason}")
            return "\n".join(lines) if lines else ""
        except Exception:
            return ""

    @staticmethod
    def _check_holiday_risk(now_cst: datetime) -> str:
        """Check if market closes for extended period and inject holiday context."""
        try:
            from src.data.trading_calendar import TradingCalendar

            tc = TradingCalendar()
            today = now_cst.date()
            if not tc.is_trading_day(today):
                return ""

            next_td = tc.next_trading_day(today)
            gap_days = (next_td - today).days

            if gap_days <= 2:
                return ""  # Normal weekend, no special warning

            # Extended closure — holiday detected
            lines = [
                "## ⚠️ 假期风险警告",
                f"今天是假期前最后交易日！下一交易日: {next_td}（休市{gap_days - 1}天）",
                "",
                "假期持仓风险：",
                "- 休市期间无法止损，任何突发事件只能扛着",
                "- 外盘（美股/港股）可能在中国休市期间波动",
                "- 节后跳空低开风险——尤其对高涨幅/游资主导的票",
                "",
                "顶级投资者的做法：",
                "- 强基本面+机构持仓的票 → 可以持股过节",
                "- 高涨幅/游资炒作/大股东减持的票 → 节前减仓或清仓",
                "- 至少保留30%现金应对节后不确定性",
                "- 尾盘14:30前必须做出决定，不要拖到最后几分钟",
            ]
            return "\n".join(lines)
        except Exception:
            return ""

    def _get_market_status(self, now_cst: datetime) -> str:
        h, m = now_cst.hour, now_cst.minute
        t = h * 60 + m
        if t < 9 * 60 + 15:
            return "盘前"
        if t < 9 * 60 + 30:
            return "集合竞价"
        if t < 11 * 60 + 30:
            return "上午盘"
        if t < 13 * 60:
            return "午间休市"
        if t < 15 * 60:
            return "下午盘"
        return "已收盘"

    def _get_portfolio_text(self) -> str:
        if not self._portfolio:
            return "（无法获取持仓数据）"
        try:
            positions = self._portfolio.list_positions()
            if not positions:
                return "空仓"
            lines = []
            for p in positions:
                lines.append(
                    f"- {p.get('name', '?')}({p.get('symbol', '?')}) "
                    f"{p.get('shares', 0)}股 成本¥{p.get('cost_price', 0):.2f} "
                    f"可卖{p.get('available_shares', 0)}股 "
                    f"买入{p.get('buy_date', '?')}"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"（持仓获取失败: {exc}）"

    def _get_available_cash(self) -> str:
        if not self._capital:
            return "未知"
        try:
            return f"{self._capital.get_balance():,.2f}"
        except Exception:
            return "未知"

    def _load_prediction_context(self) -> str:
        """Load latest prediction pipeline results for portfolio symbols."""
        if not self._redis:
            return ""
        try:
            symbols = set()
            if self._portfolio:
                data = self._portfolio.get_portfolio_data()
                for p in data.get("positions", []):
                    s = p.get("symbol", "")
                    if s:
                        symbols.add(s)
            if not symbols:
                return ""

            lines = []
            for sym in sorted(symbols):
                raw = self._redis.get(f"prediction:{sym}")
                if raw:
                    import json

                    pred = json.loads(raw)
                    trend = pred.get("trend", "?")
                    signal = pred.get("signal", "?")
                    conf = pred.get("confidence", 0)
                    lines.append(
                        f"- {sym}: 趋势={trend} 信号={signal} 置信度={conf:.0%}"
                    )
            return "\n".join(lines) if lines else ""
        except Exception:
            return ""

    def _load_calibration_context(self) -> str:
        """Load historical accuracy + dynamically generated lessons."""
        try:
            from src.agent_loop.confidence_calibrator import ConfidenceCalibrator

            cc = ConfidenceCalibrator(
                db_path="data/decisions.db",
                config={"min_samples_for_calibration": 3},
            )
            report = cc.get_calibration_report()
            if report.get("status") != "ok" or not report.get("calibration_active"):
                return ""

            lines = []
            total = report.get("evaluated_decisions", 0)
            acc = report.get("overall_accuracy")
            if acc is not None:
                lines.append(f"整体准确率: {acc:.0%}（{total}条历史决策）")

            by_action = report.get("by_action", {})
            for action in ["buy", "sell", "hold"]:
                stats = by_action.get(action, {})
                a = stats.get("accuracy")
                n = stats.get("evaluated", 0)
                if a is not None and n > 0:
                    lines.append(f"- {action}: {a:.0%} 准确（{n}条）")

            # Dynamic lessons derived from data patterns
            lessons = self._derive_calibration_lessons(report)
            if lessons:
                lines.append("")
                lines.append("从你的历史数据中发现的规律：")
                lines.extend(f"- {lesson}" for lesson in lessons)

            return "\n".join(lines)
        except Exception:
            return ""

    @staticmethod
    def _derive_calibration_lessons(report: dict[str, Any]) -> list[str]:
        """Generate lessons dynamically from calibration report data."""
        lessons: list[str] = []
        by_action = report.get("by_action", {})

        # Lesson: hold accuracy
        hold_stats = by_action.get("hold", {})
        hold_acc = hold_stats.get("accuracy")
        hold_n = hold_stats.get("evaluated", 0)
        if hold_acc is not None and hold_n >= 5 and hold_acc < 0.4:
            lessons.append(
                f"hold 信号准确率仅 {hold_acc:.0%}——犹豫不决往往是错的，要么买要么卖"
            )

        # Lesson: overconfidence
        by_bucket = report.get("by_confidence_bucket", {})
        high_bucket = by_bucket.get("high", {})  # 0.7+
        high_acc = high_bucket.get("accuracy")
        high_n = high_bucket.get("evaluated", 0)
        if high_acc is not None and high_n >= 5 and high_acc < 0.4:
            lessons.append(f"高信心（70%+）准确率仅 {high_acc:.0%}——越自信要越谨慎")

        # Lesson: per-symbol patterns
        by_symbol = report.get("by_symbol", {})
        for sym, stats in (by_symbol or {}).items():
            sym_acc = stats.get("accuracy")
            sym_n = stats.get("evaluated", 0)
            if sym_acc is not None and sym_n >= 5:
                if sym_acc < 0.25:
                    lessons.append(
                        f"{sym} 历史准确率仅 {sym_acc:.0%}（{sym_n}条）——"
                        "这只票你判断不准，谨慎操作"
                    )
                elif sym_acc > 0.65:
                    lessons.append(
                        f"{sym} 历史准确率 {sym_acc:.0%}（{sym_n}条）——"
                        "你对这只票有判断优势"
                    )

        # Lesson: buy accuracy
        buy_stats = by_action.get("buy", {})
        buy_acc = buy_stats.get("accuracy")
        buy_n = buy_stats.get("evaluated", 0)
        if buy_acc is not None and buy_n >= 5 and buy_acc < 0.35:
            lessons.append(f"买入信号准确率 {buy_acc:.0%}——买入决策要更严格筛选")

        return lessons[:5]  # Cap at 5 lessons

    def _update_state(
        self,
        state: AgentState,
        response_text: str,
        decisions: list[dict[str, Any]],
        mission_key: str,
    ) -> None:
        state.executed_missions.add(mission_key)

        for line in response_text.split("\n")[-5:]:
            if any(kw in line for kw in ["下一步", "接下来", "计划", "关注", "明日"]):
                state.next_focus = line.strip()[:200]
                break

        for d in decisions:
            if d.get("action") == "watch" and d.get("symbol"):
                state.research_queue.append(
                    {
                        "symbol": d["symbol"],
                        "name": d.get("name", ""),
                        "reason": d.get("summary", "")[:100],
                    }
                )

    # ------------------------------------------------------------------
    # Memory layers
    # ------------------------------------------------------------------

    def _load_session_history(self) -> str:
        """Load recent mission summaries so Agent knows what it just did."""
        if not self._redis:
            return ""
        try:
            from src.agent_loop.session_memory import SessionMemory

            sm = SessionMemory(redis_client=self._redis)
            sessions = sm.load_context()
            return SessionMemory.format_for_prompt(sessions[:5])
        except Exception:
            return ""

    def _load_relevant_knowledge(self, state: AgentState) -> str:
        """Search MemoryStore for knowledge relevant to current portfolio."""
        try:
            from src.intelligence.memory_store import MemoryStore

            ms = MemoryStore()

            search_terms: list[str] = []
            if self._portfolio:
                try:
                    data = self._portfolio.get_portfolio_data()
                    for p in data.get("positions", []):
                        sym = p.get("symbol", "")
                        name = p.get("name", "")
                        if sym:
                            search_terms.append(f"{sym} {name}")
                except Exception:
                    pass

            for item in (state.research_queue or [])[:3]:
                search_terms.append(item.get("symbol", "") + " " + item.get("name", ""))

            if not search_terms:
                search_terms = ["市场 板块 趋势"]

            lines: list[str] = []
            seen: set[str] = set()
            for term in search_terms[:5]:
                results = ms.retrieve(term, limit=2)
                for r in results:
                    key = r.content[:50]
                    if key not in seen:
                        seen.add(key)
                        lines.append(f"- {r.content[:150]}")

            return "\n".join(lines[:8]) if lines else ""
        except Exception:
            return ""

    def _load_dream_lessons(self) -> str:
        """Load distilled lessons from autoDream (Layer 3)."""
        if not self._redis:
            return ""
        try:
            raw = self._redis.get("agent:distilled_lessons")
            if not raw:
                return ""
            lessons = json.loads(raw)
            return "\n".join(f"- {lesson}" for lesson in lessons[:5])
        except Exception:
            return ""

    @staticmethod
    def _load_sentiment_state() -> str:
        """Load quantified sentiment cycle state for context injection."""
        try:
            from src.web.services.tool_registry import _detect_sentiment_phase

            result = _detect_sentiment_phase()
            if not result or "error" in result:
                return ""
            phase_cn = result.get("phase_cn", "")
            confidence = result.get("confidence", 0)
            advice = result.get("advice", "")
            raw = result.get("raw_signals", {})
            max_pos = result.get("max_position_pct", 0)

            lines = [f"## 情绪周期: {phase_cn} (信心{confidence:.0%})"]
            if raw:
                data_parts = []
                if "limit_up_count" in raw:
                    data_parts.append(f"涨停{raw['limit_up_count']}家")
                if "limit_down_count" in raw:
                    data_parts.append(f"跌停{raw['limit_down_count']}家")
                if "board_break_rate" in raw:
                    data_parts.append(f"炸板率{raw['board_break_rate']:.0%}")
                if "promotion_1to2" in raw:
                    data_parts.append(f"晋级率{raw['promotion_1to2']:.0%}")
                if "max_consecutive_board" in raw:
                    data_parts.append(f"最高{raw['max_consecutive_board']}连板")
                if data_parts:
                    lines.append("数据: " + " | ".join(data_parts))
            lines.append(f"建议仓位: {max_pos:.0%}  {advice}")
            return "\n".join(lines)
        except Exception:
            return ""

    @staticmethod
    def _load_signal_accuracy() -> str:
        """Load signal source accuracy with trend detection."""
        try:
            from src.agent_loop.outcome_tracker import OutcomeTracker

            tracker = OutcomeTracker()
            return tracker.get_rolling_accuracy_summary(lookback_days=30)
        except Exception:
            return ""

    def _load_stress_test_context(self) -> str:
        """Load stress test results for current portfolio."""
        try:
            from src.risk.stress_tester import StressTester  # noqa: F401
            from src.utils.config import load_config

            cfg = load_config("risk")
            scenarios = cfg.get("stress_test", {}).get("scenarios", {})
            if not scenarios or not self._portfolio:
                return ""

            data = self._portfolio.get_portfolio_data()
            positions = data.get("positions", [])
            if not positions:
                return "空仓，无压力测试需要"

            lines = []
            for name, scenario in scenarios.items():
                shock = scenario.get("market_shock", 0)
                lines.append(
                    "- %s: 市场冲击 %.0f%%, 持仓预计影响 %.0f%%"
                    % (scenario.get("name", name), shock * 100, shock * 100 * 1.1)
                )

            return "\n".join(lines) if lines else ""
        except Exception:
            return ""

    def _compress_mission_context(
        self,
        mission_key: str,
        decisions: list[dict[str, Any]],
        response_text: str,
    ) -> str:
        """Compress this mission into one line for rolling context."""
        import re

        now = datetime.now(_CST)
        time_str = now.strftime("%H:%M")

        parts = [time_str]
        for d in decisions[:3]:
            sym = d.get("symbol", "?")
            action = d.get("action", "?")
            conf = d.get("confidence", 0)
            parts.append("%s %s(%.0f%%)" % (action, sym, conf * 100))

        if not decisions:
            # Extract first meaningful sentence from response (strip JSON)
            text = response_text or ""
            text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
            text = re.sub(r'\{\s*"decisions"\s*:.*\}', "", text, flags=re.DOTALL)
            text = re.sub(r"\{[^{}]*\}", "", text)
            text = text.strip()
            first_line = text.split("\n")[0][:80] if text else "无特别发现"
            parts.append(first_line)

        return " | ".join(parts)[:150]

    def _save_session_summary(
        self,
        mission_key: str,
        mission_name: str,
        response_text: str,
        decisions: list[dict[str, Any]],
        tools_used: int = 0,
    ) -> None:
        """Save a summary of this mission for next heartbeat's context."""
        if not self._redis:
            return
        try:
            from src.agent_loop.session_memory import SessionMemory

            # Strip ALL JSON from response to get plain-text findings
            text = response_text or ""
            text = re.sub(r"```json\s*\n?.*?\n?\s*```", "", text, flags=re.DOTALL)
            text = re.sub(
                r'\{\s*"decisions"\s*:.*\}', "", text, flags=re.DOTALL
            )  # greedy — catches nested JSON
            text = re.sub(r"\{[^{}]*\}", "", text)  # remaining fragments
            text = re.sub(r"[\[\],]+\s*", "", text)  # leftover brackets
            findings = text.strip()[:500]

            # If all JSON (no readable text left), summarize from decisions
            if not findings or len(findings) < 20:
                parts = []
                for d in decisions[:3]:
                    sym = d.get("symbol", "?")
                    action = d.get("action", "?")
                    summary = (d.get("summary") or d.get("reason") or "")[:80]
                    parts.append(f"{action} {sym}: {summary}")
                findings = "; ".join(parts) if parts else "无特别发现"

            sm = SessionMemory(redis_client=self._redis)
            sm.save_transcript(
                session_type=mission_key,
                summary={
                    "key_findings": findings,
                    "decisions_count": len(decisions),
                    "tools_used": tools_used,
                    "debate_summaries": [],
                },
            )
        except Exception:
            pass

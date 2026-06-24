"""InvestorAgent — LLM-driven agent loop for A-share investment decisions.

Architecture: "The model is the agent. The code is the harness."

The LLM autonomously decides which tools to call, when to stop,
and what decisions to make. The harness provides tools, context,
and delivery infrastructure.

Flow:
    Celery beat (key market times)
      → run_session(session_type)
        → Build system prompt (portfolio + regime)
        → AgentLoop.run(messages, tools) ← LLM drives the loop
          ↳ LLM calls tools, gets results, reasons, repeats
        → Parse decisions from final response
        → Push to MessageStore + Redis (Discord)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
_CST = ZoneInfo("Asia/Shanghai")


# ---------------------------------------------------------------------------
# Session directives — goals only, LLM decides which tools to use
# ---------------------------------------------------------------------------

_SESSION_DIRECTIVES: dict[str, dict[str, str]] = {
    "pre_market": {
        "time": "08:00",
        "name": "盘前策略",
        "directive": (
            "现在是盘前分析时间(08:00)。隔夜美股已收盘。\n\n"
            "分析步骤:\n"
            "1. 调用 get_global_markets 获取美股/港股/大宗商品/汇率隔夜数据\n"
            "2. 如果美股主要指数涨跌>1%，调用 search_intel 查找原因\n"
            "3. 调用 get_overnight_transmission 获取隔夜传导评分\n"
            "   根据传导评分判断A股哪些板块可能受益/承压\n"
            "4. 调用 get_opportunity_candidates 查看昨日全市场扫描结果\n"
            "5. 检查当前持仓的隔夜风险\n\n"
            "如果需要跨市场分析方法论，调用 load_skill('overnight_analysis')。\n\n"
            "输出: 隔夜摘要(数据+原因) + 传导分析(受益/承压板块) + 今日策略 + 候选调整"
        ),
    },
    "call_auction": {
        "time": "09:15",
        "name": "集合竞价",
        "directive": (
            "集合竞价时间(09:15-09:25)。\n"
            "检查持仓股竞价情况，判断开盘方向。\n"
            "如果持仓股大幅低开(>3%)，给出预警。\n"
            "一切正常则不需要输出决策。"
        ),
    },
    "market_open": {
        "time": "09:30",
        "name": "开盘观察",
        "directive": (
            "市场刚开盘(09:30)。\n"
            "检查持仓安全，评估大盘状况。\n"
            "持仓安全 > 新机会。如果有风险立即给出卖出建议。"
        ),
    },
    "morning_check": {
        "time": "10:30",
        "name": "早盘检查",
        "directive": (
            "早盘已过1小时(10:30)。\n"
            "检查持仓盈亏和走势，扫描板块异动。\n"
            "只在有明确机会或风险时输出。\n\n"
            "盘中工具：用get_intraday_fund_flow_timeline看资金流趋势，"
            "用get_intraday_patterns看异动模式。先用轻量工具再决定是否deep_analyze。"
        ),
    },
    "midday": {
        "time": "11:35",
        "name": "午间总结",
        "directive": ("上午收盘(11:35)。\n简洁总结上午表现，重点规划下午策略。"),
    },
    "afternoon": {
        "time": "13:30",
        "name": "午后扫描",
        "directive": (
            "下午开盘30分钟(13:30)。\n"
            "1. 先调用 get_opportunity_candidates 查看今日全市场扫描结果\n"
            "2. 从中挑选1-2个最佳标的做深度分析(用deep_analyze)\n"
            "3. 检查持仓股资金流是否反转(get_intraday_fund_flow_timeline)\n"
            "4. 用get_minute_bars看分时量价关系\n\n"
            "为14:30尾盘决策准备好候选标的。"
        ),
    },
    "late_session": {
        "time": "14:30",
        "name": "尾盘决策",
        "directive": (
            "14:30，尾盘买入窗口开启！这是今天最重要的决策时刻。\n\n"
            "做出最终决策：买什么？买多少？什么价位？\n"
            "对持仓做评估：明天继续持有还是准备卖出？\n\n"
            "决策流程:\n"
            "1. 先调用 get_opportunity_candidates 查看今日发现的机会列表\n"
            "2. 对最有潜力的候选调用 get_intraday_fund_flow_timeline + get_intraday_patterns\n"
            "3. 对持仓检查 get_dragon_tiger + get_support_resistance\n"
            "4. 综合判断，给出明确买卖建议(含价格/数量/止损)\n\n"
            "如果有好机会，必须给出明确的买入建议。\n"
            "如果没有好机会，说清楚为什么，不要勉强推荐。\n"
            "记住：T+1规则，今天买入明天才能卖。评估隔夜风险。"
        ),
    },
    "market_scan": {
        "time": "10:00,13:00",
        "name": "全市场扫描",
        "directive": (
            "全市场机会扫描时间。你的任务是发现新的投资机会。\n\n"
            "必做步骤:\n"
            "1. 调用 get_opportunity_candidates 获取市场扫描器发现的候选标的\n"
            "2. 调用 get_concept_heat 查看当前最热概念板块\n"
            "3. 调用 get_consecutive_board_rate 查看连板晋级率\n"
            "4. 调用 get_trending_news 了解市场热点\n\n"
            "从中筛选出3-5个最值得关注的机会，说清楚:\n"
            "- 为什么这个板块/个股值得关注\n"
            "- 龙头评分多少，什么维度突出\n"
            "- 当前情绪周期是否支持参与\n"
            "- 风险点是什么\n\n"
            "如果需要选股方法论指导，调用 load_skill('stock_selection')。"
        ),
    },
    "opportunity_research": {
        "time": "intraday",
        "name": "机会深研",
        "directive": "",  # Dynamically built per candidate
    },
    "event_triggered": {
        "time": "intraday",
        "name": "事件触发",
        "directive": "",  # Dynamically built per event
    },
    "close": {
        "time": "15:05",
        "name": "收盘总结",
        "directive": (
            "市场收盘(15:05)。\n"
            "查看最终持仓盈亏，回顾今天操作。\n"
            "用大白话输出收盘总结，包括具体盈亏数字和明天计划。"
        ),
    },
}

# Session type → LLM caller for model routing (config/llm.yaml)
_CALLER_MAP = {
    "pre_market": "trading_advisor",
    "call_auction": "trading_advisor",
    "market_open": "trading_advisor",
    "morning_check": "trading_advisor",
    "midday": "review_agent",
    "afternoon": "trading_advisor",
    "late_session": "final_decision",
    "close": "review_agent",
    "market_scan": "trading_advisor",
    "opportunity_research": "trading_advisor",
    "event_triggered": "trading_advisor",
}


# ---------------------------------------------------------------------------
# System prompt — the agent's identity and operating rules
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
你是一个专业的A股投资总监，负责管理一个实盘投资组合。

重要：你不是辅助工具——你就是投资团队本身。你的分析直接驱动真金白银的交易决策。

## 当前持仓

{portfolio_section}

## 可用资金

{cash_section}

{regime_section}\

## 工作方式

你有大量工具可以获取实时市场数据。自主决定需要调用哪些工具来完成分析。
不要猜测数据——用工具获取真实数据后再做判断。

## 输出规则

1. **说人话**：用户是不懂金融的散户。用大白话解释。
2. **有结论**：每条消息必须有明确结论（买/卖/持有/观望），不要含糊其辞。
3. **有依据**：结论必须基于你从工具获取的真实数据，不能凭空推测。
4. **有操作**：如果建议买入，必须给出：股票代码、价位、数量、止损、目标价。
5. **有风险**：必须说明主要风险是什么。
6. **够简洁**：没有重要发现就说"目前正常，无需操作"。

## 买入建议格式

当你建议买入时，必须包含：
- 股票名称和代码
- 建议买入价位（一个区间）
- 建议买入数量（具体股数，必须是100的整数倍）
- 止损价位（具体价格，不是百分比）
- 目标价位
- 预计持有天数
- 买入理由（2-3句话）
- 主要风险（1-2句话）

## A股规则

- T+1：今天买的股票，明天才能卖
- 涨跌停：主板±10%，创业板/科创板±20%
- 最小单位：100股（1手）
- 交易时间：09:30-11:30, 13:00-15:00
- 最佳买入时段：14:30-15:00（尾盘）
- 最佳卖出时段：09:30-10:00（早盘）

## 分析结束后

在分析的最后，输出结构化的决策JSON（如果有决策的话）：

```json
{{
  "decisions": [
    {{
      "type": "buy_signal/sell_signal/risk_alert/hold_update/market_insight",
      "action": "buy/sell/add/reduce/hold",
      "symbol": "600498",
      "name": "烽火通信",
      "shares": 200,
      "entry_price": 47.20,
      "stop_loss": 45.50,
      "target_price": 50.00,
      "hold_days": 3,
      "confidence": 0.75,
      "priority": "critical/high/medium/low",
      "summary": "用大白话说清楚为什么（2-3句话）",
      "risk_note": "主要风险提示"
    }}
  ],
  "no_action_reason": "如果没有任何决策，解释为什么"
}}
```

规则:
- buy/sell 类型必须填写 shares, entry_price, stop_loss, target_price
- shares 必须是100的整数倍
- stop_loss < entry_price（买入时）, stop_loss > entry_price（卖出时）
- hold_update/market_insight 类型不需要价格字段
- 买入前建议先调用 run_decision_pipeline 工具验证
"""


class InvestorAgent:
    """LLM-driven agent loop for investment decisions.

    The model IS the agent. This class is just the harness:
    provide tools → AgentLoop.run() → parse decisions → deliver to user.

    Uses caller-based routing: each session type maps to the appropriate
    model via config/llm.yaml caller_model_map.
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
        bridge_url: str = "http://127.0.0.1:19821",
    ) -> None:
        self._gateway = gateway
        self._tool_registry = tool_registry
        self._portfolio = portfolio_store
        self._capital = capital_service
        self._message_store = message_store
        self._quote_manager = quote_manager
        self._global_market = global_market_fetcher
        self._bridge_url = bridge_url
        self._timeout = 300

        # Session memory for cross-session context
        try:
            from src.agent_loop.session_memory import SessionMemory

            self._memory = SessionMemory()
        except Exception:
            self._memory = None

        # Create the agent loop if tools are available
        self._agent_loop = None
        if tool_registry and gateway:
            from src.agent_loop.llm_agent import AgentLoop

            self._agent_loop = AgentLoop(
                gateway=gateway,
                tool_executor=tool_registry.execute,
                tool_definitions=tool_registry.get_tool_definitions(),
                max_turns=10,
            )

    async def run_session(
        self,
        session_type: str,
        *,
        symbol: str | None = None,
        event_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one agent session at a key market time or on event trigger.

        The LLM drives the loop — it decides which tools to call
        and when it has enough information to make decisions.

        Args:
            session_type: Session type (e.g. "late_session", "event_triggered").
            symbol: Target symbol for event-triggered sessions.
            event_data: Event dict with z_score, price, change_pct, etc.
        """
        session = _SESSION_DIRECTIVES.get(session_type)
        if not session:
            return {"error": f"Unknown session type: {session_type}"}

        logger.info(
            "=== InvestorAgent [%s] %s START ===",
            session_type,
            session["name"],
        )

        try:
            # 1. Build system prompt with portfolio + regime context
            system_prompt = self._build_system_prompt()

            # 2. Build the user message (session directive)
            if session_type == "event_triggered" and symbol and event_data:
                directive = self._build_event_directive(symbol, event_data)
            elif session_type == "opportunity_research" and event_data:
                directive = self._build_opportunity_research_directive(event_data)
            else:
                directive = session["directive"]

            # 3. Load session memory for cross-session context
            memory_context = ""
            if self._memory:
                from src.agent_loop.session_memory import SessionMemory

                prev_sessions = self._memory.load_context()
                memory_context = SessionMemory.format_for_prompt(prev_sessions)

            # 4. Run agent loop — LLM decides which tools to call
            from src.llm.base import LLMMessage

            user_content = directive
            if memory_context:
                user_content = memory_context + "\n---\n\n" + directive

            messages = [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_content),
            ]

            caller = _CALLER_MAP.get(session_type, "trading_advisor")

            if self._agent_loop:
                # Event-triggered: use constrained mini loop (3 turns, $0.02)
                if session_type == "event_triggered":
                    from src.agent_loop.llm_agent import AgentLoop

                    mini_loop = AgentLoop(
                        gateway=self._gateway,
                        tool_executor=self._tool_registry.execute,
                        tool_definitions=self._tool_registry.get_tool_definitions(),
                        max_turns=3,
                        max_cost_usd=0.02,
                    )
                    result = await mini_loop.run(
                        messages,
                        caller=caller,
                        max_tokens=2048,
                        temperature=0.2,
                        symbol=symbol or "",
                    )
                else:
                    result = await self._agent_loop.run(
                        messages,
                        caller=caller,
                        max_tokens=4096,
                        temperature=0.3,
                    )
                response_text = result.text or ""
                logger.info(
                    "Agent loop: session=%s turns=%d tools=%d $%.4f",
                    session_type,
                    result.turns,
                    result.tool_calls_made,
                    result.total_cost_usd,
                )
            else:
                # Fallback: single LLM call without tools
                response_text = await self._call_llm_fallback(
                    system_prompt, directive, caller
                )

            if not response_text:
                logger.error("LLM returned empty response for %s", session_type)
                return {"error": "empty_response", "session": session_type}

            # 4. Parse decisions from response
            decisions = self._parse_decisions(response_text)

            # 5. Push decisions to MessageStore + Discord
            pushed = await self._push_decisions(decisions, session_type)

            # 6. If no explicit decisions but response has content,
            #    push the whole response as a session briefing
            if not decisions and response_text.strip():
                await self._push_briefing(response_text, session_type, session)

            # 7. Save session transcript for cross-session memory
            if self._memory:
                self._memory.save_transcript(
                    session_type,
                    {
                        "decisions_count": len(decisions),
                        "tools_used": getattr(result, "tool_calls_made", 0)
                        if self._agent_loop
                        else 0,
                        "key_findings": response_text[:300],
                    },
                )

            logger.info(
                "=== InvestorAgent [%s] END — %d decisions, %d pushed ===",
                session_type,
                len(decisions),
                pushed,
            )

            return {
                "session": session_type,
                "decisions": len(decisions),
                "pushed": pushed,
                "response_length": len(response_text),
            }

        except Exception as exc:
            logger.error(
                "InvestorAgent [%s] failed: %s", session_type, exc, exc_info=True
            )
            return {"error": str(exc), "session": session_type}

    def _build_system_prompt(self) -> str:
        """Build system prompt with portfolio state and market regime."""
        # Portfolio
        portfolio_section = "无持仓"
        if self._portfolio:
            try:
                positions = self._portfolio.list_positions()
                if positions:
                    lines = []
                    for p in positions:
                        shares = int(p.get("shares", 0))
                        if shares <= 0:
                            continue
                        name = p.get("name", p.get("symbol", ""))
                        symbol = p.get("symbol", "")
                        cost = p.get("cost_price", 0)
                        buy_date = p.get("buy_date", "")
                        today_bought = int(p.get("today_bought", 0))
                        available = shares - today_bought
                        lines.append(
                            f"- {name}({symbol}): {shares}股, 成本{cost}元, "
                            f"买入日期{buy_date}, "
                            f"今天可卖{available}股"
                        )
                    if lines:
                        portfolio_section = "\n".join(lines)
                    else:
                        portfolio_section = "无持仓（所有仓位已清空）"
            except Exception as exc:
                logger.warning("Failed to get portfolio: %s", exc)
                portfolio_section = "持仓数据获取失败，请用工具查询"

        # Cash
        cash_section = "未知（请用工具查询）"
        if self._capital:
            try:
                bal = self._capital.get_balance()
                if isinstance(bal, (int, float)):
                    cash_section = f"¥{bal:,.2f}"
                elif hasattr(bal, "available_cash"):
                    cash_section = f"¥{bal.available_cash:,.2f}"
            except Exception:
                pass

        # Regime context from SharedBeliefState
        regime_section = self._get_regime_section()

        return _SYSTEM_PROMPT_TEMPLATE.format(
            portfolio_section=portfolio_section,
            cash_section=cash_section,
            regime_section=regime_section,
        )

    def _get_regime_section(self) -> str:
        """Get current market regime from SharedBeliefState."""
        try:
            from src.agent_loop.shared_belief_state import SharedBeliefState

            state = SharedBeliefState()
            data = state.to_dict()
            if not data:
                return ""

            regime = data.get("regime", {})
            risk = data.get("risk_budget", {})
            cash_strategy = data.get("cash_strategy", {})

            lines = ["## 市场状态\n"]

            sentiment = regime.get("sentiment_phase", "unknown")
            phase_names = {
                "freezing": "冰点期(极度保守)",
                "ignition": "启动期(开始建仓)",
                "acceleration": "加速期(积极操作)",
                "climax": "高潮期(开始减仓)",
                "ebb": "退潮期(全面防守)",
            }
            phase_cn = phase_names.get(sentiment, sentiment)
            lines.append(f"- 情绪阶段: {phase_cn}")

            hmm = regime.get("hmm_state", "unknown")
            if hmm != "unknown":
                lines.append(f"- HMM状态: {hmm}")

            daily_loss = risk.get("daily_loss_pct", 0)
            limit = risk.get("daily_limit_pct", 3.0)
            remaining = limit - abs(daily_loss)
            lines.append(f"- 风险预算: 剩余{remaining:.1f}% (日限{limit:.1f}%)")

            if risk.get("halt"):
                lines.append("- ⚠️ 风控暂停: 已触发止损，暂停新买入")

            target_cash = cash_strategy.get("target_pct")
            if target_cash is not None:
                lines.append(f"- 目标现金比例: {target_cash:.0f}%")

            return "\n".join(lines) + "\n"

        except Exception:
            return ""

    async def _call_llm_fallback(
        self, system_prompt: str, message: str, caller: str
    ) -> str:
        """Fallback: single LLM call without tools (if no ToolRegistry)."""
        import asyncio

        if not self._gateway:
            logger.error("No LLM gateway configured")
            return ""

        from src.llm.base import LLMMessage

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=message),
        ]

        try:
            response = await asyncio.to_thread(
                self._gateway.complete,
                messages=messages,
                caller=caller,
                max_tokens=4096,
                temperature=0.3,
            )
            return response.text or ""
        except Exception as exc:
            logger.error("LLM fallback call failed: %s", exc)
            return ""

    def _parse_decisions(self, response_text: str) -> list[dict[str, Any]]:
        """Extract structured decisions from LLM response.

        Looks for JSON blocks with a "decisions" key.
        """
        # Try to find JSON block in the response
        json_pattern = re.compile(r"```json\s*\n?(.*?)\n?\s*```", re.DOTALL)
        matches = json_pattern.findall(response_text)

        for match in matches:
            try:
                parsed = json.loads(match)
                if isinstance(parsed, dict) and "decisions" in parsed:
                    decisions = parsed["decisions"]
                    if isinstance(decisions, list):
                        return [d for d in decisions if isinstance(d, dict)]
            except (json.JSONDecodeError, TypeError):
                continue

        # Also try to find bare JSON object with decisions key
        try:
            brace_start = response_text.rfind('{"decisions"')
            if brace_start == -1:
                brace_start = response_text.rfind('"decisions"')
                if brace_start != -1:
                    brace_start = response_text.rfind("{", 0, brace_start)

            if brace_start != -1:
                depth = 0
                for i in range(brace_start, len(response_text)):
                    if response_text[i] == "{":
                        depth += 1
                    elif response_text[i] == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = response_text[brace_start : i + 1]
                            parsed = json.loads(candidate)
                            if isinstance(parsed, dict) and "decisions" in parsed:
                                decisions = parsed["decisions"]
                                if isinstance(decisions, list):
                                    return [d for d in decisions if isinstance(d, dict)]
                            break
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        return []

    async def _push_decisions(
        self, decisions: list[dict[str, Any]], session_type: str
    ) -> int:
        """Route decisions to MessageStore + Redis for Discord."""
        if not decisions or not self._message_store:
            return 0

        pushed = 0
        for decision in decisions:
            try:
                msg_type = decision.get("type", "market_insight")
                symbol = decision.get("symbol")
                name = decision.get("name", symbol or "")
                title = decision.get("title", "")
                summary = decision.get("summary", "")
                risk_note = decision.get("risk_note", "")
                confidence = decision.get("confidence", 0.5)
                priority = decision.get("priority", "medium")
                action = decision.get("action", "")

                if not title and not summary:
                    continue

                # Skip hold/insight messages with no actual analysis content
                if action == "hold" and not summary and not risk_note:
                    logger.debug("Skipping empty hold decision for %s", symbol)
                    continue

                # Build structured trade instruction if available
                trade_data: dict[str, Any] | None = None
                action_advice = ""
                if action in ("buy", "sell", "add", "reduce"):
                    shares = int(decision.get("shares", 0))
                    shares = (shares // 100) * 100
                    entry_price = decision.get("entry_price")
                    stop_loss = decision.get("stop_loss")
                    target_price = decision.get("target_price")

                    if shares > 0 and entry_price:
                        trade_data = {
                            "action": action,
                            "symbol": symbol,
                            "name": name,
                            "shares": shares,
                            "entry_price": entry_price,
                            "stop_loss": stop_loss,
                            "target_price": target_price,
                            "confidence": confidence,
                            "hold_days": decision.get("hold_days"),
                        }
                        action_advice = (
                            f"{action} {shares}股 @{entry_price}"
                            f" 止损{stop_loss or '?'}"
                            f" 目标{target_price or '?'}"
                        )
                    else:
                        action_advice = decision.get("action_advice", summary)
                else:
                    action_advice = decision.get("action_advice", summary)

                # Auto-generate title if missing
                if not title and action and symbol:
                    action_labels = {
                        "buy": "建议买入",
                        "sell": "建议卖出",
                        "add": "建议加仓",
                        "reduce": "建议减仓",
                        "hold": "继续持有",
                    }
                    title = f"{action_labels.get(action, action)} {name}"

                now = datetime.now(UTC)
                # Use trading_signal type for executable instructions
                store_type = "trading_signal" if trade_data else msg_type

                msg_id = self._message_store.create_message(
                    symbol=symbol,
                    msg_type=store_type,
                    title=title,
                    summary=summary,
                    content=summary,
                    priority=priority,
                    action_advice=action_advice,
                    risk_note=risk_note,
                    stock_recommendations=(
                        json.dumps([trade_data], ensure_ascii=False)
                        if trade_data
                        else None
                    ),
                    raw_data_ref={
                        "source": "investor_agent",
                        "session": session_type,
                        "confidence": confidence,
                        "action": action,
                    },
                    data_freshness="realtime",
                    data_collected_at=now.isoformat(),
                )

                redis_payload = {
                    "type": store_type,
                    "symbol": symbol or "",
                    "name": name,
                    "title": title,
                    "summary": summary,
                    "priority": priority,
                    "action_advice": action_advice,
                    "risk_note": risk_note,
                    "confidence": confidence,
                    "message_id": msg_id,
                }
                if trade_data:
                    redis_payload.update(trade_data)
                self._publish_to_redis(redis_payload)

                pushed += 1
                logger.info(
                    "Pushed decision: [%s] %s for %s (confidence=%.2f)",
                    msg_type,
                    title[:40],
                    symbol or "N/A",
                    confidence,
                )

            except Exception as exc:
                logger.error("Failed to push decision: %s", exc, exc_info=True)

        return pushed

    async def _push_briefing(
        self,
        response_text: str,
        session_type: str,
        session: dict[str, str],
    ) -> None:
        """Push the agent's full response as a session briefing."""
        if not self._message_store:
            return

        type_map = {
            "pre_market": "pre_market",
            "call_auction": "call_auction",
            "market_open": "pre_market",
            "morning_check": "market_insight",
            "midday": "market_insight",
            "afternoon": "market_insight",
            "late_session": "late_session",
            "close": "post_market",
        }
        msg_type = type_map.get(session_type, "market_insight")

        summary = response_text[:2000] if len(response_text) > 2000 else response_text
        summary = re.sub(r"```json\s*\n?.*?\n?\s*```", "", summary, flags=re.DOTALL)
        summary = summary.strip()
        if not summary:
            return

        title = session["name"]
        now = datetime.now(UTC)

        msg_id = self._message_store.create_message(
            msg_type=msg_type,
            title=title,
            summary=summary[:500],
            content=summary,
            priority="medium",
            raw_data_ref={
                "source": "investor_agent",
                "session": session_type,
            },
            data_freshness="realtime",
            data_collected_at=now.isoformat(),
        )

        self._publish_to_redis(
            {
                "type": msg_type,
                "title": title,
                "summary": summary[:500],
                "priority": "medium",
                "message_id": msg_id,
            }
        )

        logger.info("Pushed briefing: [%s] %s", msg_type, title)

    @staticmethod
    def _build_opportunity_research_directive(candidate: dict[str, Any]) -> str:
        """Build a focused directive for deep-diving an opportunity candidate."""
        symbol = candidate.get("symbol", "")
        name = candidate.get("name", "")
        score = candidate.get("total_score", 0)
        reason = candidate.get("reason", "")
        sector = candidate.get("sector", "")

        return (
            f"## 机会深研: {name}({symbol})\n\n"
            f"市场扫描器评分: {score}分\n"
            f"板块: {sector}\n"
            f"初评: {reason}\n\n"
            f"请做深度分析:\n"
            f"1. deep_analyze {symbol} 获取全面数据\n"
            f"2. get_dragon_tiger {symbol} 查龙虎榜\n"
            f"3. get_intraday_patterns {symbol} 查日内走势\n"
            f"4. get_intraday_fund_flow_timeline {symbol} 查资金流\n\n"
            f"最终输出: 明确的买入建议(含价位/数量/止损) 或 明确的放弃理由。"
        )

    @staticmethod
    def _build_event_directive(symbol: str, event_data: dict[str, Any]) -> str:
        """Build a focused directive for event-triggered mini sessions."""
        event_type = event_data.get("type", "price_spike")
        z_score = event_data.get("z_score", 0)
        price = event_data.get("price", "?")
        change_pct = event_data.get("change_pct", event_data.get("return_pct", "?"))
        direction = event_data.get("direction", "unknown")
        name = event_data.get("name", symbol)

        return (
            f"## 事件触发: {name}({symbol}) {event_type}\n\n"
            f"异动: z_score={z_score:.1f} 价格={price} 涨跌={change_pct}% 方向={direction}\n\n"
            f"快速判断（限时30秒）:\n"
            f"1. 用 get_realtime_quote 查看最新行情\n"
            f"2. 用 get_intraday_fund_flow_timeline 查看资金流趋势\n"
            f"3. 做出决策: 买入（含价格数量止损）/ 卖出 / 持有 / 不操作\n\n"
            f"不要调用 deep_analyze。不要写长篇分析。\n"
            f"只输出结论和决策JSON。"
        )

    @staticmethod
    def _publish_to_redis(payload: dict[str, Any]) -> None:
        """Publish message to Redis for Discord AssistantPushCog."""
        try:
            import redis

            r = redis.Redis(host="redis", port=6379, db=0, decode_responses=True)
            r.publish("assistant:messages", json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            logger.warning("Redis publish failed: %s", exc)

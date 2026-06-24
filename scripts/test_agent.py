"""One-shot agent test — runs portfolio_watch mission with o4-mini."""
import asyncio
import json


async def run():
    from src.web.dependencies import (
        get_llm_gateway, get_tool_registry, get_portfolio_store,
        get_capital_service, get_realtime_quote_manager,
    )
    from src.web.services.message_store import MessageStore
    from src.agent_loop.heartbeat_agent import HeartbeatAgent, _MISSIONS
    from src.agent_loop.agent_state import AgentState
    from src.agent_loop.llm_agent import AgentLoop, LLMMessage
    from src.agent_loop.decision_handler import DecisionHandler
    from datetime import datetime
    from zoneinfo import ZoneInfo

    agent = HeartbeatAgent(
        gateway=get_llm_gateway(),
        tool_registry=get_tool_registry(),
        portfolio_store=get_portfolio_store(),
        capital_service=get_capital_service(),
        message_store=MessageStore(),
        quote_manager=get_realtime_quote_manager(),
    )

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    state = AgentState(date=now.strftime("%Y%m%d"))
    state.heartbeat_count = 5

    mission = _MISSIONS["portfolio_watch"]
    prompt = agent._build_system_prompt(now, state, mission)

    gateway = get_llm_gateway()
    registry = get_tool_registry()

    aloop = AgentLoop(
        gateway=gateway,
        tool_executor=registry.execute,
        tool_definitions=registry.get_tool_definitions(),
        max_turns=mission["max_turns"],
        max_cost_usd=mission["max_cost"],
    )
    result = await aloop.run(
        messages=[
            LLMMessage(role="system", content=prompt),
            LLMMessage(role="user", content=mission["mission"]),
        ],
        caller=mission.get("caller", "final_decision"),
    )

    text = result.text if result else ""
    decisions = DecisionHandler.parse_decisions(text)

    print("Model: {} | Cost: ${:.4f} | Tools: {} | Turns: {}".format(
        result.model, result.total_cost_usd, result.tool_call_count, result.turns))
    print("Decisions: {}".format(len(decisions)))

    for d in decisions:
        sym = d.get("symbol", "?")
        name = d.get("name", "")
        action = d.get("action", "?").upper()
        conf = d.get("confidence", 0)
        sl = d.get("stop_loss")
        tp = d.get("target_price")
        summary = d.get("summary", "")
        risk = d.get("risk_note", "")
        src = d.get("_source", "json")

        print()
        print("=" * 55)
        print("{} ({}) | {} | conf={:.0%} [{}]".format(name, sym, action, conf, src))
        if sl:
            print("  STOP-LOSS: {}".format(sl))
        if tp:
            print("  TARGET: {}".format(tp))
        print("  {}".format(summary[:300]))
        if risk:
            print("  RISK: {}".format(risk[:200]))

    if not decisions:
        print()
        print("=== NO JSON DECISIONS ===")
        print("LLM output tail (last 800 chars):")
        print(text[-800:])


asyncio.run(run())

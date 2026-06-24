"""Deep regression test — 3 heartbeats + full chain audit."""

import asyncio
import json
import re
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

_CST = ZoneInfo("Asia/Shanghai")


async def main():
    from openclaw.daemon.always_on_agent import _get_heartbeat_agent
    from src.agent_loop import llm_agent
    from src.agent_loop.decision_handler import DecisionHandler

    agent = _get_heartbeat_agent()

    # Intercept AgentLoop.run to capture tool history + response
    all_runs: list[dict] = []
    original_run = llm_agent.AgentLoop.run

    async def capture_run(self_loop, *a, **kw):
        result = await original_run(self_loop, *a, **kw)
        run = {
            "response": result.text if result else "",
            "model": str(result.model) if result else "",
            "tools": [],
        }
        if hasattr(result, "tool_history") and result.tool_history:
            for name, _inp, out in result.tool_history:
                out_str = str(out) if out else ""
                run["tools"].append(
                    {
                        "name": name,
                        "len": len(out_str),
                        "err": "error" in out_str.lower()[:500],
                        "sample": out_str[:200],
                    }
                )
        all_runs.append(run)
        return result

    llm_agent.AgentLoop.run = capture_run

    # Intercept prompt builder
    prompts: list[dict] = []
    orig_build = agent._build_system_prompt

    def capture_prompt(now, state, mission):
        p = orig_build(now, state, mission)
        prompts.append({"mission": mission.get("name", ""), "len": len(p), "text": p})
        return p

    agent._build_system_prompt = capture_prompt

    # === Run 3 heartbeats ===
    results = []
    for i in range(3):
        print(f"Running heartbeat #{i + 1}...", end="", flush=True)
        r = await agent.run_heartbeat()
        results.append(r)
        print(
            f" {r.get('mission')} tools={r.get('tools_used')} "
            f"decisions={r.get('decisions')} pushed={r.get('pushed')} "
            f"${r.get('cost',0):.4f} {r.get('duration_seconds')}s"
        )

    llm_agent.AgentLoop.run = original_run
    print("\n" + "=" * 70)
    print("DEEP REGRESSION REPORT")
    print("=" * 70)

    # [A] TOOL HEALTH
    print("\n[A] TOOL HEALTH")
    ts: dict[str, dict] = {}
    for run in all_runs:
        for t in run["tools"]:
            n = t["name"]
            if n not in ts:
                ts[n] = {"c": 0, "e": 0, "tl": 0, "em": []}
            ts[n]["c"] += 1
            if t["err"]:
                ts[n]["e"] += 1
                ts[n]["em"].append(t["sample"][:80])
            ts[n]["tl"] += t["len"]

    for n, s in sorted(ts.items(), key=lambda x: -x[1]["e"]):
        ep = s["e"] / s["c"] * 100
        al = s["tl"] // max(s["c"], 1)
        m = "❌" if ep > 50 else ("⚠️" if ep > 0 else "✅")
        print(f"  {m} {n:35s} {s['c']}x err={ep:.0f}% avg={al}ch")
        if s["em"]:
            print(f"     {s['em'][0]}")

    # [B] PROMPT QUALITY
    print("\n[B] PROMPTS")
    for p in prompts:
        c = p["text"]
        idx = c.find("¥")
        cash_ok = idx >= 0 and "未知" not in c[idx : idx + 20]
        jl = c.count('{"decisions"')
        print(
            f"  {p['mission']:12s} {p['len']:5d}ch "
            f"cash={'✅' if cash_ok else '❌'} json_leaks={jl}"
        )

    # [C] DECISIONS
    print("\n[C] DECISIONS")
    all_d: list[dict] = []
    for i, run in enumerate(all_runs):
        decs = DecisionHandler.parse_decisions(run["response"])
        jp = run["response"].find('{"decisions"')
        if jp < 0:
            jp = run["response"].find("```json")
        txt = run["response"][:jp].strip() if jp > 0 else ""
        print(
            f"  Run #{i+1}: {len(run['response'])}ch "
            f"analysis={len(txt)}ch {len(decs)} decisions"
        )
        for d in decs:
            sym = d.get("symbol", "")
            act = d.get("action", "")
            conf = d.get("confidence", 0)
            sl = d.get("stop_loss")
            tp = d.get("target_price")
            sh = d.get("shares")
            summary = d.get("summary", "")
            vsym = bool(re.fullmatch(r"\d{6}", sym))

            issues = []
            if not vsym and act not in ("no_trade", "watch"):
                issues.append("BAD_SYM")
            if act in ("buy", "add") and not d.get("entry_price"):
                issues.append("NO_ENTRY")
            if act in ("buy", "add", "hold") and not sl:
                issues.append("NO_SL")
            if act in ("buy", "add") and not sh:
                issues.append("NO_SHARES")
            if not summary or len(summary) < 10:
                issues.append("THIN")

            mk = "❌ " + ",".join(issues) if issues else "✅"
            print(f"    {mk} {act:8s} {sym:6s} conf={conf:.0%} sl={sl} tp={tp} sh={sh}")
            print(f"      {summary[:100]}")
            all_d.append(d)

    # [D] PIPELINE
    print("\n[D] PIPELINE")
    conn = sqlite3.connect("data/decisions.db")
    tot = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    rec = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE decided_at >= datetime('now','-1 day')"
    ).fetchone()[0]
    conn.close()
    print(f"  decisions.db: {tot} total, {rec} last 24h")

    try:
        c2 = sqlite3.connect("data/outcome_tracker.db")
        ot = c2.execute("SELECT COUNT(*) FROM tracked_signals").fetchone()[0]
        print(f"  outcome_tracker: {ot} tracked")
        c2.close()
    except Exception:
        print("  outcome_tracker: unavailable")

    from src.agent_loop.session_memory import SessionMemory
    from src.web.dependencies import get_redis

    redis = get_redis()
    sm = SessionMemory(redis_client=redis)
    sessions = sm.load_context()
    clean = sum(
        1
        for s in sessions[:5]
        if not s.get("key_findings", "").startswith("{")
    )
    print(f"  session_memory: {len(sessions)} entries, {clean}/5 clean")

    from src.web.services.message_store import MessageStore

    ms = MessageStore()
    msgs, total_msgs = ms.list_messages(per_page=5)
    jm = sum(1 for m in msgs if '{"decisions"' in (m.get("summary") or ""))
    print(f"  message_store: {total_msgs} total, {jm} with JSON leak in top 5")

    # [E] STATE
    print("\n[E] STATE")
    from src.agent_loop.agent_state import AgentState

    state = AgentState.load(redis, datetime.now(_CST).strftime("%Y%m%d"))
    print(
        f"  heartbeats={state.heartbeat_count} decisions={len(state.decisions)} "
        f"missions={state.executed_missions}"
    )
    cash_ctx = any("CASH" in c for c in state.rolling_context)
    print(f"  rolling_context: {len(state.rolling_context)} CASH={'⚠️' if cash_ctx else '✅ none'}")

    # [F] PORTFOLIO
    print("\n[F] PORTFOLIO")
    from src.web.dependencies import get_capital_service, get_portfolio_store

    ps = get_portfolio_store()
    cs = get_capital_service()
    for p in ps.list_positions():
        print(f"  {p.get('name')}({p.get('symbol')}) {p.get('shares')}股 cost={p.get('cost_price')}")
    print(f"  Cash: ¥{cs.get_balance():,.2f}")

    # [G] RISK GATE
    print("\n[G] RISK GATE")
    huge = DecisionHandler._hard_risk_check(
        {"symbol": "002688", "shares": 100000, "entry_price": 6.14}
    )
    print(f"  100K shares: {'✅ VETOED: '+huge if huge else '❌ NOT VETOED'}")
    normal = DecisionHandler._hard_risk_check(
        {"symbol": "601857", "shares": 300, "entry_price": 12.5}
    )
    print(f"  300 shares:  {'✅ passed' if not normal else '⚠️ '+normal}")

    # [H] SUMMARY
    print("\n" + "=" * 70)
    print("[H] SUMMARY")
    t_tools = sum(r.get("tools_used", 0) for r in results)
    t_dec = sum(r.get("decisions", 0) for r in results)
    t_push = sum(r.get("pushed", 0) for r in results)
    t_cost = sum(r.get("cost", 0) for r in results)
    t_errs = sum(1 for s in ts.values() if s["e"] > 0)
    bad = sum(
        1
        for d in all_d
        if not re.fullmatch(r"\d{6}", d.get("symbol", ""))
        and d.get("action") not in ("no_trade", "watch")
    )
    safe = "execute_trade" not in [t["name"] for r in all_runs for t in r["tools"]]
    print(f"  3 heartbeats: {t_tools} tools, {t_dec} decisions, {t_push} pushed, ${t_cost:.4f}")
    print(f"  Tool errors: {t_errs}/{len(ts)} tools had errors")
    print(f"  Bad decisions: {bad}/{len(all_d)}")
    print(f"  execute_trade: {'✅ NEVER called' if safe else '🚨 WAS CALLED!'}")


if __name__ == "__main__":
    asyncio.run(main())

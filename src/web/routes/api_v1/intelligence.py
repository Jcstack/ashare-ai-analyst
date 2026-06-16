"""Intelligence agent endpoints — impact chains, macro profiles, rotation, debate.

Mounted under ``/intelligence``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from src.utils.logger import get_logger
from src.web.dependencies import (
    get_black_swan_detector,
    get_competitor_benchmark,
    get_debate_engine,
    get_impact_chain_engine,
    get_macro_calendar_fetcher,
    get_munger_checklist,
    get_portfolio_store,
    get_position_macro_mapper,
    get_qlib_alpha_engine,
    get_qlib_portfolio_optimizer,
    get_relevance_scorer,
    get_rotation_engine,
    get_trading_constraints_engine,
)

logger = get_logger(__name__)

router = APIRouter(tags=["intelligence"])


@router.post("/impact-chain")
async def analyze_impact_chain(
    body: dict[str, Any],
    engine=Depends(get_impact_chain_engine),
) -> dict[str, Any]:
    """Analyze event impact chain transmission paths."""
    event_text = body.get("event_text", "")
    if not event_text:
        return {"error": "event_text is required", "chains": []}

    chains = engine.build_chains_for_event(event_text)
    if not chains:
        return {"event": event_text, "chains": [], "message": "未匹配到影响链模板"}
    return {
        "event": event_text,
        "chains": [c.to_dict() for c in chains],
        "affected_sectors": chains[0].all_affected_sectors if chains else [],
    }


@router.post("/position-macro")
async def analyze_position_macro(
    body: dict[str, Any],
    mapper=Depends(get_position_macro_mapper),
) -> dict[str, Any]:
    """Analyze position macro sensitivity and rotation signal."""
    from src.intelligence.position_macro_mapper import MacroEnvironment

    symbol = body.get("symbol", "")
    if not symbol:
        return {"error": "symbol is required"}

    name = body.get("name", "")
    macro_data = body.get("macro", {})
    env = MacroEnvironment(**macro_data) if macro_data else MacroEnvironment()

    profile = mapper.analyze_position(symbol, name, env)
    return profile.to_dict()


@router.post("/portfolio-macro")
async def analyze_portfolio_macro(
    body: dict[str, Any],
    mapper=Depends(get_position_macro_mapper),
) -> dict[str, Any]:
    """Analyze full portfolio macro exposure."""
    from src.intelligence.position_macro_mapper import MacroEnvironment

    positions = body.get("positions", [])
    if not positions:
        return {"error": "positions list is required"}

    macro_data = body.get("macro", {})
    env = MacroEnvironment(**macro_data) if macro_data else MacroEnvironment()

    result = mapper.analyze_portfolio(positions, env)
    return {
        "profiles": [p.to_dict() for p in result],
        "count": len(result),
    }


@router.post("/rotation-scan")
async def scan_rotation(
    body: dict[str, Any],
    engine=Depends(get_rotation_engine),
    store=Depends(get_portfolio_store),
) -> dict[str, Any]:
    """Scan portfolio for rotation opportunities."""
    from src.intelligence.position_macro_mapper import MacroEnvironment

    positions = body.get("positions", [])
    if not positions:
        try:
            data = store.get_portfolio_data()
            positions = [
                {"symbol": p["symbol"], "name": p.get("name", p["symbol"])}
                for p in data.get("positions", [])
            ]
        except Exception:
            return {"error": "无法读取持仓数据", "plans": []}

    if not positions:
        return {"message": "持仓为空，无需轮动分析", "plans": []}

    macro_data = body.get("macro", {})
    env = MacroEnvironment(**macro_data) if macro_data else MacroEnvironment()

    plans = engine.scan_portfolio(positions, env)
    return {
        "position_count": len(positions),
        "rotation_plans": [p.to_dict() for p in plans],
        "plans_count": len(plans),
    }


@router.post("/munger-checklist")
async def run_munger_checklist(
    body: dict[str, Any],
    checklist=Depends(get_munger_checklist),
) -> dict[str, Any]:
    """Run Munger mental model checklist on a stock."""
    symbol = body.get("symbol", "")
    if not symbol:
        return {"error": "symbol is required"}

    result = checklist.run_checklist(
        symbol=symbol,
        name=body.get("name", ""),
        current_price=body.get("current_price"),
        fair_value=body.get("fair_value"),
        recent_gain_pct=body.get("recent_gain_pct"),
        news_count_24h=body.get("news_count_24h", 0),
    )
    return result.to_dict()


@router.post("/debate")
async def run_debate(
    body: dict[str, Any],
    engine=Depends(get_debate_engine),
) -> dict[str, Any]:
    """Run bull/bear adversarial debate analysis."""
    symbol = body.get("symbol", "")
    if not symbol:
        return {"error": "symbol is required"}

    record = engine.run_debate(
        symbol=symbol,
        name=body.get("name", ""),
        trigger=body.get("trigger", "api request"),
        market_data=body.get("market_data", {}),
        checklist_result=body.get("checklist_result"),
    )
    return record.to_dict()


@router.post("/constraint-check")
async def check_constraints(
    body: dict[str, Any],
    engine=Depends(get_trading_constraints_engine),
) -> dict[str, Any]:
    """Check trading constraints for a stock."""
    symbol = body.get("symbol", "")
    if not symbol:
        return {"error": "symbol is required"}

    name = body.get("name", "")
    result = engine.check(symbol, name)
    return {
        "symbol": symbol,
        "name": name,
        "board": engine.get_board(symbol),
        "passed": result.passed,
        "blocked": result.blocked,
        "violations": [
            {"rule": v.rule, "severity": v.severity, "message": v.message}
            for v in result.violations
        ],
    }


@router.post("/black-swan-scan")
async def scan_black_swan(
    body: dict[str, Any],
    detector=Depends(get_black_swan_detector),
) -> dict[str, Any]:
    """Scan for black swan indicators."""
    alert = detector.scan(body)
    if alert is None:
        return {"alert_level": "NONE", "indicators": [], "message": "无异常信号"}
    return alert.to_dict()


@router.post("/relevance-score")
async def score_relevance(
    body: dict[str, Any],
    scorer=Depends(get_relevance_scorer),
    store=Depends(get_portfolio_store),
) -> dict[str, Any]:
    """Score relevance of intel items to portfolio holdings.

    Body can contain:
    - intel_item: single item to score against all positions
    - positions: optional override (otherwise loads from portfolio)
    - min_relevance: minimum score threshold (default 0.1)
    """
    intel_item = body.get("intel_item")
    if not intel_item:
        return {"error": "intel_item is required"}

    positions = body.get("positions")
    if not positions:
        try:
            data = store.get_portfolio_data()
            positions = [
                {"symbol": p["symbol"], "name": p.get("name", p["symbol"])}
                for p in data.get("positions", [])
            ]
        except Exception:
            return {"error": "无法读取持仓数据", "scores": []}

    if not positions:
        return {"message": "持仓为空", "scores": []}

    min_rel = body.get("min_relevance", 0.1)
    scores = scorer.score_portfolio(intel_item, positions, min_relevance=min_rel)
    return {
        "scores": [s.to_dict() for s in scores],
        "count": len(scores),
    }


@router.get("/equity-curve")
async def get_equity_curve(
    days: int = 90,
) -> dict[str, Any]:
    """Read portfolio equity curve from daily snapshots.

    Returns date-series of total value, cost, and unrealized PnL
    for charting the portfolio performance over time.
    """
    import sqlite3

    from src.utils.config import get_project_root

    db_path = get_project_root() / "data" / "portfolio_snapshots.db"
    if not db_path.exists():
        return {"snapshots": [], "message": "暂无快照数据"}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT date, total_value, total_cost, unrealized_pnl,
                  position_count
           FROM snapshots
           ORDER BY date DESC
           LIMIT ?""",
        (days,),
    ).fetchall()
    conn.close()

    snapshots = [
        {
            "date": r["date"],
            "total_value": r["total_value"],
            "total_cost": r["total_cost"],
            "unrealized_pnl": r["unrealized_pnl"],
            "position_count": r["position_count"],
        }
        for r in reversed(rows)
    ]
    return {"snapshots": snapshots, "count": len(snapshots)}


@router.get("/macro-calendar")
async def get_macro_calendar(
    n_latest: int = 3,
    fetcher=Depends(get_macro_calendar_fetcher),
) -> dict[str, Any]:
    """Fetch latest macro economic calendar data with surprise detection."""
    return fetcher.fetch_all(n_latest)


@router.get("/macro-lpr")
async def get_macro_lpr(
    fetcher=Depends(get_macro_calendar_fetcher),
) -> dict[str, Any]:
    """Fetch latest LPR (Loan Prime Rate) decisions."""
    releases = fetcher.fetch_lpr()
    return {"releases": releases, "count": len(releases)}


@router.get("/dashboard")
async def intelligence_dashboard(
    store=Depends(get_portfolio_store),
    mapper=Depends(get_position_macro_mapper),
    detector=Depends(get_black_swan_detector),
    constraints=Depends(get_trading_constraints_engine),
) -> dict[str, Any]:
    """CIO dashboard data — portfolio macro exposure + black swan status.

    Aggregates macro sensitivity for all holdings and returns a summary
    suitable for the frontend CIO dashboard.
    """
    from src.intelligence.position_macro_mapper import MacroEnvironment

    result: dict[str, Any] = {}

    # Portfolio macro profiles
    try:
        data = store.get_portfolio_data()
        positions = [
            {"symbol": p["symbol"], "name": p.get("name", p["symbol"])}
            for p in data.get("positions", [])
        ]
    except Exception:
        positions = []

    if positions:
        env = MacroEnvironment()
        profiles = mapper.analyze_portfolio(positions, env)
        exposure = mapper.portfolio_macro_exposure(positions)
        stressed = [p for p in profiles if p.rotation_signal in ("exit", "reduce")]

        result["portfolio"] = {
            "position_count": len(positions),
            "profiles": [p.to_dict() for p in profiles],
            "macro_exposure": exposure,
            "stressed_count": len(stressed),
            "stressed_symbols": [p.symbol for p in stressed],
        }
    else:
        result["portfolio"] = {"position_count": 0, "profiles": []}

    # Black swan status (no real data, just structure)
    result["black_swan"] = {"alert_level": "NONE", "message": "无异常信号"}

    # Constraint summary for positions
    if positions:
        blocked = []
        for pos in positions:
            check = constraints.check(pos["symbol"], pos.get("name", ""))
            if not check.passed:
                blocked.append(
                    {
                        "symbol": pos["symbol"],
                        "name": pos.get("name", ""),
                        "violations": [v.message for v in check.violations],
                    }
                )
        result["constraint_alerts"] = blocked

    return result


@router.post("/competitor-benchmark")
async def competitor_benchmark(
    body: dict[str, Any],
    bench=Depends(get_competitor_benchmark),
) -> dict[str, Any]:
    """Compare a stock against its sector peers.

    Body: ``{"symbol": "600519", "name": "贵州茅台", "current_price": 1800.0}``
    """
    symbol = body.get("symbol", "")
    if not symbol:
        return {"error": "symbol is required"}

    name = body.get("name", "")
    current_price = body.get("current_price")

    comparison = bench.compare(symbol, name, current_price=current_price)
    if comparison is None:
        return {
            "symbol": symbol,
            "name": name,
            "error": "无法确定所属板块，暂不支持同业对比",
        }

    result = comparison.to_dict()
    result["peers"] = bench.find_peers(symbol, name)
    return result


@router.post("/alpha-factors")
async def get_alpha_factors(
    body: dict[str, Any],
    engine=Depends(get_qlib_alpha_engine),
) -> dict[str, Any]:
    """Compute alpha factors for a stock or batch of stocks.

    Body: ``{"symbol": "600519"}`` or ``{"symbols": ["600519", "000001"]}``
    """
    symbols = body.get("symbols", [])
    if not symbols:
        sym = body.get("symbol", "")
        if not sym:
            return {"error": "symbol or symbols is required"}
        symbols = [sym]

    if len(symbols) == 1:
        result = engine.compute_factors(symbols[0])
        return result.to_dict()

    batch = engine.compute_batch(symbols)
    return {
        "results": {s: f.to_dict() for s, f in batch.items()},
        "count": len(batch),
    }


@router.post("/factor-exposure")
async def factor_exposure(
    body: dict[str, Any],
    engine=Depends(get_qlib_alpha_engine),
    store=Depends(get_portfolio_store),
) -> dict[str, Any]:
    """Compute portfolio-level factor exposure for radar chart (FR-QL003).

    Returns 6-dimensional factor scores: momentum, value, volatility,
    liquidity, quality, size — suitable for radar chart visualization.
    """
    # Get portfolio positions
    positions = body.get("positions", [])
    if not positions:
        try:
            data = store.get_portfolio_data()
            positions = [
                {"symbol": p["symbol"], "name": p.get("name", p["symbol"])}
                for p in data.get("positions", [])
            ]
        except Exception:
            return {"error": "无法读取持仓数据", "factors": []}

    if not positions:
        return {"message": "持仓为空", "factors": []}

    # Compute factors for each position
    symbols = [p["symbol"] for p in positions]
    batch = engine.compute_batch(symbols)

    # Aggregate to portfolio level (equal-weighted average)
    available = [f for f in batch.values() if f.available]
    if not available:
        return {
            "factors": _default_radar_factors(),
            "position_count": len(positions),
            "available_count": 0,
            "message": "Qlib 不可用，使用默认值",
        }

    n = len(available)
    agg_momentum = sum(f.momentum_score for f in available) / n
    agg_volatility = sum(f.volatility_score for f in available) / n
    agg_liquidity = sum(f.liquidity_score for f in available) / n
    agg_quality = sum(f.factors.get("quality_score", 0.5) for f in available) / n
    agg_value = sum(f.factors.get("price_to_ma20", 0.5) for f in available) / n
    agg_size = 0.5  # placeholder — no size factor from current Qlib data

    factors = [
        {"label": "动量", "value": round(agg_momentum, 3), "benchmark": 0.5},
        {"label": "价值", "value": round(1.0 - agg_value, 3), "benchmark": 0.5},
        {"label": "波动", "value": round(agg_volatility, 3), "benchmark": 0.5},
        {"label": "流动性", "value": round(agg_liquidity, 3), "benchmark": 0.5},
        {"label": "质量", "value": round(agg_quality, 3), "benchmark": 0.5},
        {"label": "规模", "value": round(agg_size, 3), "benchmark": 0.5},
    ]

    return {
        "factors": factors,
        "position_count": len(positions),
        "available_count": len(available),
        "details": {s: f.to_dict() for s, f in batch.items()},
    }


@router.post("/portfolio-optimize")
async def portfolio_optimize(
    body: dict[str, Any],
    optimizer=Depends(get_qlib_portfolio_optimizer),
    alpha_engine=Depends(get_qlib_alpha_engine),
    store=Depends(get_portfolio_store),
) -> dict[str, Any]:
    """Run portfolio optimization based on alpha factor scores (FR-QL002).

    Returns target weights and rebalance suggestions.
    """
    positions = body.get("positions", [])
    if not positions:
        try:
            data = store.get_portfolio_data()
            positions = [
                {
                    "symbol": p["symbol"],
                    "name": p.get("name", p["symbol"]),
                    "market_value": p.get("market_value", 0),
                }
                for p in data.get("positions", [])
            ]
        except Exception:
            return {"error": "无法读取持仓数据"}

    if not positions:
        return {"message": "持仓为空"}

    # Compute alpha scores
    symbols = [p["symbol"] for p in positions]
    batch = alpha_engine.compute_batch(symbols)
    alpha_scores = {s: f.composite_score for s, f in batch.items()}

    result = optimizer.optimize(positions, alpha_scores)
    return result.to_dict()


def _default_radar_factors() -> list[dict[str, Any]]:
    """Default radar chart factors when Qlib is unavailable."""
    return [
        {"label": "动量", "value": 0.5, "benchmark": 0.5},
        {"label": "价值", "value": 0.5, "benchmark": 0.5},
        {"label": "波动", "value": 0.5, "benchmark": 0.5},
        {"label": "流动性", "value": 0.5, "benchmark": 0.5},
        {"label": "质量", "value": 0.5, "benchmark": 0.5},
        {"label": "规模", "value": 0.5, "benchmark": 0.5},
    ]

"""Collect ALL data needed for deep research analysis in a single call.

Outputs a comprehensive JSON with:
- price: Daily OHLCV with freshness check
- portfolio: Current positions + capital balance
- trades: Recent trade history for the symbol
- recommendations: Recent recommendation history
- fund_flow: Capital flow data
- market: Index data for context

Usage:
    .venv/bin/python scripts/deep_research_data.py --symbol 002063
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Suppress all log output — only JSON goes to stdout
logging.disable(logging.CRITICAL)

# Ensure project root is on sys.path (supports running from any cwd)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Setup environment
try:
    import dotenv

    dotenv.load_dotenv()
except ImportError:
    pass

try:
    from src.data.eastmoney_proxy import init_proxy_patch

    init_proxy_patch()
except Exception:
    pass


DB_PATH = Path("data/agent.db")
REC_DB_PATH = Path("data/recommendations.db")


def _fetch_price(symbol: str) -> dict:
    """Fetch daily OHLCV with freshness metadata."""
    try:
        from src.data.fetcher import StockDataFetcher
        from src.data.trading_calendar import TradingCalendar

        fetcher = StockDataFetcher()
        cal = TradingCalendar()
        df = fetcher.fetch_daily_ohlcv(symbol)
        if df is not None and not df.empty:
            last_date = str(df["date"].iloc[-1])[:10]
            prev_td = cal.prev_trading_day().isoformat()
            return {
                "status": "ok",
                "data": df.tail(10).to_dict(orient="records"),
                "last_date": last_date,
                "expected_min": prev_td,
                "is_trading_day": cal.is_trading_day(),
                "total_rows": len(df),
                "stale": last_date < prev_td,
            }
        return {"status": "empty", "error": "fetcher returned no data", "stale": True}
    except Exception as e:
        return {"status": "error", "error": str(e), "stale": True}


def _fetch_portfolio(symbol: str) -> dict:
    """Fetch current positions and capital."""
    result: dict = {"positions": [], "capital": 0.0, "holding_target": False}
    if not DB_PATH.exists():
        return result
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row

        # All positions
        rows = conn.execute(
            "SELECT symbol, name, board, cost_price, shares, buy_date, note "
            "FROM portfolio_positions ORDER BY created_at"
        ).fetchall()
        result["positions"] = [dict(r) for r in rows]

        # Check if target symbol is held
        target = conn.execute(
            "SELECT symbol, name, cost_price, shares, buy_date "
            "FROM portfolio_positions WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        if target:
            result["holding_target"] = True
            result["target_position"] = dict(target)

        # Capital balance
        bal = conn.execute(
            "SELECT balance_after FROM capital_transactions "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        result["capital"] = bal["balance_after"] if bal else 0.0

        # Total portfolio value (cost basis)
        total_cost = sum(p["cost_price"] * p["shares"] for p in result["positions"])
        result["total_invested"] = round(total_cost, 2)
        result["total_assets_cost"] = round(total_cost + result["capital"], 2)

        conn.close()
    except Exception as e:
        result["error"] = str(e)
    return result


def _fetch_trades(symbol: str) -> list[dict]:
    """Fetch recent trade history for the symbol."""
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, side, price, quantity, status, reason, created_at "
            "FROM trades WHERE symbol = ? ORDER BY created_at DESC LIMIT 10",
            (symbol,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _fetch_recommendations(symbol: str) -> list[dict]:
    """Fetch recent recommendation history for the symbol."""
    if not REC_DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(REC_DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, name, style, score, ai_analysis, "
            "created_at FROM recommendations "
            "WHERE symbol = ? ORDER BY created_at DESC LIMIT 5",
            (symbol,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _fetch_fund_flow(symbol: str) -> dict:
    """Fetch fund flow data with pre-computed summary to prevent misinterpretation."""
    try:
        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        df = fetcher.fetch_fund_flow(symbol)
        if df is None or df.empty:
            return {"status": "empty"}

        recent = df.tail(10)
        data = recent.to_dict(orient="records")

        # Pre-compute summary so the LLM doesn't cherry-pick
        summary: dict = {}
        if "main_net" in recent.columns:
            nets = recent["main_net"].tolist()
            dates = [str(d)[:10] for d in recent["date"].tolist()]

            # Per-day breakdown (human-readable)
            daily = []
            for d, n in zip(dates, nets):
                direction = "流入" if n > 0 else "流出"
                daily.append(f"{d}: 主力{direction} {abs(n) / 1e4:,.0f}万")
            summary["daily_breakdown"] = daily

            # Aggregated metrics
            inflow_days = [n for n in nets if n > 0]
            outflow_days = [n for n in nets if n < 0]
            total_net = sum(nets)
            summary["total_net_10d"] = round(total_net / 1e4, 0)
            summary["total_net_10d_label"] = (
                f"近10日主力净{'流入' if total_net > 0 else '流出'} "
                f"{abs(total_net) / 1e4:,.0f}万"
            )
            summary["inflow_days"] = len(inflow_days)
            summary["outflow_days"] = len(outflow_days)
            if inflow_days:
                summary["max_inflow"] = round(max(inflow_days) / 1e4, 0)
            if outflow_days:
                summary["max_outflow"] = round(abs(min(outflow_days)) / 1e4, 0)

            # Recent 3-day and 5-day net
            last3 = nets[-3:] if len(nets) >= 3 else nets
            last5 = nets[-5:] if len(nets) >= 5 else nets
            net3 = sum(last3)
            net5 = sum(last5)
            summary["net_3d"] = (
                f"近3日主力净{'流入' if net3 > 0 else '流出'} {abs(net3) / 1e4:,.0f}万"
            )
            summary["net_5d"] = (
                f"近5日主力净{'流入' if net5 > 0 else '流出'} {abs(net5) / 1e4:,.0f}万"
            )

            # Trend detection
            if len(nets) >= 3:
                last3_signs = [1 if n > 0 else -1 for n in last3]
                if all(s == 1 for s in last3_signs):
                    summary["trend"] = "连续流入"
                elif all(s == -1 for s in last3_signs):
                    summary["trend"] = "连续流出"
                else:
                    summary["trend"] = "流向交替（多空分歧）"

            # Behavior pattern detection (cross-reference price + flow)
            if "pct_change" in recent.columns and len(nets) >= 3:
                pcts = recent["pct_change"].tolist()
                patterns = []
                # Last day pattern
                last_net = nets[-1]
                last_pct = pcts[-1] if pcts else 0
                if last_pct > 2 and last_net < 0:
                    patterns.append("边拉边出（股价涨但主力流出，警惕出货）")
                elif last_pct < -2 and last_net > 0:
                    patterns.append("打压吸筹（股价跌但主力流入，关注建仓）")
                # Multi-day patterns
                if len(pcts) >= 3:
                    last3_pct = pcts[-3:]
                    if all(p > 0 for p in last3_pct) and all(
                        n < nets[-3] for n in nets[-2:]
                    ):
                        patterns.append("缩量上涨（量能递减但连涨，筹码锁定）")
                    if (
                        max(abs(p) for p in last3_pct) > 5
                        and max(abs(n) for n in last3) > 1e8
                    ):
                        patterns.append("放量分歧（巨量换手+大波动，多空激战）")
                if patterns:
                    summary["behavior_patterns"] = patterns

        return {
            "status": "ok",
            "data": data,
            "rows": len(df),
            "summary": summary,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _fetch_market_context() -> dict:
    """Fetch market index data for context."""
    try:
        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        indices = {}
        for idx, name in [
            ("000001", "上证指数"),
            ("399001", "深证成指"),
            ("399006", "创业板指"),
        ]:
            try:
                df = fetcher.fetch_index(idx)
                if df is not None and not df.empty:
                    last = df.iloc[-1]
                    prev = df.iloc[-2] if len(df) > 1 else last
                    pct = (
                        round((last["close"] - prev["close"]) / prev["close"] * 100, 2)
                        if prev["close"]
                        else 0
                    )
                    indices[name] = {
                        "close": round(float(last["close"]), 2),
                        "change_pct": pct,
                        "date": str(last["date"])[:10],
                    }
            except Exception:
                pass
        return {"status": "ok" if indices else "empty", "indices": indices}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Deep research data collector")
    parser.add_argument("--symbol", required=True, help="6-digit stock code")
    args = parser.parse_args()
    symbol = args.symbol

    # Strip exchange prefix
    if len(symbol) > 6 and symbol[:2] in ("sh", "sz"):
        symbol = symbol[2:]

    result = {
        "symbol": symbol,
        "collected_at": datetime.now().isoformat(),
        "price": _fetch_price(symbol),
        "portfolio": _fetch_portfolio(symbol),
        "trades": _fetch_trades(symbol),
        "recommendations": _fetch_recommendations(symbol),
        "fund_flow": _fetch_fund_flow(symbol),
        "market": _fetch_market_context(),
    }

    # Summary flags
    result["summary"] = {
        "price_ok": result["price"].get("status") == "ok"
        and not result["price"].get("stale"),
        "holding": result["portfolio"].get("holding_target", False),
        "capital": result["portfolio"].get("capital", 0),
        "has_trade_history": len(result["trades"]) > 0,
        "has_recommendations": len(result["recommendations"]) > 0,
        "has_fund_flow": result["fund_flow"].get("status") == "ok",
        "has_market_context": result["market"].get("status") == "ok",
    }

    print(json.dumps(result, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()

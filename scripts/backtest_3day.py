"""3-day backtest — feed Agent historical data, compare with actual outcomes.

Takes the prediction pipeline results + current prices to retroactively
evaluate: if the agent had acted on its signals, would it have made money?
"""
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path


def run():
    from src.data.fetcher import StockDataFetcher

    fetcher = StockDataFetcher()

    # Get all symbols we track
    db_path = Path("data/agent.db")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Get recent decisions from the journal
    rows = conn.execute("""
        SELECT symbol, action, confidence, timestamp, entry_price
        FROM decision_journal
        WHERE symbol IS NOT NULL
        AND timestamp >= datetime('now', '-7 days')
        ORDER BY timestamp DESC
    """).fetchall()

    print("=" * 60)
    print("3-DAY BACKTEST — Agent Decisions vs Actual Outcomes")
    print("=" * 60)

    if not rows:
        print("No decisions in last 7 days. Using prediction pipeline instead.")
        _backtest_from_predictions(fetcher)
        return

    # Group by symbol, take latest decision per symbol
    seen = {}
    for r in rows:
        sym = r["symbol"]
        if sym not in seen:
            seen[sym] = dict(r)

    wins = 0
    losses = 0
    total = 0

    for sym, d in seen.items():
        action = d["action"]
        conf = d["confidence"] or 0.5
        ts = d["timestamp"][:10] if d["timestamp"] else "?"

        # Get price history
        try:
            df = fetcher.fetch_daily_ohlcv(sym)
            if df is None or len(df) < 3:
                continue
        except Exception:
            continue

        # Decision date price vs T+1, T+3
        last_3 = df.tail(3)
        prices = list(last_3["close"])
        dates = list(last_3.index) if hasattr(last_3.index, '__iter__') else []

        if len(prices) < 3:
            continue

        t0 = prices[-3]  # 3 days ago
        t1 = prices[-2]  # 2 days ago
        t3 = prices[-1]  # latest

        t1_ret = (t1 - t0) / t0 * 100
        t3_ret = (t3 - t0) / t0 * 100

        # Was the direction correct?
        is_bullish = action in ("buy", "add", "hold")
        direction_correct = (t3_ret > 0) if is_bullish else (t3_ret < 0)

        total += 1
        if direction_correct:
            wins += 1
        else:
            losses += 1

        mark = "✅" if direction_correct else "❌"
        print()
        print("{} {} {} (conf={:.0%}) @ {:.2f}".format(
            mark, sym, action.upper(), conf, t0))
        print("   T+1: {:.2f} ({:+.1f}%)  T+3: {:.2f} ({:+.1f}%)".format(
            t1, t1_ret, t3, t3_ret))
        print("   Decision date: {}".format(ts))

    print()
    print("=" * 60)
    if total > 0:
        print("RESULT: {}/{} correct ({:.0f}%)".format(wins, total, wins/total*100))
        print("  Wins: {}  Losses: {}".format(wins, losses))
    else:
        print("No evaluable decisions. Running prediction-based backtest...")
        _backtest_from_predictions(fetcher)

    conn.close()


def _backtest_from_predictions(fetcher):
    """Use the prediction pipeline results to backtest."""
    from src.web.dependencies import get_redis
    import redis

    r = get_redis()
    if not r:
        print("Redis unavailable")
        return

    # Get all predictions from Redis
    keys = r.keys("prediction:*")
    if not keys:
        print("No predictions in Redis")
        return

    wins = 0
    losses = 0
    total = 0

    for key in sorted(keys):
        raw = r.get(key)
        if not raw:
            continue
        pred = json.loads(raw)
        sym = key.split(":")[-1]
        signal = pred.get("signal", "")
        trend = pred.get("trend", "")
        conf = pred.get("confidence", 0)

        # Get actual price movement (last 3 trading days)
        try:
            df = fetcher.fetch_daily_ohlcv(sym)
            if df is None or len(df) < 3:
                continue
        except Exception:
            continue

        last_3 = df.tail(3)
        prices = list(last_3["close"])
        t0 = prices[-3]
        t3 = prices[-1]
        ret_3d = (t3 - t0) / t0 * 100

        # Prediction was bullish?
        is_bullish = signal in ("buy", "strong_buy") or trend == "bullish"
        is_bearish = signal in ("sell", "strong_sell") or trend == "bearish"

        if is_bullish:
            direction_correct = ret_3d > 0
        elif is_bearish:
            direction_correct = ret_3d < 0
        else:
            # Neutral — correct if magnitude < 3%
            direction_correct = abs(ret_3d) < 3.0

        total += 1
        if direction_correct:
            wins += 1
        else:
            losses += 1

        mark = "✅" if direction_correct else "❌"
        print("{} {} pred={}/{} conf={:.0%} → 3d return {:+.1f}%".format(
            mark, sym, trend, signal, conf, ret_3d))

    print()
    print("=" * 60)
    if total > 0:
        print("PREDICTION BACKTEST: {}/{} correct ({:.0f}%)".format(
            wins, total, wins/total*100))
    else:
        print("No evaluable predictions")


if __name__ == "__main__":
    run()

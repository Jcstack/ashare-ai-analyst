"""Seed calibration DB with LLM-analyzed predictions over 15 trading days.

Uses the full StockAnalyzer (LLM + technical indicators + patterns +
support/resistance) — NOT simple momentum. This is the closest
approximation to what the live agent would produce.

7 stocks × 15 days = 105 LLM calls ≈ 13 minutes.
"""
import sys
sys.path.insert(0, "/app")

import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from src.data.fetcher import StockDataFetcher
from src.analysis.indicators import TechnicalIndicators
from src.analysis.patterns import PatternRecognizer
from src.prediction.analyzer import StockAnalyzer


def run():
    fetcher = StockDataFetcher()
    ind_calc = TechnicalIndicators()
    pat_rec = PatternRecognizer()
    analyzer = StockAnalyzer()

    # Create fresh decisions.db
    db = Path("data/decisions.db")
    conn = sqlite3.connect(str(db))
    conn.execute("DROP TABLE IF EXISTS decisions")
    conn.execute("""CREATE TABLE decisions (
        proposal_id TEXT PRIMARY KEY, symbol TEXT, action TEXT, confidence REAL,
        decided_at TEXT, entry_price REAL, sector TEXT DEFAULT '',
        t1_price REAL, t3_price REAL, t5_price REAL,
        t1_return_pct REAL, t3_return_pct REAL, t5_return_pct REAL,
        direction_correct INTEGER)""")

    symbols = ["600498", "000547", "603618", "002063", "601600", "600410", "002498"]
    WINDOW = 15
    results = []
    buckets = defaultdict(lambda: {"total": 0, "correct": 0, "conf_sum": 0.0})
    action_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    inserted = 0

    for sym in symbols:
        df_full = fetcher.fetch_daily_ohlcv(sym)
        if df_full is None or len(df_full) < WINDOW + 5 + 60:
            print("SKIP %s" % sym)
            continue

        print("--- %s (%d days) ---" % (sym, len(df_full)))

        for i in range(WINDOW + 3, 3, -1):
            day_idx = len(df_full) - i
            if day_idx < 60:
                continue

            # Point-in-time data (no future leak)
            hist = df_full.iloc[:day_idx + 1].copy()
            dc = float(hist.iloc[-1]["close"])

            # T+1 and T+3 actual
            t1_idx = day_idx + 1
            t3_idx = day_idx + 3
            if t3_idx >= len(df_full):
                continue

            t1c = float(df_full.iloc[t1_idx]["close"])
            t3c = float(df_full.iloc[t3_idx]["close"])
            t1r = (t1c - dc) / dc * 100
            t3r = (t3c - dc) / dc * 100

            try:
                # Full LLM analysis pipeline
                df_i = ind_calc.add_all(hist)
                lr = df_i.iloc[-1]
                ic = [c for c in df_i.columns if c.startswith(
                    ("MA_", "EMA_", "RSI", "MACD", "KDJ", "BB_", "OBV", "VWAP"))]
                iv = {c: round(float(lr[c]), 4) for c in ic if lr[c] == lr[c]}
                pc = [c for c in df_i.columns if c.startswith("CDL")]
                ap = [{"name": c, "value": float(lr[c])} for c in pc if lr[c] != 0]
                sr = pat_rec.find_support_resistance(df_i)

                pred = analyzer.analyze(
                    symbol=sym, ohlcv_df=df_i, indicators=iv,
                    patterns=ap, sr_levels=sr)

                sig = pred.get("signal", "hold")
                trend = pred.get("trend", "neutral")
                conf = pred.get("confidence", 0.5)

                # Map to action
                if sig in ("buy", "strong_buy") or trend == "bullish":
                    action = "buy"
                elif sig in ("sell", "strong_sell"):
                    action = "sell"
                elif trend == "bearish":
                    action = "sell"
                else:
                    action = "hold"

                # Direction correct?
                if action == "buy":
                    cor = 1 if t3r > 0 else 0
                elif action == "sell":
                    cor = 1 if t3r < 0 else 0
                else:
                    cor = 1 if abs(t3r) < 3.0 else 0

                # Confidence bucket
                if conf < 0.6:
                    bk = "0.50-0.60"
                elif conf < 0.7:
                    bk = "0.60-0.70"
                elif conf < 0.8:
                    bk = "0.70-0.80"
                else:
                    bk = "0.80+"
                buckets[bk]["total"] += 1
                if cor:
                    buckets[bk]["correct"] += 1
                buckets[bk]["conf_sum"] += conf

                action_stats[action]["total"] += 1
                if cor:
                    action_stats[action]["correct"] += 1

                # Write to DB
                pid = "llm-%s-%d" % (sym, day_idx)
                decided_at = "2026-03-%02d" % max(1, min(31, 31 - i + 3))
                conn.execute(
                    "INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, sym, action, conf, decided_at, dc, "",
                     t1c, t3c, None, round(t1r, 2), round(t3r, 2), None, cor))
                inserted += 1
                results.append({"sym": sym, "action": action, "conf": conf,
                                "t3r": t3r, "ok": bool(cor), "trend": trend, "sig": sig})

                mark = "O" if cor else "X"
                print("  %s %s/%s c=%.0f%% T3=%+.1f%%" % (mark, trend, sig, conf * 100, t3r))
                time.sleep(0.3)

            except Exception as e:
                print("  ERR: %s" % str(e)[:60])
                continue

    conn.commit()

    # =================== RESULTS ===================
    print()
    print("=" * 60)
    total = len(results)
    if total == 0:
        print("No results!")
        conn.close()
        return

    wins = sum(1 for r in results if r["ok"])
    print("SEEDED %d LLM-analyzed decisions" % inserted)
    print("OVERALL: %d/%d correct (%.1f%%)" % (wins, total, wins / total * 100))

    print()
    print("BY ACTION:")
    for act in sorted(action_stats.keys()):
        s = action_stats[act]
        print("  %s: %d/%d (%.0f%%)" % (act, s["correct"], s["total"],
              s["correct"] / s["total"] * 100 if s["total"] else 0))

    print()
    print("BY STOCK:")
    by_sym = defaultdict(lambda: {"t": 0, "w": 0})
    for r in results:
        by_sym[r["sym"]]["t"] += 1
        if r["ok"]:
            by_sym[r["sym"]]["w"] += 1
    for sym in sorted(by_sym.keys()):
        s = by_sym[sym]
        print("  %s: %d/%d (%.0f%%)" % (sym, s["w"], s["t"], s["w"] / s["t"] * 100))

    print()
    print("CONFIDENCE CALIBRATION (Bayesian):")
    print("  Bucket      | N   | Correct | Actual | Claimed | Gap")
    print("  ------------|-----|---------|--------|---------|-----")
    for bk in sorted(buckets.keys()):
        b = buckets[bk]
        rate = b["correct"] / b["total"] * 100 if b["total"] > 0 else 0
        avg_c = b["conf_sum"] / b["total"] * 100 if b["total"] > 0 else 0
        gap = avg_c - rate
        print("  %-12s| %3d | %7d | %5.1f%% | %5.1f%% | %+.0f%%" % (
            bk, b["total"], b["correct"], rate, avg_c, -gap))

    # Test calibrator
    print()
    print("CALIBRATOR TEST:")
    from src.agent_loop.confidence_calibrator import ConfidenceCalibrator
    cc = ConfidenceCalibrator(
        db_path="data/decisions.db",
        config={"min_samples_for_calibration": 3})
    rpt = cc.get_calibration_report()
    print("  Active: %s | Overall accuracy: %s" % (
        rpt.get("calibration_active"),
        "%.0f%%" % (rpt["overall_accuracy"] * 100) if rpt.get("overall_accuracy") else "N/A"))

    print()
    print("LIVE ADJUSTMENTS (raw confidence → calibrated):")
    for act in ["buy", "sell", "hold"]:
        for raw in [0.6, 0.75, 0.85]:
            cal = cc.calibrate(raw, "600498", act)
            if abs(cal - raw) > 0.005:
                print("  %s %.2f → %.2f (%+.2f)" % (act, raw, cal, cal - raw))

    conn.close()
    print()
    print("Done. decisions.db ready for HeartbeatAgent calibration.")


if __name__ == "__main__":
    run()

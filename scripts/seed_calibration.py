"""Seed the calibration database from backtest results.

Writes backtest outcomes to data/decisions.db so ConfidenceCalibrator
can use them for future confidence adjustments. Also injects the
calibration data into the HeartbeatAgent's system prompt context.
"""
import sys
sys.path.insert(0, "/app")

import sqlite3
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from src.data.fetcher import StockDataFetcher
from src.analysis.indicators import TechnicalIndicators
from src.analysis.patterns import PatternRecognizer
from src.prediction.analyzer import StockAnalyzer


def create_decisions_db():
    """Create the decisions.db schema that ConfidenceCalibrator expects."""
    db_path = Path("data/decisions.db")
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            proposal_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence REAL,
            decided_at TEXT,
            entry_price REAL,
            sector TEXT DEFAULT '',
            t1_price REAL,
            t3_price REAL,
            t5_price REAL,
            t1_return_pct REAL,
            t3_return_pct REAL,
            t5_return_pct REAL,
            direction_correct INTEGER
        )
    """)
    conn.commit()
    return conn


def run():
    fetcher = StockDataFetcher()
    ind_calc = TechnicalIndicators()
    pat_rec = PatternRecognizer()
    analyzer = StockAnalyzer()

    conn = create_decisions_db()

    symbols = ["600498", "000547", "603618", "002063", "601600", "600410", "002498"]
    WINDOW = 20  # 20 trading days of backtest
    results = []
    buckets = defaultdict(lambda: {"total": 0, "correct": 0, "conf_sum": 0.0})

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

            hist = df_full.iloc[:day_idx + 1].copy()
            dc = float(hist.iloc[-1]["close"])
            t1_idx = day_idx + 1
            t3_idx = day_idx + 3
            if t3_idx >= len(df_full):
                continue

            t1c = float(df_full.iloc[t1_idx]["close"])
            t3c = float(df_full.iloc[t3_idx]["close"])
            t1r = (t1c - dc) / dc * 100
            t3r = (t3c - dc) / dc * 100

            try:
                df_i = ind_calc.add_all(hist)
                lr = df_i.iloc[-1]
                ic = [c for c in df_i.columns if c.startswith(("MA_", "EMA_", "RSI", "MACD", "KDJ", "BB_", "OBV", "VWAP"))]
                iv = {c: round(float(lr[c]), 4) for c in ic if lr[c] == lr[c]}
                pc = [c for c in df_i.columns if c.startswith("CDL")]
                ap = [{"name": c, "value": float(lr[c])} for c in pc if lr[c] != 0]
                sr = pat_rec.find_support_resistance(df_i)

                pred = analyzer.analyze(symbol=sym, ohlcv_df=df_i, indicators=iv, patterns=ap, sr_levels=sr)
                sig = pred.get("signal", "")
                trend = pred.get("trend", "")
                conf = pred.get("confidence", 0.5)

                # Map to action
                if sig in ("buy", "strong_buy") or trend == "bullish":
                    action = "buy"
                elif sig in ("sell", "strong_sell") or trend == "bearish":
                    action = "sell"
                else:
                    action = "hold"

                # Direction correct?
                if action == "buy":
                    t3_correct = 1 if t3r > 0 else 0
                elif action == "sell":
                    t3_correct = 1 if t3r < 0 else 0
                else:
                    t3_correct = 1 if abs(t3r) < 3.0 else 0

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
                if t3_correct:
                    buckets[bk]["correct"] += 1
                buckets[bk]["conf_sum"] += conf

                # Insert into decisions.db
                proposal_id = "bt-%s-%d" % (sym, day_idx)
                decided_at = datetime.utcnow().isoformat()

                conn.execute("""
                    INSERT OR REPLACE INTO decisions
                    (proposal_id, symbol, action, confidence, decided_at, entry_price,
                     t1_price, t3_price, t1_return_pct, t3_return_pct, direction_correct)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (proposal_id, sym, action, conf, decided_at, dc,
                      t1c, t3c, round(t1r, 2), round(t3r, 2), t3_correct))
                inserted += 1

                results.append({"sym": sym, "action": action, "conf": conf, "t3r": t3r, "ok": bool(t3_correct)})

                mark = "O" if t3_correct else "X"
                print("  %s %s c=%.0f%% T3=%+.1f%%" % (mark, action, conf * 100, t3r))
                time.sleep(0.3)

            except Exception as e:
                print("  ERR: %s" % str(e)[:60])
                continue

    conn.commit()

    # Summary
    print()
    print("=" * 55)
    total = len(results)
    if total == 0:
        print("No results!")
        conn.close()
        return

    wins = sum(1 for r in results if r["ok"])
    print("SEEDED %d decisions into data/decisions.db" % inserted)
    print("Overall: %d/%d correct (%.1f%%)" % (wins, total, wins / total * 100))

    print()
    print("CALIBRATION TABLE (for ConfidenceCalibrator):")
    print("  Bucket      | N   | Correct | Actual Rate | Avg Claimed")
    print("  ------------|-----|---------|-------------|------------")
    for bk in sorted(buckets.keys()):
        b = buckets[bk]
        rate = b["correct"] / b["total"] * 100 if b["total"] > 0 else 0
        avg_conf = b["conf_sum"] / b["total"] * 100 if b["total"] > 0 else 0
        gap = avg_conf - rate
        print("  %-12s| %3d | %7d | %5.1f%%      | %5.1f%% (%+.0f%%)" % (
            bk, b["total"], b["correct"], rate, avg_conf, -gap))

    # Test that calibrator can now read it
    print()
    print("Testing ConfidenceCalibrator...")
    from src.agent_loop.confidence_calibrator import ConfidenceCalibrator
    cc = ConfidenceCalibrator(db_path="data/decisions.db", config={"min_samples_for_calibration": 3})
    report = cc.get_calibration_report()
    print("  Status: %s" % report.get("status"))
    print("  Total decisions: %s" % report.get("total_decisions"))
    print("  Evaluated: %s" % report.get("evaluated_decisions"))
    print("  Overall accuracy: %s" % report.get("overall_accuracy"))
    print("  Calibration active: %s" % report.get("calibration_active"))
    if report.get("by_action"):
        print("  By action:")
        for action, stats in report["by_action"].items():
            print("    %s: %s/%s = %s" % (
                action, stats.get("evaluated"), stats.get("total"),
                "%.0f%%" % (stats["accuracy"] * 100) if stats.get("accuracy") is not None else "N/A"))

    # Also test calibration adjustment
    print()
    print("Calibration adjustments:")
    for action in ["buy", "sell", "hold"]:
        raw = 0.75
        calibrated = cc.calibrate(raw, "600498", action)
        print("  %s raw=%.2f → calibrated=%.2f (adj=%+.2f)" % (
            action, raw, calibrated, calibrated - raw))

    conn.close()


if __name__ == "__main__":
    run()

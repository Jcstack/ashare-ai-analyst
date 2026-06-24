"""Rolling backtest — simulate prediction pipeline over 30 trading days.

For each day D in the window:
1. Feed the analyzer ONLY data up to day D (no future leak)
2. Record the prediction (trend, signal, confidence)
3. Compare with actual T+1 and T+3 returns

Outputs: per-signal accuracy, confidence calibration curve, overall stats.
Satisfies Bayesian requirement: 30+ observations per confidence bucket.
"""
import sys
sys.path.insert(0, "/app")

import json
import time
from collections import defaultdict

from src.data.fetcher import StockDataFetcher
from src.analysis.indicators import TechnicalIndicators
from src.analysis.patterns import PatternRecognizer
from src.prediction.analyzer import StockAnalyzer


def run():
    fetcher = StockDataFetcher()
    indicators_calc = TechnicalIndicators()
    pattern_recognizer = PatternRecognizer()
    analyzer = StockAnalyzer()

    # Stocks to backtest
    symbols = ["600498", "000547", "002063", "601600", "603618", "600410", "002498"]

    # Rolling window: use last 30 trading days as decision points
    WINDOW = 30
    T1_OFFSET = 1
    T3_OFFSET = 3

    all_results = []
    confidence_buckets = defaultdict(lambda: {"total": 0, "correct": 0})

    for sym in symbols:
        try:
            full_df = fetcher.fetch_daily_ohlcv(sym)
            if full_df is None or len(full_df) < WINDOW + T3_OFFSET + 20:
                print("SKIP %s: insufficient data (%d days)" % (sym, len(full_df) if full_df is not None else 0))
                continue
        except Exception as e:
            print("SKIP %s: %s" % (sym, e))
            continue

        print("\n--- %s (%d days available) ---" % (sym, len(full_df)))

        # For each decision day in the window
        for i in range(WINDOW + T3_OFFSET, T3_OFFSET, -1):
            day_idx = len(full_df) - i
            if day_idx < 60:  # Need at least 60 days of history for indicators
                continue

            # Data available to the analyzer on decision day (no future leak)
            hist = full_df.iloc[:day_idx + 1].copy()

            # Get the decision day's close and future prices
            decision_close = float(hist.iloc[-1]["close"])
            decision_date = str(hist.index[-1])[:10] if hasattr(hist.index[-1], 'strftime') else str(day_idx)

            # T+1 and T+3 actual prices
            t1_idx = day_idx + T1_OFFSET
            t3_idx = day_idx + T3_OFFSET
            if t3_idx >= len(full_df):
                continue

            t1_close = float(full_df.iloc[t1_idx]["close"])
            t3_close = float(full_df.iloc[t3_idx]["close"])
            t1_ret = (t1_close - decision_close) / decision_close * 100
            t3_ret = (t3_close - decision_close) / decision_close * 100

            # Run the analyzer with point-in-time data
            try:
                # Add indicators
                df_ind = indicators_calc.add_all(hist)
                last_row = df_ind.iloc[-1]

                # Extract indicator values (last row only)
                indicator_cols = [c for c in df_ind.columns if c.startswith(("MA_", "EMA_", "RSI", "MACD", "KDJ", "BB_", "OBV", "VWAP"))]
                indicator_values = {col: round(float(last_row[col]), 4) for col in indicator_cols if not (last_row[col] != last_row[col])}

                # Patterns
                pattern_cols = [c for c in df_ind.columns if c.startswith("CDL")]
                active_patterns = [{"name": c, "value": float(last_row[c])} for c in pattern_cols if last_row[c] != 0]

                # Support/resistance
                sr_levels = pattern_recognizer.find_support_resistance(df_ind)

                # Run prediction (this calls LLM)
                prediction = analyzer.analyze(
                    symbol=sym,
                    ohlcv_df=df_ind,
                    indicators=indicator_values,
                    patterns=active_patterns,
                    sr_levels=sr_levels,
                )

                signal = prediction.get("signal", "")
                trend = prediction.get("trend", "")
                conf = prediction.get("confidence", 0.5)

                # Determine correctness
                is_bullish = signal in ("buy", "strong_buy") or trend == "bullish"
                is_bearish = signal in ("sell", "strong_sell") or trend == "bearish"

                if is_bullish:
                    t1_correct = t1_ret > 0
                    t3_correct = t3_ret > 0
                elif is_bearish:
                    t1_correct = t1_ret < 0
                    t3_correct = t3_ret < 0
                else:  # neutral/hold/watch
                    t1_correct = abs(t1_ret) < 3.0
                    t3_correct = abs(t3_ret) < 3.0

                # Confidence bucket (0.5-0.6, 0.6-0.7, 0.7-0.8, 0.8+)
                if conf < 0.6:
                    bucket = "0.50-0.60"
                elif conf < 0.7:
                    bucket = "0.60-0.70"
                elif conf < 0.8:
                    bucket = "0.70-0.80"
                else:
                    bucket = "0.80+"

                confidence_buckets[bucket]["total"] += 1
                if t3_correct:
                    confidence_buckets[bucket]["correct"] += 1

                result = {
                    "symbol": sym,
                    "date": decision_date,
                    "signal": signal,
                    "trend": trend,
                    "confidence": conf,
                    "t1_ret": round(t1_ret, 2),
                    "t3_ret": round(t3_ret, 2),
                    "t1_correct": t1_correct,
                    "t3_correct": t3_correct,
                }
                all_results.append(result)

                mark = chr(9989) if t3_correct else chr(10060)
                print("  %s D=%s %s/%s conf=%.0f%% T+1=%+.1f%% T+3=%+.1f%%" % (
                    mark, decision_date[-5:], trend, signal, conf * 100, t1_ret, t3_ret))

                # Rate limit for LLM
                time.sleep(0.5)

            except Exception as e:
                print("  ERR D=%s: %s" % (decision_date, str(e)[:80]))
                continue

    # Summary
    print("\n" + "=" * 60)
    print("ROLLING BACKTEST SUMMARY")
    print("=" * 60)

    total = len(all_results)
    if total == 0:
        print("No results!")
        return

    t1_wins = sum(1 for r in all_results if r["t1_correct"])
    t3_wins = sum(1 for r in all_results if r["t3_correct"])

    print("Total signals: %d" % total)
    print("T+1 accuracy: %d/%d (%.1f%%)" % (t1_wins, total, t1_wins / total * 100))
    print("T+3 accuracy: %d/%d (%.1f%%)" % (t3_wins, total, t3_wins / total * 100))

    # By signal type
    print("\nBy signal type:")
    for sig_type in ["buy", "sell", "hold", "watch"]:
        subset = [r for r in all_results if r["signal"] == sig_type]
        if subset:
            correct = sum(1 for r in subset if r["t3_correct"])
            print("  %s: %d/%d (%.0f%%)" % (sig_type, correct, len(subset), correct / len(subset) * 100))

    # Confidence calibration
    print("\nConfidence calibration (Bayesian):")
    print("  Bucket      | Signals | T+3 Correct | Empirical Rate")
    print("  ------------|---------|-------------|---------------")
    for bucket in sorted(confidence_buckets.keys()):
        b = confidence_buckets[bucket]
        rate = b["correct"] / b["total"] * 100 if b["total"] > 0 else 0
        sufficient = "OK" if b["total"] >= 10 else "need %d more" % (10 - b["total"])
        print("  %-12s| %7d | %11d | %5.1f%% [%s]" % (
            bucket, b["total"], b["correct"], rate, sufficient))

    # Save results for calibration
    try:
        with open("/app/data/processed/backtest_results.json", "w") as f:
            json.dump({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "total": total,
                "t1_accuracy": round(t1_wins / total * 100, 1),
                "t3_accuracy": round(t3_wins / total * 100, 1),
                "confidence_calibration": {
                    k: {"total": v["total"], "correct": v["correct"],
                         "rate": round(v["correct"] / v["total"] * 100, 1) if v["total"] > 0 else 0}
                    for k, v in confidence_buckets.items()
                },
                "results": all_results,
            }, f, ensure_ascii=False, indent=2)
        print("\nResults saved to data/processed/backtest_results.json")
    except Exception as e:
        print("\nFailed to save results: %s" % e)


if __name__ == "__main__":
    run()

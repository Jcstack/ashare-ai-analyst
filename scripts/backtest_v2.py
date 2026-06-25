#!/usr/bin/env python3
"""Backtest the v2 quant signal/sizing stack on the A-share backtest engine.

This is the P2.1 scaffold from ``ROADMAP.md``: it wires the v2 signal layer
(``SignalLibrary`` + ``RegimeDetector``, via :class:`QuantSignalV2Strategy`)
through the existing A-share-correct backtest engine (T+1, board price limits,
100-share lots, stamp tax) so the v2 stack can finally be evaluated
out-of-sample and produce a publishable equity curve + metrics.

Usage:
    # Fetch history from the configured data sources (needs network/cache):
    python -m scripts.backtest_v2 --symbol 600519 --start 20230101 --end 20240101

    # Or run fully offline from a local OHLCV CSV
    # (columns: date,open,high,low,close,volume):
    python -m scripts.backtest_v2 --csv data/sample/600519.csv --board main

Simulation/research only — outputs are **not investment advice**.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

_REQUIRED_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def _load_from_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")
    df["date"] = pd.to_datetime(df["date"])
    return df[_REQUIRED_COLUMNS].reset_index(drop=True)


def _load_from_source(symbol: str, start: str, end: str) -> pd.DataFrame:
    from src.data.fetcher import StockDataFetcher

    fetcher = StockDataFetcher()
    df = fetcher.fetch_daily_ohlcv(symbol, start_date=start, end_date=end)
    if df is None or df.empty:
        raise RuntimeError(f"No OHLCV data returned for {symbol} [{start}..{end}]")
    df["date"] = pd.to_datetime(df["date"])
    return df[_REQUIRED_COLUMNS].reset_index(drop=True)


def run(args: argparse.Namespace) -> int:
    from src.backtest.engine import BacktestEngine
    from src.backtest.metrics import PerformanceMetrics
    from src.strategy.quant_v2 import QuantSignalV2Strategy

    # 1. Load price history (offline CSV preferred when given).
    if args.csv:
        df = _load_from_csv(args.csv)
        label = Path(args.csv).stem
    else:
        df = _load_from_source(args.symbol, args.start, args.end)
        label = args.symbol
    print(
        f"Loaded {len(df)} bars for {label} "
        f"[{df['date'].iloc[0].date()}..{df['date'].iloc[-1].date()}]"
    )

    # 2. Build the v2 strategy and run it through the engine.
    strategy = QuantSignalV2Strategy(
        min_history=args.min_history,
        use_regime=not args.no_regime,
    )
    engine = BacktestEngine()
    result = engine.run(df, strategy, board=args.board)

    # 3. Metrics + baseline (buy-and-hold) for an honest comparison.
    metrics = PerformanceMetrics().calculate(result)
    buy_hold = df["close"].iloc[-1] / df["close"].iloc[0] - 1.0

    print(PerformanceMetrics().generate_report(metrics))
    summary = {
        "label": label,
        "board": args.board,
        "bars": len(df),
        "trades": metrics.get("total_trades"),
        "total_return": round(metrics.get("total_return", 0.0), 4),
        "buy_hold_return": round(float(buy_hold), 4),
        "excess_vs_buy_hold": round(
            metrics.get("total_return", 0.0) - float(buy_hold), 4
        ),
        "annual_return": round(metrics.get("annual_return", 0.0), 4),
        "sharpe_ratio": round(metrics.get("sharpe_ratio", 0.0), 3),
        "max_drawdown": round(metrics.get("max_drawdown", 0.0), 4),
        "win_rate": round(metrics.get("win_rate", 0.0), 4),
    }
    print("\nSUMMARY " + json.dumps(summary, ensure_ascii=False))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Wrote {args.json_out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="600519", help="6-digit A-share code")
    parser.add_argument("--start", default="20230101", help="YYYYMMDD")
    parser.add_argument("--end", default="", help="YYYYMMDD (empty = today)")
    parser.add_argument("--board", default="main", choices=["main", "chinext", "star"])
    parser.add_argument("--csv", default="", help="Load OHLCV from a local CSV instead")
    parser.add_argument("--min-history", type=int, default=30, dest="min_history")
    parser.add_argument(
        "--no-regime", action="store_true", help="Disable the regime gate"
    )
    parser.add_argument("--json-out", default="", dest="json_out")
    args = parser.parse_args(argv)

    try:
        return run(args)
    except Exception as exc:  # CLI: surface a clean error, no traceback spam
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

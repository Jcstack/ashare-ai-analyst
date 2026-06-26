#!/usr/bin/env python3
"""Backtest the v2 quant stack across a universe of A-shares and report aggregates.

Reproduces the table + equity-curve chart in ``docs/backtest-v2-results.md``.
Each symbol is fetched once and cached as CSV (``--cache-dir``) so re-runs are
offline and instant. The board (price-limit tier) is inferred from the code
prefix: ``300/301`` → ChiNext, ``688/689`` → STAR, otherwise main board.

Example (the published run):
    python -m scripts.backtest_v2_universe \\
        --start 20190101 --end 20241231 \\
        --chart docs/assets/backtest-v2-equity.png

Simulation/research only — outputs are **not investment advice**.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# A sector-diverse default universe of liquid large-caps.
DEFAULT_UNIVERSE = [
    "600519",
    "000858",
    "600036",
    "601318",
    "000333",
    "600276",
    "002594",
    "300750",
    "600030",
    "601899",
    "600887",
    "601012",
    "300059",
    "000651",
]
_REQUIRED = ["date", "open", "high", "low", "close", "volume"]


def infer_board(symbol: str) -> str:
    if symbol[:3] in ("300", "301"):
        return "chinext"
    if symbol[:3] in ("688", "689"):
        return "star"
    return "main"


def get_data(
    symbol: str, start: str, end: str, cache_dir: Path | None
) -> pd.DataFrame | None:
    cache = (cache_dir / f"{symbol}_{start}_{end}.csv") if cache_dir else None
    if cache and cache.exists():
        df = pd.read_csv(cache)
        df["date"] = pd.to_datetime(df["date"])
        return df
    from src.data.fetcher import StockDataFetcher

    try:
        df = StockDataFetcher().fetch_daily_ohlcv(
            symbol, start_date=start, end_date=end
        )
    except Exception as exc:
        print(f"  {symbol}: fetch error {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    if df is None or df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    df = df[_REQUIRED].reset_index(drop=True)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache, index=False)
    return df


def run_one(symbol: str, df: pd.DataFrame, use_regime: bool):
    from src.backtest.engine import BacktestEngine
    from src.backtest.metrics import PerformanceMetrics
    from src.strategy.quant_v2 import QuantSignalV2Strategy

    strat = QuantSignalV2Strategy(use_regime=use_regime)
    result = BacktestEngine().run(df, strat, board=infer_board(symbol))
    m = PerformanceMetrics().calculate(result)
    bh = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1.0)
    return result, m, bh


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--symbols",
        default="",
        help="Comma-separated codes (default: built-in universe)",
    )
    p.add_argument("--start", default="20190101", help="YYYYMMDD")
    p.add_argument("--end", default="20241231", help="YYYYMMDD")
    p.add_argument("--no-regime", action="store_true")
    p.add_argument("--cache-dir", default="", help="Dir to cache fetched CSVs")
    p.add_argument(
        "--chart", default="", help="Write an equal-weight equity-curve PNG here"
    )
    args = p.parse_args(argv)

    symbols = [
        s.strip() for s in args.symbols.split(",") if s.strip()
    ] or DEFAULT_UNIVERSE
    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    use_regime = not args.no_regime

    rows, eq_strat, eq_bh = [], {}, {}
    for sym in symbols:
        df = get_data(sym, args.start, args.end, cache_dir)
        if df is None or len(df) < 60:
            print(f"  {sym}: insufficient data", file=sys.stderr)
            continue
        result, m, bh = run_one(sym, df, use_regime)
        rows.append(
            (
                sym,
                m["total_return"],
                bh,
                m["total_return"] - bh,
                m["sharpe_ratio"],
                m["max_drawdown"],
                m["win_rate"],
            )
        )
        ec = pd.Series(result.equity_curve, index=pd.to_datetime(result.dates))
        eq_strat[sym] = ec / ec.iloc[0]
        c = df.set_index("date")["close"]
        eq_bh[sym] = c / c.iloc[0]
        print(
            f"  {sym}: {m['total_return']:+.1%} vs B&H {bh:+.1%} "
            f"(sharpe {m['sharpe_ratio']:.2f})",
            file=sys.stderr,
        )

    if not rows:
        print("No results.", file=sys.stderr)
        return 1

    n = len(rows)

    def mean(i: int) -> float:
        return sum(r[i] for r in rows) / n

    beat = sum(1 for r in rows if r[3] > 0)
    print(
        f"\n### v2 stack vs Buy & Hold — {args.start}..{args.end}, "
        f"{n} names, regime {'on' if use_regime else 'off'}\n"
    )
    print("| Symbol | Board | Strategy | Buy&Hold | Excess | Sharpe | MaxDD | Win |")
    print("|---|---|---|---|---|---|---|---|")
    for s, ret, bh, ex, sh, dd, w in rows:
        print(
            f"| {s} | {infer_board(s)} | {ret:+.1%} | {bh:+.1%} | {ex:+.1%} | "
            f"{sh:.2f} | -{dd:.1%} | {w:.0%} |"
        )
    print(
        f"| **Mean** | | **{mean(1):+.1%}** | **{mean(2):+.1%}** | **{mean(3):+.1%}** | "
        f"**{mean(4):.2f}** | **-{mean(5):.1%}** | |"
    )
    print(
        f"\n**Beat buy & hold: {beat}/{n}**  ·  "
        f"strategy mean {mean(1):+.1%} vs buy & hold {mean(2):+.1%}"
    )

    if args.chart:
        _write_chart(eq_strat, eq_bh, Path(args.chart), args.start, args.end, n)
    return 0


def _write_chart(eq_strat, eq_bh, out: Path, start: str, end: str, n: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = pd.DataFrame(eq_strat).mean(axis=1).sort_index()
    b = pd.DataFrame(eq_bh).mean(axis=1).sort_index()
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(
        b.index,
        b.values,
        color="#888",
        lw=1.6,
        label=f"Buy & Hold (equal-weight) → {b.iloc[-1] - 1:+.0%}",
    )
    ax.plot(
        s.index,
        s.values,
        color="#c0392b",
        lw=1.8,
        label=f"v2 strategy (equal-weight) → {s.iloc[-1] - 1:+.0%}",
    )
    ax.set_title(
        f"v2 quant stack vs Buy & Hold — {n} A-shares, equal-weight, "
        f"{start[:4]}–{end[:4]}"
    )
    ax.set_ylabel("Growth of 1.0 (normalized)")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.25)
    ax.text(
        0.5,
        -0.13,
        "Simulation only — not investment advice. Long/flat, single-name "
        "timing; engine TP=15% / SL=8%.",
        transform=ax.transAxes,
        ha="center",
        fontsize=8,
        color="#666",
    )
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(f"\nSaved chart: {out}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

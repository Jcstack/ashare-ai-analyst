#!/usr/bin/env python3
"""Qlib data updater — extends Qlib binary data from cached parquet files.

Reads daily OHLCV parquet files from ``data/raw/{symbol}_daily_*.parquet``
and appends them to the Qlib binary data at ``~/.qlib/qlib_data/cn_data/``.

Also supports fetching fresh data via AKShare when network is available.

The Qlib binary format:
- ``calendars/day.txt``: one date per line (YYYY-MM-DD), all trading days
- ``instruments/all.txt``: tab-separated ``SYMBOL\\tSTART\\tEND``
- ``features/{SYMBOL}/*.day.bin``: float32 arrays indexed by calendar position

Usage:
    # From cached parquet files (works offline)
    python scripts/qlib_data_updater.py --from-cache

    # From AKShare (needs network)
    python scripts/qlib_data_updater.py --from-akshare --symbols 600519,000001

    # Show current data status
    python scripts/qlib_data_updater.py --status
"""

from __future__ import annotations

import argparse
import glob
import os
import struct
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()  # Load .env (AKSHARE_PROXY_TOKEN, etc.) for CLI usage

# Ensure project root on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

QLIB_DATA_DIR = Path(os.path.expanduser("~/.qlib/qlib_data/cn_data"))
CALENDAR_FILE = QLIB_DATA_DIR / "calendars" / "day.txt"
INSTRUMENTS_FILE = QLIB_DATA_DIR / "instruments" / "all.txt"
FEATURES_DIR = QLIB_DATA_DIR / "features"

# Feature columns: parquet column → Qlib binary filename
FEATURE_MAP = {
    "open": "open.day.bin",
    "close": "close.day.bin",
    "high": "high.day.bin",
    "low": "low.day.bin",
    "volume": "volume.day.bin",
}


def _to_qlib_code(symbol: str) -> str:
    """Convert 6-digit stock code to Qlib format (SH/SZ prefix)."""
    if symbol.startswith("6") or symbol.startswith("9"):
        return f"SH{symbol}"
    return f"SZ{symbol}"


def load_calendar() -> list[str]:
    """Load the Qlib trading calendar.

    Raises:
        FileNotFoundError: If the calendar file does not exist.
    """
    if not CALENDAR_FILE.exists():
        raise FileNotFoundError(f"Calendar not found: {CALENDAR_FILE}")
    with open(CALENDAR_FILE) as f:
        return [line.strip() for line in f if line.strip()]


def load_instruments() -> dict[str, tuple[str, str]]:
    """Load instrument start/end dates. Returns {symbol: (start, end)}."""
    instruments: dict[str, tuple[str, str]] = {}
    if not INSTRUMENTS_FILE.exists():
        return instruments
    with open(INSTRUMENTS_FILE) as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                instruments[parts[0]] = (parts[1], parts[2])
    return instruments


def save_calendar(calendar: list[str]) -> None:
    """Write the calendar back to disk."""
    with open(CALENDAR_FILE, "w") as f:
        for date in calendar:
            f.write(date + "\n")


def save_instruments(instruments: dict[str, tuple[str, str]]) -> None:
    """Write instruments back to disk."""
    with open(INSTRUMENTS_FILE, "w") as f:
        for symbol in sorted(instruments.keys()):
            start, end = instruments[symbol]
            f.write(f"{symbol}\t{start}\t{end}\n")


def append_float32(filepath: Path, values: list[float]) -> None:
    """Append float32 values to a binary file."""
    with open(filepath, "ab") as f:
        for val in values:
            f.write(struct.pack("<f", val))


def read_float32_count(filepath: Path) -> int:
    """Count float32 values in a binary file."""
    if not filepath.exists():
        return 0
    return filepath.stat().st_size // 4


def generate_trading_calendar(start_date: str, end_date: str) -> list[str]:
    """Generate approximate A-share trading calendar between dates.

    Uses weekday filtering (Mon-Fri) as a basic approximation.
    Major holidays are excluded based on known patterns.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    # Known A-share holidays (approximate — major ones)
    # This is a simplified calendar; real production would use exchange data
    holidays = set()

    # Chinese New Year (approximate weeks)
    cny_ranges = [
        ("2021-02-10", "2021-02-17"),
        ("2022-01-31", "2022-02-06"),
        ("2023-01-21", "2023-01-27"),
        ("2024-02-09", "2024-02-17"),
        ("2025-01-28", "2025-02-04"),
        ("2026-02-17", "2026-02-23"),
    ]
    for h_start, h_end in cny_ranges:
        d = datetime.strptime(h_start, "%Y-%m-%d")
        d_end = datetime.strptime(h_end, "%Y-%m-%d")
        while d <= d_end:
            holidays.add(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)

    # National Day (Oct 1-7)
    for year in range(2020, 2027):
        for day in range(1, 8):
            holidays.add(f"{year}-10-{day:02d}")

    # Other holidays (simplified)
    for year in range(2020, 2027):
        holidays.add(f"{year}-01-01")  # New Year
        holidays.add(f"{year}-05-01")  # Labor Day
        holidays.add(f"{year}-05-02")
        holidays.add(f"{year}-05-03")

    trading_days: list[str] = []
    current = start
    while current <= end:
        ds = current.strftime("%Y-%m-%d")
        # Weekday (Mon=0, Sun=6) and not a holiday
        if current.weekday() < 5 and ds not in holidays:
            trading_days.append(ds)
        current += timedelta(days=1)

    return trading_days


def compute_change_and_factor(
    df: pd.DataFrame,
) -> tuple[list[float], list[float]]:
    """Compute change (pct return) and factor (adjustment ratio) from OHLCV.

    Qlib 'change' = daily return = (close - prev_close) / prev_close
    Qlib 'factor' = adjustment factor (we use 1.0 for non-adjusted data,
    or compute from raw vs adjusted close if both available).
    """
    changes: list[float] = []
    factors: list[float] = []

    closes = df["close"].tolist()
    for i in range(len(closes)):
        if i == 0:
            changes.append(0.0)
        else:
            prev = closes[i - 1]
            if prev != 0:
                changes.append((closes[i] - prev) / prev)
            else:
                changes.append(0.0)
        # Factor: use 1.0 for forward-adjusted (qfq) data
        # The existing Qlib data uses adj factor; for new data we approximate
        factors.append(1.0)

    return changes, factors


def load_parquet_data(symbol: str) -> pd.DataFrame | None:
    """Load and merge all parquet files for a symbol."""
    pattern = str(_PROJECT_ROOT / f"data/raw/{symbol}_daily_*.parquet")
    files = sorted(glob.glob(pattern))
    if not files:
        return None

    dfs: list[pd.DataFrame] = []
    for f in files:
        try:
            df = pd.read_parquet(f)
            dfs.append(df)
        except Exception as exc:
            print(f"  Warning: failed to read {f}: {exc}")

    if not dfs:
        return None

    merged = pd.concat(dfs, ignore_index=True)
    # Ensure date column is string
    if "date" in merged.columns:
        merged["date"] = pd.to_datetime(merged["date"]).dt.strftime("%Y-%m-%d")
        merged = merged.drop_duplicates(subset=["date"]).sort_values("date")
    return merged


def update_symbol_from_df(
    symbol: str,
    df: pd.DataFrame,
    calendar: list[str],
    instruments: dict[str, tuple[str, str]],
    calendar_set: set[str],
) -> int:
    """Update Qlib binary data for one symbol from a DataFrame.

    Returns the number of new trading days appended.
    """
    qlib_code = _to_qlib_code(symbol)
    feat_dir = FEATURES_DIR / qlib_code

    if not feat_dir.exists():
        # New symbol not in existing Qlib data — create directory
        feat_dir.mkdir(parents=True, exist_ok=True)

    # Get current instrument range
    inst_start, inst_end = instruments.get(qlib_code, (None, None))

    if inst_end is None:
        # New symbol — find first date in data
        first_date = df["date"].iloc[0]
        inst_start = first_date
        inst_end = first_date

    # Filter df to dates after the current instrument end
    new_df = df[df["date"] > inst_end].copy()
    if new_df.empty:
        return 0

    # Only include dates that are in the calendar
    new_df = new_df[new_df["date"].isin(calendar_set)]
    if new_df.empty:
        return 0

    new_df = new_df.sort_values("date").reset_index(drop=True)

    # Compute change and factor
    changes, factors = compute_change_and_factor(new_df)

    # Find calendar positions for gap-filling
    # Between inst_end and new data, there may be calendar days without data → fill NaN
    end_idx = calendar.index(inst_end) if inst_end in calendar_set else -1

    # For each feature, we need to append values for ALL calendar days from
    # inst_end+1 to the last new data date, filling NaN for missing days
    new_dates = new_df["date"].tolist()
    last_new_date = new_dates[-1]
    last_new_idx = calendar.index(last_new_date)

    # Build a date→row mapping
    date_to_row: dict[str, int] = {d: i for i, d in enumerate(new_dates)}

    # For each calendar day from inst_end+1 to last_new_date
    nan_val = float("nan")
    values_map: dict[str, list[float]] = {
        "open.day.bin": [],
        "close.day.bin": [],
        "high.day.bin": [],
        "low.day.bin": [],
        "volume.day.bin": [],
        "change.day.bin": [],
        "factor.day.bin": [],
    }

    for cal_idx in range(end_idx + 1, last_new_idx + 1):
        cal_date = calendar[cal_idx]
        if cal_date in date_to_row:
            row_idx = date_to_row[cal_date]
            row = new_df.iloc[row_idx]
            values_map["open.day.bin"].append(float(row["open"]))
            values_map["close.day.bin"].append(float(row["close"]))
            values_map["high.day.bin"].append(float(row["high"]))
            values_map["low.day.bin"].append(float(row["low"]))
            values_map["volume.day.bin"].append(float(row["volume"]))
            values_map["change.day.bin"].append(changes[row_idx])
            values_map["factor.day.bin"].append(factors[row_idx])
        else:
            # Calendar day exists but no data for this symbol → NaN
            for key in values_map:
                values_map[key].append(nan_val)

    # Append to binary files
    count = len(values_map["close.day.bin"])
    for filename, values in values_map.items():
        append_float32(feat_dir / filename, values)

    # Update instrument end date
    instruments[qlib_code] = (inst_start, last_new_date)

    return count


def get_qlib_status() -> dict:
    """Return structured Qlib data status dict.

    Used by Celery tasks and API endpoints. Does not print or sys.exit.
    """
    if not QLIB_DATA_DIR.exists():
        return {"error": f"Qlib data directory not found: {QLIB_DATA_DIR}"}

    calendar = load_calendar()
    instruments = load_instruments()

    # Sample key symbols
    sample_symbols: dict[str, dict] = {}
    for sym in ["SH600519", "SZ000001", "SZ000858"]:
        if sym in instruments:
            start, end = instruments[sym]
            feat_dir = FEATURES_DIR / sym
            close_bin = feat_dir / "close.day.bin"
            n_values = read_float32_count(close_bin) if close_bin.exists() else 0
            sample_symbols[sym] = {
                "start": start,
                "end": end,
                "values": n_values,
            }

    # Check parquet data availability
    pattern = str(_PROJECT_ROOT / "data/raw/*_daily_*.parquet")
    files = glob.glob(pattern)
    symbols_in_cache: set[str] = set()
    for f in files:
        base = os.path.basename(f)
        sym = base.split("_daily_")[0]
        if sym.isdigit() and len(sym) == 6:
            symbols_in_cache.add(sym)

    parquet_cache: dict = {"symbols": len(symbols_in_cache)}
    if symbols_in_cache:
        all_dates: set[str] = set()
        for f in files[:5]:
            try:
                df = pd.read_parquet(f)
                if "date" in df.columns:
                    dates = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                    all_dates.update(dates.tolist())
            except Exception:
                pass
        if all_dates:
            parquet_cache["date_range"] = {
                "start": min(all_dates),
                "end": max(all_dates),
            }

    return {
        "data_dir": str(QLIB_DATA_DIR),
        "exists": True,
        "calendar": {
            "start": calendar[0],
            "end": calendar[-1],
            "count": len(calendar),
        },
        "instruments": len(instruments),
        "sample_symbols": sample_symbols,
        "parquet_cache": parquet_cache,
    }


def cmd_status() -> None:
    """Show current Qlib data status (CLI entry point)."""
    result = get_qlib_status()
    if "error" in result:
        print(result["error"])
        return

    cal = result["calendar"]
    print(f"Qlib data: {result['data_dir']}")
    print(f"Calendar: {cal['start']} — {cal['end']} ({cal['count']} trading days)")
    print(f"Instruments: {result['instruments']} symbols")

    for sym, info in result.get("sample_symbols", {}).items():
        print(f"  {sym}: {info['start']} — {info['end']} ({info['values']} values)")

    cache = result.get("parquet_cache", {})
    print(f"\nCached parquet data: {cache.get('symbols', 0)} symbols")
    dr = cache.get("date_range")
    if dr:
        print(f"  Date range: {dr['start']} — {dr['end']}")


def update_from_cache() -> dict:
    """Update Qlib binary data from cached parquet files. Returns result dict.

    Used by Celery tasks and CLI. Does not print or sys.exit.
    """
    if not QLIB_DATA_DIR.exists():
        return {"error": f"Qlib data directory not found: {QLIB_DATA_DIR}"}

    calendar = load_calendar()
    instruments = load_instruments()
    calendar_set = set(calendar)

    # Discover all parquet symbols
    pattern = str(_PROJECT_ROOT / "data/raw/*_daily_*.parquet")
    files = glob.glob(pattern)
    symbols: set[str] = set()
    for f in files:
        base = os.path.basename(f)
        sym = base.split("_daily_")[0]
        if sym.isdigit() and len(sym) == 6:
            symbols.add(sym)

    if not symbols:
        return {"error": "No parquet data found in data/raw/"}

    # Extend the calendar with new trading days
    all_dates: set[str] = set()
    for sym in symbols:
        df = load_parquet_data(sym)
        if df is not None and "date" in df.columns:
            all_dates.update(df["date"].tolist())

    new_dates = sorted(d for d in all_dates if d not in calendar_set)
    calendar_extended = False
    if new_dates:
        old_end = calendar[-1]
        new_end = max(new_dates)
        generated = generate_trading_calendar(old_end, new_end)
        for d in generated:
            if d not in calendar_set:
                calendar.append(d)
                calendar_set.add(d)
        for d in new_dates:
            if d not in calendar_set:
                calendar.append(d)
                calendar_set.add(d)
        calendar.sort()
        save_calendar(calendar)
        calendar_extended = True

    # Update each symbol
    total_appended = 0
    updated_count = 0
    for sym in sorted(symbols):
        df = load_parquet_data(sym)
        if df is None or df.empty:
            continue

        n = update_symbol_from_df(sym, df, calendar, instruments, calendar_set)
        if n > 0:
            total_appended += n
            updated_count += 1

    save_instruments(instruments)

    return {
        "updated_symbols": updated_count,
        "total_symbols": len(symbols),
        "total_days": total_appended,
        "calendar_end": calendar[-1],
        "calendar_count": len(calendar),
        "calendar_extended": calendar_extended,
    }


def cmd_from_cache() -> None:
    """Update Qlib data from cached parquet files (CLI entry point)."""
    result = update_from_cache()

    if "error" in result:
        print(result["error"])
        sys.exit(1)

    print(
        f"Done: updated {result['updated_symbols']}/{result['total_symbols']} symbols, "
        f"{result['total_days']} total new days"
    )
    print(
        f"Calendar: ends {result['calendar_end']} "
        f"({result['calendar_count']} trading days)"
    )
    if result["calendar_extended"]:
        print("Calendar was extended with new trading days")


def update_from_akshare(symbols: list[str], start_date: str, end_date: str) -> dict:
    """Core AKShare → Qlib update logic (shared by CLI and external callers).

    Returns a result dict with keys: updated, total_days, calendar_end, errors.
    """
    try:
        import akshare as ak
    except ImportError:
        return {"error": "AKShare not installed"}

    from src.data.eastmoney_proxy import em_api_call

    if not QLIB_DATA_DIR.exists():
        return {"error": f"Qlib data directory not found: {QLIB_DATA_DIR}"}

    calendar = load_calendar()
    instruments = load_instruments()
    calendar_set = set(calendar)

    all_dates: set[str] = set()
    symbol_dfs: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    for sym in symbols:
        try:
            df = em_api_call(
                ak.stock_zh_a_hist,
                symbol=sym,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",
            )
            if df is not None and not df.empty:
                col_map = {
                    "日期": "date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                }
                df = df.rename(columns=col_map)
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                symbol_dfs[sym] = df
                all_dates.update(df["date"].tolist())
        except Exception as exc:
            errors.append(f"{sym}: {exc}")

    if not symbol_dfs:
        return {"error": "No data fetched", "errors": errors}

    # Extend calendar
    new_dates = sorted(d for d in all_dates if d not in calendar_set)
    if new_dates:
        old_end = calendar[-1]
        new_end = max(new_dates)
        generated = generate_trading_calendar(old_end, new_end)
        for d in generated:
            if d not in calendar_set:
                calendar.append(d)
                calendar_set.add(d)
        for d in new_dates:
            if d not in calendar_set:
                calendar.append(d)
                calendar_set.add(d)
        calendar.sort()
        save_calendar(calendar)

    # Update each symbol
    total = 0
    updated_count = 0
    for sym, df in symbol_dfs.items():
        n = update_symbol_from_df(sym, df, calendar, instruments, calendar_set)
        if n > 0:
            total += n
            updated_count += 1

    save_instruments(instruments)

    return {
        "updated": updated_count,
        "total_days": total,
        "calendar_end": calendar[-1],
        "fetched": len(symbol_dfs),
        "errors": errors,
    }


def cmd_from_akshare(symbols: list[str], start_date: str, end_date: str) -> None:
    """Fetch data from AKShare and update Qlib binary data (CLI entry point)."""
    print(f"Fetching data for {len(symbols)} symbols: {start_date} — {end_date}")

    result = update_from_akshare(symbols, start_date, end_date)

    if "error" in result:
        print(result["error"])
        if result.get("errors"):
            for err in result["errors"]:
                print(f"  {err}")
        sys.exit(1)

    for err in result.get("errors", []):
        print(f"  Warning: {err}")

    print(
        f"\nDone: {result['total_days']} total new days across "
        f"{result['fetched']} symbols ({result['updated']} updated)"
    )
    print(f"Calendar end: {result['calendar_end']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Qlib data updater")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="Show data status")
    group.add_argument(
        "--from-cache", action="store_true", help="Update from cached parquet files"
    )
    group.add_argument(
        "--from-akshare", action="store_true", help="Fetch from AKShare and update"
    )
    parser.add_argument(
        "--symbols", type=str, default="", help="Symbols for --from-akshare"
    )
    parser.add_argument(
        "--start-date", type=str, default="2020-09-28", help="Start date"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date",
    )

    args = parser.parse_args()

    try:
        _dispatch_command(args)
    except FileNotFoundError as exc:
        print(str(exc))
        sys.exit(1)


def _dispatch_command(args: argparse.Namespace) -> None:
    """Dispatch CLI sub-commands."""
    if args.status:
        cmd_status()
    elif args.from_cache:
        cmd_from_cache()
    elif args.from_akshare:
        if not args.symbols:
            print("--symbols required with --from-akshare")
            sys.exit(1)
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        cmd_from_akshare(symbols, args.start_date, args.end_date)


if __name__ == "__main__":
    main()

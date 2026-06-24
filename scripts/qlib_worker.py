#!/usr/bin/env python3
"""Qlib worker — runs inside .venv-qlib (Python 3.11) as a subprocess.

Called by QlibAdapter via subprocess when Qlib is not available in the
main Python 3.13 venv. Receives commands via CLI args, returns JSON to stdout.

Calendar-aware: automatically detects the available data range and queries
within it, so predictions work even with stale pre-downloaded data.

Usage (called by QlibAdapter, not directly):
    .venv-qlib/bin/python scripts/qlib_worker.py predict --symbols 600519,000001 --horizon 5
    .venv-qlib/bin/python scripts/qlib_worker.py ic --symbol 600519
    .venv-qlib/bin/python scripts/qlib_worker.py alpha --symbol 600519
    .venv-qlib/bin/python scripts/qlib_worker.py health
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# Ensure project root on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import yaml  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_research_config() -> dict[str, Any]:
    config_path = _PROJECT_ROOT / "config" / "research.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_RESEARCH_CFG = _load_research_config()
_ACTUARY_CFG = _RESEARCH_CFG.get("actuary", {})

# ---------------------------------------------------------------------------
# Qlib init
# ---------------------------------------------------------------------------

_INITIALIZED = False
_CALENDAR_END: str | None = None  # Last available trading day (e.g. "2020-09-25")
_CALENDAR_START: str | None = None


def _ensure_init() -> bool:
    global _INITIALIZED, _CALENDAR_END, _CALENDAR_START
    if _INITIALIZED:
        return True
    try:
        import qlib
        from qlib.config import REG_CN

        provider_uri = _ACTUARY_CFG.get(
            "qlib_provider_uri", "~/.qlib/qlib_data/cn_data"
        )
        qlib.init(provider_uri=provider_uri, region=REG_CN)
        _INITIALIZED = True

        # Detect calendar range for smart date queries
        from qlib.data import D

        cal = D.calendar(freq="day")
        if cal is not None and len(cal) > 0:
            _CALENDAR_START = str(cal[0])[:10]
            _CALENDAR_END = str(cal[-1])[:10]

        return True
    except Exception as exc:
        print(json.dumps({"error": f"Qlib init failed: {exc}"}))
        sys.exit(1)


def _get_query_start(days_back: int) -> str:
    """Compute a start_time that falls within available calendar data.

    If the calendar ends at 2020-09-25 and we ask for 60 days back,
    returns "2020-07-27" (not "2025-12-31" which has no data).
    """
    if _CALENDAR_END is None:
        # Fallback: use a safe old date
        return "2020-01-01"

    from datetime import datetime, timedelta

    end_dt = datetime.strptime(_CALENDAR_END, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=days_back)
    return start_dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _to_qlib_code(symbol: str) -> str:
    if symbol.startswith("6") or symbol.startswith("9"):
        return f"SH{symbol}"
    return f"SZ{symbol}"


def cmd_health() -> dict[str, Any]:
    try:
        import qlib

        # Also init to get calendar info
        if not _INITIALIZED:
            _ensure_init()

        return {
            "installed": True,
            "version": qlib.__version__,
            "initialized": _INITIALIZED,
            "provider_uri": _ACTUARY_CFG.get(
                "qlib_provider_uri", "~/.qlib/qlib_data/cn_data"
            ),
            "calendar_start": _CALENDAR_START,
            "calendar_end": _CALENDAR_END,
        }
    except ImportError:
        return {"installed": False}


def cmd_predict(symbols: list[str], horizon: int) -> dict[str, dict[str, Any]]:
    _ensure_init()
    from qlib.data import D

    results: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        try:
            qc = _to_qlib_code(symbol)

            # Query within available data range
            start_time = _get_query_start(horizon * 3)
            fields = ["$close/Ref($close, 1) - 1"]
            data = D.features(
                [qc],
                fields=fields,
                start_time=start_time,
                end_time=_CALENDAR_END,
            )

            score = None
            ic = None
            if data is not None and not data.empty:
                returns = data.iloc[:, 0].dropna()
                if len(returns) >= 2:
                    # Use mean recent return as raw score, sigmoid to [0,1]
                    raw = float(returns.mean()) * 100  # scale up
                    score = round(1.0 / (1.0 + math.exp(-raw)), 4)
                    # IC: autocorrelation of returns as proxy
                    if len(returns) >= 10:
                        ic = round(float(returns.autocorr()), 4)

            # Alpha factors
            alpha = _get_alpha_factors_for(qc)

            results[symbol] = {
                "score": score,
                "ic": ic,
                "features": _ACTUARY_CFG.get("features", ["Alpha158"]),
                "alpha_factors": alpha,
                "horizon": horizon,
                "model": _ACTUARY_CFG.get("default_model", "LGBModel"),
                "data_end": _CALENDAR_END,
            }
        except Exception as exc:
            results[symbol] = {
                "score": None,
                "ic": None,
                "features": [],
                "alpha_factors": None,
                "horizon": horizon,
                "error": str(exc),
            }
    return results


def _get_alpha_factors_for(qlib_code: str) -> dict[str, float] | None:
    """Compute alpha factors for a single Qlib code."""
    from qlib.data import D

    # Query last 120 days of available data (need lookback for 60d indicators)
    start_time = _get_query_start(120)

    factor_exprs = [
        # Momentum (5 factors)
        ("momentum_5d", "$close/Ref($close, 5) - 1"),
        ("momentum_10d", "$close/Ref($close, 10) - 1"),
        ("momentum_20d", "$close/Ref($close, 20) - 1"),
        ("momentum_60d", "$close/Ref($close, 60) - 1"),
        ("roc_10d", "($close - Ref($close, 10)) / Ref($close, 10)"),
        # Reversal (3 factors)
        ("mean_reversion_5d", "Mean($close, 5) / $close - 1"),
        ("mean_reversion_20d", "Mean($close, 20) / $close - 1"),
        ("high_low_ratio_20d", "($high - $low) / Mean($close, 20)"),
        # Volatility (3 factors)
        ("volatility_5d", "Std($close, 5) / Mean($close, 5)"),
        ("volatility_20d", "Std($close, 20) / Mean($close, 20)"),
        (
            "atr_14d",
            "Mean(If($high - $low > Abs($high - Ref($close, 1)), "
            "If($high - $low > Abs($low - Ref($close, 1)), $high - $low, Abs($low - Ref($close, 1))), "
            "If(Abs($high - Ref($close, 1)) > Abs($low - Ref($close, 1)), Abs($high - Ref($close, 1)), Abs($low - Ref($close, 1)))), 14) / $close",
        ),
        # Volume/Liquidity (4 factors)
        ("turnover_ratio", "$volume / Ref($volume, 5)"),
        ("volume_ma_ratio_5_20", "Mean($volume, 5) / Mean($volume, 20)"),
        (
            "obv_slope",
            "Sum(If($close > Ref($close, 1), $volume, -$volume), 10) "
            "/ Sum($volume, 10)",
        ),
        (
            "vwap_deviation",
            "Sum($close * $volume, 5) / Sum($volume, 5) / $close - 1",
        ),
        # Price Pattern (3 factors)
        ("price_to_ma5", "$close / Mean($close, 5) - 1"),
        ("price_to_ma20", "$close / Mean($close, 20) - 1"),
        ("price_to_ma60", "$close / Mean($close, 60) - 1"),
        # Quality/Strength (2 factors)
        (
            "rsi_14",
            "100 - 100 / (1 + Mean(If($close - Ref($close, 1) > 0, $close - Ref($close, 1), 0), 14) "
            "/ Mean(If(Ref($close, 1) - $close > 0, Ref($close, 1) - $close, 0), 14))",
        ),
        (
            "upper_shadow_ratio",
            "($high - If($close > $open, $close, $open)) / ($high - $low + 1e-8)",
        ),
    ]
    factors: dict[str, float] = {}
    for name, expr in factor_exprs:
        try:
            data = D.features(
                [qlib_code],
                fields=[expr],
                start_time=start_time,
                end_time=_CALENDAR_END,
            )
            if data is not None and not data.empty:
                val = data.iloc[-1, 0]
                if val is not None and not (isinstance(val, float) and math.isnan(val)):
                    factors[name] = round(float(val), 6)
        except Exception:
            pass
    return factors if factors else None


def cmd_ic(symbol: str) -> dict[str, Any]:
    _ensure_init()
    from qlib.data import D

    qc = _to_qlib_code(symbol)
    lookback = _ACTUARY_CFG.get("ic_lookback_days", 60)

    try:
        start_time = _get_query_start(lookback)
        data = D.features(
            [qc],
            fields=["$close/Ref($close, 1) - 1"],
            start_time=start_time,
            end_time=_CALENDAR_END,
        )
        if data is None or data.empty or len(data) < 10:
            return {"symbol": symbol, "ic": None, "reason": "insufficient data"}

        ic_val = float(data.iloc[:, 0].dropna().autocorr())
        threshold = _ACTUARY_CFG.get("ic_threshold", 0.03)
        return {
            "symbol": symbol,
            "ic": round(ic_val, 4),
            "valid": abs(ic_val) >= threshold,
            "threshold": threshold,
            "data_end": _CALENDAR_END,
        }
    except Exception as exc:
        return {"symbol": symbol, "ic": None, "error": str(exc)}


def cmd_alpha(symbol: str) -> dict[str, Any]:
    _ensure_init()
    qc = _to_qlib_code(symbol)
    factors = _get_alpha_factors_for(qc)
    return {"symbol": symbol, "alpha_factors": factors, "data_end": _CALENDAR_END}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Qlib worker subprocess")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("health")

    p_predict = sub.add_parser("predict")
    p_predict.add_argument("--symbols", required=True)
    p_predict.add_argument("--horizon", type=int, default=5)

    p_ic = sub.add_parser("ic")
    p_ic.add_argument("--symbol", required=True)

    p_alpha = sub.add_parser("alpha")
    p_alpha.add_argument("--symbol", required=True)

    args = parser.parse_args()

    if args.command == "health":
        result = cmd_health()
    elif args.command == "predict":
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        result = cmd_predict(symbols, args.horizon)
    elif args.command == "ic":
        result = cmd_ic(args.symbol)
    elif args.command == "alpha":
        result = cmd_alpha(args.symbol)
    else:
        parser.print_help()
        sys.exit(1)

    # JSON output to stdout (only line that matters for subprocess communication)
    # Replace NaN/Inf with None for valid JSON
    def _sanitize(obj: Any) -> Any:
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize(v) for v in obj]
        return obj

    print(json.dumps(_sanitize(result), ensure_ascii=False))


if __name__ == "__main__":
    main()

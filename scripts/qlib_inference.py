#!/usr/bin/env python3
"""Qlib inference CLI — standalone prediction via QlibAdapter.

Usage:
    python scripts/qlib_inference.py [--symbols 600519,000001] [--horizon 5] [--output json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure project root on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.prediction.qlib_adapter import QlibAdapter  # noqa: E402
from src.utils.config import load_config  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger("scripts.qlib_inference")


def run_inference(
    symbols: list[str],
    horizon: int = 5,
    output_format: str = "text",
) -> dict[str, dict[str, Any]]:
    """Run Qlib inference for given symbols.

    Args:
        symbols: List of 6-digit stock codes.
        horizon: Prediction horizon in trading days.
        output_format: Output format ("text" or "json").

    Returns:
        Prediction results dict.
    """
    adapter = QlibAdapter()

    if not adapter.is_available():
        msg = adapter.get_health_info()
        print(f"Qlib not available: {msg}")
        return {}

    results = adapter.predict(symbols, horizon=horizon)

    if output_format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for symbol, pred in results.items():
            score = pred.get("score", "N/A")
            ic = pred.get("ic", "N/A")
            error = pred.get("error", "")
            status = f"  error: {error}" if error else ""
            print(f"{symbol}: score={score}, IC={ic}, horizon={horizon}d{status}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Qlib inference CLI")
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Comma-separated stock codes (e.g. 600519,000001)",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=5,
        help="Prediction horizon in trading days (default: 5)",
    )
    parser.add_argument(
        "--output",
        type=str,
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    # Load default symbols from config
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        try:
            config = load_config("research")
            symbols = config.get("orchestration", {}).get("default_symbols", [])
        except FileNotFoundError:
            symbols = []

    if not symbols:
        print("No symbols specified. Use --symbols or configure default_symbols.")
        sys.exit(1)

    run_inference(symbols, horizon=args.horizon, output_format=args.output)


if __name__ == "__main__":
    main()

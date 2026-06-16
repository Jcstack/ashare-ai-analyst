#!/usr/bin/env python3
"""Alpha factor IC validation — verifies Qlib prediction quality.

Checks the Information Coefficient (IC) for Qlib predictions to
determine if the quantitative model is still producing valid signals.

Used by the ``/deep-research`` skill to validate actuary quality
before incorporating Qlib scores into the final report.

Usage:
    python scripts/check_alpha.py [--symbols 600519,000001] [--threshold 0.03]
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

logger = get_logger("scripts.check_alpha")


def check_alpha(
    symbols: list[str],
    ic_threshold: float = 0.03,
) -> dict[str, Any]:
    """Validate IC values for given symbols.

    Args:
        symbols: List of 6-digit stock codes.
        ic_threshold: Minimum IC to consider valid.

    Returns:
        Validation result dict with per-symbol IC and overall status.
    """
    adapter = QlibAdapter()
    result: dict[str, Any] = {
        "qlib_available": adapter.is_available(),
        "ic_threshold": ic_threshold,
        "symbols": {},
        "overall_valid": False,
    }

    if not adapter.is_available():
        print("Qlib not available — IC validation skipped")
        result["message"] = "Qlib not installed or not initialized"
        return result

    valid_count = 0
    for symbol in symbols:
        ic = adapter.get_ic_value(symbol)
        is_valid = ic is not None and abs(ic) >= ic_threshold
        result["symbols"][symbol] = {
            "ic": ic,
            "valid": is_valid,
        }
        if is_valid:
            valid_count += 1

    result["overall_valid"] = valid_count > 0
    result["valid_count"] = valid_count
    result["total_count"] = len(symbols)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Alpha factor IC validation")
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Comma-separated stock codes (e.g. 600519,000001)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.03,
        help="IC threshold (default: 0.03)",
    )
    parser.add_argument(
        "--output",
        type=str,
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    # Load default symbols
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

    result = check_alpha(symbols, ic_threshold=args.threshold)

    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Qlib available: {result['qlib_available']}")
        print(f"IC threshold: {result['ic_threshold']}")
        for symbol, data in result.get("symbols", {}).items():
            ic_str = f"{data['ic']:.4f}" if data["ic"] is not None else "N/A"
            status = "VALID" if data["valid"] else "INVALID"
            print(f"  {symbol}: IC={ic_str} [{status}]")
        print(
            f"Overall: {result.get('valid_count', 0)}/{result.get('total_count', 0)} valid"
        )


if __name__ == "__main__":
    main()

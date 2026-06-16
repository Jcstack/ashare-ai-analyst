"""Shared utility functions for web layer route handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


def sanitize_records(records: list[dict]) -> list[dict]:
    """Replace NaN with None and datetime objects with strings.

    Eliminates the repetitive per-handler cleanup pattern::

        for rec in records:
            for key, val in rec.items():
                if isinstance(val, float) and val != val:
                    rec[key] = None
                elif hasattr(val, "strftime"):
                    rec[key] = str(val)

    Args:
        records: List of dicts (typically from ``DataFrame.to_dict(orient="records")``).

    Returns:
        The same list, mutated in-place for efficiency.
    """
    for rec in records:
        for key, val in rec.items():
            if isinstance(val, float) and val != val:  # NaN check
                rec[key] = None
            elif hasattr(val, "strftime"):
                rec[key] = str(val)
    return records


def df_to_records(
    df: pd.DataFrame,
    columns: list[str] | None = None,
) -> list[dict]:
    """Convert a DataFrame to JSON-safe records with NaN/datetime cleanup.

    Args:
        df: Source DataFrame.
        columns: Optional column subset. If provided, only these columns
            are included in the output.

    Returns:
        List of sanitized dicts ready for JSON serialization.
    """
    if columns is not None:
        available = [c for c in columns if c in df.columns]
        records = df[available].to_dict(orient="records")
    else:
        records = df.to_dict(orient="records")
    return sanitize_records(records)

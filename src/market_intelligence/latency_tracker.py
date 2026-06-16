"""Latency tracker — end-to-end signal pipeline latency metrics.

Part of v20.0 Phase 7: Observability.

Tracks latency measurements across the signal pipeline, providing
P50/P95/P99 percentile statistics and per-source breakdowns.
Uses a rolling window of 10,000 measurements to bound memory.
"""

from __future__ import annotations

import logging
import statistics
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)

_MAX_WINDOW = 10_000


class LatencyTracker:
    """Track end-to-end signal pipeline latency metrics."""

    def __init__(self) -> None:
        self._measurements: list[float] = []  # milliseconds
        self._source_measurements: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def record(self, latency_ms: float, source: str | None = None) -> None:
        """Record a latency measurement.

        Args:
            latency_ms: Latency in milliseconds.
            source: Optional source identifier (e.g. "akshare", "llm", "signal_bus").
        """
        with self._lock:
            self._measurements.append(latency_ms)
            if len(self._measurements) > _MAX_WINDOW:
                self._measurements = self._measurements[-_MAX_WINDOW:]

            if source is not None:
                src_list = self._source_measurements[source]
                src_list.append(latency_ms)
                if len(src_list) > _MAX_WINDOW:
                    self._source_measurements[source] = src_list[-_MAX_WINDOW:]

    def get_percentiles(self) -> dict:
        """Return P50/P95/P99 latency stats.

        Returns:
            Dictionary with keys: p50, p95, p99, count, mean.
            All latency values are in milliseconds.
            Returns zeros if no measurements recorded.
        """
        with self._lock:
            if not self._measurements:
                return {
                    "p50": 0.0,
                    "p95": 0.0,
                    "p99": 0.0,
                    "count": 0,
                    "mean": 0.0,
                }
            return _compute_stats(self._measurements)

    def get_source_latency(self) -> dict[str, dict]:
        """Return per-source latency stats.

        Returns:
            Dictionary mapping source name to its P50/P95/P99/count/mean stats.
        """
        with self._lock:
            result: dict[str, dict] = {}
            for source, measurements in self._source_measurements.items():
                if measurements:
                    result[source] = _compute_stats(measurements)
            return result

    def reset(self) -> None:
        """Clear all measurements (called on rotation)."""
        with self._lock:
            self._measurements.clear()
            self._source_measurements.clear()
            logger.info("Latency tracker reset")


def _compute_stats(data: list[float]) -> dict:
    """Compute percentile statistics for a list of measurements.

    Args:
        data: Non-empty list of latency values in milliseconds.

    Returns:
        Dictionary with p50, p95, p99, count, mean.
    """
    sorted_data = sorted(data)
    count = len(sorted_data)
    return {
        "p50": round(statistics.median(sorted_data), 2),
        "p95": round(_percentile(sorted_data, 0.95), 2),
        "p99": round(_percentile(sorted_data, 0.99), 2),
        "count": count,
        "mean": round(statistics.mean(sorted_data), 2),
    }


def _percentile(sorted_data: list[float], pct: float) -> float:
    """Compute a percentile from pre-sorted data.

    Uses the nearest-rank method for consistency.

    Args:
        sorted_data: Sorted list of values.
        pct: Percentile as a fraction (0.0 - 1.0).

    Returns:
        The value at the given percentile.
    """
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    idx = int(pct * (n - 1))
    return sorted_data[min(idx, n - 1)]

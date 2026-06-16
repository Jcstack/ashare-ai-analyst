"""Data source health tracker — centralized monitoring.

Tracks success/failure/latency per data source (Sina, Tencent, East Money,
adata, Yahoo) and exposes health status for the admin dashboard.

Part of WS2: Data Source Verification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("data.health_tracker")

# Alert threshold: degraded for > 5 minutes
_DEGRADED_THRESHOLD_S = 300


@dataclass
class SourceHealth:
    """Health metrics for a single data source."""

    name: str
    total_calls: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0
    last_error: str = ""
    avg_latency_ms: float = 0.0
    _latencies: list[float] = field(default_factory=list, repr=False)

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.success_count / self.total_calls

    @property
    def status(self) -> str:
        """Return 'healthy', 'degraded', or 'down'."""
        if self.total_calls == 0:
            return "healthy"
        if self.failure_count == 0:
            return "healthy"
        now = time.time()
        if self.last_failure_ts > self.last_success_ts:
            elapsed = now - self.last_failure_ts
            if elapsed < _DEGRADED_THRESHOLD_S:
                return "degraded"
            return "down" if self.success_rate < 0.5 else "degraded"
        return "healthy" if self.success_rate >= 0.8 else "degraded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "total_calls": self.total_calls,
            "success_rate": round(self.success_rate, 3),
            "failure_count": self.failure_count,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "last_success": self.last_success_ts,
            "last_failure": self.last_failure_ts,
            "last_error": self.last_error[:200] if self.last_error else "",
        }


class DataHealthTracker:
    """Singleton tracker for data source health metrics.

    Usage::

        tracker = DataHealthTracker()
        tracker.record_success("sina", latency_ms=150)
        tracker.record_failure("eastmoney", error="timeout")
        health = tracker.get_all_health()
    """

    # Known data sources
    SOURCES = ("sina", "tencent", "eastmoney", "adata", "xueqiu", "yahoo")

    def __init__(self) -> None:
        self._sources: dict[str, SourceHealth] = {}
        for name in self.SOURCES:
            self._sources[name] = SourceHealth(name=name)

    def record_success(
        self,
        source: str,
        latency_ms: float = 0.0,
    ) -> None:
        """Record a successful data fetch.

        Args:
            source: Data source name (e.g. "sina").
            latency_ms: Request latency in milliseconds.
        """
        health = self._get_or_create(source)
        health.total_calls += 1
        health.success_count += 1
        health.last_success_ts = time.time()
        if latency_ms > 0:
            health._latencies.append(latency_ms)
            # Keep rolling window of 100 latencies
            if len(health._latencies) > 100:
                health._latencies = health._latencies[-100:]
            health.avg_latency_ms = sum(health._latencies) / len(health._latencies)

    def record_failure(
        self,
        source: str,
        error: str = "",
    ) -> None:
        """Record a failed data fetch.

        Args:
            source: Data source name.
            error: Error message.
        """
        health = self._get_or_create(source)
        health.total_calls += 1
        health.failure_count += 1
        health.last_failure_ts = time.time()
        health.last_error = error

        if health.status == "down":
            logger.warning(
                "Data source '%s' is DOWN: %d failures, last error: %s",
                source,
                health.failure_count,
                error[:100],
            )

    def get_health(self, source: str) -> dict[str, Any]:
        """Get health status for a single source."""
        health = self._sources.get(source)
        if not health:
            return {"name": source, "status": "unknown"}
        return health.to_dict()

    def get_all_health(self) -> dict[str, Any]:
        """Get health status for all tracked sources."""
        sources = {name: health.to_dict() for name, health in self._sources.items()}

        # Overall status
        statuses = [h.status for h in self._sources.values()]
        if "down" in statuses:
            overall = "degraded"
        elif "degraded" in statuses:
            overall = "degraded"
        else:
            overall = "healthy"

        return {
            "overall_status": overall,
            "sources": sources,
            "timestamp": time.time(),
        }

    def get_degraded_sources(self) -> list[str]:
        """Return names of sources that are degraded or down."""
        return [
            name
            for name, health in self._sources.items()
            if health.status in ("degraded", "down")
        ]

    def _get_or_create(self, source: str) -> SourceHealth:
        if source not in self._sources:
            self._sources[source] = SourceHealth(name=source)
        return self._sources[source]

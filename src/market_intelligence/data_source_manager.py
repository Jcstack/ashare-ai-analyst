"""Unified data source health management.

Tracks the availability and latency of external data sources (market data
APIs, news feeds, etc.) and routes requests to the healthiest provider.

Part of v20.0 Phase 5 market intelligence layer.
"""

from __future__ import annotations

import time
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("market_intelligence.data_source_manager")

# Source type → ordered list of provider names.
_DEFAULT_SOURCES: dict[str, list[str]] = {
    "market_data": ["tushare", "akshare", "eastmoney"],
    "news": ["sina_finance", "eastmoney_news", "cls_news"],
    "global_market": ["yahoo_finance", "investing_com"],
    "sentiment": ["xueqiu", "eastmoney_guba"],
}


class DataSourceManager:
    """Manage health status and routing for external data sources.

    Maintains a health record per source and selects the best available
    provider for a given data type.

    Args:
        health_tracker: Optional external health tracker instance. When
            provided, the manager delegates health state persistence to it.
    """

    def __init__(self, health_tracker: Any | None = None) -> None:
        self._health_tracker = health_tracker
        self._sources: dict[str, list[str]] = {
            k: list(v) for k, v in _DEFAULT_SOURCES.items()
        }
        # Internal health state: source_name → {"status", "last_check", "latency_ms", "error_count"}
        self._health: dict[str, dict[str, Any]] = {}

        # Bootstrap default health entries
        for providers in self._sources.values():
            for name in providers:
                if name not in self._health:
                    self._health[name] = {
                        "status": "healthy",
                        "last_check": _now(),
                        "latency_ms": 0,
                        "error_count": 0,
                    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_source_status(self) -> dict[str, Any]:
        """Get health status of all registered data sources.

        Returns:
            Dict keyed by data type, each mapping to a list of provider
            status dicts with name, status, latency_ms, error_count, and
            last_check.
        """
        result: dict[str, list[dict[str, Any]]] = {}

        for data_type, providers in self._sources.items():
            entries: list[dict[str, Any]] = []
            for name in providers:
                health = self._health.get(name, {})
                entries.append(
                    {
                        "name": name,
                        "status": health.get("status", "unknown"),
                        "latency_ms": health.get("latency_ms", 0),
                        "error_count": health.get("error_count", 0),
                        "last_check": health.get("last_check", ""),
                    }
                )
            result[data_type] = entries

        return {
            "sources": result,
            "overall_status": "degraded" if self.is_degraded() else "healthy",
            "timestamp": _now(),
        }

    def get_best_source(self, data_type: str) -> str:
        """Return the healthiest provider for *data_type*.

        Selection priority:
        1. Healthy sources, ordered by lowest latency.
        2. Degraded sources if no healthy ones exist.
        3. First configured source as ultimate fallback.

        Args:
            data_type: One of the keys in the source registry (e.g.
                ``"market_data"``, ``"news"``).

        Returns:
            Provider name string.
        """
        providers = self._sources.get(data_type, [])
        if not providers:
            logger.warning("Unknown data type requested: %s", data_type)
            return ""

        healthy: list[tuple[str, int]] = []
        degraded: list[tuple[str, int]] = []

        for name in providers:
            health = self._health.get(name, {})
            status = health.get("status", "unknown")
            latency = health.get("latency_ms", 9999)

            if status == "healthy":
                healthy.append((name, latency))
            elif status == "degraded":
                degraded.append((name, latency))

        if healthy:
            healthy.sort(key=lambda x: x[1])
            return healthy[0][0]
        if degraded:
            degraded.sort(key=lambda x: x[1])
            return degraded[0][0]

        # All down — return first provider as last resort
        return providers[0]

    def is_degraded(self) -> bool:
        """Return ``True`` if any critical data source is degraded or down.

        A source is considered critical if it belongs to the
        ``"market_data"`` or ``"news"`` categories.
        """
        critical_types = ("market_data", "news")
        for data_type in critical_types:
            providers = self._sources.get(data_type, [])
            for name in providers:
                health = self._health.get(name, {})
                status = health.get("status", "unknown")
                if status in ("degraded", "down", "unknown"):
                    return True
        return False

    # ------------------------------------------------------------------
    # Health state mutation (used by monitors / probes)
    # ------------------------------------------------------------------

    def report_success(self, source_name: str, latency_ms: int = 0) -> None:
        """Record a successful probe / request to *source_name*."""
        if source_name not in self._health:
            self._health[source_name] = {}

        self._health[source_name].update(
            {
                "status": "healthy",
                "last_check": _now(),
                "latency_ms": latency_ms,
                "error_count": 0,
            }
        )

    def report_failure(self, source_name: str, error: str = "") -> None:
        """Record a failed probe / request to *source_name*.

        Increments the error count and degrades or marks the source as
        down depending on consecutive failures.
        """
        if source_name not in self._health:
            self._health[source_name] = {
                "status": "unknown",
                "last_check": _now(),
                "latency_ms": 0,
                "error_count": 0,
            }

        entry = self._health[source_name]
        entry["error_count"] = entry.get("error_count", 0) + 1
        entry["last_check"] = _now()

        if entry["error_count"] >= 5:
            entry["status"] = "down"
        elif entry["error_count"] >= 2:
            entry["status"] = "degraded"

        if error:
            logger.warning(
                "Data source %s failure #%d: %s",
                source_name,
                entry["error_count"],
                error,
            )


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

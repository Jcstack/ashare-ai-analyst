"""Data source routing with proxy-aware domain classification.

Routes AKShare requests to working data sources based on proxy/network
configuration, with health tracking and automatic failover.

Per PRD v2.0 NFR-DS001: Configurable data source priority with proxy-aware routing.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("data.source_router")


class SourceDomain(str, Enum):
    """Data source backend domain classification."""

    QMT = "qmt"  # XtQuant local SDK — lowest latency, push-capable
    SINA = "sina"
    EASTMONEY_PUSH2 = "push2"  # push2.eastmoney.com — often blocked by proxy
    EASTMONEY_DATACENTER = "datacenter"  # datacenter-web.eastmoney.com — works
    XUEQIU = "xueqiu"
    TENCENT = "tencent"
    ADATA = "adata"  # adata multi-source fusion (proxy-friendly fallback)


class SourceHealth(str, Enum):
    """Health status of a data source."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class SourceStatus:
    """Runtime health tracking for a data source."""

    domain: SourceDomain
    health: SourceHealth = SourceHealth.HEALTHY
    consecutive_failures: int = 0
    total_requests: int = 0
    total_failures: int = 0

    def record_success(self) -> None:
        """Record a successful request and reset failure counter."""
        self.total_requests += 1
        self.consecutive_failures = 0
        if self.health != SourceHealth.HEALTHY:
            self.health = SourceHealth.HEALTHY
            logger.info("Source %s recovered to HEALTHY", self.domain.value)

    def record_failure(self, max_failures: int = 3) -> None:
        """Record a failed request and update health status."""
        self.total_requests += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        if self.consecutive_failures >= max_failures:
            self.health = SourceHealth.DOWN
            logger.warning(
                "Source %s marked DOWN after %d failures",
                self.domain.value,
                self.consecutive_failures,
            )
        elif self.consecutive_failures >= max_failures // 2:
            self.health = SourceHealth.DEGRADED


class DataSourceRouter:
    """Routes data requests to the best available AKShare source.

    Classifies AKShare functions by backend domain and routes to
    working sources based on proxy configuration and runtime health.

    Args:
        config_name: Config file name (stocks or agent).
    """

    def __init__(self, config_name: str = "stocks") -> None:
        config = load_config(config_name)
        ds_cfg = config.get("data_sources", {})
        self._blocked_domains: list[str] = ds_cfg.get("proxy_blocked_domains", [])
        self._preferred_realtime: str = ds_cfg.get("preferred_realtime", "sina")
        self._fallback_enabled: bool = ds_cfg.get("fallback_enabled", True)
        self._sources: dict[SourceDomain, SourceStatus] = {
            domain: SourceStatus(domain=domain) for domain in SourceDomain
        }
        # Pre-mark blocked domains
        for blocked in self._blocked_domains:
            for domain in SourceDomain:
                if domain.value in blocked or blocked in domain.value:
                    self._sources[domain].health = SourceHealth.DOWN
                    logger.info(
                        "Source %s pre-marked DOWN (proxy blocked: %s)",
                        domain.value,
                        blocked,
                    )

    def get_realtime_sources(self) -> list[SourceDomain]:
        """Return ordered list of healthy realtime data sources.

        QMT is highest priority (local SDK, <1s latency, push-capable).
        Sina uses lightweight hq.sinajs.cn (per-symbol, fast, includes name).
        Xueqiu is fallback (reliable through overseas proxy, but no stock name).
        adata is last resort (Sina+Tencent fusion, may return empty).
        """
        candidates = [
            SourceDomain.QMT,
            SourceDomain.SINA,
            SourceDomain.XUEQIU,
            SourceDomain.ADATA,
            SourceDomain.EASTMONEY_DATACENTER,
        ]
        return [s for s in candidates if self._sources[s].health != SourceHealth.DOWN]

    def get_news_sources(self) -> list[SourceDomain]:
        """Return ordered list of healthy news/anomaly data sources."""
        # News uses datacenter-web.eastmoney.com which works through proxy
        candidates = [SourceDomain.EASTMONEY_DATACENTER]
        return [s for s in candidates if self._sources[s].health != SourceHealth.DOWN]

    def record_success(self, domain: SourceDomain) -> None:
        """Record a successful request for the given domain.

        Args:
            domain: The data source domain that succeeded.
        """
        self._sources[domain].record_success()

    def record_failure(self, domain: SourceDomain) -> None:
        """Record a failed request for the given domain.

        Args:
            domain: The data source domain that failed.
        """
        self._sources[domain].record_failure()

    def get_status(self) -> dict[str, dict[str, Any]]:
        """Return health status for all sources."""
        return {
            domain.value: {
                "health": status.health.value,
                "consecutive_failures": status.consecutive_failures,
                "total_requests": status.total_requests,
                "total_failures": status.total_failures,
            }
            for domain, status in self._sources.items()
        }

    def is_source_available(self, domain: SourceDomain) -> bool:
        """Check if a data source is available (not DOWN).

        Args:
            domain: The data source domain to check.

        Returns:
            True if the source is not marked DOWN.
        """
        return self._sources[domain].health != SourceHealth.DOWN

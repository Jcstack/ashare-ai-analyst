"""Monitoring agent — rule-based system health monitoring.

Part of v19.0 Production Hardening.

No LLM dependency — pure rule engine that monitors API latency,
error rates, token consumption, and disk space. Generates alerts
when thresholds are exceeded.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class MetricType(str, Enum):
    """Types of monitored metrics."""

    API_LATENCY = "api_latency"
    ERROR_RATE = "error_rate"
    TOKEN_USAGE = "token_usage"
    DISK_SPACE = "disk_space"
    DB_SIZE = "db_size"
    MEMORY_COUNT = "memory_count"
    PREDICTION_DRIFT = "prediction_drift"


@dataclass
class Alert:
    """A generated alert."""

    severity: str
    metric_type: str
    message: str
    current_value: float
    threshold: float
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class HealthCheck:
    """Result of a full health check."""

    healthy: bool
    checks: dict[str, MetricStatus] = field(default_factory=dict)
    alerts: list[Alert] = field(default_factory=list)
    checked_at: float = 0.0

    def __post_init__(self) -> None:
        if self.checked_at == 0.0:
            self.checked_at = time.time()


@dataclass
class MetricStatus:
    """Status of a single monitored metric."""

    metric_type: str
    value: float
    unit: str
    healthy: bool
    message: str = ""


@dataclass
class MonitoringConfig:
    """Configuration for the monitoring agent."""

    # API latency thresholds (milliseconds)
    api_latency_warning_ms: float = 2000.0
    api_latency_critical_ms: float = 5000.0

    # Error rate thresholds (percentage, 0-100)
    error_rate_warning_pct: float = 5.0
    error_rate_critical_pct: float = 15.0

    # Token usage thresholds (per day)
    token_daily_warning: int = 500_000
    token_daily_critical: int = 1_000_000

    # Disk space thresholds (MB)
    disk_warning_mb: float = 500.0
    disk_critical_mb: float = 100.0

    # Database size thresholds (MB)
    db_size_warning_mb: float = 100.0
    db_size_critical_mb: float = 500.0

    # Data directory to monitor
    data_dir: str = "data"


class MonitoringAgent:
    """Rule-based system health monitoring agent.

    No LLM dependency — uses pure threshold-based rules to monitor
    system metrics and generate alerts.

    Checks:
    - API latency (average response time)
    - Error rate (% of failed requests)
    - Token usage (daily consumption)
    - Disk space (data directory size)
    - Database sizes (agent.db, audit.db, etc.)
    """

    def __init__(self, config: MonitoringConfig | None = None):
        self.config = config or MonitoringConfig()
        self._latency_samples: list[float] = []
        self._error_counts: dict[str, int] = {"total": 0, "errors": 0}
        self._token_counts: dict[str, int] = {"input": 0, "output": 0}

    def record_api_call(
        self,
        latency_ms: float,
        success: bool = True,
        endpoint: str = "",
    ) -> None:
        """Record an API call for monitoring.

        Args:
            latency_ms: Response time in milliseconds.
            success: Whether the call succeeded.
            endpoint: Optional endpoint identifier.
        """
        self._latency_samples.append(latency_ms)
        # Keep only last 1000 samples
        if len(self._latency_samples) > 1000:
            self._latency_samples = self._latency_samples[-1000:]

        self._error_counts["total"] += 1
        if not success:
            self._error_counts["errors"] += 1

    def record_token_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Record LLM token usage."""
        self._token_counts["input"] += input_tokens
        self._token_counts["output"] += output_tokens

    def check_health(self) -> HealthCheck:
        """Run all health checks and return results.

        Returns:
            HealthCheck with individual metric statuses and alerts.
        """
        checks: dict[str, MetricStatus] = {}
        alerts: list[Alert] = []

        # Check API latency
        latency_status = self._check_latency()
        checks["api_latency"] = latency_status
        if not latency_status.healthy:
            alerts.append(
                Alert(
                    severity=(
                        AlertSeverity.CRITICAL.value
                        if latency_status.value >= self.config.api_latency_critical_ms
                        else AlertSeverity.WARNING.value
                    ),
                    metric_type=MetricType.API_LATENCY.value,
                    message=latency_status.message,
                    current_value=latency_status.value,
                    threshold=self.config.api_latency_warning_ms,
                )
            )

        # Check error rate
        error_status = self._check_error_rate()
        checks["error_rate"] = error_status
        if not error_status.healthy:
            alerts.append(
                Alert(
                    severity=(
                        AlertSeverity.CRITICAL.value
                        if error_status.value >= self.config.error_rate_critical_pct
                        else AlertSeverity.WARNING.value
                    ),
                    metric_type=MetricType.ERROR_RATE.value,
                    message=error_status.message,
                    current_value=error_status.value,
                    threshold=self.config.error_rate_warning_pct,
                )
            )

        # Check token usage
        token_status = self._check_token_usage()
        checks["token_usage"] = token_status
        if not token_status.healthy:
            alerts.append(
                Alert(
                    severity=(
                        AlertSeverity.CRITICAL.value
                        if token_status.value >= self.config.token_daily_critical
                        else AlertSeverity.WARNING.value
                    ),
                    metric_type=MetricType.TOKEN_USAGE.value,
                    message=token_status.message,
                    current_value=token_status.value,
                    threshold=float(self.config.token_daily_warning),
                )
            )

        # Check disk space
        disk_status = self._check_disk_space()
        checks["disk_space"] = disk_status
        if not disk_status.healthy:
            alerts.append(
                Alert(
                    severity=(
                        AlertSeverity.CRITICAL.value
                        if disk_status.value >= self.config.db_size_critical_mb
                        else AlertSeverity.WARNING.value
                    ),
                    metric_type=MetricType.DISK_SPACE.value,
                    message=disk_status.message,
                    current_value=disk_status.value,
                    threshold=self.config.disk_warning_mb,
                )
            )

        healthy = all(s.healthy for s in checks.values())
        return HealthCheck(healthy=healthy, checks=checks, alerts=alerts)

    def get_metrics(self) -> dict[str, Any]:
        """Get current metric values as a dictionary."""
        avg_latency = (
            sum(self._latency_samples) / len(self._latency_samples)
            if self._latency_samples
            else 0.0
        )
        total = self._error_counts["total"]
        error_rate = (self._error_counts["errors"] / total * 100) if total > 0 else 0.0
        total_tokens = self._token_counts["input"] + self._token_counts["output"]

        return {
            "api_latency_avg_ms": round(avg_latency, 1),
            "api_latency_samples": len(self._latency_samples),
            "error_rate_pct": round(error_rate, 2),
            "total_requests": total,
            "error_count": self._error_counts["errors"],
            "token_input": self._token_counts["input"],
            "token_output": self._token_counts["output"],
            "token_total": total_tokens,
            "data_dir_size_mb": round(self._get_data_dir_size_mb(), 2),
        }

    def reset_counters(self) -> None:
        """Reset all counters (e.g. at start of a new day)."""
        self._latency_samples.clear()
        self._error_counts = {"total": 0, "errors": 0}
        self._token_counts = {"input": 0, "output": 0}

    def _check_latency(self) -> MetricStatus:
        """Check API latency against thresholds."""
        if not self._latency_samples:
            return MetricStatus(
                metric_type=MetricType.API_LATENCY.value,
                value=0.0,
                unit="ms",
                healthy=True,
                message="无 API 调用数据",
            )

        avg = sum(self._latency_samples) / len(self._latency_samples)
        healthy = avg < self.config.api_latency_warning_ms

        msg = f"平均延迟 {avg:.0f}ms"
        if avg >= self.config.api_latency_critical_ms:
            msg += f" (严重超限，阈值 {self.config.api_latency_critical_ms:.0f}ms)"
        elif avg >= self.config.api_latency_warning_ms:
            msg += f" (超过警告阈值 {self.config.api_latency_warning_ms:.0f}ms)"

        return MetricStatus(
            metric_type=MetricType.API_LATENCY.value,
            value=round(avg, 1),
            unit="ms",
            healthy=healthy,
            message=msg,
        )

    def _check_error_rate(self) -> MetricStatus:
        """Check error rate against thresholds."""
        total = self._error_counts["total"]
        if total == 0:
            return MetricStatus(
                metric_type=MetricType.ERROR_RATE.value,
                value=0.0,
                unit="%",
                healthy=True,
                message="无请求记录",
            )

        rate = self._error_counts["errors"] / total * 100
        healthy = rate < self.config.error_rate_warning_pct

        msg = f"错误率 {rate:.1f}% ({self._error_counts['errors']}/{total})"
        if rate >= self.config.error_rate_critical_pct:
            msg += " (严重)"
        elif rate >= self.config.error_rate_warning_pct:
            msg += " (警告)"

        return MetricStatus(
            metric_type=MetricType.ERROR_RATE.value,
            value=round(rate, 2),
            unit="%",
            healthy=healthy,
            message=msg,
        )

    def _check_token_usage(self) -> MetricStatus:
        """Check token usage against daily thresholds."""
        total = self._token_counts["input"] + self._token_counts["output"]
        healthy = total < self.config.token_daily_warning

        msg = f"Token 消耗 {total:,}"
        if total >= self.config.token_daily_critical:
            msg += " (严重超限)"
        elif total >= self.config.token_daily_warning:
            msg += " (超过日限)"

        return MetricStatus(
            metric_type=MetricType.TOKEN_USAGE.value,
            value=float(total),
            unit="tokens",
            healthy=healthy,
            message=msg,
        )

    def _check_disk_space(self) -> MetricStatus:
        """Check data directory size."""
        size_mb = self._get_data_dir_size_mb()
        healthy = size_mb < self.config.disk_warning_mb

        msg = f"数据目录 {size_mb:.1f}MB"
        if size_mb >= self.config.db_size_critical_mb:
            msg += " (严重)"
        elif size_mb >= self.config.disk_warning_mb:
            msg += " (空间不足)"

        return MetricStatus(
            metric_type=MetricType.DISK_SPACE.value,
            value=round(size_mb, 2),
            unit="MB",
            healthy=healthy,
            message=msg,
        )

    def _get_data_dir_size_mb(self) -> float:
        """Calculate total size of data directory in MB."""
        data_path = Path(self.config.data_dir)
        if not data_path.exists():
            return 0.0

        total_bytes = 0
        try:
            for f in data_path.rglob("*"):
                if f.is_file():
                    total_bytes += f.stat().st_size
        except OSError:
            pass

        return total_bytes / (1024 * 1024)

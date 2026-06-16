"""Tests for MonitoringAgent — rule-based system health monitoring.

Part of v19.0 Production Hardening.
"""

from __future__ import annotations

import pytest

from src.agents.monitoring_agent import (
    Alert,
    AlertSeverity,
    HealthCheck,
    MetricType,
    MonitoringAgent,
    MonitoringConfig,
)


@pytest.fixture
def agent():
    """Create a monitoring agent with default config."""
    return MonitoringAgent()


@pytest.fixture
def custom_agent():
    """Create a monitoring agent with tight thresholds for testing."""
    config = MonitoringConfig(
        api_latency_warning_ms=100.0,
        api_latency_critical_ms=200.0,
        error_rate_warning_pct=2.0,
        error_rate_critical_pct=5.0,
        token_daily_warning=1000,
        token_daily_critical=5000,
        disk_warning_mb=10.0,
        disk_critical_mb=5.0,
        data_dir="/nonexistent",  # Always returns 0 MB
    )
    return MonitoringAgent(config=config)


class TestRecordApiCall:
    """Tests for API call recording."""

    def test_record_success(self, agent):
        agent.record_api_call(100.0, success=True)
        metrics = agent.get_metrics()
        assert metrics["api_latency_samples"] == 1
        assert metrics["total_requests"] == 1
        assert metrics["error_count"] == 0

    def test_record_failure(self, agent):
        agent.record_api_call(100.0, success=False)
        metrics = agent.get_metrics()
        assert metrics["error_count"] == 1

    def test_latency_rolling_window(self, agent):
        """Only keep last 1000 samples."""
        for i in range(1200):
            agent.record_api_call(float(i))
        metrics = agent.get_metrics()
        assert metrics["api_latency_samples"] == 1000


class TestRecordTokenUsage:
    """Tests for token usage recording."""

    def test_record_tokens(self, agent):
        agent.record_token_usage(100, 50)
        agent.record_token_usage(200, 100)
        metrics = agent.get_metrics()
        assert metrics["token_input"] == 300
        assert metrics["token_output"] == 150
        assert metrics["token_total"] == 450


class TestCheckHealth:
    """Tests for health check orchestration."""

    def test_healthy_no_data(self, agent):
        """With no data recorded, all checks should be healthy."""
        health = agent.check_health()
        assert health.healthy is True
        assert len(health.alerts) == 0
        assert "api_latency" in health.checks
        assert "error_rate" in health.checks
        assert "token_usage" in health.checks
        assert "disk_space" in health.checks

    def test_healthy_normal_load(self, custom_agent):
        """Normal metrics should produce healthy status."""
        for _ in range(10):
            custom_agent.record_api_call(50.0, success=True)
        custom_agent.record_token_usage(100, 50)

        health = custom_agent.check_health()
        assert health.healthy is True
        assert len(health.alerts) == 0


class TestCheckLatency:
    """Tests for API latency checks."""

    def test_no_samples(self, agent):
        health = agent.check_health()
        assert health.checks["api_latency"].healthy is True
        assert "无 API 调用数据" in health.checks["api_latency"].message

    def test_warning_latency(self, custom_agent):
        """Latency above warning threshold but below critical."""
        for _ in range(5):
            custom_agent.record_api_call(150.0)  # > 100ms warning

        health = custom_agent.check_health()
        assert health.checks["api_latency"].healthy is False
        latency_alerts = [
            a for a in health.alerts if a.metric_type == MetricType.API_LATENCY.value
        ]
        assert len(latency_alerts) == 1
        assert latency_alerts[0].severity == AlertSeverity.WARNING.value

    def test_critical_latency(self, custom_agent):
        """Latency above critical threshold."""
        for _ in range(5):
            custom_agent.record_api_call(250.0)  # > 200ms critical

        health = custom_agent.check_health()
        latency_alerts = [
            a for a in health.alerts if a.metric_type == MetricType.API_LATENCY.value
        ]
        assert len(latency_alerts) == 1
        assert latency_alerts[0].severity == AlertSeverity.CRITICAL.value


class TestCheckErrorRate:
    """Tests for error rate checks."""

    def test_no_requests(self, agent):
        health = agent.check_health()
        assert health.checks["error_rate"].healthy is True
        assert "无请求记录" in health.checks["error_rate"].message

    def test_warning_error_rate(self, custom_agent):
        """Error rate above warning (2%) but below critical (5%)."""
        for _ in range(97):
            custom_agent.record_api_call(50.0, success=True)
        for _ in range(3):
            custom_agent.record_api_call(50.0, success=False)
        # 3% error rate

        health = custom_agent.check_health()
        assert health.checks["error_rate"].healthy is False
        error_alerts = [
            a for a in health.alerts if a.metric_type == MetricType.ERROR_RATE.value
        ]
        assert len(error_alerts) == 1
        assert error_alerts[0].severity == AlertSeverity.WARNING.value

    def test_critical_error_rate(self, custom_agent):
        """Error rate above critical (5%)."""
        for _ in range(90):
            custom_agent.record_api_call(50.0, success=True)
        for _ in range(10):
            custom_agent.record_api_call(50.0, success=False)
        # 10% error rate

        health = custom_agent.check_health()
        error_alerts = [
            a for a in health.alerts if a.metric_type == MetricType.ERROR_RATE.value
        ]
        assert len(error_alerts) == 1
        assert error_alerts[0].severity == AlertSeverity.CRITICAL.value

    def test_zero_error_rate(self, custom_agent):
        """0% error rate should be healthy."""
        for _ in range(10):
            custom_agent.record_api_call(50.0, success=True)

        health = custom_agent.check_health()
        assert health.checks["error_rate"].healthy is True


class TestCheckTokenUsage:
    """Tests for token usage checks."""

    def test_warning_tokens(self, custom_agent):
        """Token usage above warning (1000) but below critical (5000)."""
        custom_agent.record_token_usage(1500, 500)  # total = 2000

        health = custom_agent.check_health()
        assert health.checks["token_usage"].healthy is False
        token_alerts = [
            a for a in health.alerts if a.metric_type == MetricType.TOKEN_USAGE.value
        ]
        assert len(token_alerts) == 1
        assert token_alerts[0].severity == AlertSeverity.WARNING.value

    def test_critical_tokens(self, custom_agent):
        """Token usage above critical (5000)."""
        custom_agent.record_token_usage(4000, 2000)  # total = 6000

        health = custom_agent.check_health()
        token_alerts = [
            a for a in health.alerts if a.metric_type == MetricType.TOKEN_USAGE.value
        ]
        assert len(token_alerts) == 1
        assert token_alerts[0].severity == AlertSeverity.CRITICAL.value


class TestCheckDiskSpace:
    """Tests for disk space checks."""

    def test_nonexistent_data_dir(self, custom_agent):
        """Nonexistent dir should return 0 MB — healthy."""
        health = custom_agent.check_health()
        assert health.checks["disk_space"].healthy is True
        assert health.checks["disk_space"].value == 0.0


class TestGetMetrics:
    """Tests for metric snapshot retrieval."""

    def test_empty_metrics(self, agent):
        metrics = agent.get_metrics()
        assert metrics["api_latency_avg_ms"] == 0.0
        assert metrics["api_latency_samples"] == 0
        assert metrics["error_rate_pct"] == 0.0
        assert metrics["total_requests"] == 0
        assert metrics["error_count"] == 0
        assert metrics["token_input"] == 0
        assert metrics["token_output"] == 0
        assert metrics["token_total"] == 0

    def test_metrics_after_recording(self, agent):
        agent.record_api_call(100.0, success=True)
        agent.record_api_call(200.0, success=False)
        agent.record_token_usage(500, 200)

        metrics = agent.get_metrics()
        assert metrics["api_latency_avg_ms"] == 150.0
        assert metrics["api_latency_samples"] == 2
        assert metrics["error_rate_pct"] == 50.0
        assert metrics["total_requests"] == 2
        assert metrics["error_count"] == 1
        assert metrics["token_total"] == 700


class TestResetCounters:
    """Tests for counter reset."""

    def test_reset(self, agent):
        agent.record_api_call(100.0, success=False)
        agent.record_token_usage(500, 200)

        agent.reset_counters()

        metrics = agent.get_metrics()
        assert metrics["api_latency_samples"] == 0
        assert metrics["total_requests"] == 0
        assert metrics["error_count"] == 0
        assert metrics["token_total"] == 0


class TestAlertDataclass:
    """Tests for the Alert dataclass."""

    def test_auto_timestamp(self):
        alert = Alert(
            severity=AlertSeverity.WARNING.value,
            metric_type=MetricType.API_LATENCY.value,
            message="test",
            current_value=100.0,
            threshold=50.0,
        )
        assert alert.timestamp > 0

    def test_explicit_timestamp(self):
        alert = Alert(
            severity=AlertSeverity.CRITICAL.value,
            metric_type=MetricType.ERROR_RATE.value,
            message="test",
            current_value=20.0,
            threshold=10.0,
            timestamp=1234567890.0,
        )
        assert alert.timestamp == 1234567890.0


class TestHealthCheckDataclass:
    """Tests for the HealthCheck dataclass."""

    def test_auto_timestamp(self):
        health = HealthCheck(healthy=True)
        assert health.checked_at > 0

    def test_default_fields(self):
        health = HealthCheck(healthy=True)
        assert health.checks == {}
        assert health.alerts == []


class TestMultipleAlerts:
    """Tests for scenarios with multiple simultaneous alerts."""

    def test_multiple_alerts(self, custom_agent):
        """Multiple metrics exceeding thresholds should produce multiple alerts."""
        # High latency
        for _ in range(5):
            custom_agent.record_api_call(250.0, success=False)
        # High token usage
        custom_agent.record_token_usage(4000, 2000)

        health = custom_agent.check_health()
        assert health.healthy is False
        # Should have latency + error rate + token alerts (at least 3)
        assert len(health.alerts) >= 3

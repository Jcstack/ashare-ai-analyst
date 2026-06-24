"""Unit tests for src/data/source_router.py — DataSourceRouter.

Tests SourceDomain enum, SourceHealth tracking, health transitions,
blocked domain pre-marking, and source availability queries.

Per PRD v2.0 NFR-DS001: Proxy-aware data source routing.
Mock strategy: Only mock load_config (external dependency).
"""

from unittest.mock import patch

import pytest

from src.data.source_router import (
    DataSourceRouter,
    SourceDomain,
    SourceHealth,
    SourceStatus,
)


# ---------------------------------------------------------------------------
# Sample config for tests
# ---------------------------------------------------------------------------
SAMPLE_STOCKS_CONFIG: dict = {
    "data_sources": {
        "proxy_blocked_domains": [],
        "preferred_realtime": "sina",
        "fallback_enabled": True,
    },
}


@pytest.fixture
def router():
    """Create a DataSourceRouter with no blocked domains."""
    with patch("src.data.source_router.load_config") as mock_cfg:
        mock_cfg.return_value = SAMPLE_STOCKS_CONFIG
        yield DataSourceRouter(config_name="stocks")


@pytest.fixture
def router_with_blocked():
    """Create a DataSourceRouter with push2 blocked (proxy scenario)."""
    config = {
        "data_sources": {
            "proxy_blocked_domains": ["push2"],
            "preferred_realtime": "sina",
            "fallback_enabled": True,
        },
    }
    with patch("src.data.source_router.load_config") as mock_cfg:
        mock_cfg.return_value = config
        yield DataSourceRouter(config_name="stocks")


class TestSourceDomainEnum:
    """Tests for the SourceDomain enumeration values."""

    def test_enum_values_exist(self):
        """All expected domain enum values should be accessible."""
        assert SourceDomain.SINA.value == "sina"
        assert SourceDomain.EASTMONEY_PUSH2.value == "push2"
        assert SourceDomain.EASTMONEY_DATACENTER.value == "datacenter"
        assert SourceDomain.XUEQIU.value == "xueqiu"
        assert SourceDomain.TENCENT.value == "tencent"
        assert SourceDomain.ADATA.value == "adata"

    def test_enum_is_string(self):
        """SourceDomain should be usable as a string."""
        assert isinstance(SourceDomain.SINA, str)


class TestSourceStatus:
    """Tests for the SourceStatus dataclass health tracking."""

    def test_initial_health_is_healthy(self):
        """New SourceStatus should start as HEALTHY."""
        status = SourceStatus(domain=SourceDomain.SINA)
        assert status.health == SourceHealth.HEALTHY
        assert status.consecutive_failures == 0
        assert status.total_requests == 0

    def test_record_success_increments_counters(self):
        """record_success should increment total_requests and reset failures."""
        status = SourceStatus(domain=SourceDomain.SINA)
        status.consecutive_failures = 2
        status.record_success()
        assert status.total_requests == 1
        assert status.consecutive_failures == 0

    def test_record_failure_transitions_to_degraded(self):
        """After half of max_failures, health should become DEGRADED."""
        status = SourceStatus(domain=SourceDomain.SINA)
        # max_failures defaults to 3, so half = 1 (3 // 2 = 1)
        status.record_failure(max_failures=4)
        assert status.health == SourceHealth.HEALTHY
        status.record_failure(max_failures=4)
        assert status.health == SourceHealth.DEGRADED

    def test_record_failure_transitions_to_down(self):
        """After max_failures consecutive failures, health should become DOWN."""
        status = SourceStatus(domain=SourceDomain.SINA)
        for _ in range(3):
            status.record_failure(max_failures=3)
        assert status.health == SourceHealth.DOWN
        assert status.total_failures == 3

    def test_success_after_degraded_recovers_to_healthy(self):
        """A success after degradation should restore HEALTHY status."""
        status = SourceStatus(domain=SourceDomain.SINA)
        status.health = SourceHealth.DEGRADED
        status.record_success()
        assert status.health == SourceHealth.HEALTHY


class TestDataSourceRouter:
    """Tests for the DataSourceRouter class."""

    def test_get_realtime_sources_default(self, router):
        """Default realtime sources should include sina, xueqiu, datacenter, adata."""
        sources = router.get_realtime_sources()
        assert SourceDomain.SINA in sources
        assert SourceDomain.XUEQIU in sources
        assert SourceDomain.EASTMONEY_DATACENTER in sources
        assert SourceDomain.ADATA in sources

    def test_get_realtime_sources_excludes_down(self, router):
        """DOWN sources should be excluded from realtime sources."""
        router._sources[SourceDomain.SINA].health = SourceHealth.DOWN
        sources = router.get_realtime_sources()
        assert SourceDomain.SINA not in sources

    def test_get_news_sources_returns_datacenter(self, router):
        """News sources should include EASTMONEY_DATACENTER."""
        sources = router.get_news_sources()
        assert SourceDomain.EASTMONEY_DATACENTER in sources

    def test_blocked_domain_premarked_down(self, router_with_blocked):
        """Proxy-blocked domains should be pre-marked as DOWN."""
        status = router_with_blocked.get_status()
        assert status["push2"]["health"] == "down"

    def test_record_success_delegates(self, router):
        """record_success should update the underlying SourceStatus."""
        router.record_success(SourceDomain.SINA)
        status = router.get_status()
        assert status["sina"]["total_requests"] == 1

    def test_record_failure_delegates(self, router):
        """record_failure should update the underlying SourceStatus."""
        router.record_failure(SourceDomain.SINA)
        status = router.get_status()
        assert status["sina"]["total_failures"] == 1

    def test_is_source_available_healthy(self, router):
        """A HEALTHY source should be available."""
        assert router.is_source_available(SourceDomain.SINA) is True

    def test_is_source_available_down(self, router):
        """A DOWN source should not be available."""
        router._sources[SourceDomain.SINA].health = SourceHealth.DOWN
        assert router.is_source_available(SourceDomain.SINA) is False

    def test_get_status_returns_all_domains(self, router):
        """get_status should return entries for every SourceDomain."""
        status = router.get_status()
        for domain in list(SourceDomain):
            assert domain.value in status

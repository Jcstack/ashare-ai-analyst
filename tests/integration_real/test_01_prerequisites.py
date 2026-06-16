"""Test environment prerequisites — imports, network, config.

These tests verify the foundational dependencies are available before
running heavier integration tests.  They make NO external data calls
but DO check network reachability via raw sockets.
"""

from __future__ import annotations

import socket

import pytest

from tests.integration_real.conftest import TestResult, measure_time

pytestmark = pytest.mark.integration_real


# ---------------------------------------------------------------------------
# Package imports
# ---------------------------------------------------------------------------


class TestImports:
    """Verify all required packages are importable."""

    @pytest.mark.parametrize(
        "module_name",
        [
            "akshare",
            "pandas",
            "yfinance",
            "requests",
            "httpx",
        ],
    )
    def test_core_imports(self, module_name):
        __import__(module_name)

    @pytest.mark.parametrize(
        "module_name",
        [
            "adata",
            "anthropic",
            "google.genai",
            "openai",
            "redis",
        ],
    )
    def test_optional_imports(self, module_name, result_collector):
        """Record which optional deps are available (don't fail)."""
        try:
            __import__(module_name)
            status = "pass"
        except ImportError:
            status = "skip"
        result_collector.record(
            TestResult(
                test_name=f"import_{module_name}",
                category="prerequisite",
                status=status,
                details={"module": module_name},
            )
        )


# ---------------------------------------------------------------------------
# Network connectivity
# ---------------------------------------------------------------------------


class TestNetworkConnectivity:
    """Check which external hosts are reachable."""

    @pytest.mark.parametrize(
        "host,port",
        [
            ("hq.sinajs.cn", 80),
            ("datacenter-web.eastmoney.com", 443),
            ("stock.xueqiu.com", 443),
            ("generativelanguage.googleapis.com", 443),
        ],
    )
    def test_host_reachable(self, host, port, result_collector):
        try:
            socket.create_connection((host, port), timeout=5)
            status = "pass"
        except (OSError, socket.timeout):
            status = "skip"
        result_collector.record(
            TestResult(
                test_name=f"network_{host}",
                category="prerequisite",
                status=status,
                details={"host": host, "port": port},
            )
        )


# ---------------------------------------------------------------------------
# Config YAML loading
# ---------------------------------------------------------------------------


class TestConfigLoading:
    """Verify config YAML files load correctly."""

    @pytest.mark.parametrize(
        "config_name",
        [
            "stocks",
            "llm",
            "web",
            "agent",
            "notification",
            "global_market",
            "calendar",
        ],
    )
    def test_load_config(self, config_name, result_collector):
        from src.utils.config import load_config

        with measure_time() as timing:
            cfg = load_config(config_name)
        assert isinstance(cfg, dict)
        assert len(cfg) > 0
        result_collector.record(
            TestResult(
                test_name=f"config_{config_name}",
                category="prerequisite",
                status="pass",
                latency_ms=timing["elapsed_ms"],
            )
        )

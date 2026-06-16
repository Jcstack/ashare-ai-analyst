"""Tests for openclaw.tasks.proxy_health_pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openclaw.tasks.proxy_health_pipeline import (
    _critical_failed,
    _probe_targets,
    _run_health_check,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TARGETS = [
    {
        "name": "gemini_api",
        "url": "https://generativelanguage.googleapis.com/",
        "timeout": 10,
        "critical": True,
    },
    {
        "name": "yahoo_finance",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
        "timeout": 10,
        "critical": True,
    },
    {
        "name": "duckduckgo",
        "url": "https://duckduckgo.com/",
        "timeout": 10,
        "critical": False,
    },
]

SAMPLE_CONFIG = {
    "proxy_health": {
        "targets": SAMPLE_TARGETS,
        "surge_policy_group": "Proxy",
        "hk_fallback_nodes": ["HK-01"],
        "benchmark_wait_seconds": 0,  # no wait in tests
    },
    "celery": {"broker_url": "redis://localhost:6379/0"},
}


@pytest.fixture()
def mock_redis():
    r = MagicMock()
    r.get.return_value = None  # no previous status
    return r


# ---------------------------------------------------------------------------
# _critical_failed
# ---------------------------------------------------------------------------


class TestCriticalFailed:
    def test_no_failed(self):
        assert _critical_failed([]) is False

    def test_only_non_critical_failed(self):
        assert _critical_failed([{"name": "ddg", "critical": False}]) is False

    def test_critical_failed(self):
        assert _critical_failed([{"name": "gemini", "critical": True}]) is True

    def test_mixed(self):
        failed = [
            {"name": "ddg", "critical": False},
            {"name": "gemini", "critical": True},
        ]
        assert _critical_failed(failed) is True


# ---------------------------------------------------------------------------
# _probe_targets
# ---------------------------------------------------------------------------


class TestProbeTargets:
    @patch("openclaw.tasks.proxy_health_pipeline.requests.head")
    def test_all_pass(self, mock_head):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_head.return_value = mock_resp

        passed, failed = _probe_targets(SAMPLE_TARGETS)
        assert len(passed) == 3
        assert len(failed) == 0

    @patch("openclaw.tasks.proxy_health_pipeline.requests.head")
    def test_timeout_fails(self, mock_head):
        import requests

        mock_head.side_effect = requests.exceptions.ConnectTimeout("timeout")

        passed, failed = _probe_targets(SAMPLE_TARGETS)
        assert len(passed) == 0
        assert len(failed) == 3

    @patch("openclaw.tasks.proxy_health_pipeline.requests.head")
    def test_5xx_fails(self, mock_head):
        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_head.return_value = mock_resp

        passed, failed = _probe_targets(SAMPLE_TARGETS)
        assert len(passed) == 0
        assert len(failed) == 3

    @patch("openclaw.tasks.proxy_health_pipeline.requests.head")
    def test_4xx_passes(self, mock_head):
        """403/404 means proxy works, target just rejects HEAD."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_head.return_value = mock_resp

        passed, failed = _probe_targets(SAMPLE_TARGETS)
        assert len(passed) == 3
        assert len(failed) == 0

    @patch("openclaw.tasks.proxy_health_pipeline.requests.head")
    def test_mixed_results(self, mock_head):
        """First target OK, rest timeout."""
        import requests as req_lib

        ok_resp = MagicMock()
        ok_resp.status_code = 200

        def side_effect(url, **kwargs):
            if "googleapis" in url:
                return ok_resp
            raise req_lib.exceptions.ConnectTimeout("timeout")

        mock_head.side_effect = side_effect

        passed, failed = _probe_targets(SAMPLE_TARGETS)
        assert len(passed) == 1
        assert passed[0]["name"] == "gemini_api"
        assert len(failed) == 2


# ---------------------------------------------------------------------------
# _run_health_check — integration-level (all externals mocked)
# ---------------------------------------------------------------------------


class TestRunHealthCheck:
    @patch("openclaw.tasks.proxy_health_pipeline._get_redis")
    @patch("openclaw.tasks.proxy_health_pipeline._load_proxy_health_config")
    def test_no_targets_configured(self, mock_cfg, mock_redis_fn):
        mock_cfg.return_value = {}
        result = _run_health_check()
        assert result["status"] == "skipped"

    @patch("openclaw.tasks.proxy_health_pipeline._discord_notify")
    @patch("openclaw.tasks.proxy_health_pipeline._get_redis")
    @patch("openclaw.tasks.proxy_health_pipeline._probe_targets")
    @patch("openclaw.tasks.proxy_health_pipeline._load_proxy_health_config")
    def test_all_ok(self, mock_cfg, mock_probe, mock_redis_fn, mock_discord):
        mock_cfg.return_value = SAMPLE_CONFIG["proxy_health"]
        mock_probe.return_value = (SAMPLE_TARGETS, [])
        r = MagicMock()
        r.get.return_value = "ok"
        mock_redis_fn.return_value = r

        result = _run_health_check()
        assert result["status"] == "ok"
        mock_discord.assert_not_called()

    @patch("openclaw.tasks.proxy_health_pipeline._discord_notify")
    @patch("openclaw.tasks.proxy_health_pipeline._get_redis")
    @patch("openclaw.tasks.proxy_health_pipeline._probe_targets")
    @patch("openclaw.tasks.proxy_health_pipeline._load_proxy_health_config")
    def test_recovery_sends_notification(
        self, mock_cfg, mock_probe, mock_redis_fn, mock_discord
    ):
        """When previous status was 'failing' and now all OK → notify recovery."""
        mock_cfg.return_value = SAMPLE_CONFIG["proxy_health"]
        mock_probe.return_value = (SAMPLE_TARGETS, [])
        r = MagicMock()
        r.get.return_value = "failing"  # was failing
        mock_redis_fn.return_value = r

        result = _run_health_check()
        assert result["status"] == "ok"
        mock_discord.assert_called_once()
        assert "恢复" in mock_discord.call_args[0][0]

    @patch("openclaw.tasks.proxy_health_pipeline._discord_notify")
    @patch("openclaw.tasks.proxy_health_pipeline._get_redis")
    @patch("openclaw.tasks.proxy_health_pipeline._probe_targets")
    @patch("openclaw.tasks.proxy_health_pipeline._load_proxy_health_config")
    @patch.dict("os.environ", {"SURGE_API_PASSWORD": ""}, clear=False)
    def test_critical_fail_no_surge_password(
        self, mock_cfg, mock_probe, mock_redis_fn, mock_discord
    ):
        """Critical targets down but no Surge password → alert only."""
        mock_cfg.return_value = SAMPLE_CONFIG["proxy_health"]
        critical_failed = [SAMPLE_TARGETS[0]]  # gemini (critical)
        mock_probe.return_value = (SAMPLE_TARGETS[1:], critical_failed)
        r = MagicMock()
        r.get.return_value = None
        mock_redis_fn.return_value = r

        result = _run_health_check()
        assert result["status"] == "failing"
        assert result["error"] == "no_surge_password"
        mock_discord.assert_called_once()

    @patch("openclaw.tasks.proxy_health_pipeline.time.sleep")
    @patch("openclaw.tasks.proxy_health_pipeline._surge_get_current_node")
    @patch("openclaw.tasks.proxy_health_pipeline._surge_trigger_benchmark")
    @patch("openclaw.tasks.proxy_health_pipeline._discord_notify")
    @patch("openclaw.tasks.proxy_health_pipeline._get_redis")
    @patch("openclaw.tasks.proxy_health_pipeline._probe_targets")
    @patch("openclaw.tasks.proxy_health_pipeline._load_proxy_health_config")
    @patch.dict("os.environ", {"SURGE_API_PASSWORD": "test_key"}, clear=False)
    def test_benchmark_remediation_success(
        self,
        mock_cfg,
        mock_probe,
        mock_redis_fn,
        mock_discord,
        mock_benchmark,
        mock_get_node,
        mock_sleep,
    ):
        """Benchmark fixes the issue on second probe."""
        mock_cfg.return_value = SAMPLE_CONFIG["proxy_health"]

        # First probe: critical fail; second probe: all pass
        critical_failed = [SAMPLE_TARGETS[0]]
        mock_probe.side_effect = [
            (SAMPLE_TARGETS[1:], critical_failed),
            (SAMPLE_TARGETS, []),
        ]
        r = MagicMock()
        r.get.return_value = "failing"
        mock_redis_fn.return_value = r
        mock_benchmark.return_value = True
        mock_get_node.side_effect = ["JP-Node-1", "JP-Node-2"]

        result = _run_health_check()
        assert result["status"] == "ok"
        assert result["remediation"] == "benchmark"
        mock_benchmark.assert_called_once()

    @patch("openclaw.tasks.proxy_health_pipeline.time.sleep")
    @patch("openclaw.tasks.proxy_health_pipeline._surge_select_node")
    @patch("openclaw.tasks.proxy_health_pipeline._surge_get_current_node")
    @patch("openclaw.tasks.proxy_health_pipeline._surge_trigger_benchmark")
    @patch("openclaw.tasks.proxy_health_pipeline._discord_notify")
    @patch("openclaw.tasks.proxy_health_pipeline._get_redis")
    @patch("openclaw.tasks.proxy_health_pipeline._probe_targets")
    @patch("openclaw.tasks.proxy_health_pipeline._load_proxy_health_config")
    @patch.dict("os.environ", {"SURGE_API_PASSWORD": "test_key"}, clear=False)
    def test_hk_fallback_success(
        self,
        mock_cfg,
        mock_probe,
        mock_redis_fn,
        mock_discord,
        mock_benchmark,
        mock_get_node,
        mock_select,
        mock_sleep,
    ):
        """Benchmark fails but HK fallback node works."""
        mock_cfg.return_value = SAMPLE_CONFIG["proxy_health"]

        critical_failed = [SAMPLE_TARGETS[0]]
        # probe 1: fail, probe 2 (post-benchmark): still fail, probe 3 (HK): pass
        mock_probe.side_effect = [
            (SAMPLE_TARGETS[1:], critical_failed),
            (SAMPLE_TARGETS[1:], critical_failed),
            (SAMPLE_TARGETS, []),
        ]
        r = MagicMock()
        r.get.return_value = None
        mock_redis_fn.return_value = r
        mock_benchmark.return_value = True
        mock_get_node.return_value = "JP-Node-1"
        mock_select.return_value = True

        result = _run_health_check()
        assert result["status"] == "ok"
        assert result["remediation"] == "hk_fallback"
        assert result["new_node"] == "HK-01"

    @patch("openclaw.tasks.proxy_health_pipeline.time.sleep")
    @patch("openclaw.tasks.proxy_health_pipeline._surge_select_node")
    @patch("openclaw.tasks.proxy_health_pipeline._surge_get_current_node")
    @patch("openclaw.tasks.proxy_health_pipeline._surge_trigger_benchmark")
    @patch("openclaw.tasks.proxy_health_pipeline._discord_notify")
    @patch("openclaw.tasks.proxy_health_pipeline._get_redis")
    @patch("openclaw.tasks.proxy_health_pipeline._probe_targets")
    @patch("openclaw.tasks.proxy_health_pipeline._load_proxy_health_config")
    @patch.dict("os.environ", {"SURGE_API_PASSWORD": "test_key"}, clear=False)
    def test_all_remediation_fails(
        self,
        mock_cfg,
        mock_probe,
        mock_redis_fn,
        mock_discord,
        mock_benchmark,
        mock_get_node,
        mock_select,
        mock_sleep,
    ):
        """Both benchmark and HK fallback fail → status=failing."""
        mock_cfg.return_value = SAMPLE_CONFIG["proxy_health"]

        critical_failed = [SAMPLE_TARGETS[0]]
        # All probes return critical failure
        mock_probe.return_value = (SAMPLE_TARGETS[1:], critical_failed)
        r = MagicMock()
        r.get.return_value = None
        mock_redis_fn.return_value = r
        mock_benchmark.return_value = True
        mock_get_node.return_value = "JP-Node-1"
        mock_select.return_value = True

        result = _run_health_check()
        assert result["status"] == "failing"
        assert result["error"] == "all_remediation_failed"

    @patch("openclaw.tasks.proxy_health_pipeline._discord_notify")
    @patch("openclaw.tasks.proxy_health_pipeline._get_redis")
    @patch("openclaw.tasks.proxy_health_pipeline._probe_targets")
    @patch("openclaw.tasks.proxy_health_pipeline._load_proxy_health_config")
    def test_debounce_no_repeat_alert(
        self, mock_cfg, mock_probe, mock_redis_fn, mock_discord
    ):
        """Already failing + still failing → no duplicate Discord notification."""
        mock_cfg.return_value = SAMPLE_CONFIG["proxy_health"]
        critical_failed = [SAMPLE_TARGETS[0]]
        mock_probe.return_value = (SAMPLE_TARGETS[1:], critical_failed)
        r = MagicMock()
        r.get.return_value = "failing"  # already known
        mock_redis_fn.return_value = r

        # No surge password → goes straight to failing
        with patch.dict("os.environ", {"SURGE_API_PASSWORD": ""}, clear=False):
            result = _run_health_check()

        assert result["status"] == "failing"
        mock_discord.assert_not_called()  # debounced

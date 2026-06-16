"""Proxy health check + Surge auto-remediation pipeline.

Probes external endpoints through HTTP_PROXY, and if critical targets fail,
uses the Surge HTTP API to trigger URL-test benchmarks or force-switch to
HK fallback nodes.  Discord notifications fire only on status *transitions*
(ok→failing, failing→ok) to avoid alert fatigue.

Schedule: every 10 min, 07:00-23:00 daily (see config/openclaw.yaml).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests
from celery.exceptions import SoftTimeLimitExceeded

from openclaw.celery_app import app
from src.utils.config import load_config
from src.utils.logger import get_logger

_CST = ZoneInfo("Asia/Shanghai")
logger = get_logger("openclaw.tasks.proxy_health_pipeline")

# Redis keys
_STATUS_KEY = "proxy_health:last_status"  # "ok" | "failing"
_STATUS_TTL = 3600  # 1 hour

# Notification list (matches existing pattern in market_status_pipeline)
_NOTIFICATION_KEY = "notifications:alerts"
_MAX_NOTIFICATIONS = 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_redis():
    """Get Redis client from Celery broker URL."""
    import redis

    config = load_config("openclaw")
    broker = config.get("celery", {}).get("broker_url", "redis://redis:6379/0")
    return redis.from_url(broker, decode_responses=True)


def _load_proxy_health_config() -> dict[str, Any]:
    """Load the proxy_health section from openclaw config."""
    config = load_config("openclaw")
    return config.get("proxy_health", {})


def _get_proxy_env() -> dict[str, str | None]:
    """Return the HTTP(S)_PROXY from environment for requests."""
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    return {"http": http_proxy, "https": https_proxy}


def _no_proxy() -> dict[str, None]:
    """Explicit direct-connect (bypass proxy) for Surge API calls."""
    return {"http": None, "https": None}


def _probe_targets(
    targets: list[dict[str, Any]],
) -> tuple[list[dict], list[dict]]:
    """Probe each target via HEAD request through the proxy.

    Returns (passed, failed) target lists.
    """
    proxy = _get_proxy_env()
    passed: list[dict] = []
    failed: list[dict] = []

    for t in targets:
        name = t["name"]
        url = t["url"]
        timeout = t.get("timeout", 10)
        try:
            resp = requests.head(
                url, proxies=proxy, timeout=timeout, allow_redirects=True
            )
            # 2xx/3xx/4xx = proxy is working (target may reject HEAD)
            if resp.status_code < 500:
                logger.debug("probe %s: %d OK", name, resp.status_code)
                passed.append(t)
            else:
                logger.warning("probe %s: HTTP %d", name, resp.status_code)
                failed.append(t)
        except Exception as exc:
            logger.warning("probe %s: %s", name, exc)
            failed.append(t)

    return passed, failed


def _critical_failed(failed: list[dict]) -> bool:
    """Return True if any critical target is in the failed list."""
    return any(t.get("critical", False) for t in failed)


# ---------------------------------------------------------------------------
# Surge HTTP API helpers
# ---------------------------------------------------------------------------


def _surge_headers() -> dict[str, str]:
    password = os.environ.get("SURGE_API_PASSWORD", "")
    return {"X-Key": password, "Content-Type": "application/json"}


def _surge_api_url() -> str:
    return os.environ.get("SURGE_API_URL", "http://host.docker.internal:6171")


def _surge_get_current_node(group: str) -> str | None:
    """GET current selected policy node for *group*."""
    try:
        resp = requests.get(
            f"{_surge_api_url()}/v1/policy_groups/select",
            params={"group_name": group},
            headers=_surge_headers(),
            proxies=_no_proxy(),
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json().get("policy")
    except Exception as exc:
        logger.error("surge get_current_node failed: %s", exc)
        return None


def _surge_trigger_benchmark(group: str) -> bool:
    """POST URL-test benchmark for *group*."""
    try:
        resp = requests.post(
            f"{_surge_api_url()}/v1/policy_groups/test",
            json={"group_name": group},
            headers=_surge_headers(),
            proxies=_no_proxy(),
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("surge benchmark triggered for group=%s", group)
        return True
    except Exception as exc:
        logger.error("surge benchmark trigger failed: %s", exc)
        return False


def _surge_select_node(group: str, node: str) -> bool:
    """POST force-select *node* in *group*."""
    try:
        resp = requests.post(
            f"{_surge_api_url()}/v1/policy_groups/select",
            json={"group_name": group, "policy": node},
            headers=_surge_headers(),
            proxies=_no_proxy(),
            timeout=5,
        )
        resp.raise_for_status()
        logger.info("surge node switched: group=%s node=%s", group, node)
        return True
    except Exception as exc:
        logger.error("surge select_node failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Discord / Redis notification
# ---------------------------------------------------------------------------


def _push_notification(r, title: str, summary: str) -> None:
    """Push a proxy_health notification to the Redis notification list."""
    notification = {
        "type": "proxy_health",
        "title": title,
        "summary": summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "read": False,
        "id": f"proxy_health_{int(time.time() * 1000)}",
    }
    r.lpush(_NOTIFICATION_KEY, json.dumps(notification, ensure_ascii=False))
    r.ltrim(_NOTIFICATION_KEY, 0, _MAX_NOTIFICATIONS - 1)


def _discord_notify(title: str, summary: str) -> None:
    """Best-effort Discord notification via DiscordNotifier."""
    try:
        from src.utils.notifier import DiscordNotifier

        notifier = DiscordNotifier()
        notifier.send_error_alert(f"**{title}**\n{summary}")
    except Exception as exc:
        logger.warning("discord notify failed: %s", exc)


def _notify(r, title: str, summary: str) -> None:
    """Push notification to Redis + Discord."""
    if r:
        try:
            _push_notification(r, title, summary)
        except Exception as exc:
            logger.warning("redis push_notification failed: %s", exc)
    _discord_notify(title, summary)


# ---------------------------------------------------------------------------
# Main Celery task
# ---------------------------------------------------------------------------


@app.task(
    name="openclaw.tasks.proxy_health_pipeline.task_proxy_health_check",
    bind=True,
    max_retries=0,
    soft_time_limit=90,
    time_limit=120,
)
def task_proxy_health_check(self) -> dict[str, Any]:
    """Probe proxy connectivity and auto-remediate via Surge if needed."""
    try:
        return _run_health_check()
    except SoftTimeLimitExceeded:
        logger.error("proxy_health_check: TIMEOUT (soft_time_limit=90s)")
        return {"status": "failed", "error": "timeout"}
    except Exception as exc:
        logger.error("proxy_health_check failed: %s", exc, exc_info=True)
        return {"status": "error", "error": str(exc)}


def _run_health_check() -> dict[str, Any]:
    """Core health-check logic (extracted for testability)."""
    cfg = _load_proxy_health_config()
    targets = cfg.get("targets", [])
    if not targets:
        logger.warning("proxy_health: no targets configured, skipping")
        return {"status": "skipped", "reason": "no_targets"}

    group = cfg.get("surge_policy_group", "Proxy")
    hk_nodes = cfg.get("hk_fallback_nodes", [])
    wait_seconds = cfg.get("benchmark_wait_seconds", 15)

    # Redis for status debounce
    try:
        r = _get_redis()
    except Exception:
        r = None

    last_status = None
    if r:
        try:
            last_status = r.get(_STATUS_KEY)
        except Exception:
            pass

    # --- Step 1: Probe ---
    passed, failed = _probe_targets(targets)
    logger.info(
        "probe result: passed=%d failed=%d (%s)",
        len(passed),
        len(failed),
        [t["name"] for t in failed],
    )

    # --- Step 2: All critical OK? ---
    if not _critical_failed(failed):
        _set_status(r, "ok")
        if last_status == "failing":
            _notify(r, "🟢 代理已恢复", "所有关键端点连通性正常。")
        return {
            "status": "ok",
            "passed": [t["name"] for t in passed],
            "failed": [t["name"] for t in failed],
        }

    # --- Step 3: Remediate ---
    logger.warning("critical targets failing, attempting remediation")

    surge_password = os.environ.get("SURGE_API_PASSWORD")
    if not surge_password:
        _set_status(r, "failing")
        msg = "代理异常但 SURGE_API_PASSWORD 未配置，无法自动修复。"
        logger.error(msg)
        if last_status != "failing":
            _notify(r, "🔴 代理异常", msg)
        return {"status": "failing", "error": "no_surge_password"}

    old_node = _surge_get_current_node(group)

    # 3a: Trigger URL-test benchmark (Surge picks fastest node)
    if _surge_trigger_benchmark(group):
        logger.info("waiting %ds for benchmark...", wait_seconds)
        time.sleep(wait_seconds)

        # Re-probe
        passed2, failed2 = _probe_targets(targets)
        if not _critical_failed(failed2):
            new_node = _surge_get_current_node(group)
            _set_status(r, "ok")
            msg = f"自动切换成功: {old_node} → {new_node}"
            if last_status != "ok":
                _notify(r, "🟢 代理自动修复", msg)
            logger.info(msg)
            return {
                "status": "ok",
                "remediation": "benchmark",
                "old_node": old_node,
                "new_node": new_node,
            }

    # 3b: Try HK fallback nodes one by one
    for hk_node in hk_nodes:
        logger.info("trying HK fallback node: %s", hk_node)
        if not _surge_select_node(group, hk_node):
            continue
        time.sleep(5)  # Brief settle time
        passed3, failed3 = _probe_targets(targets)
        if not _critical_failed(failed3):
            _set_status(r, "ok")
            msg = f"已降级到 HK 节点: {old_node} → {hk_node}"
            _notify(r, "🟡 代理降级修复", msg)
            logger.info(msg)
            return {
                "status": "ok",
                "remediation": "hk_fallback",
                "old_node": old_node,
                "new_node": hk_node,
            }

    # 3c: All attempts failed
    _set_status(r, "failing")
    msg = "所有修复尝试失败（benchmark + HK fallback）。"
    if last_status != "failing":
        _notify(r, "🔴 代理修复失败", msg)
    logger.error(msg)
    return {
        "status": "failing",
        "error": "all_remediation_failed",
        "failed": [t["name"] for t in failed],
    }


def _set_status(r, status: str) -> None:
    """Write proxy health status to Redis with TTL."""
    if r:
        try:
            r.set(_STATUS_KEY, status, ex=_STATUS_TTL)
        except Exception as exc:
            logger.warning("redis set status failed: %s", exc)

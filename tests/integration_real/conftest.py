"""Shared fixtures for real integration tests — NO mocks, real API calls.

All external dependencies (AKShare, Sina, Xueqiu, adata, yfinance,
LLM providers, Redis) are called with real credentials and network access.
"""

from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Test result collection
# ---------------------------------------------------------------------------

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


@dataclass
class TestResult:
    """Single test measurement."""

    __test__ = False  # prevent pytest collection

    test_name: str
    category: str  # data_source, api_endpoint, llm, security, realtime, stability
    status: str  # pass, fail, skip, error
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class ResultCollector:
    """Accumulates test results across the entire session."""

    def __init__(self) -> None:
        self.results: list[TestResult] = []
        self.start_time = time.monotonic()

    def record(self, result: TestResult) -> None:
        self.results.append(result)

    def to_dict(self) -> dict[str, Any]:
        passed = sum(1 for r in self.results if r.status == "pass")
        failed = sum(1 for r in self.results if r.status == "fail")
        skipped = sum(1 for r in self.results if r.status == "skip")
        errored = sum(1 for r in self.results if r.status == "error")
        return {
            "generated_at": datetime.now().isoformat(),
            "total_duration_s": round(time.monotonic() - self.start_time, 2),
            "summary": {
                "total": len(self.results),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "errored": errored,
            },
            "results": [asdict(r) for r in self.results],
        }

    def save(self, path: Path | None = None) -> Path:
        path = path or (REPORTS_DIR / "integration-real-results.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        return path


# ---------------------------------------------------------------------------
# Rate-limit guard
# ---------------------------------------------------------------------------


class RateLimitGuard:
    """Enforces minimum interval between calls to avoid 429 errors."""

    def __init__(self, min_interval: float = 0.5) -> None:
        self._min_interval = min_interval
        self._last_call = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()


# ---------------------------------------------------------------------------
# Timing helper
# ---------------------------------------------------------------------------


@contextmanager
def measure_time():
    """Context manager yielding a dict that will contain ``elapsed_ms`` on exit."""
    result: dict[str, float] = {}
    start = time.perf_counter()
    try:
        yield result
    finally:
        result["elapsed_ms"] = (time.perf_counter() - start) * 1000


# ---------------------------------------------------------------------------
# Network & env helpers
# ---------------------------------------------------------------------------


def _env_available(var: str) -> bool:
    return bool(os.environ.get(var, "").strip())


def _network_reachable(host: str, port: int = 80, timeout: float = 3.0) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except (OSError, socket.timeout):
        return False


def _redis_available() -> bool:
    try:
        import redis as _redis

        r = _redis.Redis(host="localhost", port=6379, socket_timeout=2)
        return r.ping()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------

requires_china_network = pytest.mark.skipif(
    not _network_reachable("hq.sinajs.cn", 80),
    reason="Chinese financial API network unreachable",
)

requires_google_key = pytest.mark.skipif(
    not _env_available("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set",
)

requires_anthropic_key = pytest.mark.skipif(
    not _env_available("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)

requires_openai_key = pytest.mark.skipif(
    not _env_available("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)

requires_any_llm_key = pytest.mark.skipif(
    not any(
        _env_available(k)
        for k in ["GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
    ),
    reason="No LLM API key set",
)

requires_redis = pytest.mark.skipif(
    not _redis_available(),
    reason="Redis not reachable on localhost:6379",
)

# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def result_collector():
    """Singleton result collector — saved to JSON at session end."""
    collector = ResultCollector()
    yield collector
    path = collector.save()
    print(f"\n[integration_real] Results saved to {path}")


@pytest.fixture(scope="session")
def real_app():
    """Create the REAL FastAPI app with NO dependency overrides."""
    from dotenv import load_dotenv

    load_dotenv()
    from src.web.app import create_app

    app = create_app()
    return app


@pytest.fixture(scope="session")
def real_client(real_app):
    """HTTPX TestClient against the real app (handles lifespan)."""
    from starlette.testclient import TestClient

    with TestClient(real_app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture(scope="session")
def rate_guard():
    """0.5-second guard for data API calls."""
    return RateLimitGuard(min_interval=0.5)


@pytest.fixture(scope="session")
def llm_rate_guard():
    """2-second guard for LLM API calls."""
    return RateLimitGuard(min_interval=2.0)


# ---------------------------------------------------------------------------
# Watchlist helper
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def watchlist_symbols() -> list[str]:
    """Symbols from config/stocks.yaml watchlist."""
    from src.utils.config import load_config

    cfg = load_config("stocks")
    return [item["symbol"] for item in cfg.get("watchlist", [])]


# Apply integration_real marker to all tests in this directory
pytestmark = pytest.mark.integration_real

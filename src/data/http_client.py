"""Shared HTTP session factory with connection pooling and retry.

Provides a centralized session factory with configurable timeouts,
connection pooling, and automatic retry for all data fetcher modules.

Part of WS3: Performance & Reliability.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.logger import get_logger

logger = get_logger("data.http_client")

# Module-level default session (lazily created)
_default_session: requests.Session | None = None


def create_session(
    timeout: tuple[float, float] = (3.0, 15.0),
    retries: int = 1,
    pool_connections: int = 10,
    pool_maxsize: int = 20,
    backoff_factor: float = 0.5,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Session:
    """Create a ``requests.Session`` with connection pooling and retry.

    Args:
        timeout: (connect_timeout, read_timeout) in seconds.
        retries: Maximum number of retries per request.
        pool_connections: Number of connection pools to cache.
        pool_maxsize: Maximum connections per pool.
        backoff_factor: Retry backoff multiplier.
        status_forcelist: HTTP status codes that trigger a retry.

    Returns:
        Configured ``requests.Session`` instance.
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )

    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Store timeout on session for use by callers
    session._default_timeout = timeout  # type: ignore[attr-defined]

    logger.debug(
        "Created HTTP session: timeout=%s, retries=%d, pool=%d/%d",
        timeout,
        retries,
        pool_connections,
        pool_maxsize,
    )
    return session


def get_default_session() -> requests.Session:
    """Return a module-level default session (singleton).

    Lazily creates the session on first call. Thread-safe because
    ``requests.Session`` is thread-safe for ``get``/``post`` calls.
    """
    global _default_session
    if _default_session is None:
        _default_session = create_session()
    return _default_session

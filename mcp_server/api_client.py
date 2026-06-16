"""Async HTTP client for the A-share Docker API.

Wraps httpx with unified error handling so MCP tool handlers
stay concise. All methods return parsed JSON dicts on success
or raise ``ApiError`` on failure.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

BASE_URL = os.environ.get("ASHARE_API_URL", "http://localhost:80/api/v1")
TIMEOUT = float(os.environ.get("ASHARE_API_TIMEOUT", "15"))


class ApiError(Exception):
    """Raised when an API call fails."""

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail}")


async def _request(method: str, path: str, **kwargs: Any) -> dict | list:
    """Execute an HTTP request and return parsed JSON.

    Args:
        method: HTTP method (GET, POST, etc.).
        path: URL path relative to BASE_URL (e.g. "/stock/600519/fund-flow").
        **kwargs: Extra arguments forwarded to httpx.

    Returns:
        Parsed JSON response.

    Raises:
        ApiError: On non-2xx status codes.
        httpx.ConnectError: When the API is unreachable.
    """
    url = f"{BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.request(method, url, **kwargs)
    if resp.status_code >= 400:
        detail = resp.text[:500]
        raise ApiError(resp.status_code, detail)
    return resp.json()


async def get(path: str, **kwargs: Any) -> dict | list:
    """Shorthand for GET request."""
    return await _request("GET", path, **kwargs)

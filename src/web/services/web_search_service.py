"""Web search service — multi-backend with automatic fallback.

Backend priority: SearXNG (self-hosted) → Tavily (API) → DDGS (free).
Rate-limited with a 5-minute sliding window.
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Any

import requests

from src.utils.logger import get_logger

logger = get_logger("web.web_search")

_WINDOW_SECONDS = 300  # 5-minute sliding window
_MAX_CALLS = 10  # max calls per window
_MIN_INTERVAL = 2.0  # seconds between calls
_SEARCH_TIMEOUT = 15  # seconds per request

# SearXNG defaults — override via env vars
_SEARXNG_URL = os.getenv("SEARXNG_URL", "http://searxng:8080")
_TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


class WebSearchService:
    """Multi-backend web search with automatic fallback.

    Priority: SearXNG (self-hosted, no rate limits) → Tavily (API, free
    tier 1K/month) → DDGS (free, rate-limited).
    """

    def __init__(self) -> None:
        self._timestamps: deque[float] = deque()
        self._last_call: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        region: str = "cn-zh",
        search_type: str = "text",
    ) -> dict[str, Any]:
        """Execute a web search with fallback chain.

        Returns:
            Dict with ``results`` list on success or ``error`` on failure.
        """
        max_results = min(int(max_results), 10)

        allowed, cooldown = self._check_rate_limit()
        if not allowed:
            return {
                "error": (
                    f"搜索频率超限（5 分钟内最多 {_MAX_CALLS} 次），"
                    f"剩余冷却 {cooldown} 秒。请不要重试此工具，"
                    "改为使用已有的 search_intel 数据或直接基于已收集信息进行分析。"
                ),
            }

        # Try backends in order
        errors: list[str] = []

        result = self._search_searxng(query, max_results, search_type)
        if result is not None:
            return {
                "query": query,
                "type": search_type,
                "backend": "searxng",
                "results": result,
            }
        errors.append("searxng")

        result = self._search_tavily(query, max_results, search_type)
        if result is not None:
            return {
                "query": query,
                "type": search_type,
                "backend": "tavily",
                "results": result,
            }
        errors.append("tavily")

        result = self._search_ddgs(query, max_results, region, search_type)
        if result is not None:
            return {
                "query": query,
                "type": search_type,
                "backend": "ddgs",
                "results": result,
            }
        errors.append("ddgs")

        logger.error("All search backends failed: %s", errors)
        return {"error": "所有搜索引擎均不可用，请稍后再试"}

    # ------------------------------------------------------------------
    # Backend: SearXNG (self-hosted, primary)
    # ------------------------------------------------------------------

    def _search_searxng(
        self, query: str, max_results: int, search_type: str
    ) -> list[dict[str, str]] | None:
        """Search via self-hosted SearXNG instance."""
        try:
            categories = "news" if search_type == "news" else "general"
            resp = requests.get(
                f"{_SEARXNG_URL}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": categories,
                    "language": "zh-CN",
                    "pageno": 1,
                },
                timeout=_SEARCH_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", [])[:max_results]:
                entry: dict[str, str] = {
                    "title": item.get("title", ""),
                    "snippet": item.get("content", ""),
                    "url": item.get("url", ""),
                }
                if item.get("publishedDate"):
                    entry["date"] = item["publishedDate"]
                results.append(entry)
            logger.info("SearXNG returned %d results for: %s", len(results), query[:50])
            return results
        except Exception as exc:
            logger.debug("SearXNG unavailable: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Backend: Tavily (API, fallback)
    # ------------------------------------------------------------------

    def _search_tavily(
        self, query: str, max_results: int, search_type: str
    ) -> list[dict[str, str]] | None:
        """Search via Tavily API (free tier: 1K searches/month)."""
        if not _TAVILY_API_KEY:
            return None
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": _TAVILY_API_KEY,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "topic": "news" if search_type == "news" else "general",
                    "include_answer": False,
                },
                timeout=_SEARCH_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", [])[:max_results]:
                entry: dict[str, str] = {
                    "title": item.get("title", ""),
                    "snippet": item.get("content", ""),
                    "url": item.get("url", ""),
                }
                if item.get("published_date"):
                    entry["date"] = item["published_date"]
                results.append(entry)
            logger.info("Tavily returned %d results for: %s", len(results), query[:50])
            return results
        except Exception as exc:
            logger.debug("Tavily failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Backend: DDGS (free, last resort)
    # ------------------------------------------------------------------

    def _search_ddgs(
        self, query: str, max_results: int, region: str, search_type: str
    ) -> list[dict[str, str]] | None:
        """Search via DDGS (DuckDuckGo aggregator)."""
        try:
            from ddgs import DDGS
        except ImportError:
            return None

        try:
            with DDGS(timeout=_SEARCH_TIMEOUT) as ddgs:
                if search_type == "news":
                    raw = list(
                        ddgs.news(
                            query,
                            region=region,
                            max_results=max_results,
                            backend="auto",
                        )
                    )
                else:
                    raw = list(
                        ddgs.text(
                            query,
                            region=region,
                            max_results=max_results,
                            backend="auto",
                        )
                    )
        except Exception as exc:
            logger.debug("DDGS failed: %s", exc)
            return None

        results = []
        for item in raw:
            entry: dict[str, str] = {
                "title": item.get("title", ""),
                "snippet": item.get("body", item.get("excerpt", "")),
                "url": item.get("href", item.get("url", "")),
            }
            if item.get("date"):
                entry["date"] = item["date"]
            results.append(entry)
        logger.info("DDGS returned %d results for: %s", len(results), query[:50])
        return results

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> tuple[bool, int]:
        """Check if a call is allowed under rate limits."""
        now = time.monotonic()

        if now - self._last_call < _MIN_INTERVAL:
            return False, int(_MIN_INTERVAL - (now - self._last_call)) + 1

        while self._timestamps and self._timestamps[0] < now - _WINDOW_SECONDS:
            self._timestamps.popleft()

        if len(self._timestamps) >= _MAX_CALLS:
            oldest = self._timestamps[0]
            cooldown = int(_WINDOW_SECONDS - (now - oldest)) + 1
            return False, cooldown

        self._timestamps.append(now)
        self._last_call = now
        return True, 0

"""Web search service — multi-engine search with rate limiting.

Provides a lightweight web search capability for the agent to find
stock-related news and information beyond the local intelligence hub.
Uses ddgs (v9+) which aggregates results from multiple search engines.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("web.web_search")

_WINDOW_SECONDS = 300  # 5-minute sliding window
_MAX_CALLS = 10  # max calls per window
_MIN_INTERVAL = 2.0  # seconds between calls
_SEARCH_TIMEOUT = 15  # seconds per request


class WebSearchService:
    """Multi-engine web search (ddgs v9+) with built-in rate limiting.

    ddgs v9 aggregates results from DuckDuckGo, Bing, Brave, Google etc.
    In Docker, set ``DDGS_PROXY`` env var for automatic proxy support.
    Gracefully degrades if the ``ddgs`` package is not installed or if
    a search fails at runtime.
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
        """Execute a web search and return slim results.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return (capped at 10).
            region: DuckDuckGo region code (default ``cn-zh``).
            search_type: ``"text"`` for general search, ``"news"`` for news.

        Returns:
            Dict with ``results`` list on success or ``error`` on failure.
        """
        max_results = min(int(max_results), 10)

        # Rate-limit check
        allowed, cooldown = self._check_rate_limit()
        if not allowed:
            return {
                "error": (
                    f"搜索频率超限（5 分钟内最多 {_MAX_CALLS} 次），"
                    f"剩余冷却 {cooldown} 秒。请不要重试此工具，"
                    "改为使用已有的 search_intel 数据或直接基于已收集信息进行分析。"
                ),
            }

        try:
            from ddgs import DDGS
        except ImportError:
            return {"error": "联网搜索暂不可用（ddgs 未安装）"}

        try:
            from ddgs.exceptions import RatelimitException, TimeoutException
        except ImportError:
            RatelimitException = TimeoutException = None

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
            if RatelimitException and isinstance(exc, RatelimitException):
                logger.warning("Web search rate-limited by upstream: %s", exc)
                return {"error": "搜索引擎限频，请稍后再试"}
            if TimeoutException and isinstance(exc, TimeoutException):
                logger.warning("Web search timeout (all backends): %s", exc)
                return {"error": "搜索超时（所有引擎均无响应），请稍后再试"}
            logger.warning("Web search failed: %s", exc)
            return {"error": f"搜索失败: {exc}"}

        results = []
        for item in raw:
            entry: dict[str, str] = {}
            entry["title"] = item.get("title", "")
            entry["snippet"] = item.get("body", item.get("excerpt", ""))
            entry["url"] = item.get("href", item.get("url", ""))
            if item.get("date"):
                entry["date"] = item["date"]
            results.append(entry)

        return {"query": query, "type": search_type, "results": results}

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> tuple[bool, int]:
        """Check if a call is allowed under rate limits.

        Returns:
            Tuple of (allowed, cooldown_seconds).  When ``allowed`` is False,
            ``cooldown_seconds`` indicates how long the caller should wait.
        """
        now = time.monotonic()

        # Enforce minimum interval between calls
        if now - self._last_call < _MIN_INTERVAL:
            return False, int(_MIN_INTERVAL - (now - self._last_call)) + 1

        # Sliding window: drop timestamps older than the window
        while self._timestamps and self._timestamps[0] < now - _WINDOW_SECONDS:
            self._timestamps.popleft()

        if len(self._timestamps) >= _MAX_CALLS:
            oldest = self._timestamps[0]
            cooldown = int(_WINDOW_SECONDS - (now - oldest)) + 1
            return False, cooldown

        self._timestamps.append(now)
        self._last_call = now
        return True, 0

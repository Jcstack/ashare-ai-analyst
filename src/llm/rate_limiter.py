"""Token bucket rate limiter with request deduplication cache.

Prevents Gemini 429 errors by throttling outgoing LLM requests and
caching duplicate request results.

Per PRD v2.5 FR-RL001/RL002.
"""

import hashlib
import random
import threading
import time
from dataclasses import dataclass
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("llm.rate_limiter")


@dataclass
class _CacheEntry:
    """A cached LLM response with TTL."""

    response: Any
    expires_at: float


class RateLimiter:
    """Token bucket rate limiter with LRU deduplication cache.

    Args:
        requests_per_minute: Maximum requests per minute (RPM).
        cache_ttl: Dedup cache TTL in seconds.
        cache_max_size: Maximum number of cached entries.
    """

    def __init__(
        self,
        requests_per_minute: int = 60,
        cache_ttl: float = 60.0,
        cache_max_size: int = 100,
    ) -> None:
        self._rpm = max(requests_per_minute, 1)
        self._interval = 60.0 / self._rpm  # seconds between tokens
        self._tokens = float(self._rpm)
        self._max_tokens = float(self._rpm)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

        # Dedup cache
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl
        self._cache_max_size = cache_max_size
        self._cache_lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> bool:
        """Acquire a rate limit token, blocking up to ``timeout`` seconds.

        Returns:
            True if a token was acquired, False on timeout.
        """
        deadline = time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                wait_time = self._interval - (time.monotonic() - self._last_refill)

            # Add jitter to avoid thundering herd
            wait_time = max(0.01, wait_time + random.uniform(0, 0.5))

            if time.monotonic() + wait_time > deadline:
                logger.warning(
                    "Rate limiter timeout after %.1fs (RPM=%d)", timeout, self._rpm
                )
                return False

            time.sleep(wait_time)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed / self._interval
        self._tokens = min(self._max_tokens, self._tokens + new_tokens)
        self._last_refill = now

    @staticmethod
    def make_cache_key(messages: list[Any]) -> str:
        """Create a hash key from message contents for dedup.

        Args:
            messages: List of LLMMessage or dicts.

        Returns:
            Hex digest string.
        """
        parts = []
        for msg in messages:
            if hasattr(msg, "role"):
                parts.append(f"{msg.role}:{msg.content}")
            elif isinstance(msg, dict):
                parts.append(f"{msg.get('role', '')}:{msg.get('content', '')}")
            else:
                parts.append(str(msg))
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get_cached(self, key: str) -> Any | None:
        """Get a cached response if still valid.

        Args:
            key: Cache key from ``make_cache_key``.

        Returns:
            Cached response or None.
        """
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                del self._cache[key]
                return None
            return entry.response

    def set_cached(self, key: str, response: Any) -> None:
        """Store a response in the dedup cache.

        Args:
            key: Cache key.
            response: LLM response to cache.
        """
        with self._cache_lock:
            # Evict expired entries if at capacity
            if len(self._cache) >= self._cache_max_size:
                now = time.monotonic()
                expired = [k for k, v in self._cache.items() if now > v.expires_at]
                for k in expired:
                    del self._cache[k]
                # If still full, remove oldest
                if len(self._cache) >= self._cache_max_size:
                    oldest_key = next(iter(self._cache))
                    del self._cache[oldest_key]

            self._cache[key] = _CacheEntry(
                response=response,
                expires_at=time.monotonic() + self._cache_ttl,
            )

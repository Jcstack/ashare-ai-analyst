"""L1/L2 two-level cache for LLM analysis results.

L1: in-process dict (per-worker, 0ms).
L2: Redis (shared across workers, 1-2ms).

Redis key namespace: ``llm:result:<cache_key>`` — isolated from
``rec:*``, ``agent_conversation:*``, and other namespaces.

If Redis is unavailable or errors, L2 is silently disabled and the
cache degrades to pure in-memory (identical to pre-cache behaviour).
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("llm.cache")

_KEY_PREFIX = "llm:result:"


class LLMResultCache:
    """Two-level (L1 in-memory + L2 Redis) cache for LLM results.

    Args:
        redis_client: A ``redis.Redis`` instance (``decode_responses=True``).
            Pass ``None`` to disable L2 (pure in-memory mode).
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._l1: dict[str, tuple[float, dict[str, Any]]] = {}

    # ── public API ──────────────────────────────────────────────────────

    def get(self, key: str, ttl: float) -> dict[str, Any] | None:
        """Look up *key*, checking L1 then L2.

        On L2 hit the result is back-filled into L1.

        Returns:
            Cached dict or ``None`` on miss.
        """
        # L1
        if key in self._l1:
            ts, data = self._l1[key]
            if time.time() - ts < ttl:
                return data

        # L2
        data = self._get_redis(key, ttl)
        if data is not None:
            self._l1[key] = (time.time(), data)
            return data

        return None

    def set(self, key: str, data: dict[str, Any], ttl_seconds: int) -> None:
        """Write to both L1 and L2."""
        self._l1[key] = (time.time(), data)
        self._set_redis(key, data, ttl_seconds)

    # ── Redis helpers (silent degradation) ──────────────────────────────

    def _get_redis(self, key: str, ttl: float) -> dict[str, Any] | None:
        if self._redis is None:
            return None
        try:
            raw = self._redis.get(f"{_KEY_PREFIX}{key}")
            if raw is None:
                return None
            payload = json.loads(raw)
            ts = payload.get("_ts", 0)
            if time.time() - ts >= ttl:
                return None
            return payload.get("data")
        except Exception as exc:
            logger.debug("Redis L2 GET failed for %s: %s", key, exc)
            return None

    def _set_redis(self, key: str, data: dict[str, Any], ttl_seconds: int) -> None:
        if self._redis is None:
            return
        try:
            payload = json.dumps({"_ts": time.time(), "data": data}, default=str)
            self._redis.set(f"{_KEY_PREFIX}{key}", payload, ex=ttl_seconds)
        except Exception as exc:
            logger.debug("Redis L2 SET failed for %s: %s", key, exc)

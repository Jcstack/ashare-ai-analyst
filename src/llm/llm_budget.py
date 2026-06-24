"""LLM Budget Tracker — Redis-backed daily/minute call limits.

Prevents runaway LLM spend by tracking calls per provider and model.
Falls back to unlimited when Redis is unavailable (never blocks normal flow).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class LLMBudgetTracker:
    """Track LLM call counts per provider/model with Redis counters.

    Args:
        redis_client: A Redis client (or None — disables tracking).
        config: Budget config dict from ``config/llm.yaml`` ``budget`` section.
    """

    def __init__(
        self, redis_client: object | None = None, config: dict | None = None
    ) -> None:
        self._redis = redis_client
        cfg = config or {}
        self._daily_limits: dict[str, int] = cfg.get("daily_limits", {})
        self._minute_limits: dict[str, int] = cfg.get("per_minute_limits", {})
        self._model_daily_limits: dict[str, int] = cfg.get("model_daily_limits", {})

    def can_call(self, provider: str, model: str | None = None) -> bool:
        """Check whether a call is within budget.

        Returns True (allow) when Redis is unavailable or not configured.
        """
        if not self._redis:
            return True

        now = datetime.now(UTC)
        try:
            # Daily provider limit
            daily_limit = self._daily_limits.get(provider)
            if daily_limit is not None:
                daily_key = f"llm_budget:daily:{provider}:{now.strftime('%Y%m%d')}"
                count = self._redis.get(daily_key)
                if count is not None and int(count) >= daily_limit:
                    logger.warning(
                        "LLM budget exceeded: %s daily %s >= %d",
                        provider,
                        count,
                        daily_limit,
                    )
                    return False

            # Per-minute provider limit
            minute_limit = self._minute_limits.get(provider)
            if minute_limit is not None:
                minute_key = (
                    f"llm_budget:minute:{provider}:{now.strftime('%Y%m%d%H%M')}"
                )
                count = self._redis.get(minute_key)
                if count is not None and int(count) >= minute_limit:
                    return False

            # Model-level daily limit
            if model:
                model_limit = self._model_daily_limits.get(model)
                if model_limit is not None:
                    model_key = (
                        f"llm_budget:daily:model:{model}:{now.strftime('%Y%m%d')}"
                    )
                    count = self._redis.get(model_key)
                    if count is not None and int(count) >= model_limit:
                        logger.warning(
                            "LLM budget exceeded: model %s daily %s >= %d",
                            model,
                            count,
                            model_limit,
                        )
                        return False
        except Exception as exc:
            logger.debug("Budget check failed (allowing call): %s", exc)

        return True

    def record_call(self, provider: str, model: str | None = None) -> None:
        """Increment call counters for provider and optional model."""
        if not self._redis:
            return

        now = datetime.now(UTC)
        try:
            # Daily counter (expires after 26h for safety)
            daily_key = f"llm_budget:daily:{provider}:{now.strftime('%Y%m%d')}"
            pipe = self._redis.pipeline(transaction=False)
            pipe.incr(daily_key)
            pipe.expire(daily_key, 93600)  # 26h

            # Per-minute counter (expires after 120s)
            minute_key = f"llm_budget:minute:{provider}:{now.strftime('%Y%m%d%H%M')}"
            pipe.incr(minute_key)
            pipe.expire(minute_key, 120)

            # Model-level daily counter
            if model:
                model_key = f"llm_budget:daily:model:{model}:{now.strftime('%Y%m%d')}"
                pipe.incr(model_key)
                pipe.expire(model_key, 93600)

            pipe.execute()
        except Exception as exc:
            logger.debug("Budget record failed (non-blocking): %s", exc)

    def get_remaining(self, provider: str) -> dict[str, int | None]:
        """Return remaining budget for a provider.

        Returns ``{"daily": N, "per_minute": N}`` where N is remaining
        calls or None if no limit is configured.
        """
        result: dict[str, int | None] = {"daily": None, "per_minute": None}

        if not self._redis:
            return result

        now = datetime.now(UTC)
        try:
            daily_limit = self._daily_limits.get(provider)
            if daily_limit is not None:
                daily_key = f"llm_budget:daily:{provider}:{now.strftime('%Y%m%d')}"
                count = int(self._redis.get(daily_key) or 0)
                result["daily"] = max(0, daily_limit - count)

            minute_limit = self._minute_limits.get(provider)
            if minute_limit is not None:
                minute_key = (
                    f"llm_budget:minute:{provider}:{now.strftime('%Y%m%d%H%M')}"
                )
                count = int(self._redis.get(minute_key) or 0)
                result["per_minute"] = max(0, minute_limit - count)
        except Exception as exc:
            logger.debug("Budget query failed: %s", exc)

        return result

"""Alert Priority Router — routes intelligence to appropriate channels.

Determines which messages are worth pushing vs storing quietly.
Deduplicates within time windows. Routes to MessageStore + Discord.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.alert_priority_router")


class AlertPriorityRouter:
    """Messenger team: routes alerts based on priority and dedup rules.

    Routes intelligence messages to MessageStore (always) and Discord
    (for high/critical priority). Deduplicates within configurable
    time windows using Redis.
    """

    # Priority → behavior mapping
    ROUTING_RULES: dict[str, dict[str, Any]] = {
        "critical": {"store": True, "discord": True, "min_interval_hours": 0.5},
        "high": {"store": True, "discord": True, "min_interval_hours": 2},
        "normal": {"store": True, "discord": False, "min_interval_hours": 4},
        "low": {"store": True, "discord": False, "min_interval_hours": 8},
    }

    def __init__(
        self,
        message_store: Any,
        notifier: Any,
        redis_client: Any | None = None,
    ) -> None:
        self._message_store = message_store
        self._notifier = notifier
        self._redis = redis_client

    async def route_alert(self, message: dict[str, Any]) -> dict[str, Any]:
        """Route a message to appropriate channels based on priority.

        Args:
            message: Message dict from PlainLanguageWriter with keys:
                type, title, content, priority, stock_recommendations, metadata.

        Returns:
            Routing result with routed flag, channels list, and message_id.
        """
        priority = message.get("priority", "normal")
        rules = self.ROUTING_RULES.get(priority, self.ROUTING_RULES["normal"])

        # Dedup check
        dedup_key = self._dedup_key(message)
        if await self._is_duplicate(dedup_key, rules["min_interval_hours"]):
            logger.debug("Deduplicated alert: %s", message.get("title", "")[:40])
            return {"routed": False, "reason": "duplicate"}

        result: dict[str, Any] = {"routed": True, "channels": []}

        # Store in MessageStore
        if rules["store"]:
            try:
                msg_id = self._store_message(message)
                result["channels"].append("message_store")
                result["message_id"] = msg_id
            except Exception as exc:
                logger.error("Failed to store message: %s", exc)

        # Push to Discord
        if rules["discord"]:
            try:
                self._push_discord(message)
                result["channels"].append("discord")
            except Exception as exc:
                logger.warning("Failed to push to Discord: %s", exc)

        # Mark as sent in Redis
        await self._mark_sent(dedup_key, rules["min_interval_hours"])

        logger.info(
            "Routed alert [%s] to %s: %s",
            priority,
            result["channels"],
            message.get("title", "")[:40],
        )
        return result

    def _store_message(self, message: dict[str, Any]) -> int:
        """Store message via MessageStore."""
        stock_recs = message.get("stock_recommendations")
        content = message.get("content", "")

        return self._message_store.create_message(
            msg_type=message.get("type", "global_intelligence"),
            title=message.get("title", ""),
            summary=content[:200] if content else "",
            content=content,
            priority=message.get("priority", "normal"),
            stock_recommendations=stock_recs,
        )

    def _push_discord(self, message: dict[str, Any]) -> None:
        """Push to Discord via notifier."""
        title = message.get("title", "全球情报")
        content = message.get("content", "")
        priority = message.get("priority", "normal")

        # Format for Discord
        emoji = {
            "critical": "🚨",
            "high": "⚠️",
            "normal": "📰",
            "low": "ℹ️",
        }.get(priority, "📰")
        discord_msg = f"{emoji} **{title}**\n\n{content[:1500]}"

        # Use the notifier's error alert as a generic send channel
        self._notifier.send_error_alert(discord_msg)

    @staticmethod
    def _dedup_key(message: dict[str, Any]) -> str:
        """Generate dedup key from message content."""
        raw = f"{message.get('type', '')}:{message.get('title', '')}".encode()
        return f"git:alert:{hashlib.md5(raw).hexdigest()[:12]}"  # noqa: S324

    async def _is_duplicate(self, key: str, hours: float) -> bool:
        """Check if an alert with this key was recently sent."""
        if not self._redis:
            return False
        try:
            return bool(await self._redis.exists(key))
        except Exception:
            return False

    async def _mark_sent(self, key: str, hours: float) -> None:
        """Mark an alert key as sent with TTL."""
        if not self._redis:
            return
        try:
            await self._redis.setex(key, int(hours * 3600), "1")
        except Exception as exc:
            logger.debug("Redis mark_sent failed: %s", exc)


@lru_cache(maxsize=1)
def get_alert_priority_router() -> AlertPriorityRouter:
    """Singleton factory for AlertPriorityRouter."""
    from src.web.dependencies import get_message_store

    from src.utils.notifier import DiscordNotifier

    notifier = DiscordNotifier()

    redis_client = None
    try:
        from src.intelligence.event_bus import EventBus

        bus = EventBus()
        # Reuse the bus Redis connection if available
        redis_client = bus._redis
    except Exception:
        pass

    return AlertPriorityRouter(
        message_store=get_message_store(),
        notifier=notifier,
        redis_client=redis_client,
    )

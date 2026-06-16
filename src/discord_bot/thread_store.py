"""Redis-backed Discord thread ↔ Agent thread mapping store.

Callers should use ``asyncio.to_thread()`` for all public methods since
the underlying redis-py client is synchronous.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("discord.thread_store")

_KEY_PREFIX = "discord:thread_map:"
_DEFAULT_TTL = 86400  # 24 hours


@dataclass
class ThreadMapping:
    """Value object persisted in Redis for each active Discord thread."""

    agent_thread_id: str
    source_command: str
    context_summary: str
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    round_count: int = 0
    ended: bool = False


class ThreadStore:
    """Synchronous Redis CRUD for Discord ↔ Agent thread mappings."""

    def __init__(self, redis_client: Any) -> None:
        self._r = redis_client

    @staticmethod
    def _key(discord_thread_id: int) -> str:
        return f"{_KEY_PREFIX}{discord_thread_id}"

    def save(self, discord_thread_id: int, mapping: ThreadMapping) -> None:
        key = self._key(discord_thread_id)
        self._r.set(key, json.dumps(asdict(mapping)), ex=_DEFAULT_TTL)

    def get(self, discord_thread_id: int) -> ThreadMapping | None:
        key = self._key(discord_thread_id)
        raw = self._r.get(key)
        if raw is None:
            return None
        try:
            return ThreadMapping(**json.loads(raw))
        except Exception:
            logger.warning("Corrupt thread mapping for %s", discord_thread_id)
            return None

    def update_active(self, discord_thread_id: int) -> ThreadMapping | None:
        """Bump last_active_at + round_count and refresh TTL."""
        mapping = self.get(discord_thread_id)
        if mapping is None:
            return None
        mapping.last_active_at = time.time()
        mapping.round_count += 1
        self.save(discord_thread_id, mapping)
        return mapping

    def mark_ended(self, discord_thread_id: int) -> ThreadMapping | None:
        mapping = self.get(discord_thread_id)
        if mapping is None:
            return None
        mapping.ended = True
        mapping.last_active_at = time.time()
        self.save(discord_thread_id, mapping)
        return mapping

    def delete(self, discord_thread_id: int) -> None:
        self._r.delete(self._key(discord_thread_id))

    def scan_active(self) -> list[tuple[int, ThreadMapping]]:
        """Return all non-ended thread mappings via SCAN."""
        results: list[tuple[int, ThreadMapping]] = []
        cursor = 0
        pattern = f"{_KEY_PREFIX}*"
        while True:
            cursor, keys = self._r.scan(cursor=cursor, match=pattern, count=100)
            for key in keys:
                raw = self._r.get(key)
                if raw is None:
                    continue
                try:
                    mapping = ThreadMapping(**json.loads(raw))
                except Exception:
                    continue
                if not mapping.ended:
                    # Extract discord_thread_id from key
                    tid_str = key.removeprefix(_KEY_PREFIX)
                    try:
                        results.append((int(tid_str), mapping))
                    except ValueError:
                        continue
            if cursor == 0:
                break
        return results

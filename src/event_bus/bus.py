"""Redis Streams-based event bus.

Implements publish/subscribe over Redis Streams (XADD/XREAD/XREADGROUP)
for the Trading Agent OS event-driven architecture.

Per PRD v50.0 §17.3: all inter-module communication flows through
typed event streams with consumer groups for reliable delivery.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

import redis

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("event_bus.bus")

# Type alias for event callback: (stream, event_id, event_data) -> None
EventCallback = Callable[[str, str, dict[str, Any]], None]


def _resolve_redis_url(config: dict[str, Any]) -> str:
    """Resolve Redis URL from config, expanding env vars."""
    url = config.get("redis_url", "redis://redis:6379/0")
    # Handle ${VAR:-default} syntax
    if url.startswith("${") and ":-" in url:
        var_name = url[2 : url.index(":-")]
        default = url[url.index(":-") + 2 : url.rindex("}")]
        return os.environ.get(var_name, default)
    return url


class EventBus:
    """Redis Streams event bus with consumer group support.

    Usage::

        bus = EventBus()
        bus.publish("events:market", "price_spike", {"symbol": "000001", "z": 3.5})

        # Consume in a loop
        bus.subscribe(
            streams=["events:market"],
            consumer_group="signal_engine",
            consumer_name="worker-1",
            callback=my_handler,
        )

    Args:
        config_name: YAML config file name (default: "event_bus").
        redis_client: Optional pre-configured redis.Redis instance.
    """

    def __init__(
        self,
        config_name: str = "event_bus",
        redis_client: redis.Redis | None = None,
    ) -> None:
        self._config = load_config(config_name)
        self._streams: dict[str, str] = self._config.get("streams", {})
        self._batch_size: int = self._config.get("batch_size", 10)
        self._block_ms: int = self._config.get("block_ms", 5000)
        self._max_stream_len: int = self._config.get("max_stream_length", 10000)

        if redis_client is not None:
            self._redis = redis_client
        else:
            url = _resolve_redis_url(self._config)
            self._redis = redis.from_url(url, decode_responses=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def stream_names(self) -> dict[str, str]:
        """Return the configured stream name mapping (logical -> Redis key)."""
        return dict(self._streams)

    def publish(
        self,
        stream: str,
        event_type: str,
        data: dict[str, Any],
        *,
        maxlen: int | None = None,
    ) -> str:
        """Publish an event to a stream.

        Args:
            stream: Redis stream key (e.g. "events:market").
            event_type: Event type tag (e.g. "price_spike").
            data: Arbitrary JSON-serializable payload.
            maxlen: Optional stream MAXLEN override (approximate trimming).

        Returns:
            The Redis stream entry ID (e.g. "1678886400000-0").
        """
        entry = {
            "type": event_type,
            "ts": str(time.time()),
            "data": json.dumps(data, default=str),
        }
        effective_maxlen = maxlen if maxlen is not None else self._max_stream_len
        entry_id: str = self._redis.xadd(
            stream,
            entry,
            maxlen=effective_maxlen,
            approximate=True,
        )
        logger.debug("Published %s to %s: id=%s", event_type, stream, entry_id)
        return entry_id

    def ensure_consumer_group(
        self,
        stream: str,
        group: str,
        start_id: str = "0",
    ) -> bool:
        """Create a consumer group if it does not already exist.

        Uses XGROUP CREATE with MKSTREAM so the stream is created if absent.

        Args:
            stream: Redis stream key.
            group: Consumer group name.
            start_id: Starting message ID ("0" = all history, "$" = new only).

        Returns:
            True if the group was created, False if it already existed.
        """
        try:
            self._redis.xgroup_create(
                stream,
                group,
                id=start_id,
                mkstream=True,
            )
            logger.info("Created consumer group %s on %s", group, stream)
            return True
        except redis.ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                logger.debug("Consumer group %s already exists on %s", group, stream)
                return False
            raise

    def subscribe(
        self,
        streams: list[str],
        consumer_group: str,
        consumer_name: str,
        callback: EventCallback,
        *,
        batch_size: int | None = None,
        block_ms: int | None = None,
        max_iterations: int | None = None,
    ) -> int:
        """Consume events from one or more streams using a consumer group.

        Blocks and reads in a loop, invoking ``callback`` for each event.
        The loop runs until ``max_iterations`` batches are consumed (or
        forever if ``max_iterations`` is None).

        Args:
            streams: List of Redis stream keys to read from.
            consumer_group: Consumer group name.
            consumer_name: Unique consumer name within the group.
            callback: Function called with (stream, entry_id, parsed_data).
            batch_size: Override default batch size.
            block_ms: Override default block timeout in ms.
            max_iterations: Stop after this many read cycles (None = infinite).

        Returns:
            Total number of events processed.
        """
        effective_batch = batch_size if batch_size is not None else self._batch_size
        effective_block = block_ms if block_ms is not None else self._block_ms

        # Ensure consumer groups exist for all requested streams
        for stream in streams:
            self.ensure_consumer_group(stream, consumer_group)

        # Build the streams dict for XREADGROUP: {stream: ">"} means undelivered
        stream_ids = {s: ">" for s in streams}
        total_processed = 0
        iterations = 0

        while max_iterations is None or iterations < max_iterations:
            iterations += 1
            try:
                results = self._redis.xreadgroup(
                    consumer_group,
                    consumer_name,
                    stream_ids,
                    count=effective_batch,
                    block=effective_block,
                )
            except redis.ConnectionError:
                logger.warning("Redis connection lost, retrying in 1s")
                time.sleep(1)
                continue

            if not results:
                continue

            for stream_name, messages in results:
                for entry_id, raw_fields in messages:
                    parsed = self._deserialize(raw_fields)
                    try:
                        callback(stream_name, entry_id, parsed)
                        # ACK after successful processing
                        self._redis.xack(stream_name, consumer_group, entry_id)
                        total_processed += 1
                    except Exception:
                        logger.exception(
                            "Error processing event %s from %s",
                            entry_id,
                            stream_name,
                        )

        return total_processed

    def read_pending(
        self,
        stream: str,
        group: str,
        consumer_name: str,
        *,
        count: int = 10,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Read pending (unacknowledged) messages for a consumer.

        Useful for reprocessing failed events on restart.

        Args:
            stream: Redis stream key.
            group: Consumer group name.
            consumer_name: Consumer name to claim messages for.
            count: Maximum number of pending messages to read.

        Returns:
            List of (entry_id, parsed_data) tuples.
        """
        # Read messages starting from ID "0" to get pending ones
        results = self._redis.xreadgroup(
            group,
            consumer_name,
            {stream: "0"},
            count=count,
            block=0,
        )
        pending = []
        if results:
            for _stream_name, messages in results:
                for entry_id, raw_fields in messages:
                    if raw_fields:  # Empty fields means already acked
                        parsed = self._deserialize(raw_fields)
                        pending.append((entry_id, parsed))
        return pending

    def health_check(self) -> dict[str, Any]:
        """Check event bus health.

        Returns:
            Dict with redis connectivity, stream info, and consumer group status.
        """
        result: dict[str, Any] = {"healthy": False, "streams": {}}
        try:
            self._redis.ping()
            result["healthy"] = True
        except redis.ConnectionError:
            return result

        for logical_name, stream_key in self._streams.items():
            try:
                info = self._redis.xinfo_stream(stream_key)
                result["streams"][logical_name] = {
                    "key": stream_key,
                    "length": info["length"],
                    "first_entry": info.get("first-entry"),
                    "last_entry": info.get("last-entry"),
                }
            except redis.ResponseError:
                result["streams"][logical_name] = {
                    "key": stream_key,
                    "length": 0,
                    "status": "not_created",
                }

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _deserialize(raw: dict[str, str]) -> dict[str, Any]:
        """Deserialize a raw Redis stream entry into a typed dict."""
        event_type = raw.get("type", "unknown")
        ts_str = raw.get("ts", "0")
        data_str = raw.get("data", "{}")
        try:
            data = json.loads(data_str)
        except (json.JSONDecodeError, TypeError):
            data = {"raw": data_str}
        return {
            "type": event_type,
            "ts": float(ts_str),
            "data": data,
        }

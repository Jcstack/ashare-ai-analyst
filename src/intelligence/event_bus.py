"""Event Bus — Redis Streams-based pub/sub for agent team communication.

Provides publish/subscribe/read_history over named streams.
Each consumer gets its own consumer group for at-least-once delivery.

Also provides IntelligenceEventBus for real-time market event routing
to research agents (news, price spikes, policy, capital flow anomalies).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from typing import Any, Callable, Awaitable

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("intelligence.event_bus")


# ---------------------------------------------------------------------------
# Market event types and data classes
# ---------------------------------------------------------------------------


class EventType(Enum):
    """Types of market events that trigger real-time analysis."""

    NEWS = "news"
    PRICE_SPIKE = "price_spike"
    POLICY = "policy"
    CAPITAL_FLOW_ANOMALY = "capital_flow_anomaly"
    SECTOR_ROTATION = "sector_rotation"
    LIMIT_UP = "limit_up"


@dataclass
class MarketEvent:
    """A market event that can trigger research agent analysis."""

    event_type: EventType
    symbol: str | None  # None for market-wide events
    data: dict[str, Any]
    severity: float  # 0.0-1.0
    timestamp: datetime
    source: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class BusEvent:
    """A single event on the bus."""

    stream: str
    event_id: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Redis Streams event bus for Global Intelligence Agent Teams.

    Streams:
      sentinel:raw_intel        — Sentinel → Analyst: raw news/data items
      analyst:event_understood   — Analyst → Strategist: parsed events
      analyst:causal_chain       — Analyst → Strategist: impact chains
      analyst:event_state_change — Analyst → All: event state transitions
      strategist:signal          — Strategist → SignalAggregator: trade signals
      strategist:scenario        — Strategist → Messenger: scenario analysis
      messenger:push             — Messenger → Discord/MessageStore: push items
    """

    STREAMS = [
        "sentinel:raw_intel",
        "analyst:event_understood",
        "analyst:causal_chain",
        "analyst:event_state_change",
        "strategist:signal",
        "strategist:scenario",
        "messenger:push",
    ]

    def __init__(self, redis_url: str | None = None, prefix: str = "git") -> None:
        self._redis_url = redis_url or self._load_redis_url()
        self._prefix = prefix
        self._redis = None
        self._maxlen: dict[str, int] = {}
        self._load_config()

    def _load_redis_url(self) -> str:
        """Load Redis URL from config or env.

        Priority: INTEL_REDIS_URL → REDIS_URL (with /1 suffix) → default.
        Uses localhost fallback when Docker hostname 'redis' is unavailable.
        """
        import os

        intel_url = os.environ.get("INTEL_REDIS_URL")
        if intel_url:
            return intel_url

        base_url = os.environ.get("REDIS_URL")
        if base_url:
            # Ensure intelligence bus uses DB 1 (separate from main bus DB 0)
            if base_url.rstrip("/").endswith("/0"):
                return base_url.rstrip("/")[:-1] + "1"
            return base_url

        # Default: try Docker hostname, fall back to localhost
        import socket

        try:
            socket.getaddrinfo("redis", 6379)
            return "redis://redis:6379/1"
        except socket.gaierror:
            return "redis://localhost:6379/1"

    def _load_config(self) -> None:
        """Load stream configuration."""
        try:
            config = load_config("global_intelligence")
            bus_cfg = config.get("event_bus", {})
            self._redis_url = bus_cfg.get("redis_url", self._redis_url)
            self._prefix = bus_cfg.get("consumer_prefix", self._prefix)
            for stream_name, stream_cfg in bus_cfg.get("streams", {}).items():
                self._maxlen[stream_name] = stream_cfg.get("maxlen", 10000)
        except Exception:
            logger.debug("No global_intelligence config found; using defaults")

    async def _ensure_redis(self):
        """Lazy-init Redis connection."""
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
            )
        return self._redis

    def _stream_key(self, stream: str) -> str:
        """Prefix stream name for namespace isolation."""
        return f"{self._prefix}:{stream}"

    async def publish(self, stream: str, data: dict[str, Any]) -> str | None:
        """Publish an event to a stream.

        Args:
            stream: Stream name (e.g. "sentinel:raw_intel")
            data: Event data dict (all values must be str-serializable)

        Returns:
            Message ID or None on failure.
        """
        try:
            r = await self._ensure_redis()
            # Flatten nested dicts to JSON strings
            flat = {}
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    flat[k] = json.dumps(v, ensure_ascii=False, default=str)
                elif isinstance(v, (int, float, bool)):
                    flat[k] = str(v)
                elif v is None:
                    flat[k] = ""
                else:
                    flat[k] = str(v)

            flat["_ts"] = str(time.time())

            key = self._stream_key(stream)
            maxlen = self._maxlen.get(stream, 10000)
            msg_id = await r.xadd(key, flat, maxlen=maxlen)
            logger.debug("Published to %s: %s", stream, msg_id)
            return msg_id
        except Exception as exc:
            logger.warning("Failed to publish to %s: %s", stream, exc)
            return None

    async def subscribe(
        self,
        stream: str,
        group: str,
        consumer: str,
        handler: Callable[[BusEvent], Awaitable[None]],
        *,
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Subscribe to a stream with consumer group.

        Runs forever, calling handler for each event.
        Creates the consumer group if it doesn't exist.
        """
        r = await self._ensure_redis()
        key = self._stream_key(stream)

        # Create consumer group (ignore if exists)
        try:
            await r.xgroup_create(key, group, id="0", mkstream=True)
        except Exception:
            pass  # Group already exists

        logger.info("Subscribed to %s as %s/%s", stream, group, consumer)

        while True:
            try:
                results = await r.xreadgroup(
                    group,
                    consumer,
                    {key: ">"},
                    count=batch_size,
                    block=block_ms,
                )

                if not results:
                    continue

                for _stream_name, messages in results:
                    for msg_id, fields in messages:
                        event = BusEvent(
                            stream=stream,
                            event_id=msg_id,
                            data=self._unflatten(fields),
                        )
                        try:
                            await handler(event)
                            await r.xack(key, group, msg_id)
                        except Exception as exc:
                            logger.error(
                                "Handler failed for %s/%s: %s",
                                stream,
                                msg_id,
                                exc,
                            )
            except asyncio.CancelledError:
                logger.info("Subscription to %s cancelled", stream)
                break
            except Exception as exc:
                logger.error("Subscribe loop error on %s: %s", stream, exc)
                await asyncio.sleep(1)

    async def read_history(
        self,
        stream: str,
        count: int = 50,
        since_minutes: int | None = None,
    ) -> list[BusEvent]:
        """Read recent events from a stream (no consumer group needed).

        Args:
            stream: Stream name.
            count: Max events to return.
            since_minutes: Only return events from last N minutes.

        Returns:
            List of BusEvent, newest last.
        """
        try:
            r = await self._ensure_redis()
            key = self._stream_key(stream)

            if since_minutes:
                # Calculate start ID from timestamp
                start_ts = int((time.time() - since_minutes * 60) * 1000)
                start_id = f"{start_ts}-0"
            else:
                start_id = "-"

            results = await r.xrange(key, min=start_id, max="+", count=count)

            events = []
            for msg_id, fields in results:
                events.append(
                    BusEvent(
                        stream=stream,
                        event_id=msg_id,
                        data=self._unflatten(fields),
                    )
                )
            return events
        except Exception as exc:
            logger.warning("Failed to read history from %s: %s", stream, exc)
            return []

    async def health_check(self) -> dict[str, Any]:
        """Check event bus health."""
        try:
            r = await self._ensure_redis()
            await r.ping()

            stream_info = {}
            for stream in self.STREAMS:
                key = self._stream_key(stream)
                try:
                    length = await r.xlen(key)
                    stream_info[stream] = {"length": length, "status": "ok"}
                except Exception:
                    stream_info[stream] = {"length": 0, "status": "empty"}

            return {
                "status": "healthy",
                "redis_url": self._redis_url.split("@")[-1],  # hide credentials
                "streams": stream_info,
            }
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    @staticmethod
    def _unflatten(fields: dict[str, str]) -> dict[str, Any]:
        """Try to parse JSON strings back to dicts/lists."""
        result = {}
        for k, v in fields.items():
            if k == "_ts":
                continue
            if isinstance(v, str) and v.startswith(("{", "[")):
                try:
                    result[k] = json.loads(v)
                except (json.JSONDecodeError, ValueError):
                    result[k] = v
            else:
                result[k] = v
        return result


# ---------------------------------------------------------------------------
# IntelligenceEventBus — real-time market event routing
# ---------------------------------------------------------------------------

# Default thresholds for event detection
_PRICE_SPIKE_PCT = 3.0  # |pct_change| > 3%
_VOLUME_SPIKE_RATIO = 2.0  # volume > 2x average
_LIMIT_UP_PCT = 9.8  # A-share 10% limit (use 9.8% to catch near-limit)
_EVENT_LOG_MAX = 500  # max in-memory events
_HANDLER_TIMEOUT_S = 30  # timeout for individual handler calls


class IntelligenceEventBus:
    """Routes market events to appropriate research agents for real-time analysis.

    Events are published by data sources (realtime quotes, news fetcher,
    capital flow monitor) and consumed by research agents that produce
    causal chains and trading signals.

    Supports both in-memory handler dispatch and Redis stream publishing
    for cross-process consumption.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._handlers: dict[EventType, list[Callable]] = {}
        self._redis = redis_client
        self._event_log: list[MarketEvent] = []

    def register_handler(self, event_type: EventType, handler: Callable) -> None:
        """Register an async handler for an event type."""
        self._handlers.setdefault(event_type, []).append(handler)
        logger.debug(
            "Registered handler %s for %s",
            getattr(handler, "__name__", repr(handler)),
            event_type.value,
        )

    async def publish(self, event: MarketEvent) -> None:
        """Publish an event to all registered handlers.

        Also publishes to Redis stream ``intelligence:events`` for
        cross-process consumption. Handlers are called concurrently
        with per-handler timeout protection.
        """
        # Store in in-memory log
        self._event_log.append(event)
        if len(self._event_log) > _EVENT_LOG_MAX:
            self._event_log = self._event_log[-_EVENT_LOG_MAX:]

        logger.debug(
            "Publishing %s event: symbol=%s severity=%.2f source=%s",
            event.event_type.value,
            event.symbol,
            event.severity,
            event.source,
        )

        if event.severity >= 0.5:
            logger.info(
                "Significant %s event: symbol=%s severity=%.2f data=%s",
                event.event_type.value,
                event.symbol,
                event.severity,
                {k: v for k, v in event.data.items() if k != "raw"},
            )

        # Dispatch to registered handlers concurrently
        handlers = self._handlers.get(event.event_type, [])
        if handlers:
            tasks = []
            for handler in handlers:
                tasks.append(self._call_handler(handler, event))
            await asyncio.gather(*tasks, return_exceptions=True)

        # Publish to Redis stream for cross-process consumers
        await self._publish_to_redis(event)

    async def _call_handler(self, handler: Callable, event: MarketEvent) -> None:
        """Call a single handler with timeout protection."""
        handler_name = getattr(handler, "__name__", repr(handler))
        try:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout=_HANDLER_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning(
                "Handler %s timed out after %ds for %s event",
                handler_name,
                _HANDLER_TIMEOUT_S,
                event.event_type.value,
            )
        except Exception as exc:
            logger.error(
                "Handler %s failed for %s event: %s",
                handler_name,
                event.event_type.value,
                exc,
            )

    async def _publish_to_redis(self, event: MarketEvent) -> None:
        """Publish event to Redis stream for cross-process consumption."""
        if self._redis is None:
            return
        try:
            stream_key = "intelligence:events"
            data = {
                "event_type": event.event_type.value,
                "symbol": event.symbol or "",
                "severity": str(event.severity),
                "source": event.source,
                "event_id": event.event_id,
                "timestamp": event.timestamp.isoformat(),
                "data": json.dumps(event.data, ensure_ascii=False, default=str),
            }
            # Support both sync and async Redis clients
            if hasattr(self._redis, "xadd") and asyncio.iscoroutinefunction(
                self._redis.xadd
            ):
                await self._redis.xadd(stream_key, data, maxlen=5000)
            elif hasattr(self._redis, "xadd"):
                self._redis.xadd(stream_key, data, maxlen=5000)
            else:
                logger.debug("Redis client does not support xadd")
        except Exception as exc:
            logger.debug("Redis publish failed (non-critical): %s", exc)

    # ------------------------------------------------------------------
    # Convenience publishers
    # ------------------------------------------------------------------

    async def on_price_spike(
        self, symbol: str, pct_change: float, volume_ratio: float
    ) -> None:
        """Publish price spike event if significant.

        Triggers if |pct_change| > 3% AND volume_ratio > 2.0.
        """
        if abs(pct_change) < _PRICE_SPIKE_PCT or volume_ratio < _VOLUME_SPIKE_RATIO:
            return

        severity = min(1.0, abs(pct_change) / 10.0 + (volume_ratio - 1.0) / 5.0)
        event = MarketEvent(
            event_type=EventType.PRICE_SPIKE,
            symbol=symbol,
            data={
                "pct_change": pct_change,
                "volume_ratio": volume_ratio,
                "direction": "up" if pct_change > 0 else "down",
            },
            severity=severity,
            timestamp=datetime.now(UTC),
            source="realtime_quotes",
        )
        await self.publish(event)

    async def on_news(self, news_item: dict) -> None:
        """Publish news event for causal chain analysis."""
        severity = float(news_item.get("score", 50)) / 100.0
        event = MarketEvent(
            event_type=EventType.NEWS,
            symbol=news_item.get("symbol"),
            data={
                "title": news_item.get("title", ""),
                "summary": news_item.get("summary", ""),
                "source": news_item.get("source", ""),
                "url": news_item.get("url", ""),
                "layer": news_item.get("layer", "L4"),
            },
            severity=severity,
            timestamp=datetime.now(UTC),
            source=news_item.get("source", "news_feed"),
        )
        await self.publish(event)

    async def on_policy(self, policy_item: dict) -> None:
        """Publish policy event for sector-wide analysis."""
        severity = float(policy_item.get("importance", 0.7))
        event = MarketEvent(
            event_type=EventType.POLICY,
            symbol=None,
            data={
                "title": policy_item.get("title", ""),
                "summary": policy_item.get("summary", ""),
                "issuer": policy_item.get("issuer", ""),
                "affected_sectors": policy_item.get("affected_sectors", []),
            },
            severity=severity,
            timestamp=datetime.now(UTC),
            source=policy_item.get("source", "policy_monitor"),
        )
        await self.publish(event)

    async def on_limit_up(
        self, symbol: str, name: str, sector: str, seal_ratio: float
    ) -> None:
        """Publish limit-up event for leader detection."""
        severity = min(1.0, 0.6 + seal_ratio * 0.4)
        event = MarketEvent(
            event_type=EventType.LIMIT_UP,
            symbol=symbol,
            data={
                "name": name,
                "sector": sector,
                "seal_ratio": seal_ratio,
            },
            severity=severity,
            timestamp=datetime.now(UTC),
            source="realtime_quotes",
        )
        await self.publish(event)

    async def check_quotes_for_events(
        self,
        quotes: dict[str, dict],
        prev_quotes: dict[str, dict] | None = None,
    ) -> list[MarketEvent]:
        """Compare current and previous quotes, publish events for significant changes.

        Detects:
        - Price spikes (|pct_change| > 3% with elevated volume)
        - Limit-up events (pct_change >= 9.8%)

        Args:
            quotes: Current quotes keyed by symbol.
            prev_quotes: Previous quotes for volume comparison.

        Returns:
            List of MarketEvent objects that were published.
        """
        published: list[MarketEvent] = []

        for symbol, quote in quotes.items():
            pct_change = quote.get("pct_change")
            if pct_change is None:
                continue

            # Volume ratio vs previous
            volume_ratio = 1.0
            if prev_quotes and symbol in prev_quotes:
                prev_vol = prev_quotes[symbol].get("volume", 0)
                cur_vol = quote.get("volume", 0)
                if prev_vol and prev_vol > 0 and cur_vol:
                    volume_ratio = cur_vol / prev_vol

            # Check for limit-up
            if pct_change >= _LIMIT_UP_PCT:
                seal_ratio = quote.get("seal_ratio", 0.5)
                await self.on_limit_up(
                    symbol=symbol,
                    name=quote.get("name", ""),
                    sector=quote.get("sector", ""),
                    seal_ratio=seal_ratio,
                )
                published.append(self._event_log[-1])

            # Check for price spike (not limit-up, to avoid double-fire)
            elif abs(pct_change) >= _PRICE_SPIKE_PCT:
                if volume_ratio >= _VOLUME_SPIKE_RATIO:
                    await self.on_price_spike(symbol, pct_change, volume_ratio)
                    if self._event_log:
                        published.append(self._event_log[-1])

        if published:
            logger.info(
                "Quote scan detected %d events across %d symbols",
                len(published),
                len(quotes),
            )
        return published

    def get_recent_events(
        self,
        event_type: EventType | None = None,
        minutes: int = 60,
    ) -> list[MarketEvent]:
        """Get recent events from in-memory log.

        Args:
            event_type: Filter by type, or None for all.
            minutes: Only return events from last N minutes.

        Returns:
            List of MarketEvent, newest last.
        """
        cutoff = datetime.now(UTC).timestamp() - minutes * 60
        result = []
        for evt in self._event_log:
            if evt.timestamp.timestamp() < cutoff:
                continue
            if event_type is not None and evt.event_type != event_type:
                continue
            result.append(evt)
        return result


# ---------------------------------------------------------------------------
# DI singletons
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_event_bus() -> EventBus:
    return EventBus()


@lru_cache(maxsize=1)
def get_intelligence_event_bus() -> IntelligenceEventBus:
    """Get the singleton IntelligenceEventBus.

    Tries to connect to Redis for cross-process event distribution.
    Falls back to in-memory-only mode if Redis is unavailable.
    """
    redis_client = None
    try:
        import redis as sync_redis

        import os
        import socket

        redis_url = os.environ.get("INTEL_REDIS_URL") or os.environ.get("REDIS_URL")
        if not redis_url:
            try:
                socket.getaddrinfo("redis", 6379)
                redis_url = "redis://redis:6379/1"
            except socket.gaierror:
                redis_url = "redis://localhost:6379/1"
        redis_client = sync_redis.from_url(
            redis_url, decode_responses=True, socket_connect_timeout=3
        )
        redis_client.ping()
        logger.info("IntelligenceEventBus connected to Redis")
    except Exception:
        logger.info(
            "IntelligenceEventBus running in-memory-only mode (Redis unavailable)"
        )
        redis_client = None

    return IntelligenceEventBus(redis_client=redis_client)

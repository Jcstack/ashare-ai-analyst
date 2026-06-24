"""News fermentation detection engine.

Fermentation = a topic gaining accelerating media attention across
multiple platforms. This engine tracks mention velocity over time
windows and detects inflection points.

Stages:
  emerging   → <6h old, <10 mentions, positive velocity
  fermenting → 6-48h old, velocity accelerating, cross-platform
  peak       → velocity decelerating but still high absolute
  fading     → velocity near zero or negative

Uses Redis sorted sets for time-series storage: ferment:{event_id}
with timestamps as scores and sources as members.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("intelligence.fermentation_engine")

__all__ = ["FermentationEvent", "FermentationEngine"]

_TTL_SECONDS = 172800  # 48 hours — events older than this get pruned


def _topic_hash(topic: str) -> str:
    """Normalize topic and compute hash for dedup."""
    normalized = re.sub(r"\s+", " ", topic.strip().lower())
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


@dataclass
class FermentationEvent:
    """A topic being tracked for fermentation."""

    event_id: str  # topic hash
    topic: str
    first_seen: datetime
    mention_counts: dict[str, int] = field(
        default_factory=lambda: {"1h": 0, "6h": 0, "24h": 0}
    )
    velocity: float = 0.0  # mentions/hour, current window
    acceleration: float = 0.0  # change in velocity (positive = fermenting)
    sources: list[str] = field(default_factory=list)  # which platforms
    stage: str = "emerging"  # emerging|fermenting|peak|fading
    related_symbols: list[str] = field(default_factory=list)
    related_sectors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "topic": self.topic,
            "first_seen": self.first_seen.isoformat(),
            "mentions": self.mention_counts,
            "velocity": self.velocity,
            "acceleration": self.acceleration,
            "sources": self.sources,
            "stage": self.stage,
            "symbols": self.related_symbols,
            "sectors": self.related_sectors,
        }

    def to_summary(self) -> str:
        """One-line summary for serialize_for_llm."""
        src_count = len(self.sources)
        accel_pct = self.acceleration * 100
        return (
            f'"{self.topic}" '
            f"({self.mention_counts.get('6h', 0)}次/6h, "
            f"加速{accel_pct:+.0f}%, "
            f"跨{src_count}平台)"
        )


class FermentationEngine:
    """Track and detect news fermentation.

    Uses Redis for time-series storage. Falls back to in-memory
    tracking if Redis is unavailable.

    Usage::

        engine = FermentationEngine()
        engine.track_mention("央行降准预期", "gdelt", datetime.now())
        engine.track_mention("央行降准预期", "xueqiu", datetime.now())
        fermenting = engine.detect_fermentation()
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._redis_url = redis_url
        self._redis = None
        self._init_redis()

        # In-memory fallback
        self._memory: dict[str, dict[str, Any]] = {}
        # topic_hash → {topic, first_seen, mentions: [(ts, source)]}

    def _init_redis(self) -> None:
        try:
            import redis

            self._redis = redis.from_url(self._redis_url, decode_responses=True)
            self._redis.ping()
        except Exception:
            self._redis = None
            logger.debug("Redis unavailable, using in-memory fermentation tracking")

    def _redis_key(self, event_id: str) -> str:
        return f"ferment:{event_id}"

    def _redis_meta_key(self, event_id: str) -> str:
        return f"ferment_meta:{event_id}"

    def track_mention(
        self,
        topic: str,
        source: str,
        timestamp: datetime | None = None,
        symbols: list[str] | None = None,
        sectors: list[str] | None = None,
    ) -> None:
        """Record a single mention of a topic.

        Args:
            topic: The topic being discussed (e.g., "央行降准预期").
            source: Platform name (e.g., "gdelt", "xueqiu", "guba", "rss").
            timestamp: When the mention occurred. Default: now.
            symbols: Related stock codes.
            sectors: Related sector names.
        """
        if timestamp is None:
            timestamp = datetime.now()

        event_id = _topic_hash(topic)
        ts = timestamp.timestamp()

        if self._redis is not None:
            try:
                key = self._redis_key(event_id)
                meta_key = self._redis_meta_key(event_id)

                # Add mention to sorted set (score=timestamp, member=source:ts)
                member = f"{source}:{ts:.3f}"
                self._redis.zadd(key, {member: ts})
                self._redis.expire(key, _TTL_SECONDS)

                # Store/update metadata
                if not self._redis.exists(meta_key):
                    self._redis.hset(
                        meta_key,
                        mapping={
                            "topic": topic,
                            "first_seen": ts,
                            "symbols": ",".join(symbols or []),
                            "sectors": ",".join(sectors or []),
                        },
                    )
                    self._redis.expire(meta_key, _TTL_SECONDS)
                else:
                    # Merge symbols/sectors
                    if symbols:
                        existing = self._redis.hget(meta_key, "symbols") or ""
                        merged = set(existing.split(",") + symbols) - {""}
                        self._redis.hset(meta_key, "symbols", ",".join(merged))
                    if sectors:
                        existing = self._redis.hget(meta_key, "sectors") or ""
                        merged = set(existing.split(",") + sectors) - {""}
                        self._redis.hset(meta_key, "sectors", ",".join(merged))

                return
            except Exception as exc:
                logger.debug("Redis track failed, using memory: %s", exc)

        # In-memory fallback
        if event_id not in self._memory:
            self._memory[event_id] = {
                "topic": topic,
                "first_seen": ts,
                "mentions": [],
                "symbols": set(symbols or []),
                "sectors": set(sectors or []),
            }
        entry = self._memory[event_id]
        entry["mentions"].append((ts, source))
        if symbols:
            entry["symbols"].update(symbols)
        if sectors:
            entry["sectors"].update(sectors)

    def detect_fermentation(self) -> list[FermentationEvent]:
        """Scan all tracked topics and return those that are fermenting.

        Returns:
            List of FermentationEvent sorted by acceleration descending.
        """
        events: list[FermentationEvent] = []

        if self._redis is not None:
            try:
                keys = self._redis.keys("ferment_meta:*")
                for meta_key in keys:
                    event_id = meta_key.replace("ferment_meta:", "")
                    event = self._analyze_redis_event(event_id)
                    if event:
                        events.append(event)
            except Exception as exc:
                logger.debug("Redis scan failed: %s", exc)

        # Also check in-memory events
        now = time.time()
        for event_id, data in list(self._memory.items()):
            # Prune stale events
            if now - data["first_seen"] > _TTL_SECONDS:
                del self._memory[event_id]
                continue
            event = self._analyze_memory_event(event_id, data)
            if event:
                events.append(event)

        events.sort(key=lambda e: e.acceleration, reverse=True)
        return events

    def _count_in_window(
        self, mentions: list[tuple[float, str]], window_hours: int
    ) -> tuple[int, set[str]]:
        """Count mentions and unique sources within a time window."""
        cutoff = time.time() - window_hours * 3600
        count = 0
        sources: set[str] = set()
        for ts, src in mentions:
            if ts >= cutoff:
                count += 1
                sources.add(src)
        return count, sources

    def _classify_stage(
        self,
        first_seen_ts: float,
        velocity: float,
        acceleration: float,
        total_mentions: int,
        source_count: int,
    ) -> str:
        """Classify the fermentation stage."""
        age_hours = (time.time() - first_seen_ts) / 3600

        if age_hours < 6 and total_mentions < 10:
            return "emerging" if velocity > 0 else "fading"

        if acceleration > 0.1 and source_count >= 2:
            return "fermenting"

        if velocity > 1.0 and acceleration <= 0:
            return "peak"

        if velocity < 0.5:
            return "fading"

        return "emerging"

    def _analyze_memory_event(
        self, event_id: str, data: dict[str, Any]
    ) -> FermentationEvent | None:
        """Analyze an in-memory event."""
        mentions = data["mentions"]
        if not mentions:
            return None

        count_1h, sources_1h = self._count_in_window(mentions, 1)
        count_6h, sources_6h = self._count_in_window(mentions, 6)
        count_24h, sources_24h = self._count_in_window(mentions, 24)

        velocity = float(count_1h)
        # Acceleration: compare 1h rate to 6h average rate
        rate_6h = count_6h / 6.0 if count_6h > 0 else 0.0
        acceleration = (velocity - rate_6h) / max(rate_6h, 0.1)

        stage = self._classify_stage(
            data["first_seen"],
            velocity,
            acceleration,
            count_24h,
            len(sources_24h),
        )

        return FermentationEvent(
            event_id=event_id,
            topic=data["topic"],
            first_seen=datetime.fromtimestamp(data["first_seen"]),
            mention_counts={"1h": count_1h, "6h": count_6h, "24h": count_24h},
            velocity=velocity,
            acceleration=round(acceleration, 3),
            sources=sorted(sources_24h),
            stage=stage,
            related_symbols=sorted(data.get("symbols", set())),
            related_sectors=sorted(data.get("sectors", set())),
        )

    def _analyze_redis_event(self, event_id: str) -> FermentationEvent | None:
        """Analyze a Redis-backed event."""
        if self._redis is None:
            return None

        try:
            key = self._redis_key(event_id)
            meta_key = self._redis_meta_key(event_id)

            meta = self._redis.hgetall(meta_key)
            if not meta:
                return None

            now = time.time()
            # Count mentions in windows
            count_1h = self._redis.zcount(key, now - 3600, "+inf")
            count_6h = self._redis.zcount(key, now - 6 * 3600, "+inf")
            count_24h = self._redis.zcount(key, now - 24 * 3600, "+inf")

            # Get unique sources from the 24h window
            members = self._redis.zrangebyscore(key, now - 24 * 3600, "+inf")
            sources = set()
            for m in members:
                src = str(m).split(":")[0]
                sources.add(src)

            velocity = float(count_1h)
            rate_6h = count_6h / 6.0 if count_6h > 0 else 0.0
            acceleration = (velocity - rate_6h) / max(rate_6h, 0.1)

            first_seen = float(meta.get("first_seen", now))
            stage = self._classify_stage(
                first_seen, velocity, acceleration, count_24h, len(sources)
            )

            symbols = [s for s in meta.get("symbols", "").split(",") if s]
            sectors = [s for s in meta.get("sectors", "").split(",") if s]

            return FermentationEvent(
                event_id=event_id,
                topic=meta.get("topic", ""),
                first_seen=datetime.fromtimestamp(first_seen),
                mention_counts={"1h": count_1h, "6h": count_6h, "24h": count_24h},
                velocity=velocity,
                acceleration=round(acceleration, 3),
                sources=sorted(sources),
                stage=stage,
                related_symbols=symbols,
                related_sectors=sectors,
            )
        except Exception as exc:
            logger.debug("Redis event analysis failed: %s", exc)
            return None

    def get_fermenting_summary(self) -> list[str]:
        """Get one-line summaries for all actively fermenting topics.

        Returns list of strings suitable for [消息发酵] block in serialize_for_llm.
        """
        events = self.detect_fermentation()
        lines = []
        for e in events:
            if e.stage in ("fermenting", "emerging"):
                stage_cn = "发酵中" if e.stage == "fermenting" else "新兴"
                lines.append(f"{stage_cn}: {e.to_summary()}")
        return lines[:5]

    def sync_to_state_tracker(self, tracker: Any) -> int:
        """Sync fermenting events to EventStateTracker (C5).

        When fermentation detects acceleration, register/update the event
        in the state tracker. This bridges attention velocity with event
        lifecycle management.

        Args:
            tracker: EventStateTracker instance with register_event() and
                update_mention_stats() methods.

        Returns:
            Number of events synced.
        """
        synced = 0
        events = self.detect_fermentation()

        for fe in events:
            if fe.stage not in ("fermenting", "peak"):
                continue

            try:
                # Register or find existing event in tracker
                tracker.register_event(
                    title=fe.topic,
                    event_type="fermentation",
                    sectors=fe.related_sectors,
                    symbols=fe.related_symbols,
                )

                # Update mention stats with current velocity
                existing = tracker._find_similar(fe.topic)
                if existing:
                    tracker.update_mention_stats(
                        existing.event_id,
                        new_mentions=fe.mention_counts.get("1h", 0),
                    )

                synced += 1
            except Exception as exc:
                logger.debug(
                    "Fermentation sync failed for '%s': %s", fe.topic[:30], exc
                )

        if synced:
            logger.info("Fermentation → StateTracker: synced %d events", synced)
        return synced

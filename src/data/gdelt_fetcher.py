"""GDELT (Global Database of Events, Language, and Tone) fetcher.

Fetches global event and tone data from the GDELT Project's free API.
No API key required. GDELT monitors worldwide news and computes tone
(sentiment) scores — critical for A-share investment because global events
transmit to Chinese markets via macro channels (e.g., Fed rate cut → RMB
appreciation → northbound capital inflow → A-share sectors).

Rate limit: ~1 req/sec (self-imposed politeness).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp

from src.utils.logger import get_logger

logger = get_logger("data.gdelt_fetcher")

__all__ = [
    "GdeltEvent",
    "GdeltToneSummary",
    "GdeltFetcher",
    "GdeltEventVelocity",
]


# ---------------------------------------------------------------------------
# CAMEO event code mapping (subset relevant to market impact)
# ---------------------------------------------------------------------------
_CAMEO_CONFLICT_CODES: dict[str, str] = {
    "190": "Use of conventional military force",
    "191": "Impose blockade",
    "192": "Occupy territory",
    "193": "Fight with small arms",
    "194": "Fight with artillery",
    "195": "Employ aerial weapons",
    "196": "Violate ceasefire",
    "200": "Use unconventional mass violence",
    "170": "Coerce",
    "171": "Seize or damage property",
    "172": "Impose embargo",
    "173": "Attack",
    "174": "Abduct, hijack, or take hostage",
    "175": "Use unconventional violence",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class GdeltEvent:
    """A GDELT news event with tone analysis."""

    title: str
    url: str
    source_domain: str
    source_country: str
    language: str
    tone: float  # negative = bearish, positive = bullish, range roughly -10 to +10
    seen_date: str  # YYYYMMDDTHHMMSS format
    fetched_at: datetime = field(default_factory=datetime.now)


@dataclass
class GdeltEventVelocity:
    """Article count velocity across time windows for fermentation detection."""

    query: str
    counts: dict[str, int]  # {"1h": 15, "6h": 45, "24h": 60}
    velocity_per_hour: float  # current 1h rate
    is_accelerating: bool  # 1h > 0.3 * 24h indicates acceleration
    fetched_at: datetime = field(default_factory=datetime.now)


@dataclass
class GdeltToneSummary:
    """Aggregated tone for a topic over a time period."""

    query: str
    avg_tone: float  # average tone across articles
    article_count: int
    tone_trend: str  # "improving" / "deteriorating" / "stable"
    most_negative_title: str  # headline with worst tone
    most_positive_title: str  # headline with best tone
    fetched_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


class GdeltFetcher:
    """Fetch global event and tone data from GDELT.

    GDELT is free and requires NO API key. Rate limit: ~1 req/sec.
    """

    BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

    # Pre-defined queries relevant to A-share investment
    CHINA_QUERIES = [
        "china economy",
        "china trade",
        "pboc monetary policy",
        "fed rate",
        "us china tariff",
        "commodity oil gold",
    ]

    A_SHARE_TRANSMISSION_QUERIES: dict[str, str] = {
        "fed_policy": "federal reserve rate OR fed funds",
        "china_economy": "china GDP OR china PMI OR china trade",
        "geopolitical": "taiwan strait OR south china sea OR us china OR russia ukraine OR ceasefire OR middle east conflict OR nato",
        "commodity": "oil price OR gold price OR copper OR iron ore OR lithium",
        "global_risk": "recession OR financial crisis OR bank failure OR sovereign debt OR geopolitical risk",
    }

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._last_request_ts: float = 0.0
        # In-memory TTL cache: key → (monotonic_ts, value)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl: float = 600.0  # 10 minutes

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _get_cache(self, key: str) -> Any | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.monotonic() - ts < self._cache_ttl:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.monotonic(), val)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _polite_wait(self) -> None:
        """Ensure at least 1 second between consecutive requests."""
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < 1.0:
            await asyncio.sleep(1.0 - elapsed)
        self._last_request_ts = time.monotonic()

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    async def _get_json(self, params: dict[str, str]) -> dict | list | None:
        """GET request to GDELT DOC API, returning parsed JSON."""
        await self._polite_wait()
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(self.BASE_URL, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "GDELT API returned HTTP %d for query=%s",
                            resp.status,
                            params.get("query", ""),
                        )
                        return None
                    return await resp.json(content_type=None)
        except asyncio.TimeoutError:
            logger.warning(
                "GDELT request timed out for query=%s", params.get("query", "")
            )
            return None
        except Exception as exc:
            logger.warning("GDELT request failed: %s", exc)
            return None

    async def _get_text(self, params: dict[str, str]) -> str | None:
        """GET request to GDELT DOC API, returning raw text (for CSV modes)."""
        await self._polite_wait()
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(self.BASE_URL, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "GDELT API returned HTTP %d for query=%s",
                            resp.status,
                            params.get("query", ""),
                        )
                        return None
                    return await resp.text()
        except asyncio.TimeoutError:
            logger.warning(
                "GDELT timeline request timed out for query=%s", params.get("query", "")
            )
            return None
        except Exception as exc:
            logger.warning("GDELT timeline request failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def fetch_events(
        self, query: str, timespan: str = "24h", max_records: int = 50
    ) -> list[GdeltEvent]:
        """Fetch recent events matching a query.

        Args:
            query: Search keywords (supports OR, AND operators).
            timespan: Time window (e.g. "24h", "7d", "30d").
            max_records: Maximum articles to return (max 250).

        Returns:
            List of GdeltEvent sorted by date descending.
        """
        cache_key = f"events:{query}:{timespan}:{max_records}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        params = {
            "query": query,
            "mode": "artlist",
            "maxrecords": str(min(max_records, 250)),
            "format": "json",
            "timespan": timespan,
            "sort": "datedesc",
        }

        data = await self._get_json(params)
        if not data or not isinstance(data, dict):
            return []

        articles = data.get("articles", [])
        if not isinstance(articles, list):
            return []

        now = datetime.now()
        events: list[GdeltEvent] = []
        for art in articles:
            if not isinstance(art, dict):
                continue
            try:
                tone = float(art.get("tone", 0))
            except (TypeError, ValueError):
                tone = 0.0
            events.append(
                GdeltEvent(
                    title=str(art.get("title", "")),
                    url=str(art.get("url", "")),
                    source_domain=str(art.get("domain", "")),
                    source_country=str(art.get("sourcecountry", "")),
                    language=str(art.get("language", "")),
                    tone=tone,
                    seen_date=str(art.get("seendate", "")),
                    fetched_at=now,
                )
            )

        logger.info("GDELT events: %d articles for query=%r", len(events), query)
        self._set_cache(cache_key, events)
        return events

    async def fetch_tone_summary(
        self, query: str, timespan: str = "7d"
    ) -> GdeltToneSummary | None:
        """Fetch aggregated tone for a topic.

        Combines article list (for min/max headlines) and timeline tone
        (for trend detection) into a single summary.

        Args:
            query: Search keywords.
            timespan: Time window for aggregation.

        Returns:
            GdeltToneSummary or None on failure.
        """
        cache_key = f"tone_summary:{query}:{timespan}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        # Fetch articles for tone stats and headline extraction
        events = await self.fetch_events(query, timespan=timespan, max_records=100)
        if not events:
            return None

        tones = [e.tone for e in events]
        avg_tone = sum(tones) / len(tones)

        # Find most negative/positive headlines
        sorted_by_tone = sorted(events, key=lambda e: e.tone)
        most_negative_title = sorted_by_tone[0].title if sorted_by_tone else ""
        most_positive_title = sorted_by_tone[-1].title if sorted_by_tone else ""

        # Determine trend: compare first half vs second half (articles are date-descending)
        # Recent articles are at the front, older at the back
        mid = len(tones) // 2
        if mid > 0:
            recent_avg = sum(tones[:mid]) / mid
            older_avg = sum(tones[mid:]) / (len(tones) - mid)
            delta = recent_avg - older_avg
            if delta > 0.5:
                tone_trend = "improving"
            elif delta < -0.5:
                tone_trend = "deteriorating"
            else:
                tone_trend = "stable"
        else:
            tone_trend = "stable"

        summary = GdeltToneSummary(
            query=query,
            avg_tone=round(avg_tone, 2),
            article_count=len(events),
            tone_trend=tone_trend,
            most_negative_title=most_negative_title,
            most_positive_title=most_positive_title,
        )

        logger.info(
            "GDELT tone summary: query=%r avg_tone=%.2f articles=%d trend=%s",
            query,
            avg_tone,
            len(events),
            tone_trend,
        )
        self._set_cache(cache_key, summary)
        return summary

    async def fetch_china_relevant(self) -> dict[str, GdeltToneSummary]:
        """Fetch tone summaries for all A-share transmission channels.

        Returns dict mapping channel name to tone summary.
        E.g. {"fed_policy": GdeltToneSummary(avg_tone=-2.3, ...), ...}

        Channels are fetched sequentially to respect rate limits.
        """
        cache_key = "china_relevant"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        results: dict[str, GdeltToneSummary] = {}
        for channel, query in self.A_SHARE_TRANSMISSION_QUERIES.items():
            summary = await self.fetch_tone_summary(query, timespan="7d")
            if summary is not None:
                results[channel] = summary

        logger.info(
            "GDELT china-relevant: %d/%d channels fetched",
            len(results),
            len(self.A_SHARE_TRANSMISSION_QUERIES),
        )
        self._set_cache(cache_key, results)
        return results

    async def get_global_tone(self) -> float:
        """Get overall global news tone (simple aggregate).

        Returns average tone across all monitored channels.
        Negative = bearish global sentiment, Positive = bullish.
        Returns 0.0 if no data available.
        """
        cache_key = "global_tone"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        summaries = await self.fetch_china_relevant()
        if not summaries:
            return 0.0

        tones = [s.avg_tone for s in summaries.values()]
        global_tone = round(sum(tones) / len(tones), 2)

        logger.info(
            "GDELT global tone: %.2f (from %d channels)", global_tone, len(tones)
        )
        self._set_cache(cache_key, global_tone)
        return global_tone

    async def fetch_event_velocity(
        self,
        query: str,
        windows: list[str] | None = None,
    ) -> GdeltEventVelocity | None:
        """Track article count velocity across time windows.

        Detects news fermentation: if 1h count > 0.3 * 24h count,
        the topic is accelerating in media attention.

        Args:
            query: Search keywords.
            windows: Time windows to check. Default ["1h", "6h", "24h"].

        Returns:
            GdeltEventVelocity or None on failure.
        """
        if windows is None:
            windows = ["1h", "6h", "24h"]

        cache_key = f"velocity:{query}:{','.join(windows)}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        counts: dict[str, int] = {}
        for window in windows:
            events = await self.fetch_events(query, timespan=window, max_records=250)
            counts[window] = len(events)

        count_1h = counts.get("1h", 0)
        count_24h = counts.get("24h", 1)  # avoid division by zero
        is_accelerating = count_1h > 0.3 * count_24h and count_24h >= 5

        result = GdeltEventVelocity(
            query=query,
            counts=counts,
            velocity_per_hour=float(count_1h),
            is_accelerating=is_accelerating,
        )

        self._set_cache(cache_key, result)
        logger.info(
            "GDELT velocity: query=%r counts=%s accelerating=%s",
            query,
            counts,
            is_accelerating,
        )
        return result

    async def fetch_geopolitical_events(
        self, timespan: str = "24h"
    ) -> list[GdeltEvent]:
        """Fetch geopolitical conflict events specifically.

        Uses the geopolitical query from A_SHARE_TRANSMISSION_QUERIES
        and returns events sorted by tone (most negative first).
        """
        query = self.A_SHARE_TRANSMISSION_QUERIES.get(
            "geopolitical",
            "taiwan strait OR south china sea OR middle east conflict",
        )
        events = await self.fetch_events(query, timespan=timespan, max_records=100)
        return sorted(events, key=lambda e: e.tone)

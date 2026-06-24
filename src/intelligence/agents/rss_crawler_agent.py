"""RSS Crawler Agent — Sentinel Team member for multi-source news aggregation.

Extends the existing RssSource pattern to 100+ feeds with parallel fetching,
per-feed circuit breakers, and event bus publishing.

Per PRD v39.0 FR-GIT001.
"""

from __future__ import annotations

import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from functools import lru_cache

from src.data.circuit_breaker import CircuitBreaker
from src.intelligence_hub.models import InfoItem
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.rss_crawler")

_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class CrawlResult:
    """Result of a single RSS crawl cycle."""

    total_fetched: int = 0
    total_deduped: int = 0
    sources_healthy: int = 0
    sources_failed: int = 0
    sources_total: int = 0
    errors: list[str] = field(default_factory=list)


class RssCrawlerAgent:
    """Sentinel team: parallel RSS feed crawler with circuit breakers.

    Fetches from 100+ configured RSS feeds in parallel, deduplicates
    results, and publishes to the event bus + existing InfoStore.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        info_store: Any | None = None,
    ) -> None:
        self._config = config or self._load_config()
        self._info_store = info_store
        self._feeds = self._config.get("sentinel", {}).get("rss_feeds", {})
        self._max_workers = self._config.get("sentinel", {}).get("max_workers", 16)
        self._breakers: dict[str, CircuitBreaker] = {}
        self._seen_hashes: set[str] = set()  # SimHash dedup within cycle
        self._seen_hashes_ttl: float = 0.0
        logger.info("RssCrawlerAgent initialized with %d feeds", len(self._feeds))

    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            return load_config("global_intelligence")
        except FileNotFoundError:
            logger.warning("global_intelligence config not found; using defaults")
            return {}

    def _get_breaker(self, feed_id: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a feed."""
        if feed_id not in self._breakers:
            self._breakers[feed_id] = CircuitBreaker(
                f"rss_{feed_id}",
                failure_threshold=3,
                recovery_timeout=300.0,
            )
        return self._breakers[feed_id]

    def crawl(self) -> CrawlResult:
        """Execute a full crawl cycle across all enabled feeds.

        Returns:
            CrawlResult with counts and errors.
        """
        result = CrawlResult()

        # Reset dedup cache every 30 minutes
        now = time.monotonic()
        if now - self._seen_hashes_ttl > 1800:
            self._seen_hashes.clear()
            self._seen_hashes_ttl = now

        enabled_feeds = {
            fid: cfg for fid, cfg in self._feeds.items() if cfg.get("enabled", True)
        }
        result.sources_total = len(enabled_feeds)

        all_items: list[dict[str, Any]] = []

        def _fetch_one(
            feed_id: str,
            feed_cfg: dict,
        ) -> tuple[str, list[dict], str | None]:
            breaker = self._get_breaker(feed_id)
            if breaker.state == "open":
                return feed_id, [], f"circuit breaker open for {feed_id}"

            try:
                items = self._fetch_feed(feed_id, feed_cfg)
                breaker._on_success()
                return feed_id, items, None
            except Exception as exc:
                breaker._on_failure()
                return feed_id, [], str(exc)

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(_fetch_one, fid, cfg): fid
                for fid, cfg in enabled_feeds.items()
            }
            for future in as_completed(futures):
                feed_id, items, error = future.result()
                if error:
                    result.sources_failed += 1
                    result.errors.append(f"{feed_id}: {error}")
                    logger.warning("Feed %s failed: %s", feed_id, error)
                else:
                    result.sources_healthy += 1
                    all_items.extend(items)

        result.total_fetched = len(all_items)

        # Dedup by URL + title hash
        deduped = self._dedup(all_items)
        result.total_deduped = len(deduped)

        # Store in existing InfoStore for backward compatibility
        if self._info_store and deduped:
            try:
                info_items = [self._to_info_item(item) for item in deduped]
                self._info_store.store_batch(info_items)
            except Exception as exc:
                logger.warning("InfoStore batch store failed: %s", exc)

        logger.info(
            "Crawl complete: %d fetched, %d after dedup, %d/%d sources healthy",
            result.total_fetched,
            result.total_deduped,
            result.sources_healthy,
            result.sources_total,
        )

        return result

    def get_raw_items(self) -> list[dict[str, Any]]:
        """Crawl and return raw items (for event bus publishing by caller)."""
        enabled_feeds = {
            fid: cfg for fid, cfg in self._feeds.items() if cfg.get("enabled", True)
        }

        all_items: list[dict[str, Any]] = []

        def _fetch_one(feed_id: str, feed_cfg: dict) -> list[dict]:
            breaker = self._get_breaker(feed_id)
            if breaker.state == "open":
                return []
            try:
                items = self._fetch_feed(feed_id, feed_cfg)
                breaker._on_success()
                return items
            except Exception as exc:
                breaker._on_failure()
                logger.warning("Feed %s failed: %s", feed_id, exc)
                return []

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = [
                pool.submit(_fetch_one, fid, cfg) for fid, cfg in enabled_feeds.items()
            ]
            for future in as_completed(futures):
                all_items.extend(future.result())

        return self._dedup(all_items)

    def _fetch_feed(
        self,
        feed_id: str,
        feed_cfg: dict,
        max_items: int = 30,
    ) -> list[dict[str, Any]]:
        """Fetch items from a single RSS feed."""
        import feedparser

        url = feed_cfg.get("url", "")
        if not url:
            return []

        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            raise ValueError(f"Feed parse error: {feed.bozo_exception}")

        items: list[dict[str, Any]] = []
        layer = feed_cfg.get("layer", "L4")
        category = feed_cfg.get("category", "general")
        language = feed_cfg.get("language", "en")

        for entry in feed.entries[:max_items]:
            published = ""
            if hasattr(entry, "published"):
                published = entry.published
            elif hasattr(entry, "updated"):
                published = entry.updated

            summary = ""
            if hasattr(entry, "summary"):
                raw = _HTML_TAG_RE.sub("", entry.summary)
                summary = raw.strip()[:500]

            title = getattr(entry, "title", "")
            if not title:
                continue

            items.append(
                {
                    "source_id": feed_id,
                    "title": title,
                    "summary": summary,
                    "url": getattr(entry, "link", ""),
                    "layer": layer,
                    "category": category,
                    "language": language,
                    "published_at": published,
                }
            )

        return items

    def _dedup(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deduplicate items by URL + title SimHash."""
        result: list[dict[str, Any]] = []
        for item in items:
            h = self._item_hash(item)
            if h not in self._seen_hashes:
                self._seen_hashes.add(h)
                result.append(item)
        return result

    @staticmethod
    def _item_hash(item: dict[str, Any]) -> str:
        """Generate dedup hash from URL + normalized title."""
        url = item.get("url", "")
        title = item.get("title", "").lower().strip()
        raw = f"{url}|{title}"
        return hashlib.md5(raw.encode()).hexdigest()

    @staticmethod
    def _to_info_item(item: dict[str, Any]) -> InfoItem:
        """Convert raw crawl item to InfoItem for backward compatibility."""
        return InfoItem(
            source_id=item.get("source_id", ""),
            source_name=f"GIT:{item.get('source_id', '')}",
            title=item.get("title", ""),
            summary=item.get("summary", ""),
            url=item.get("url", ""),
            category=item.get("category", "general"),
            published_at=item.get("published_at", ""),
            tags=[item.get("layer", "L4"), item.get("language", "en")],
        )

    def health(self) -> dict[str, Any]:
        """Return health status of all feeds."""
        total = len(self._feeds)
        enabled = sum(1 for c in self._feeds.values() if c.get("enabled", True))
        open_breakers = sum(1 for b in self._breakers.values() if b.state == "open")
        return {
            "total_feeds": total,
            "enabled_feeds": enabled,
            "circuit_breakers_open": open_breakers,
            "dedup_cache_size": len(self._seen_hashes),
        }


# ---------------------------------------------------------------------------
# DI singleton
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_rss_crawler_agent() -> RssCrawlerAgent:
    from src.web.dependencies import get_info_store

    return RssCrawlerAgent(
        config=load_config("global_intelligence"),
        info_store=get_info_store(),
    )

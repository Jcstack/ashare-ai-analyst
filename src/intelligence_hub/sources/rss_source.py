"""RSS/Atom feed source adapter — uses feedparser → InfoItem.

Part of v21.0 Intelligence Hub.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.source_base import InformationSource

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


class RssSource(InformationSource):
    """Fetches items from an RSS or Atom feed URL via feedparser."""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self._feed_url = config.get("feed_url", "")
        self._max_items = config.get("max_items", 30)

    def fetch(self) -> list[InfoItem]:
        """Parse an RSS/Atom feed and convert entries to InfoItem."""
        if not self._feed_url:
            logger.warning("RssSource %s has no feed_url configured", self.source_id)
            return []

        try:
            import feedparser
        except ImportError:
            logger.warning(
                "feedparser not installed, skipping RssSource %s", self.source_id
            )
            return []

        try:
            feed = feedparser.parse(self._feed_url)
        except Exception as exc:
            logger.warning("RssSource %s parse failed: %s", self.source_id, exc)
            return []

        items: list[InfoItem] = []
        for entry in feed.entries[: self._max_items]:
            published = ""
            if hasattr(entry, "published"):
                published = entry.published
            elif hasattr(entry, "updated"):
                published = entry.updated

            summary = ""
            if hasattr(entry, "summary"):
                raw = _HTML_TAG_RE.sub("", entry.summary)
                summary = raw.strip()[:200]

            items.append(
                InfoItem(
                    source_id=self.source_id,
                    source_name=self.display_name,
                    title=getattr(entry, "title", ""),
                    summary=summary,
                    url=getattr(entry, "link", ""),
                    category=self.default_category,
                    published_at=published,
                )
            )

        logger.info("RssSource %s fetched %d items", self.source_id, len(items))
        return items

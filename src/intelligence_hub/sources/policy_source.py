"""Policy news source adapter — wraps PolicyNewsFetcher → InfoItem.

Part of v21.0 Intelligence Hub.
"""

from __future__ import annotations

import logging
from typing import Any

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.source_base import InformationSource

logger = logging.getLogger(__name__)


class PolicySource(InformationSource):
    """Fetches policy news from a specific regulatory source via PolicyNewsFetcher."""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self._source_key = config.get("source_key", "")
        self._fetcher = None

    def _get_fetcher(self):
        if self._fetcher is None:
            from src.data.policy_news import PolicyNewsFetcher

            self._fetcher = PolicyNewsFetcher()
        return self._fetcher

    def fetch(self) -> list[InfoItem]:
        """Fetch policy items from a single regulatory source and convert to InfoItem."""
        if not self._source_key:
            logger.warning(
                "PolicySource %s has no source_key configured", self.source_id
            )
            return []

        try:
            fetcher = self._get_fetcher()
            raw_items = fetcher.fetch_source(self._source_key)
        except Exception as exc:
            logger.warning("PolicySource %s fetch failed: %s", self.source_id, exc)
            return []

        items: list[InfoItem] = []
        for raw in raw_items:
            items.append(
                InfoItem(
                    source_id=self.source_id,
                    source_name=self.display_name,
                    title=raw.title,
                    url=raw.url,
                    category=self.default_category,
                    published_at=raw.date,
                    extra={"impact_category": raw.impact_category},
                )
            )
        logger.info("PolicySource %s fetched %d items", self.source_id, len(items))
        return items

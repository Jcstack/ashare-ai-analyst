"""Reddit public JSON API source adapter.

Fetches hot posts from configured subreddits via the public
``/r/{sub}/hot.json`` endpoint (no auth required).

Part of v21.0 Intelligence Hub — Phase 1.5.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import requests

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.source_base import InformationSource

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = "IntelligenceHub/1.0 (market-research-tool)"
_DEFAULT_DELAY = 1.5


class RedditSource(InformationSource):
    """Fetches hot posts from one or more subreddits via Reddit's public JSON API."""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self._subreddits: list[str] = config.get("subreddits", [])
        self._max_items_per_sub: int = config.get("max_items_per_sub", 10)
        self._delay: float = config.get("request_delay_seconds", _DEFAULT_DELAY)
        self._user_agent: str = config.get("user_agent", _DEFAULT_USER_AGENT)

    def fetch(self) -> list[InfoItem]:
        if not self._subreddits:
            logger.warning(
                "RedditSource %s has no subreddits configured", self.source_id
            )
            return []

        items: list[InfoItem] = []
        for idx, sub in enumerate(self._subreddits):
            if idx > 0:
                time.sleep(self._delay)
            try:
                sub_items = self._fetch_subreddit(sub)
                items.extend(sub_items)
            except Exception as exc:
                logger.warning(
                    "RedditSource %s failed for r/%s: %s", self.source_id, sub, exc
                )

        logger.info("RedditSource %s fetched %d items", self.source_id, len(items))
        return items

    def _fetch_subreddit(self, subreddit: str) -> list[InfoItem]:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={self._max_items_per_sub}"
        headers = {"User-Agent": self._user_agent}

        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        items: list[InfoItem] = []
        children = data.get("data", {}).get("children", [])
        for child in children:
            post = child.get("data", {})
            if post.get("stickied", False):
                continue

            title = post.get("title", "")
            if not title:
                continue

            permalink = post.get("permalink", "")
            post_url = f"https://www.reddit.com{permalink}" if permalink else ""
            selftext = (post.get("selftext") or "")[:200]
            created_utc = post.get("created_utc", 0)
            published = (
                datetime.fromtimestamp(created_utc, tz=UTC).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                if created_utc
                else ""
            )

            items.append(
                InfoItem(
                    source_id=self.source_id,
                    source_name=self.display_name,
                    title=title,
                    summary=selftext,
                    url=post_url,
                    category=self.default_category,
                    published_at=published,
                    extra={
                        "score": post.get("score", 0),
                        "num_comments": post.get("num_comments", 0),
                        "subreddit": subreddit,
                    },
                )
            )

        return items

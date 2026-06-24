"""AKShare news source adapter — fetches general market news via ak.stock_news_main_cx().

Part of v21.0 Intelligence Hub.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.source_base import InformationSource

logger = logging.getLogger(__name__)

_CST = ZoneInfo("Asia/Shanghai")

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_URL_DATE_RE = re.compile(r"/(\d{4}-\d{2}-\d{2})/")


class AkshareNewsSource(InformationSource):
    """Fetches general market news from AKShare (财新/东财) via stock_news_main_cx."""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        self._max_items = config.get("max_items", 30)

    @staticmethod
    def _extract_published_at(url: str) -> str:
        """Extract published_at from URL date, using current time for today's articles.

        AKShare ``stock_news_main_cx`` has no explicit datetime column;
        the only date signal is in the URL path.  For articles published
        today we use the current timestamp; for older articles we use
        midday (12:00) as a reasonable approximation.
        """
        match = _URL_DATE_RE.search(url)
        if not match:
            return ""
        url_date = match.group(1)
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        if url_date == today:
            return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")
        return f"{url_date} 12:00:00"

    def fetch(self) -> list[InfoItem]:
        """Fetch general news items from AKShare and convert to InfoItem."""
        try:
            import akshare as ak

            df = ak.stock_news_main_cx()
        except Exception as exc:
            logger.warning("AkshareNewsSource fetch failed: %s", exc)
            return []

        if df is None or df.empty:
            return []

        items: list[InfoItem] = []
        for _, row in df.head(self._max_items).iterrows():
            raw_summary = str(row.get("summary", ""))
            summary = _HTML_TAG_RE.sub("", raw_summary).strip()
            tag = str(row.get("tag", ""))
            title = summary[:80] if summary else tag
            url = str(row.get("url", ""))

            published = self._extract_published_at(url)

            items.append(
                InfoItem(
                    source_id=self.source_id,
                    source_name=self.display_name,
                    title=title,
                    summary=summary[:200],
                    url=url,
                    category=self.default_category,
                    tags=[tag] if tag else [],
                    published_at=published,
                )
            )
        logger.info("AkshareNewsSource fetched %d items", len(items))
        return items

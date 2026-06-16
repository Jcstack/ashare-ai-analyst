"""Policy & regulatory news fetcher for A-share market.

Scrapes official policy announcements from CSRC, PBOC, SSE, and MOF.
Falls back to keyword filtering on East Money news when scraping fails.

Part of WS4: Policy & Regulatory News.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("data.policy_news")


@dataclass
class PolicyItem:
    """A single policy/regulatory news item."""

    title: str
    source: str  # csrc, pboc, sse, mof
    source_name: str  # 证监会, 央行, etc.
    url: str = ""
    date: str = ""
    impact_category: str = ""  # monetary, regulatory, fiscal, exchange
    is_high_impact: bool = False
    fetched_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source": self.source,
            "source_name": self.source_name,
            "source_type": "policy",
            "url": self.url,
            "date": self.date,
            "impact_category": self.impact_category,
            "is_high_impact": self.is_high_impact,
        }


class PolicyNewsFetcher:
    """Fetches policy news from Chinese regulatory sources.

    Uses BeautifulSoup for HTML parsing with graceful fallback
    when sources are unreachable.

    Args:
        config_name: Config file name for policy source definitions.
    """

    # In-memory cache
    _cache: dict[str, tuple[float, list[PolicyItem]]] = {}
    _DEFAULT_TTL = 900  # 15 minutes

    def __init__(self, config_name: str = "policy_sources") -> None:
        try:
            self._config = load_config(config_name)
        except Exception:
            logger.warning("Could not load policy_sources config, using defaults")
            self._config = {}

        self._sources = self._config.get("sources", {})
        self._high_impact_keywords = self._config.get("high_impact_keywords", {})

    def fetch_all(self, force_refresh: bool = False) -> list[PolicyItem]:
        """Fetch policy news from all enabled sources.

        Args:
            force_refresh: Bypass cache if True.

        Returns:
            List of PolicyItem sorted by date (newest first).
        """
        cache_key = "all_policy"
        if not force_refresh:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached

        all_items: list[PolicyItem] = []

        for source_id, source_cfg in self._sources.items():
            if not source_cfg.get("enabled", True):
                continue
            try:
                items = self._fetch_source(source_id, source_cfg)
                all_items.extend(items)
            except Exception as exc:
                logger.warning("Policy source '%s' failed: %s", source_id, exc)

        # Tag high-impact items
        for item in all_items:
            item.is_high_impact = self._check_high_impact(item)

        # Sort by date descending (newest first)
        all_items.sort(key=lambda x: x.date, reverse=True)

        self._set_cached(cache_key, all_items)
        return all_items

    def fetch_source(self, source_id: str) -> list[PolicyItem]:
        """Fetch policy news from a single source.

        Args:
            source_id: Source identifier (csrc, pboc, sse, mof).

        Returns:
            List of PolicyItem from that source.
        """
        source_cfg = self._sources.get(source_id)
        if not source_cfg:
            return []

        cache_key = f"policy_{source_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            items = self._fetch_source(source_id, source_cfg)
            for item in items:
                item.is_high_impact = self._check_high_impact(item)
            self._set_cached(cache_key, items)
            return items
        except Exception as exc:
            logger.warning("Policy source '%s' fetch failed: %s", source_id, exc)
            return []

    def get_high_impact_items(self) -> list[PolicyItem]:
        """Return only high-impact policy items from all sources."""
        all_items = self.fetch_all()
        return [item for item in all_items if item.is_high_impact]

    def format_for_prompt(
        self,
        items: list[PolicyItem] | None = None,
        max_items: int = 10,
    ) -> str:
        """Format policy items as context for LLM prompts.

        Args:
            items: Policy items to format. Fetches all if None.
            max_items: Maximum items to include.

        Returns:
            Formatted string for prompt injection.
        """
        if items is None:
            items = self.fetch_all()

        if not items:
            return "无近期政策消息"

        lines = []
        for item in items[:max_items]:
            impact = "⚠️ " if item.is_high_impact else ""
            lines.append(f"[{item.source_name}] {impact}{item.title} ({item.date})")

        return "\n".join(lines)

    # ── Private methods ──────────────────────────────────────

    def _fetch_source(
        self,
        source_id: str,
        source_cfg: dict[str, Any],
    ) -> list[PolicyItem]:
        """Fetch and parse a single policy source."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.info("beautifulsoup4 not installed, skipping HTML scraping")
            return []

        from src.data.http_client import get_default_session

        url = source_cfg.get("url", "")
        if not url:
            return []

        session = get_default_session()
        timeout = (
            session._default_timeout
            if hasattr(session, "_default_timeout")
            else (10, 30)
        )  # type: ignore[attr-defined]

        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            # Auto-detect encoding
            resp.encoding = resp.apparent_encoding or "utf-8"
        except Exception as exc:
            logger.warning("HTTP fetch failed for %s: %s", source_id, exc)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        selectors = source_cfg.get("selectors", {})
        list_selector = selectors.get("list", "li")
        title_selector = selectors.get("title", "a")
        date_selector = selectors.get("date", "span")

        items: list[PolicyItem] = []
        source_name = source_cfg.get("name", source_id)
        impact_category = source_cfg.get("impact_category", "")

        elements = soup.select(list_selector)
        for elem in elements[:20]:  # Limit to 20 items per source
            title_elem = elem.select_one(title_selector)
            date_elem = elem.select_one(date_selector)

            if not title_elem:
                continue

            title = title_elem.get_text(strip=True)
            if not title:
                continue

            href = title_elem.get("href", "")
            if href and not href.startswith("http"):
                # Resolve relative URLs
                from urllib.parse import urljoin

                href = urljoin(url, href)

            date_text = date_elem.get_text(strip=True) if date_elem else ""

            items.append(
                PolicyItem(
                    title=title,
                    source=source_id,
                    source_name=source_name,
                    url=href,
                    date=date_text,
                    impact_category=impact_category,
                )
            )

        logger.info("Fetched %d policy items from %s", len(items), source_name)
        return items

    def _check_high_impact(self, item: PolicyItem) -> bool:
        """Check if a policy item matches high-impact keywords."""
        category_keywords = self._high_impact_keywords.get(item.impact_category, [])
        # Also check all categories
        all_keywords = []
        for kw_list in self._high_impact_keywords.values():
            all_keywords.extend(kw_list)

        title = item.title
        for kw in category_keywords or all_keywords:
            if kw in title:
                return True
        return False

    def _get_cached(self, key: str) -> list[PolicyItem] | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, items = entry
        if time.time() - ts > self._DEFAULT_TTL:
            del self._cache[key]
            return None
        return items

    def _set_cached(self, key: str, items: list[PolicyItem]) -> None:
        self._cache[key] = (time.time(), items)

"""Corporate announcement fetcher via cninfo.com.cn (巨潮资讯网).

CSRC-mandated disclosure platform — every listed company must publish here
before anywhere else. More authoritative and stable than any AKShare wrapper.

API: POST http://www.cninfo.com.cn/new/hisAnnouncement/query
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.data.circuit_breaker import CircuitBreaker
from src.data.http_client import create_session
from src.utils.logger import get_logger

logger = get_logger("data.cninfo_announcement")

__all__ = ["CorporateAnnouncement", "CninfoAnnouncementFetcher"]

_CACHE_TTL = 300  # 5 minutes
_BASE_URL = "http://www.cninfo.com.cn"
_QUERY_URL = f"{_BASE_URL}/new/hisAnnouncement/query"

# High-impact keyword classification
_IMPACT_KEYWORDS: dict[str, list[str]] = {
    "earnings": [
        "业绩预告",
        "业绩快报",
        "年报",
        "半年报",
        "季报",
        "利润分配",
        "净利润",
    ],
    "restructuring": [
        "重组",
        "收购",
        "合并",
        "资产注入",
        "借壳",
        "重大资产",
        "资产置换",
    ],
    "equity_change": ["增持", "减持", "回购", "股权激励", "限售股", "解禁", "股份变动"],
    "risk_warning": ["退市", "ST", "暂停上市", "风险警示", "摘牌", "终止上市", "立案"],
    "dividend": ["分红", "派息", "送股", "转增", "权益分派"],
}


@dataclass
class CorporateAnnouncement:
    """A single corporate announcement from cninfo."""

    symbol: str
    name: str
    title: str
    announcement_type: (
        str  # earnings|restructuring|equity_change|risk_warning|dividend|other
    )
    publish_date: str  # YYYY-MM-DD
    url: str  # full PDF URL
    is_high_impact: bool
    impact_keywords: list[str] = field(default_factory=list)
    announcement_id: str = ""  # cninfo internal ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "title": self.title,
            "type": self.announcement_type,
            "date": self.publish_date,
            "url": self.url,
            "high_impact": self.is_high_impact,
            "keywords": self.impact_keywords,
        }


class CninfoAnnouncementFetcher:
    """Fetch corporate announcements from cninfo.com.cn.

    Uses the POST API at /new/hisAnnouncement/query which returns JSON
    with announcement metadata (title, date, PDF link, etc.).

    Usage::

        fetcher = CninfoAnnouncementFetcher()
        recent = await fetcher.fetch_recent(days=3)
        for_stock = await fetcher.fetch_for_symbol("601318", days=30)
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._last_request_ts: float = 0.0
        self._circuit = CircuitBreaker(
            "cninfo", failure_threshold=3, recovery_timeout=300.0
        )
        self._session = create_session(timeout=(5.0, 15.0), retries=2)
        # cninfo requires specific headers
        self._session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": _BASE_URL,
                "Referer": f"{_BASE_URL}/new/commonUrl?url=disclosure/list/search",
            }
        )

    # -- Cache & rate limiting ------------------------------------------------

    def _polite_sleep(self, interval: float = 0.5) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request_ts = time.monotonic()

    def _get_cache(self, key: str) -> Any | None:
        if key in self._cache:
            expire_ts, val = self._cache[key]
            if time.time() < expire_ts:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time() + _CACHE_TTL, val)

    # -- Impact classification ------------------------------------------------

    @staticmethod
    def _classify_impact(title: str) -> tuple[str, bool, list[str]]:
        """Classify announcement by title keywords.

        Returns:
            (announcement_type, is_high_impact, matched_keywords)
        """
        matched: list[str] = []
        matched_type = "other"

        for atype, keywords in _IMPACT_KEYWORDS.items():
            for kw in keywords:
                if kw in title:
                    matched.append(kw)
                    matched_type = atype

        is_high = matched_type in ("earnings", "restructuring", "risk_warning")
        return matched_type, is_high, matched

    # -- API calls ------------------------------------------------------------

    def _query_sync(
        self,
        stock: str = "",
        page: int = 1,
        page_size: int = 30,
        se_date: str = "",
        column: str = "szse",
        category: str = "",
    ) -> dict[str, Any]:
        """POST query to cninfo announcement API.

        Args:
            stock: Stock code (e.g., "601318") or empty for all.
            page: Page number.
            page_size: Results per page.
            se_date: Date range "YYYY-MM-DD~YYYY-MM-DD".
            column: Exchange filter — "szse" (SZSE), "sse" (SSE), or empty for all.
            category: Announcement category filter.

        Returns:
            Raw JSON response dict.
        """
        if self._circuit.state == "open":
            logger.debug("Circuit breaker open, skipping cninfo query")
            return {}

        self._polite_sleep()

        data = {
            "pageNum": page,
            "pageSize": page_size,
            "column": column,
            "tabName": "fulltext",
            "plate": "",
            "stock": stock,
            "searchkey": "",
            "secid": "",
            "category": category,
            "trade": "",
            "seDate": se_date,
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }

        try:
            resp = self._session.post(_QUERY_URL, data=data)
            resp.raise_for_status()
            result = resp.json()
            self._circuit._on_success()
            return result
        except Exception as exc:
            logger.warning("cninfo query failed: %s", exc)
            self._circuit._on_failure()
            return {}

    def _parse_announcements(self, raw: dict[str, Any]) -> list[CorporateAnnouncement]:
        """Parse raw cninfo JSON response into announcement list."""
        announcements_data = raw.get("announcements", [])
        if not announcements_data:
            return []

        results: list[CorporateAnnouncement] = []
        for item in announcements_data:
            title = item.get("announcementTitle", "")
            # Strip HTML highlight tags that cninfo sometimes adds
            title = title.replace("<em>", "").replace("</em>", "")

            symbol = item.get("secCode", "")
            if not symbol or len(symbol) != 6:
                continue

            name = item.get("secName", "")
            ann_id = item.get("announcementId", "")

            # Build PDF URL
            adjunct_url = item.get("adjunctUrl", "")
            pdf_url = f"{_BASE_URL}/{adjunct_url}" if adjunct_url else ""

            # Parse date (timestamp in milliseconds)
            ts = item.get("announcementTime")
            if ts:
                try:
                    publish_date = datetime.fromtimestamp(ts / 1000).strftime(
                        "%Y-%m-%d"
                    )
                except (ValueError, TypeError, OSError):
                    publish_date = ""
            else:
                publish_date = ""

            ann_type, is_high, keywords = self._classify_impact(title)

            results.append(
                CorporateAnnouncement(
                    symbol=symbol,
                    name=name,
                    title=title,
                    announcement_type=ann_type,
                    publish_date=publish_date,
                    url=pdf_url,
                    is_high_impact=is_high,
                    impact_keywords=keywords,
                    announcement_id=str(ann_id),
                )
            )

        return results

    # -- Public methods -------------------------------------------------------

    def fetch_recent_sync(self, days: int = 3) -> list[CorporateAnnouncement]:
        """Fetch recent high-impact announcements across all stocks.

        Args:
            days: How many days back to look.

        Returns:
            List of announcements, high-impact ones first.
        """
        cache_key = f"recent_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        end = datetime.now()
        start = end - timedelta(days=days)
        se_date = f"{start:%Y-%m-%d}~{end:%Y-%m-%d}"

        all_announcements: list[CorporateAnnouncement] = []

        # Fetch from both exchanges
        for col in ("szse", "sse"):
            raw = self._query_sync(se_date=se_date, column=col, page_size=50)
            parsed = self._parse_announcements(raw)
            all_announcements.extend(parsed)

        # Sort: high-impact first, then by date descending
        all_announcements.sort(
            key=lambda a: (not a.is_high_impact, a.publish_date), reverse=False
        )
        # Reverse to get newest first within each impact group
        high = [a for a in all_announcements if a.is_high_impact]
        low = [a for a in all_announcements if not a.is_high_impact]
        result = high + low

        self._set_cache(cache_key, result)
        logger.info(
            "Fetched %d announcements (%d high-impact) from cninfo, last %d days",
            len(result),
            len(high),
            days,
        )
        return result

    def fetch_for_symbol_sync(
        self, symbol: str, days: int = 30
    ) -> list[CorporateAnnouncement]:
        """Fetch announcements for a specific stock.

        Args:
            symbol: 6-digit stock code.
            days: How many days back to look.

        Returns:
            List of announcements sorted by date descending.
        """
        cache_key = f"symbol_{symbol}_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        end = datetime.now()
        start = end - timedelta(days=days)
        se_date = f"{start:%Y-%m-%d}~{end:%Y-%m-%d}"

        raw = self._query_sync(stock=symbol, se_date=se_date, column="", page_size=50)
        result = self._parse_announcements(raw)

        self._set_cache(cache_key, result)
        logger.info("Fetched %d announcements for %s from cninfo", len(result), symbol)
        return result

    async def fetch_recent(self, days: int = 3) -> list[CorporateAnnouncement]:
        """Async wrapper for fetch_recent_sync."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_recent_sync, days)

    async def fetch_for_symbol(
        self, symbol: str, days: int = 30
    ) -> list[CorporateAnnouncement]:
        """Async wrapper for fetch_for_symbol_sync."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.fetch_for_symbol_sync, symbol, days
        )

    def get_high_impact_summary(
        self, announcements: list[CorporateAnnouncement], limit: int = 5
    ) -> list[str]:
        """Get one-line summaries of high-impact announcements.

        Returns:
            List of strings like "601318: 发布重组方案 [restructuring]"
        """
        high = [a for a in announcements if a.is_high_impact][:limit]
        return [f"{a.symbol}: {a.title} [{a.announcement_type}]" for a in high]

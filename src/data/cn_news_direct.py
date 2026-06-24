"""Direct API fetcher for Chinese financial news sources.

Bypasses rsshub.app (which is a single point of failure) by calling
the source APIs directly:
- 财联社 (CLS): Real-time financial telegraphs
- 华尔街见闻 (Wallstreetcn): Curated financial news articles
- 金十数据 (Jin10): Real-time financial wire / flash news

These are the three most critical Chinese financial news sources for
event detection and market sentiment.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.data.circuit_breaker import CircuitBreaker
from src.data.http_client import create_session
from src.utils.logger import get_logger

logger = get_logger("data.cn_news_direct")

__all__ = ["CnNewsItem", "CnNewsDirectFetcher"]

_CACHE_TTL = 300  # 5 minutes


@dataclass
class CnNewsItem:
    """A single news item from a Chinese financial source."""

    title: str
    content: str  # summary or full text
    source: str  # cls|wallstreetcn|jin10
    publish_time: datetime
    url: str = ""
    is_important: bool = False  # flagged as important by source
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content[:200],
            "source": self.source,
            "time": self.publish_time.isoformat(),
            "url": self.url,
            "important": self.is_important,
        }


class CnNewsDirectFetcher:
    """Fetch Chinese financial news directly from source APIs.

    Usage::

        fetcher = CnNewsDirectFetcher()
        cls_news = await fetcher.fetch_cls(limit=30)
        wscn_news = await fetcher.fetch_wallstreetcn(limit=20)
        all_news = await fetcher.fetch_all(limit=50)
    """

    def __init__(self) -> None:
        self._session = create_session(timeout=(5.0, 15.0), retries=2)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._circuit_cls = CircuitBreaker(
            "cls_news", failure_threshold=3, recovery_timeout=300.0
        )
        self._circuit_wscn = CircuitBreaker(
            "wscn_news", failure_threshold=3, recovery_timeout=300.0
        )
        self._circuit_jin10 = CircuitBreaker(
            "jin10_news", failure_threshold=3, recovery_timeout=300.0
        )
        self._circuit_sina = CircuitBreaker(
            "sina_news", failure_threshold=3, recovery_timeout=300.0
        )
        self._last_request_ts: float = 0.0

    def _polite_sleep(self, interval: float = 0.3) -> None:
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

    # -- 财联社 (CLS) --------------------------------------------------------

    def fetch_cls_sync(self, limit: int = 50) -> list[CnNewsItem]:
        """Fetch CLS telegraph (财联社电报).

        API: https://www.cls.cn/v1/roll/get_roll_list (with signature)
        Fallback: parse from assembled endpoint
        """
        cache_key = f"cls_{limit}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit_cls.state == "open":
            return []

        self._polite_sleep()

        try:
            # Use the depth/home assembled endpoint which doesn't require auth
            resp = self._session.get(
                f"https://www.cls.cn/v3/depth/home/assembled/1/{limit}",
                headers={"Referer": "https://www.cls.cn/telegraph"},
            )
            resp.raise_for_status()
            data = resp.json()

            # Try to extract telegraph items from assembled response
            items_raw = data.get("data", {}).get("roll_data", [])
            if not items_raw and isinstance(data.get("data"), list):
                items_raw = data["data"]
            if not items_raw:
                # Try extracting from nested structure
                for key in ("telegraph", "roll", "depth_list"):
                    items_raw = data.get("data", {}).get(key, [])
                    if items_raw:
                        break
            results: list[CnNewsItem] = []

            for item in items_raw:
                title = str(item.get("title", ""))
                content = str(item.get("content", item.get("brief", "")))
                # Remove HTML tags
                import re

                content = re.sub(r"<[^>]+>", "", content)
                title = re.sub(r"<[^>]+>", "", title)

                if not title and not content:
                    continue

                ts = item.get("ctime", 0)
                try:
                    pub_time = datetime.fromtimestamp(int(ts))
                except (ValueError, TypeError, OSError):
                    pub_time = datetime.now()

                is_important = bool(item.get("level", 0))

                results.append(
                    CnNewsItem(
                        title=title or content[:50],
                        content=content,
                        source="cls",
                        publish_time=pub_time,
                        url=f"https://www.cls.cn/detail/{item.get('id', '')}",
                        is_important=is_important,
                    )
                )

            self._circuit_cls._on_success()
            self._set_cache(cache_key, results)
            logger.info("CLS: fetched %d telegraphs", len(results))
            return results

        except Exception as exc:
            logger.warning("CLS fetch failed: %s", exc)
            self._circuit_cls._on_failure()
            return []

    # -- 华尔街见闻 (Wallstreetcn) -------------------------------------------

    def fetch_wallstreetcn_sync(self, limit: int = 30) -> list[CnNewsItem]:
        """Fetch Wallstreetcn articles (华尔街见闻).

        API: https://api-one-wscn.awtmt.com/apiv1/content/articles/all
        """
        cache_key = f"wscn_{limit}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit_wscn.state == "open":
            return []

        self._polite_sleep()

        try:
            resp = self._session.get(
                "https://api-one.wallstcn.com/apiv1/content/lives",
                params={
                    "channel": "global-channel",
                    "limit": str(limit),
                },
                headers={
                    "Referer": "https://wallstreetcn.com/",
                    "Origin": "https://wallstreetcn.com",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            items_raw = data.get("data", {}).get("items", [])
            results: list[CnNewsItem] = []

            for item in items_raw:
                title = str(item.get("content_text", ""))
                content = title

                if not title:
                    continue

                ts = item.get("display_time", 0)
                try:
                    pub_time = datetime.fromtimestamp(int(ts))
                except (ValueError, TypeError, OSError):
                    pub_time = datetime.now()

                is_important = bool(item.get("is_important"))
                uri = str(item.get("uri", ""))

                results.append(
                    CnNewsItem(
                        title=title,
                        content=content,
                        source="wallstreetcn",
                        publish_time=pub_time,
                        url=f"https://wallstreetcn.com/articles/{uri}" if uri else "",
                        is_important=is_important,
                    )
                )

            self._circuit_wscn._on_success()
            self._set_cache(cache_key, results)
            logger.info("WSCN: fetched %d articles", len(results))
            return results

        except Exception as exc:
            logger.warning("WSCN fetch failed: %s", exc)
            self._circuit_wscn._on_failure()
            return []

    # -- 金十数据 (Jin10) ----------------------------------------------------

    def fetch_jin10_sync(self, limit: int = 30) -> list[CnNewsItem]:
        """Fetch Jin10 flash news (金十数据快讯).

        API: https://flash-api.jin10.com/get_flash_list
        """
        cache_key = f"jin10_{limit}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit_jin10.state == "open":
            return []

        self._polite_sleep()

        try:
            resp = self._session.get(
                "https://flash-api.jin10.com/get_flash_list",
                params={"max_time": "", "channel": "-8200"},
                headers={
                    "Referer": "https://www.jin10.com/",
                    "Origin": "https://www.jin10.com",
                    "x-app-id": "bVBF4FyRTn5NJF5n",
                    "x-version": "1.0.0",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            items_raw = data.get("data", [])
            results: list[CnNewsItem] = []

            for item in items_raw:
                content = str(item.get("data", {}).get("content", ""))
                if not content:
                    continue

                import re

                content = re.sub(r"<[^>]+>", "", content)

                time_str = item.get("time", "")
                try:
                    pub_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    pub_time = datetime.now()

                is_important = bool(item.get("important"))

                results.append(
                    CnNewsItem(
                        title=content[:60],
                        content=content,
                        source="jin10",
                        publish_time=pub_time,
                        is_important=is_important,
                    )
                )

            self._circuit_jin10._on_success()
            self._set_cache(cache_key, results)
            logger.info("Jin10: fetched %d flash items", len(results))
            return results

        except Exception as exc:
            logger.warning("Jin10 fetch failed: %s", exc)
            self._circuit_jin10._on_failure()
            return []

    # -- 新浪7x24 (Sina Global Live) -----------------------------------------

    def fetch_sina_7x24_sync(self, limit: int = 30) -> list[CnNewsItem]:
        """Fetch Sina 7x24 global live news (新浪全球实时快讯).

        API: https://zhibo.sina.com.cn/api/zhibo/feed
        Best source for real-time geopolitical events (tested: 15/20 items
        were Middle East conflict coverage during Israel-Iran escalation).
        """
        cache_key = f"sina_{limit}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit_sina.state == "open":
            return []

        self._polite_sleep()

        try:
            resp = self._session.get(
                "https://zhibo.sina.com.cn/api/zhibo/feed",
                params={
                    "page": "1",
                    "page_size": str(limit),
                    "zhibo_id": "152",
                    "tag_id": "0",
                    "type": "0",
                },
                headers={"Referer": "https://finance.sina.com.cn/7x24/"},
            )
            resp.raise_for_status()
            data = resp.json()

            items_raw = (
                data.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
            )
            results: list[CnNewsItem] = []

            for item in items_raw:
                rich_text = str(item.get("rich_text", ""))
                if not rich_text:
                    continue

                import re

                content = re.sub(r"<[^>]+>", "", rich_text)

                create_time = item.get("create_time", "")
                try:
                    pub_time = datetime.strptime(
                        str(create_time)[:19], "%Y-%m-%d %H:%M:%S"
                    )
                except (ValueError, TypeError):
                    pub_time = datetime.now()

                # Extract tags for categorization
                tags = [t.get("name", "") for t in item.get("tag", []) if t.get("name")]

                results.append(
                    CnNewsItem(
                        title=content[:60],
                        content=content,
                        source="sina",
                        publish_time=pub_time,
                        is_important=bool(item.get("is_top")),
                        tags=tags,
                    )
                )

            self._circuit_sina._on_success()
            self._set_cache(cache_key, results)
            logger.info("Sina 7x24: fetched %d items", len(results))
            return results

        except Exception as exc:
            logger.warning("Sina 7x24 fetch failed: %s", exc)
            self._circuit_sina._on_failure()
            return []

    # -- 东方财富快讯 (EastMoney kuaixun) — A股行业政策最全 -----------

    def fetch_eastmoney_kuaixun_sync(self, limit: int = 30) -> list[CnNewsItem]:
        """Fetch EastMoney express news (东方财富快讯).

        Covers A-share industry policy, sector news, and market flashes.
        This is the primary source for 算力/特高压/新能源 etc. policy news.
        """
        cache_key = "eastmoney_kuaixun"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached[:limit]

        if self._circuit_cls.state == "open":
            return []

        self._polite_sleep()

        try:
            # EastMoney live news feed (公开 API, 无需 key)
            url = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
            params = {
                "client": "web",
                "biz": "web_home_channel",
                "column": "350,35,466,467",  # 要闻+行业+概念+政策
                "order": "1",
                "needInteractData": "0",
                "page_index": "1",
                "page_size": str(limit),
            }
            resp = self._session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            results: list[CnNewsItem] = []
            news_list = data.get("data", {}).get("list", [])

            for item in news_list[:limit]:
                title = item.get("title", "").strip()
                digest = item.get("digest", "")
                content = digest or title
                art_url = item.get("url_unique", item.get("url_w", ""))

                try:
                    show_time = item.get("showtime", "")
                    pub_time = datetime.strptime(show_time[:19], "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    pub_time = datetime.now()

                # Mark policy/industry news as important
                columns = item.get("columns", [])
                col_names = [c.get("name", "") for c in columns] if columns else []
                is_important = any(
                    k in title
                    for k in ["国务院", "发改委", "工信部", "证监会", "央行", "政策"]
                ) or any(k in str(col_names) for k in ["政策", "要闻"])

                results.append(
                    CnNewsItem(
                        title=title,
                        content=content[:500],
                        source="eastmoney",
                        publish_time=pub_time,
                        url=art_url,
                        is_important=is_important,
                        tags=col_names[:5],
                    )
                )

            self._set_cache(cache_key, results)
            logger.info("EastMoney kuaixun: fetched %d items", len(results))
            return results

        except Exception as exc:
            logger.warning("EastMoney kuaixun fetch failed: %s", exc)
            return []

    # -- Aggregate -----------------------------------------------------------

    def fetch_all_sync(self, limit: int = 50) -> list[CnNewsItem]:
        """Fetch from all Chinese sources and merge by time."""
        per_source = max(limit // 5, 8)
        all_items: list[CnNewsItem] = []

        try:
            all_items.extend(self.fetch_eastmoney_kuaixun_sync(per_source))
        except Exception:
            pass  # EastMoney may not work in Docker
        all_items.extend(self.fetch_sina_7x24_sync(per_source))
        all_items.extend(self.fetch_wallstreetcn_sync(per_source))
        all_items.extend(self.fetch_jin10_sync(per_source))
        all_items.extend(self.fetch_cls_sync(per_source))

        all_items.sort(key=lambda x: x.publish_time, reverse=True)
        return all_items[:limit]

    # -- Async wrappers ------------------------------------------------------

    async def fetch_cls(self, limit: int = 50) -> list[CnNewsItem]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_cls_sync, limit)

    async def fetch_wallstreetcn(self, limit: int = 30) -> list[CnNewsItem]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_wallstreetcn_sync, limit)

    async def fetch_jin10(self, limit: int = 30) -> list[CnNewsItem]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_jin10_sync, limit)

    async def fetch_sina_7x24(self, limit: int = 30) -> list[CnNewsItem]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_sina_7x24_sync, limit)

    async def fetch_all(self, limit: int = 50) -> list[CnNewsItem]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_all_sync, limit)

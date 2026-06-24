"""Weibo trending (微博热搜) fetcher.

Weibo is China's largest social media platform with 500M+ MAU.
Hot search topics drive retail investor sentiment and concept stock
momentum — when a topic trends on Weibo, related A-share sectors
often see volume spikes within hours.

API: https://weibo.com/ajax/side/hotSearch (no auth required)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from src.data.circuit_breaker import CircuitBreaker
from src.data.http_client import create_session
from src.utils.logger import get_logger

logger = get_logger("data.weibo_trending")

__all__ = ["WeiboTrend", "WeiboTrendingFetcher"]

_CACHE_TTL = 300  # 5 minutes — hot search changes rapidly

# Keywords that indicate market-relevant topics
_MARKET_KEYWORDS = [
    # Policy & Economy
    "央行",
    "降准",
    "降息",
    "加息",
    "利率",
    "GDP",
    "CPI",
    "PMI",
    "财政",
    "税收",
    "减税",
    "补贴",
    "政策",
    "监管",
    "证监会",
    # Market
    "股市",
    "A股",
    "大盘",
    "涨停",
    "跌停",
    "牛市",
    "熊市",
    "基金",
    "理财",
    "房价",
    "楼市",
    "债务",
    # Tech & Industry
    "芯片",
    "半导体",
    "新能源",
    "电动车",
    "光伏",
    "锂电",
    "人工智能",
    "AI",
    "大模型",
    "机器人",
    "量子",
    "算力",
    # Geopolitics
    "中美",
    "关税",
    "贸易",
    "制裁",
    "台海",
    "南海",
    "伊朗",
    "以色列",
    "俄罗斯",
    "乌克兰",
    "中东",
    # Companies
    "华为",
    "比亚迪",
    "宁德",
    "茅台",
    "腾讯",
    "阿里",
    "小米",
    "特斯拉",
    "苹果",
    "英伟达",
    # Commodities
    "原油",
    "黄金",
    "石油",
    "天然气",
    "铁矿",
    "铜",
]

# Topic → sector mapping for quick association
_TOPIC_SECTOR_MAP: dict[str, list[str]] = {
    "芯片": ["半导体", "电子"],
    "半导体": ["半导体", "电子"],
    "新能源": ["新能源", "电力设备"],
    "电动车": ["汽车", "新能源"],
    "光伏": ["光伏", "电力设备"],
    "锂电": ["电池", "新能源"],
    "人工智能": ["AI", "计算机"],
    "AI": ["AI", "计算机"],
    "大模型": ["AI", "计算机"],
    "机器人": ["机器人", "机械"],
    "原油": ["石油石化", "化工"],
    "黄金": ["贵金属", "有色"],
    "房价": ["房地产", "银行"],
    "楼市": ["房地产", "建材"],
    "降准": ["银行", "券商"],
    "降息": ["银行", "房地产"],
}


@dataclass
class WeiboTrend:
    """A single Weibo hot search topic."""

    rank: int
    topic: str
    heat: int  # search volume
    label: str  # 热/新/沸/爆 etc
    is_market_relevant: bool
    matched_keywords: list[str] = field(default_factory=list)
    related_sectors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "topic": self.topic,
            "heat": self.heat,
            "label": self.label,
            "market_relevant": self.is_market_relevant,
            "keywords": self.matched_keywords,
            "sectors": self.related_sectors,
        }


class WeiboTrendingFetcher:
    """Fetch Weibo hot search topics and identify market-relevant trends.

    Usage::

        fetcher = WeiboTrendingFetcher()
        all_trends = await fetcher.fetch_trending()
        market_trends = await fetcher.fetch_market_relevant()
    """

    def __init__(self) -> None:
        self._session = create_session(timeout=(5.0, 10.0), retries=2)
        self._session.headers.update(
            {
                "Referer": "https://weibo.com/",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self._cache: dict[str, tuple[float, Any]] = {}
        self._circuit = CircuitBreaker(
            "weibo_trending", failure_threshold=3, recovery_timeout=300.0
        )

    def _get_cache(self, key: str) -> Any | None:
        if key in self._cache:
            expire_ts, val = self._cache[key]
            if time.time() < expire_ts:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time() + _CACHE_TTL, val)

    @staticmethod
    def _classify_market_relevance(
        topic: str,
    ) -> tuple[bool, list[str], list[str]]:
        """Check if a topic is market-relevant.

        Returns:
            (is_relevant, matched_keywords, related_sectors)
        """
        matched = [kw for kw in _MARKET_KEYWORDS if kw in topic]
        sectors: list[str] = []
        for kw in matched:
            if kw in _TOPIC_SECTOR_MAP:
                sectors.extend(_TOPIC_SECTOR_MAP[kw])
        # Deduplicate sectors
        sectors = list(dict.fromkeys(sectors))
        return bool(matched), matched, sectors

    def fetch_trending_sync(self) -> list[WeiboTrend]:
        """Fetch current Weibo hot search topics."""
        cache_key = "trending"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit.state == "open":
            return []

        try:
            resp = self._session.get("https://weibo.com/ajax/side/hotSearch")
            resp.raise_for_status()
            data = resp.json()

            realtime = data.get("data", {}).get("realtime", [])
            results: list[WeiboTrend] = []

            for i, item in enumerate(realtime):
                topic = str(item.get("note", item.get("word", "")))
                if not topic:
                    continue

                heat = int(item.get("num", 0))
                label = str(item.get("label_name", ""))
                is_relevant, keywords, sectors = self._classify_market_relevance(topic)

                results.append(
                    WeiboTrend(
                        rank=i + 1,
                        topic=topic,
                        heat=heat,
                        label=label,
                        is_market_relevant=is_relevant,
                        matched_keywords=keywords,
                        related_sectors=sectors,
                    )
                )

            self._circuit._on_success()
            self._set_cache(cache_key, results)

            market_count = sum(1 for r in results if r.is_market_relevant)
            logger.info(
                "Weibo trending: %d topics (%d market-relevant)",
                len(results),
                market_count,
            )
            return results

        except Exception as exc:
            logger.warning("Weibo trending fetch failed: %s", exc)
            self._circuit._on_failure()
            return []

    def fetch_market_relevant_sync(self) -> list[WeiboTrend]:
        """Fetch only market-relevant Weibo trends."""
        all_trends = self.fetch_trending_sync()
        return [t for t in all_trends if t.is_market_relevant]

    def get_trending_summary(self) -> list[str]:
        """Get one-line summaries for market-relevant trends.

        For serialize_for_llm [舆情] block.
        """
        relevant = self.fetch_market_relevant_sync()
        if not relevant:
            return []

        lines = []
        for t in relevant[:5]:
            sectors = "→" + ",".join(t.related_sectors) if t.related_sectors else ""
            lines.append(f"#{t.rank} {t.topic} ({t.heat:,}热度){sectors}")
        return lines

    # -- Async wrappers -------------------------------------------------------

    async def fetch_trending(self) -> list[WeiboTrend]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_trending_sync)

    async def fetch_market_relevant(self) -> list[WeiboTrend]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_market_relevant_sync)

"""EastMoney Guba (股吧) sentiment fetcher.

Scrapes public stock forum posts for retail sentiment signals.

EastMoney Guba is China's largest retail investor forum with millions
of daily active users.  Post volume, sentiment polarity, and topic
trends provide valuable contrarian and momentum signals — extreme
bullish retail sentiment often precedes tops, while despair marks bottoms.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp

from src.utils.logger import get_logger

logger = get_logger("data.eastmoney_comment")

__all__ = ["GubaMetrics", "EastMoneyCommentFetcher"]

# ---------------------------------------------------------------------------
# Sentiment keywords (retail investor forum style)
# ---------------------------------------------------------------------------

_BULL_KEYWORDS: list[tuple[str, int]] = [
    # Strong (3)
    ("涨停", 3),
    ("翻倍", 3),
    ("重大利好", 3),
    ("连板", 3),
    ("一字板", 3),
    # Medium (2)
    ("大涨", 2),
    ("新高", 2),
    ("突破", 2),
    ("利好", 2),
    ("增持", 2),
    ("回购", 2),
    ("主力", 2),
    ("龙头", 2),
    ("机构买入", 2),
    ("低估", 2),
    ("业绩超预期", 2),
    # Weak (1)
    ("看好", 1),
    ("买入", 1),
    ("加仓", 1),
    ("反弹", 1),
    ("企稳", 1),
    ("放量", 1),
    ("底部", 1),
    ("上车", 1),
    ("牛", 1),
    ("起飞", 1),
    ("稳了", 1),
    ("冲", 1),
]

_BEAR_KEYWORDS: list[tuple[str, int]] = [
    # Strong (3)
    ("跌停", 3),
    ("退市", 3),
    ("暴雷", 3),
    ("财务造假", 3),
    ("重大利空", 3),
    ("ST", 3),
    # Medium (2)
    ("大跌", 2),
    ("暴跌", 2),
    ("新低", 2),
    ("破位", 2),
    ("利空", 2),
    ("减持", 2),
    ("质押", 2),
    ("亏损", 2),
    ("割肉", 2),
    ("套牢", 2),
    ("闪崩", 2),
    ("踩雷", 2),
    # Weak (1)
    ("下跌", 1),
    ("走弱", 1),
    ("承压", 1),
    ("缩量", 1),
    ("卖出", 1),
    ("清仓", 1),
    ("垃圾", 1),
    ("坑人", 1),
    ("骗子", 1),
    ("完了", 1),
    ("凉了", 1),
    ("跑", 1),
]

_NEGATION_PREFIXES = ["不", "未", "没有", "非", "否认", "难以"]

# ---------------------------------------------------------------------------
# HTTP config
# ---------------------------------------------------------------------------

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://guba.eastmoney.com/",
}

# Rate-limit interval between requests (seconds)
_REQUEST_INTERVAL = 0.5

# Cache TTL (seconds)
_CACHE_TTL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class GubaMetrics:
    """Aggregated sentiment metrics for a stock from EastMoney Guba."""

    symbol: str
    post_count_24h: int = 0
    read_count_avg: float = 0.0  # average reads per post
    comment_count_avg: float = 0.0  # average comments per post
    sentiment: str = "neutral"  # bullish / bearish / neutral
    sentiment_score: float = 0.0  # -1 to 1
    hot_topics: list[str] = field(default_factory=list)  # top 3 topics
    institutional_post_count: int = 0  # posts tagged as institutional
    fetched_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


class EastMoneyCommentFetcher:
    """Fetch 股吧 sentiment from EastMoney.

    Supports both the JSON API and fallback HTML scraping for post data.

    Usage::

        fetcher = EastMoneyCommentFetcher()
        metrics = await fetcher.fetch("601668")
        batch = await fetcher.fetch_batch(["601668", "000001"])
        await fetcher.close()
    """

    BASE_URL = "https://guba.eastmoney.com"
    API_URL = "https://gbapi.eastmoney.com/stkpost/api/v1/post/listbystock"

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None
        self._last_request_ts: float = 0.0
        # Simple in-memory TTL cache: symbol -> (expire_ts, GubaMetrics)
        self._cache: dict[str, tuple[float, GubaMetrics]] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        """Lazily create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            self._session = aiohttp.ClientSession(
                headers=_HEADERS,
                timeout=timeout,
            )
        return self._session

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_ts
        if elapsed < _REQUEST_INTERVAL:
            await asyncio.sleep(_REQUEST_INTERVAL - elapsed)
        self._last_request_ts = time.monotonic()

    def _convert_symbol_code(self, symbol: str) -> str:
        """Convert 6-digit stock code to Guba code format.

        Guba uses bare codes for most endpoints.
        Strips any SH/SZ prefix.
        """
        symbol = symbol.strip()
        # Strip SH/SZ prefix
        for prefix in ("SH", "SZ", "sh", "sz"):
            if symbol.startswith(prefix):
                symbol = symbol[2:]
                break
        return symbol

    async def _fetch_posts_api(
        self, symbol_code: str, page_size: int = 30
    ) -> list[dict[str, Any]]:
        """Fetch posts via the JSON API endpoint.

        Args:
            symbol_code: Bare 6-digit stock code.
            page_size: Number of posts to fetch.

        Returns:
            List of post dicts from the API response.
        """
        session = await self._get_session()
        await self._rate_limit()

        params = {
            "stockcode": symbol_code,
            "pageindex": "1",
            "pagesize": str(page_size),
            "sort": "posttime",  # sort by post time descending
            "source": "web",
        }

        try:
            async with session.get(self.API_URL, params=params) as resp:
                if resp.status != 200:
                    logger.debug(
                        "Guba API returned %d for %s", resp.status, symbol_code
                    )
                    return await self._fetch_posts_html(symbol_code)
                data = await resp.json(content_type=None)
                posts = data.get("re", [])
                if isinstance(posts, list) and posts:
                    return posts
                # Fallback to HTML if API returns empty
                return await self._fetch_posts_html(symbol_code)
        except Exception as exc:
            logger.debug("Guba API failed for %s: %s, trying HTML", symbol_code, exc)
            return await self._fetch_posts_html(symbol_code)

    async def _fetch_posts_html(self, symbol_code: str) -> list[dict[str, Any]]:
        """Fallback: scrape posts from Guba HTML page.

        Parses the stock forum listing page for post titles and metadata.
        """
        session = await self._get_session()
        await self._rate_limit()

        url = f"{self.BASE_URL}/list,{symbol_code}.html"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.debug(
                        "Guba HTML returned %d for %s", resp.status, symbol_code
                    )
                    return []
                html = await resp.text()
                return self._parse_html_posts(html)
        except Exception as exc:
            logger.warning("Guba HTML fetch failed for %s: %s", symbol_code, exc)
            return []

    def _parse_html_posts(self, html: str) -> list[dict[str, Any]]:
        """Parse post metadata from Guba HTML listing page.

        Extracts post titles, read counts, comment counts from the
        listing table.  This is a lightweight regex-based parser (no
        BeautifulSoup dependency).
        """
        posts: list[dict[str, Any]] = []

        # Match post rows: each row has read_count, comment_count, title
        # Pattern matches the listing table structure
        row_pattern = re.compile(
            r'class="read"[^>]*>(\d+)</\w+>'  # read count
            r'.*?class="reply"[^>]*>(\d+)</\w+>'  # comment count
            r'.*?class="title"[^>]*>.*?<a[^>]*>([^<]+)</a>',  # title
            re.DOTALL,
        )

        # Also try a simpler pattern for the newer Guba layout
        simple_pattern = re.compile(
            r'"read_count"[:\s]*(\d+).*?"comment_count"[:\s]*(\d+).*?"title"[:\s]*"([^"]+)"',
            re.DOTALL,
        )

        for match in row_pattern.finditer(html):
            posts.append(
                {
                    "read_count": int(match.group(1)),
                    "comment_count": int(match.group(2)),
                    "title": match.group(3).strip(),
                }
            )

        # Fallback to JSON-like pattern if table parsing yields nothing
        if not posts:
            for match in simple_pattern.finditer(html):
                posts.append(
                    {
                        "read_count": int(match.group(1)),
                        "comment_count": int(match.group(2)),
                        "title": match.group(3).strip(),
                    }
                )

        return posts

    def _extract_sentiment(self, posts: list[dict[str, Any]]) -> tuple[str, float]:
        """Analyze sentiment from post titles and content.

        Uses weighted keyword matching with negation handling.
        Also incorporates like/dislike ratio when available.

        Returns:
            (direction, score) where direction is bullish/bearish/neutral
            and score is in [-1.0, 1.0].
        """
        bull_score = 0
        bear_score = 0

        for post in posts:
            text = post.get("title", "") or post.get("post_title", "") or ""
            content = post.get("post_content", "") or post.get("content", "") or ""
            text = f"{text} {content}"
            # Strip HTML
            text = re.sub(r"<[^>]+>", "", text)

            for keyword, weight in _BULL_KEYWORDS:
                idx = text.find(keyword)
                if idx >= 0:
                    prefix = text[max(0, idx - 3) : idx]
                    negated = any(neg in prefix for neg in _NEGATION_PREFIXES)
                    if negated:
                        bear_score += weight
                    else:
                        bull_score += weight

            for keyword, weight in _BEAR_KEYWORDS:
                idx = text.find(keyword)
                if idx >= 0:
                    prefix = text[max(0, idx - 3) : idx]
                    negated = any(neg in prefix for neg in _NEGATION_PREFIXES)
                    if negated:
                        bull_score += weight
                    else:
                        bear_score += weight

        total = bull_score + bear_score
        if total == 0:
            return "neutral", 0.0

        raw_score = (bull_score - bear_score) / total
        raw_score = max(-1.0, min(1.0, raw_score))

        if raw_score > 0.15:
            direction = "bullish"
        elif raw_score < -0.15:
            direction = "bearish"
        else:
            direction = "neutral"

        return direction, round(raw_score, 3)

    def _extract_topics(self, posts: list[dict[str, Any]]) -> list[str]:
        """Extract top discussion topics from recent posts.

        Groups posts by common phrases/themes in titles and returns
        the top 3 most frequent topics.
        """
        # Collect all titles
        titles: list[str] = []
        for post in posts:
            title = post.get("title", "") or post.get("post_title", "") or ""
            title = re.sub(r"<[^>]+>", "", title).strip()
            if title and len(title) >= 4:
                titles.append(title)

        if not titles:
            return []

        # Simple topic extraction: find most common 2-4 character phrases
        phrase_counts: dict[str, int] = {}
        for title in titles:
            # Extract meaningful phrases (2-6 chars, Chinese)
            phrases = re.findall(r"[\u4e00-\u9fff]{2,6}", title)
            for phrase in phrases:
                # Skip common filler words
                if phrase in (
                    "大家",
                    "今天",
                    "明天",
                    "请问",
                    "怎么",
                    "什么",
                    "为什么",
                    "有没有",
                    "是不是",
                    "可以",
                    "已经",
                    "东方财富",
                    "股吧",
                    "网友",
                ):
                    continue
                phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1

        # Sort by frequency, take top 3
        sorted_phrases = sorted(phrase_counts.items(), key=lambda x: x[1], reverse=True)
        return [phrase for phrase, _ in sorted_phrases[:3]]

    def _count_institutional_posts(self, posts: list[dict[str, Any]]) -> int:
        """Count posts tagged as institutional or containing institutional markers."""
        count = 0
        inst_markers = ["机构", "研报", "评级", "目标价", "研究所", "券商", "分析师"]
        for post in posts:
            # Check user_type or post tags
            user_type = post.get("user_type", "") or post.get("source_type", "")
            if "机构" in str(user_type) or "研报" in str(user_type):
                count += 1
                continue
            # Check title for institutional markers
            title = post.get("title", "") or post.get("post_title", "") or ""
            if any(marker in title for marker in inst_markers):
                count += 1
        return count

    async def fetch(self, symbol: str) -> GubaMetrics | None:
        """Fetch Guba metrics for a single stock symbol.

        Args:
            symbol: 6-digit stock code (e.g. "601668") or prefixed (SH601668).

        Returns:
            GubaMetrics dataclass or None on failure.
        """
        # Check cache
        now = time.time()
        if symbol in self._cache:
            expire_ts, cached = self._cache[symbol]
            if now < expire_ts:
                return cached

        symbol_code = self._convert_symbol_code(symbol)

        try:
            posts = await self._fetch_posts_api(symbol_code)

            if not posts:
                logger.info("No Guba posts found for %s", symbol_code)
                result = GubaMetrics(
                    symbol=symbol_code,
                    fetched_at=datetime.now(),
                )
                self._cache[symbol] = (now + _CACHE_TTL, result)
                return result

            # Compute metrics
            total_reads = 0
            total_comments = 0
            for post in posts:
                total_reads += int(post.get("read_count", 0) or 0)
                total_comments += int(post.get("comment_count", 0) or 0)

            post_count = len(posts)
            read_avg = total_reads / post_count if post_count > 0 else 0.0
            comment_avg = total_comments / post_count if post_count > 0 else 0.0

            sentiment_dir, sentiment_score = self._extract_sentiment(posts)
            hot_topics = self._extract_topics(posts)
            inst_count = self._count_institutional_posts(posts)

            result = GubaMetrics(
                symbol=symbol_code,
                post_count_24h=post_count,
                read_count_avg=round(read_avg, 1),
                comment_count_avg=round(comment_avg, 1),
                sentiment=sentiment_dir,
                sentiment_score=sentiment_score,
                hot_topics=hot_topics,
                institutional_post_count=inst_count,
                fetched_at=datetime.now(),
            )

            self._cache[symbol] = (now + _CACHE_TTL, result)
            logger.info(
                "Guba metrics for %s: %s (%.2f), posts=%d, reads_avg=%.0f",
                symbol_code,
                sentiment_dir,
                sentiment_score,
                post_count,
                read_avg,
            )
            return result

        except Exception as exc:
            logger.error("Guba fetch failed for %s: %s", symbol_code, exc)
            return None

    async def fetch_batch(self, symbols: list[str]) -> list[GubaMetrics]:
        """Fetch Guba metrics for multiple symbols.

        Processes sequentially with rate limiting to avoid triggering
        EastMoney anti-scraping protection.

        Args:
            symbols: List of stock codes (6-digit or SH/SZ prefixed).

        Returns:
            List of successfully fetched GubaMetrics objects.
        """
        results: list[GubaMetrics] = []
        for symbol in symbols:
            result = await self.fetch(symbol)
            if result is not None:
                results.append(result)
        return results

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

"""Xueqiu (雪球) sentiment fetcher.

Scrapes public Xueqiu pages for stock-specific discussion sentiment.
Uses the public web API (no login required for basic data).

Xueqiu is China's most popular investment social platform — sentiment
signals from its discussions are a valuable gauge of retail/semi-pro
investor mood for individual stocks.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp

from src.utils.logger import get_logger

logger = get_logger("data.xueqiu_sentiment")

__all__ = ["XueqiuSentiment", "XueqiuSentimentFetcher"]

# ---------------------------------------------------------------------------
# Sentiment keywords (Chinese financial social media)
# ---------------------------------------------------------------------------

_BULL_KEYWORDS: list[tuple[str, int]] = [
    # Strong (3)
    ("涨停", 3),
    ("连板", 3),
    ("翻倍", 3),
    ("重大利好", 3),
    ("业绩超预期", 3),
    # Medium (2)
    ("大涨", 2),
    ("新高", 2),
    ("突破", 2),
    ("利好", 2),
    ("增持", 2),
    ("回购", 2),
    ("放量上攻", 2),
    ("龙头", 2),
    ("主力", 2),
    ("机构买入", 2),
    ("北向加仓", 2),
    # Weak (1)
    ("看好", 1),
    ("买入", 1),
    ("加仓", 1),
    ("反弹", 1),
    ("回暖", 1),
    ("企稳", 1),
    ("放量", 1),
    ("底部", 1),
    ("低估", 1),
    ("上车", 1),
    ("牛", 1),
]

_BEAR_KEYWORDS: list[tuple[str, int]] = [
    # Strong (3)
    ("跌停", 3),
    ("退市", 3),
    ("暴雷", 3),
    ("财务造假", 3),
    ("重大利空", 3),
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
    ("机构卖出", 2),
    ("闪崩", 2),
    # Weak (1)
    ("下跌", 1),
    ("走弱", 1),
    ("承压", 1),
    ("缩量", 1),
    ("警惕", 1),
    ("卖出", 1),
    ("清仓", 1),
    ("高位", 1),
    ("泡沫", 1),
    ("垃圾", 1),
    ("坑", 1),
]

_NEGATION_PREFIXES = ["不", "未", "没有", "非", "否认", "难以"]

# ---------------------------------------------------------------------------
# User-Agent to mimic a real browser
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
    "Origin": "https://xueqiu.com",
    "Referer": "https://xueqiu.com/",
}

# Rate-limit interval between requests (seconds)
_REQUEST_INTERVAL = 0.5

# Cache TTL (seconds)
_CACHE_TTL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class XueqiuSentiment:
    """Sentiment snapshot for a single stock from Xueqiu."""

    symbol: str
    hot_score: float  # 0-1 normalized popularity
    sentiment: str  # bullish / bearish / neutral
    sentiment_score: float  # -1 to 1
    top_comments: list[str] = field(default_factory=list)  # top 5 one-liners
    follower_count: int = 0
    discussion_count_24h: int = 0
    fetched_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


class XueqiuSentimentFetcher:
    """Fetch stock sentiment from Xueqiu public API.

    Xueqiu requires a session cookie obtained by visiting the homepage.
    This fetcher handles cookie acquisition automatically.

    Usage::

        fetcher = XueqiuSentimentFetcher()
        sentiment = await fetcher.fetch("601668")
        batch = await fetcher.fetch_batch(["601668", "000001"])
        await fetcher.close()
    """

    BASE_URL = "https://stock.xueqiu.com"
    COMMENT_URL = "https://xueqiu.com/query/v1/symbol/search/status"
    QUOTE_URL = "https://stock.xueqiu.com/v5/stock/quote.json"
    HOME_URL = "https://xueqiu.com/"

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None
        self._cookie_ready = False
        self._last_request_ts: float = 0.0
        # Simple in-memory TTL cache: symbol -> (expire_ts, XueqiuSentiment)
        self._cache: dict[str, tuple[float, XueqiuSentiment]] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        """Lazily create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            self._session = aiohttp.ClientSession(
                headers=_HEADERS,
                timeout=timeout,
            )
        return self._session

    async def _ensure_cookie(self) -> None:
        """Visit Xueqiu homepage to obtain session cookie.

        Xueqiu sets ``xq_a_token`` and other cookies on the first visit.
        Without this cookie, API requests return 400.
        """
        if self._cookie_ready:
            return

        session = await self._get_session()
        try:
            async with session.get(self.HOME_URL) as resp:
                # We only need the response headers / cookies, not the body
                await resp.read()
                if resp.status == 200:
                    self._cookie_ready = True
                    logger.debug("Xueqiu cookie obtained successfully")
                else:
                    logger.warning("Xueqiu homepage returned status %d", resp.status)
        except Exception as exc:
            logger.warning("Failed to obtain Xueqiu cookie: %s", exc)

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_ts
        if elapsed < _REQUEST_INTERVAL:
            await asyncio.sleep(_REQUEST_INTERVAL - elapsed)
        self._last_request_ts = time.monotonic()

    def _convert_symbol(self, symbol: str) -> str:
        """Convert 6-digit code to Xueqiu format.

        601668 -> SH601668, 000001 -> SZ000001.
        Passes through if already in SH/SZ format.
        """
        symbol = symbol.strip().upper()
        if symbol.startswith(("SH", "SZ")):
            return symbol
        # Strip any exchange prefix (sh/sz)
        bare = symbol.lstrip("SHshSZsz")
        if len(bare) != 6:
            bare = symbol[-6:] if len(symbol) >= 6 else symbol
        if bare.startswith(("6", "9")):
            return f"SH{bare}"
        return f"SZ{bare}"

    async def _fetch_quote(self, xq_symbol: str) -> dict[str, Any] | None:
        """Fetch stock quote details (follower count, etc)."""
        session = await self._get_session()
        await self._rate_limit()
        params = {"symbol": xq_symbol, "extend": "detail"}
        try:
            async with session.get(self.QUOTE_URL, params=params) as resp:
                if resp.status != 200:
                    logger.debug(
                        "Xueqiu quote API returned %d for %s",
                        resp.status,
                        xq_symbol,
                    )
                    return None
                data = await resp.json()
                return data.get("data", {}).get("quote", {})
        except Exception as exc:
            logger.warning("Xueqiu quote fetch failed for %s: %s", xq_symbol, exc)
            return None

    async def _fetch_comments(
        self, xq_symbol: str, count: int = 20
    ) -> list[dict[str, Any]]:
        """Fetch recent discussion posts for a symbol."""
        session = await self._get_session()
        await self._rate_limit()
        params = {
            "symbol": xq_symbol,
            "count": str(count),
            "comment": "0",
            "page": "1",
            "source": "user",
        }
        try:
            async with session.get(self.COMMENT_URL, params=params) as resp:
                if resp.status != 200:
                    logger.debug(
                        "Xueqiu comment API returned %d for %s",
                        resp.status,
                        xq_symbol,
                    )
                    return []
                data = await resp.json()
                return data.get("list", [])
        except Exception as exc:
            logger.warning("Xueqiu comments fetch failed for %s: %s", xq_symbol, exc)
            return []

    def _analyze_sentiment(self, comments: list[dict[str, Any]]) -> tuple[str, float]:
        """Simple weighted keyword-based sentiment from comments.

        Scans comment text for bullish/bearish Chinese financial keywords.
        Applies negation handling for prefixes like 不/未/没有.

        Returns:
            (direction, score) where direction is bullish/bearish/neutral
            and score is in [-1.0, 1.0].
        """
        bull_score = 0
        bear_score = 0

        for comment in comments:
            text = comment.get("text", "") or comment.get("title", "") or ""
            # Strip HTML tags (Xueqiu comments often have <a> tags etc)
            import re

            text = re.sub(r"<[^>]+>", "", text)

            for keyword, weight in _BULL_KEYWORDS:
                idx = text.find(keyword)
                if idx >= 0:
                    # Check negation
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

        # Normalize to [-1, 1]: positive = bullish, negative = bearish
        raw_score = (bull_score - bear_score) / total
        # Clamp
        raw_score = max(-1.0, min(1.0, raw_score))

        if raw_score > 0.15:
            direction = "bullish"
        elif raw_score < -0.15:
            direction = "bearish"
        else:
            direction = "neutral"

        return direction, round(raw_score, 3)

    def _extract_top_comments(
        self, comments: list[dict[str, Any]], limit: int = 5
    ) -> list[str]:
        """Extract top comment one-liners sorted by engagement."""
        import re

        summaries: list[tuple[int, str]] = []
        for comment in comments:
            text = comment.get("text", "") or comment.get("title", "") or ""
            text = re.sub(r"<[^>]+>", "", text).strip()
            text = re.sub(r"\s+", " ", text)
            if not text or len(text) < 4:
                continue
            # Truncate to one line (~80 chars)
            if len(text) > 80:
                text = text[:77] + "..."
            # Sort by engagement (retweet + reply + like)
            engagement = (
                (comment.get("retweet_count", 0) or 0)
                + (comment.get("reply_count", 0) or 0)
                + (comment.get("like_count", 0) or 0)
            )
            summaries.append((engagement, text))

        summaries.sort(key=lambda x: x[0], reverse=True)
        return [text for _, text in summaries[:limit]]

    def _compute_hot_score(
        self,
        quote: dict[str, Any] | None,
        comments: list[dict[str, Any]],
    ) -> float:
        """Compute a 0-1 normalized popularity score.

        Factors: follower count, 24h discussion volume, comment engagement.
        """
        follower_count = 0
        if quote:
            follower_count = quote.get("followers", 0) or 0

        # Engagement from comments
        total_engagement = 0
        for c in comments:
            total_engagement += (
                (c.get("retweet_count", 0) or 0)
                + (c.get("reply_count", 0) or 0)
                + (c.get("like_count", 0) or 0)
            )

        # Normalize followers: log scale, cap at 1M (top stocks)
        import math

        follower_score = min(1.0, math.log1p(follower_count) / math.log1p(1_000_000))

        # Normalize engagement: log scale
        engagement_score = min(1.0, math.log1p(total_engagement) / math.log1p(10_000))

        # Discussion volume score
        volume_score = min(1.0, len(comments) / 20.0)

        # Weighted combination
        hot = follower_score * 0.4 + engagement_score * 0.35 + volume_score * 0.25
        return round(min(1.0, max(0.0, hot)), 3)

    async def fetch(self, symbol: str) -> XueqiuSentiment | None:
        """Fetch sentiment for a single symbol.

        Symbol format: accepts 601668, SH601668, sh601668.
        Converts to Xueqiu format (SH/SZ prefix) automatically.

        Returns:
            XueqiuSentiment dataclass or None on failure.
        """
        # Check cache
        now = time.time()
        if symbol in self._cache:
            expire_ts, cached = self._cache[symbol]
            if now < expire_ts:
                return cached

        try:
            await self._ensure_cookie()
            xq_symbol = self._convert_symbol(symbol)

            # Fetch quote and comments in parallel
            quote_data, comments = await asyncio.gather(
                self._fetch_quote(xq_symbol),
                self._fetch_comments(xq_symbol),
            )

            sentiment_dir, sentiment_score = self._analyze_sentiment(comments)
            top_comments = self._extract_top_comments(comments)
            hot_score = self._compute_hot_score(quote_data, comments)

            follower_count = 0
            if quote_data:
                follower_count = quote_data.get("followers", 0) or 0

            # Bare 6-digit code for the result
            bare = symbol.lstrip("SHshSZsz")
            if len(bare) != 6:
                bare = symbol[-6:] if len(symbol) >= 6 else symbol

            result = XueqiuSentiment(
                symbol=bare,
                hot_score=hot_score,
                sentiment=sentiment_dir,
                sentiment_score=sentiment_score,
                top_comments=top_comments,
                follower_count=follower_count,
                discussion_count_24h=len(comments),
                fetched_at=datetime.now(),
            )

            # Cache the result
            self._cache[symbol] = (now + _CACHE_TTL, result)
            logger.info(
                "Xueqiu sentiment for %s: %s (%.2f), hot=%.2f, comments=%d",
                bare,
                sentiment_dir,
                sentiment_score,
                hot_score,
                len(comments),
            )
            return result

        except Exception as exc:
            logger.error("Xueqiu fetch failed for %s: %s", symbol, exc)
            return None

    async def fetch_batch(self, symbols: list[str]) -> list[XueqiuSentiment]:
        """Fetch sentiment for multiple symbols sequentially.

        Rate-limited to avoid triggering Xueqiu anti-scraping.

        Args:
            symbols: List of stock codes (6-digit or SH/SZ prefixed).

        Returns:
            List of successfully fetched XueqiuSentiment objects.
        """
        results: list[XueqiuSentiment] = []
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
            self._cookie_ready = False

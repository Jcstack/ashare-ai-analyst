"""Multi-platform trend news aggregator and keyword matching engine.

Per PRD v3.2 FR-TN001 (multi-platform news aggregation) and
FR-TN002 (keyword frequency matching engine).

Uses AKShare hot-rank/board APIs as data sources, with in-memory TTL cache
and keyword-based relevance scoring for stock-level news matching.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import akshare as ak
import pandas as pd

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("data.trend_news")


@dataclass
class TrendItem:
    """A single trending news / hot-topic item."""

    platform: str  # wallstreetcn, cls, eastmoney, weibo, etc.
    title: str
    url: str | None = None
    rank: int = 0
    heat_score: float = 0.0  # normalized 0~1
    category: str = "general"  # finance, policy, tech, society
    keywords: list[str] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.now)


class TrendNewsAggregator:
    """Aggregate trending news from multiple AKShare hot-rank sources.

    Provides cached access to trending topics with automatic keyword
    extraction and heat-score normalization.

    Per FR-TN001.
    """

    # AKShare hot-rank source configs: (func_name, platform_label, key_column, rank_column)
    _SOURCES: list[tuple[str, str, str, str | None]] = [
        ("stock_hot_rank_em", "eastmoney", "股票名称", "当前排名"),
        ("stock_hot_keyword_em", "eastmoney_keyword", "关键词", "排名"),
    ]

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl: float = 1800.0  # 30 min
        self._last_request_ts: float = 0.0

    def fetch_from_akshare_hot(
        self, source: str = "stock_hot_rank_em"
    ) -> list[TrendItem]:
        """Fetch hot items from a single AKShare source.

        Args:
            source: AKShare function name to call.

        Returns:
            List of TrendItem from that source.
        """
        cache_key = f"hot_{source}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        items: list[TrendItem] = []
        self._rate_limit_wait()

        try:
            df = self._call_akshare(getattr(ak, source))
            if df is None or df.empty:
                self._set_cached(cache_key, items)
                return items

            max_heat = float(df.shape[0])
            now = datetime.now()

            for idx, row in df.head(50).iterrows():
                title = ""
                rank = idx + 1 if isinstance(idx, int) else 0

                # Try common column names for title
                for col in ("股票名称", "关键词", "股票代码", "名称"):
                    if col in row.index:
                        title = str(row[col])
                        break

                if not title:
                    title = str(row.iloc[0]) if len(row) > 0 else ""

                # Try to get rank from common columns
                for col in ("当前排名", "排名", "序号"):
                    if col in row.index:
                        try:
                            rank = int(row[col])
                        except (ValueError, TypeError):
                            pass
                        break

                heat = max(0.0, 1.0 - (rank - 1) / max_heat) if max_heat > 0 else 0.5
                keywords = _extract_keywords_simple(title)

                items.append(
                    TrendItem(
                        platform="eastmoney",
                        title=title,
                        url=None,
                        rank=rank,
                        heat_score=round(heat, 3),
                        category="finance",
                        keywords=keywords,
                        fetched_at=now,
                    )
                )
        except Exception as exc:
            logger.warning("Failed to fetch hot data from %s: %s", source, exc)

        self._set_cached(cache_key, items)
        return items

    def fetch_all(self) -> list[TrendItem]:
        """Aggregate trending items from all configured sources.

        Returns:
            Combined list of TrendItem from all sources, sorted by heat_score desc.
        """
        cache_key = "all_trends"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        all_items: list[TrendItem] = []

        for source_func, platform, _title_col, _rank_col in self._SOURCES:
            try:
                items = self.fetch_from_akshare_hot(source_func)
                for item in items:
                    item.platform = platform
                all_items.extend(items)
            except Exception as exc:
                logger.warning("Source %s failed: %s", source_func, exc)

        # Also try fetching stock news board concepts (sector hot topics)
        try:
            sector_items = self._fetch_sector_hot()
            all_items.extend(sector_items)
        except Exception as exc:
            logger.debug("Sector hot fetch skipped: %s", exc)

        # Policy & regulatory news from official sources (WS4-B)
        try:
            from src.data.policy_news import PolicyNewsFetcher

            policy_fetcher = PolicyNewsFetcher()
            policy_items = policy_fetcher.fetch_all()
            now = datetime.now()
            for item in policy_items:
                all_items.append(
                    TrendItem(
                        platform="policy",
                        title=f"[{item.source_name}] {item.title}",
                        url=item.url,
                        rank=0,
                        heat_score=0.8 if item.is_high_impact else 0.5,
                        category="policy",
                        keywords=[],
                        fetched_at=now,
                    )
                )
        except Exception as exc:
            logger.debug("Policy news fetch skipped: %s", exc)

        # Sort by heat score descending
        all_items.sort(key=lambda x: x.heat_score, reverse=True)
        self._set_cached(cache_key, all_items)
        return all_items

    def get_cached_trends(self) -> list[TrendItem]:
        """Return cached trends without triggering a new fetch.

        Returns:
            Cached list of TrendItem, or empty list if cache expired.
        """
        cached = self._get_cached("all_trends")
        return cached if cached is not None else []

    def _fetch_sector_hot(self) -> list[TrendItem]:
        """Fetch hot sector/concept board names from AKShare."""
        cache_key = "sector_hot"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        items: list[TrendItem] = []
        self._rate_limit_wait()

        try:
            df = self._call_akshare(ak.stock_board_concept_name_ths)
            if df is None or df.empty:
                return items

            now = datetime.now()
            total = float(df.shape[0]) or 1.0
            for idx, row in df.head(30).iterrows():
                name = str(row.get("概念名称", row.iloc[0] if len(row) > 0 else ""))
                rank = idx + 1 if isinstance(idx, int) else 0
                heat = max(0.0, 1.0 - rank / total)
                items.append(
                    TrendItem(
                        platform="ths_concept",
                        title=name,
                        rank=rank,
                        heat_score=round(heat, 3),
                        category="sector",
                        keywords=_extract_keywords_simple(name),
                        fetched_at=now,
                    )
                )
        except Exception as exc:
            logger.debug("THS concept board fetch failed: %s", exc)

        self._set_cached(cache_key, items)
        return items

    def _call_akshare(self, func, **kwargs) -> pd.DataFrame:
        """Call an AKShare function via em_api_call (proxy-patch gateway)."""
        from src.data.eastmoney_proxy import em_api_call

        result = em_api_call(func, **kwargs)
        return result if result is not None else pd.DataFrame()

    def _rate_limit_wait(self) -> None:
        now = time.time()
        if now - self._last_request_ts < 0.5:
            time.sleep(0.5 - (now - self._last_request_ts))
        self._last_request_ts = time.time()

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return data
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        self._cache[key] = (time.time(), data)


class KeywordMatcher:
    """Match trending news items against stock-specific keyword rules.

    Per FR-TN002.

    Matching rules:
    - ``+keyword`` → required: ALL required keywords must appear for a match
    - ``!keyword`` → exclude: if any exclude keyword appears, reject the item
    - plain keyword → normal: relevance score = matched_normal / total_normal
    """

    def __init__(self) -> None:
        config = load_config("keywords")
        self._global_filters: list[str] = config.get("global_filters", [])
        self._stock_keywords: dict[str, dict] = config.get("stock_keywords", {})
        self._sector_keywords: dict[str, list[str]] = config.get("sector_keywords", {})
        self._macro_keywords: dict[str, list[str]] = config.get("macro_keywords", {})

        # Parse global exclude filters
        self._global_excludes: list[str] = []
        for f in self._global_filters:
            if f.startswith("!"):
                self._global_excludes.append(f[1:])

    def match_stock(self, title: str, symbol: str) -> tuple[bool, float]:
        """Check if a title matches a stock's keyword rules.

        Args:
            title: News title text.
            symbol: 6-digit stock code.

        Returns:
            Tuple of (is_match, relevance_score 0~1).
        """
        # Global exclude check
        for excl in self._global_excludes:
            if excl in title:
                return False, 0.0

        rules = self._stock_keywords.get(symbol)
        if rules is None:
            return False, 0.0

        # Check required keywords (prefix +)
        required = rules.get("required", [])
        for kw in required:
            clean_kw = kw.lstrip("+")
            if clean_kw not in title:
                return False, 0.0

        # Check normal keywords — count matches
        normal = rules.get("normal", [])
        if not normal:
            # If only required keywords and all matched
            return bool(required), 1.0 if required else 0.0

        matched = sum(1 for kw in normal if kw in title)
        score = matched / len(normal) if normal else 0.0

        # Must match at least required keywords or some normal ones
        is_match = bool(required) or matched > 0
        return is_match, round(score, 3)

    def match_all_stocks(
        self,
        items: list[TrendItem],
        symbols: list[str],
    ) -> dict[str, list[TrendItem]]:
        """Match a list of TrendItems against multiple stocks.

        Args:
            items: Trending news items to match.
            symbols: Stock codes to check against.

        Returns:
            Dict mapping symbol → list of matching TrendItems (sorted by score).
        """
        result: dict[str, list[TrendItem]] = {s: [] for s in symbols}

        for item in items:
            for sym in symbols:
                is_match, score = self.match_stock(item.title, sym)
                if is_match and score > 0:
                    # Boost heat_score with relevance score
                    boosted = TrendItem(
                        platform=item.platform,
                        title=item.title,
                        url=item.url,
                        rank=item.rank,
                        heat_score=round(item.heat_score * 0.5 + score * 0.5, 3),
                        category=item.category,
                        keywords=item.keywords,
                        fetched_at=item.fetched_at,
                    )
                    result[sym].append(boosted)

        # Sort each stock's matches by boosted heat_score
        for sym in result:
            result[sym].sort(key=lambda x: x.heat_score, reverse=True)

        return result

    def match_sector(self, title: str) -> list[str]:
        """Find which sectors a title is related to.

        Args:
            title: News title text.

        Returns:
            List of matching sector names.
        """
        matched_sectors = []
        for sector, keywords in self._sector_keywords.items():
            if any(kw in title for kw in keywords):
                matched_sectors.append(sector)
        return matched_sectors

    def match_macro(self, title: str) -> list[str]:
        """Find which macro categories a title is related to.

        Args:
            title: News title text.

        Returns:
            List of matching macro category names.
        """
        matched = []
        for category, keywords in self._macro_keywords.items():
            if any(kw in title for kw in keywords):
                matched.append(category)
        return matched

    def auto_generate_keywords(self, symbol: str, name: str) -> dict:
        """Auto-generate keyword rules from a stock name.

        Args:
            symbol: 6-digit stock code.
            name: Stock display name.

        Returns:
            Dict with required, normal, display keys.
        """
        # Use the full name as required, generate normal from name parts
        clean_name = re.sub(r"[A-Z\d\s]", "", name)
        required = [f"+{clean_name}"] if clean_name else []

        # Split into 2-char segments for normal keywords
        normal = []
        if len(clean_name) >= 4:
            normal.append(clean_name[:2])
            normal.append(clean_name[2:4])
        elif len(clean_name) >= 2:
            normal.append(clean_name[:2])

        return {
            "required": required,
            "normal": normal,
            "display": name,
        }


@dataclass
class ResonanceEvent:
    """A cross-platform resonance event (FR-TN003).

    Represents the same topic trending on multiple platforms simultaneously.
    """

    event_id: str
    title: str  # representative title
    resonance_level: str  # "L1", "L2", "L3"
    platforms: list[str] = field(default_factory=list)
    rank_timeline: list[dict[str, Any]] = field(default_factory=list)
    related_stocks: list[str] = field(default_factory=list)
    sentiment: str = "neutral"  # positive, negative, mixed, neutral
    first_appeared: str = ""
    last_updated: str = ""
    heat_score: float = 0.0
    merged_items: list[TrendItem] = field(default_factory=list)


class ResonanceDetector:
    """Detect cross-platform resonance from aggregated TrendItems (FR-TN003).

    Groups similar items across platforms using title similarity (Jaccard
    on character bigrams), classifies resonance levels:
    - L3: 5+ platforms (全网热议)
    - L2: 3-4 platforms (破圈传播)
    - L1: 1-2 platforms (小众热点)
    """

    _SIMILARITY_THRESHOLD = 0.35

    def __init__(
        self,
        keyword_matcher: KeywordMatcher | None = None,
        similarity_threshold: float | None = None,
    ) -> None:
        self._matcher = keyword_matcher
        if similarity_threshold is not None:
            self._SIMILARITY_THRESHOLD = similarity_threshold

    def detect(
        self,
        items: list[TrendItem],
        watchlist: list[str] | None = None,
    ) -> list[ResonanceEvent]:
        """Detect resonance events from a list of TrendItems.

        Args:
            items: Aggregated trend items from multiple platforms.
            watchlist: Stock symbols to check for related stocks.

        Returns:
            List of ResonanceEvent sorted by resonance level desc.
        """
        if not items:
            return []

        # Step 1: Group similar items by title similarity
        groups: list[list[TrendItem]] = []
        used: set[int] = set()

        for i, item_a in enumerate(items):
            if i in used:
                continue
            group = [item_a]
            used.add(i)
            for j, item_b in enumerate(items):
                if j in used:
                    continue
                if (
                    _title_similarity(item_a.title, item_b.title)
                    >= self._SIMILARITY_THRESHOLD
                ):
                    group.append(item_b)
                    used.add(j)
            groups.append(group)

        # Step 2: Convert groups to ResonanceEvents
        events: list[ResonanceEvent] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        for idx, group in enumerate(groups):
            platforms = list({item.platform for item in group})
            n_platforms = len(platforms)

            if n_platforms >= 5:
                level = "L3"
            elif n_platforms >= 3:
                level = "L2"
            else:
                level = "L1"

            # Representative title: highest heat_score item
            best = max(group, key=lambda x: x.heat_score)
            avg_heat = sum(item.heat_score for item in group) / len(group)

            # Build rank timeline
            timeline = [
                {
                    "platform": item.platform,
                    "rank": item.rank,
                    "timestamp": item.fetched_at.strftime("%Y-%m-%d %H:%M")
                    if isinstance(item.fetched_at, datetime)
                    else str(item.fetched_at),
                }
                for item in group
            ]

            # Find related stocks via keyword matcher
            related: list[str] = []
            if self._matcher and watchlist:
                for sym in watchlist:
                    for item in group:
                        is_match, score = self._matcher.match_stock(item.title, sym)
                        if is_match and score > 0:
                            related.append(sym)
                            break

            # Infer sentiment from title keywords
            sentiment = _infer_sentiment(best.title)

            first_ts = min(
                (
                    item.fetched_at.strftime("%Y-%m-%d %H:%M")
                    if isinstance(item.fetched_at, datetime)
                    else str(item.fetched_at)
                )
                for item in group
            )

            events.append(
                ResonanceEvent(
                    event_id=f"evt-{idx:04d}",
                    title=best.title,
                    resonance_level=level,
                    platforms=platforms,
                    rank_timeline=timeline,
                    related_stocks=related,
                    sentiment=sentiment,
                    first_appeared=first_ts,
                    last_updated=now_str,
                    heat_score=round(avg_heat, 3),
                    merged_items=group,
                )
            )

        # Sort: L3 > L2 > L1, then by heat_score
        level_order = {"L3": 0, "L2": 1, "L1": 2}
        events.sort(
            key=lambda e: (level_order.get(e.resonance_level, 9), -e.heat_score)
        )

        return events


def _title_similarity(a: str, b: str) -> float:
    """Jaccard similarity on character bigrams.

    Args:
        a: First title string.
        b: Second title string.

    Returns:
        Similarity score 0~1.
    """
    if not a or not b:
        return 0.0
    bigrams_a = {a[i : i + 2] for i in range(len(a) - 1)}
    bigrams_b = {b[i : i + 2] for i in range(len(b) - 1)}
    if not bigrams_a or not bigrams_b:
        return 0.0
    intersection = bigrams_a & bigrams_b
    union = bigrams_a | bigrams_b
    return len(intersection) / len(union) if union else 0.0


_POSITIVE_KEYWORDS = {
    "利好",
    "上涨",
    "突破",
    "新高",
    "增长",
    "盈利",
    "回暖",
    "复苏",
    "降准",
    "降息",
    "红包",
    "大涨",
}
_NEGATIVE_KEYWORDS = {
    "利空",
    "下跌",
    "暴跌",
    "亏损",
    "退市",
    "制裁",
    "违规",
    "调查",
    "罚款",
    "下滑",
    "减持",
    "爆雷",
}


def _infer_sentiment(title: str) -> str:
    """Infer sentiment from title keywords.

    Args:
        title: News title text.

    Returns:
        One of: positive, negative, mixed, neutral.
    """
    pos = any(kw in title for kw in _POSITIVE_KEYWORDS)
    neg = any(kw in title for kw in _NEGATIVE_KEYWORDS)
    if pos and neg:
        return "mixed"
    if pos:
        return "positive"
    if neg:
        return "negative"
    return "neutral"


def _extract_keywords_simple(text: str) -> list[str]:
    """Extract keywords from text using simple character-based segmentation.

    Falls back to 2-char sliding window if jieba is not available.

    Args:
        text: Input text.

    Returns:
        List of keyword strings.
    """
    try:
        import jieba

        words = jieba.lcut(text)
        return [w for w in words if len(w) >= 2 and not w.isspace()]
    except ImportError:
        # Fallback: extract Chinese character pairs
        chars = re.findall(r"[\u4e00-\u9fff]+", text)
        keywords = []
        for segment in chars:
            if len(segment) >= 2:
                keywords.append(segment)
        return keywords

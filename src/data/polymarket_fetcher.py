"""Polymarket prediction market data fetcher.

Fetches geopolitical risk signals from Polymarket — the world's largest
prediction market. Money-weighted probabilities provide superior risk
pricing compared to news sentiment for events like Fed rate decisions,
US-China trade escalation, and Taiwan strait tensions.

No API key required. Public Gamma API with ~2 req/sec rate limit.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("data.polymarket_fetcher")

__all__ = [
    "PredictionMarket",
    "GeopoliticalRiskSignals",
    "PolymarketFetcher",
]


@dataclass
class PredictionMarket:
    """A single prediction market contract."""

    market_id: str
    question: str
    category: str
    probability: float  # 0-1, primary outcome probability
    outcomes: list[str]  # e.g. ["Yes", "No"]
    outcome_prices: list[float]  # e.g. [0.72, 0.28]
    volume_24h: float  # USD
    total_volume: float  # USD
    liquidity: float  # USD
    end_date: str | None
    slug: str
    fetched_at: datetime = field(default_factory=datetime.now)


@dataclass
class GeopoliticalRiskSignals:
    """Aggregated geopolitical risk signals from prediction markets."""

    fed_rate_cut_prob: float | None = None  # P(rate cut next meeting)
    us_china_trade_risk: float | None = None  # P(new tariffs/sanctions)
    taiwan_conflict_risk: float | None = None  # P(military escalation)
    recession_prob: float | None = None  # P(US recession this year)

    top_markets: list[PredictionMarket] = field(default_factory=list)

    overall_risk_score: float = 0.0

    fetched_at: datetime = field(default_factory=datetime.now)

    def to_snapshot_text(self) -> str:
        """Serialize for MarketSnapshot injection."""
        parts = []
        if self.fed_rate_cut_prob is not None:
            parts.append(f"降息概率:{self.fed_rate_cut_prob:.0%}")
        if self.us_china_trade_risk is not None:
            parts.append(f"贸易风险:{self.us_china_trade_risk:.0%}")
        if self.taiwan_conflict_risk is not None:
            parts.append(f"台海风险:{self.taiwan_conflict_risk:.0%}")
        if self.recession_prob is not None:
            parts.append(f"衰退概率:{self.recession_prob:.0%}")
        parts.append(f"地缘风险评分:{self.overall_risk_score:.2f}")
        return " | ".join(parts)


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert value to float, returning *default* for None/empty/errors."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


class PolymarketFetcher:
    """Fetch prediction market data from Polymarket.

    No API key required. Rate limit: ~2 req/sec (we self-throttle to 0.5s).
    """

    BASE_URL = "https://gamma-api.polymarket.com"

    # Keywords to search for A-share relevant markets
    CHINA_RELEVANT_SEARCHES = [
        "china",
        "taiwan",
        "fed rate",
        "tariff",
        "recession",
        "trade war",
    ]

    # Slug fragments for categorizing markets into risk buckets
    KNOWN_SLUGS: dict[str, list[str]] = {
        "fed_rate_cut": ["fed-cut", "federal-reserve", "rate-cut", "fed-rate"],
        "us_china": ["china-tariff", "us-china", "trade-war", "tariff"],
        "taiwan": ["taiwan", "china-taiwan"],
        "recession": ["recession", "us-recession"],
    }

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._session: Any = None  # lazy aiohttp.ClientSession
        self._last_request_ts: float = 0.0
        # In-memory cache: key → (monotonic_ts, value)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl: float = 300.0  # 5 minutes
        logger.info("PolymarketFetcher initialized (timeout=%.1fs)", timeout)

    # ------------------------------------------------------------------
    # Cache helpers (same pattern as MacroFlowFetcher / GlobalMarketFetcher)
    # ------------------------------------------------------------------

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.monotonic() - ts < self._cache_ttl:
                return val
        return None

    def _set_cached(self, key: str, val: Any) -> None:
        self._cache[key] = (time.monotonic(), val)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> Any:
        """Lazy-create aiohttp session."""
        if self._session is None or self._session.closed:
            import aiohttp

            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout),
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; AShareBot/1.0)",
                    "Accept": "application/json",
                },
            )
        return self._session

    async def _rate_limit_wait(self) -> None:
        """Self-throttle to ~2 req/sec."""
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < 0.5:
            await asyncio.sleep(0.5 - elapsed)
        self._last_request_ts = time.monotonic()

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET request returning parsed JSON, or None on failure."""
        session = await self._ensure_session()
        url = f"{self.BASE_URL}{path}"
        await self._rate_limit_wait()
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning("Polymarket API %s returned %d", path, resp.status)
                    return None
                return await resp.json()
        except Exception as exc:
            logger.warning("Polymarket API request failed (%s): %s", path, exc)
            return None

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Market parsing
    # ------------------------------------------------------------------

    def _parse_market(self, raw: dict[str, Any]) -> PredictionMarket | None:
        """Parse a single market dict from the Gamma API."""
        try:
            outcomes = raw.get("outcomes") or []
            raw_prices = raw.get("outcomePrices") or []

            # Parse outcome prices (strings → floats)
            outcome_prices = [_safe_float(p) for p in raw_prices]

            # Primary probability: first outcome ("Yes") price
            probability = outcome_prices[0] if outcome_prices else 0.0

            return PredictionMarket(
                market_id=raw.get("id", ""),
                question=raw.get("question", ""),
                category=raw.get("category", ""),
                probability=probability,
                outcomes=outcomes,
                outcome_prices=outcome_prices,
                volume_24h=_safe_float(raw.get("volume24hr")),
                total_volume=_safe_float(raw.get("volume")),
                liquidity=_safe_float(raw.get("liquidity")),
                end_date=raw.get("endDate"),
                slug=raw.get("slug", ""),
                fetched_at=datetime.now(),
            )
        except Exception as exc:
            logger.debug("Failed to parse market: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_markets(
        self,
        limit: int = 50,
        category: str | None = None,
        slug_contains: str | None = None,
    ) -> list[PredictionMarket]:
        """Fetch active prediction markets.

        Args:
            limit: Max markets to return.
            category: Filter by category tag (e.g. "politics").
            slug_contains: Filter by slug substring (e.g. "china").

        Returns:
            List of parsed PredictionMarket objects.
        """
        params: dict[str, Any] = {
            "closed": "false",
            "limit": limit,
            "order": "volume24hr",
            "ascending": "false",
        }
        if category:
            params["tag"] = category
        if slug_contains:
            params["slug_contains"] = slug_contains

        data = await self._get_json("/markets", params=params)
        if not data or not isinstance(data, list):
            return []

        markets: list[PredictionMarket] = []
        for item in data:
            m = self._parse_market(item)
            if m is not None:
                markets.append(m)
        return markets

    async def search_markets(self, query: str) -> list[PredictionMarket]:
        """Search markets by keyword via slug_contains.

        Args:
            query: Search keyword (matched against market slug).

        Returns:
            List of matching PredictionMarket objects.
        """
        return await self.fetch_markets(limit=20, slug_contains=query)

    async def get_geopolitical_signals(self) -> GeopoliticalRiskSignals:
        """Build aggregated geopolitical risk signals.

        Searches for A-share relevant prediction markets and
        extracts probability-based risk signals. Results are cached
        for 5 minutes.

        Returns:
            GeopoliticalRiskSignals with best-effort probability fills.
        """
        cached = self._get_cached("geo_signals")
        if cached is not None:
            return cached

        logger.info("Fetching geopolitical risk signals from Polymarket")

        # Collect markets from all relevant searches
        all_markets: dict[str, PredictionMarket] = {}  # slug → market (dedup)
        for query in self.CHINA_RELEVANT_SEARCHES:
            try:
                results = await self.search_markets(query)
                for m in results:
                    if m.slug and m.slug not in all_markets:
                        all_markets[m.slug] = m
            except Exception as exc:
                logger.warning("Search for '%s' failed: %s", query, exc)

        markets = list(all_markets.values())
        logger.info(
            "Found %d unique markets across %d searches",
            len(markets),
            len(self.CHINA_RELEVANT_SEARCHES),
        )

        # Categorize markets into risk buckets
        signals = GeopoliticalRiskSignals(fetched_at=datetime.now())

        signals.fed_rate_cut_prob = self._extract_best_prob(
            markets, self.KNOWN_SLUGS["fed_rate_cut"]
        )
        signals.us_china_trade_risk = self._extract_best_prob(
            markets, self.KNOWN_SLUGS["us_china"]
        )
        signals.taiwan_conflict_risk = self._extract_best_prob(
            markets, self.KNOWN_SLUGS["taiwan"]
        )
        signals.recession_prob = self._extract_best_prob(
            markets, self.KNOWN_SLUGS["recession"]
        )

        # Top 5 markets by 24h volume (relevant to A-share)
        sorted_by_vol = sorted(markets, key=lambda m: m.volume_24h, reverse=True)
        signals.top_markets = sorted_by_vol[:5]

        # Composite risk score
        signals.overall_risk_score = self._compute_risk_score(signals)

        self._set_cached("geo_signals", signals)
        return signals

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_best_prob(
        self,
        markets: list[PredictionMarket],
        slug_fragments: list[str],
    ) -> float | None:
        """Find the best-matching market for a risk category.

        Matches markets whose slug contains any of the given fragments,
        then returns the probability of the highest-volume match.

        Returns:
            Probability (0-1) of the best match, or None if no match.
        """
        matches: list[PredictionMarket] = []
        for m in markets:
            slug_lower = m.slug.lower()
            question_lower = m.question.lower()
            for frag in slug_fragments:
                if frag in slug_lower or frag in question_lower:
                    matches.append(m)
                    break

        if not matches:
            return None

        # Pick highest-volume match (most liquid = most reliable price)
        best = max(matches, key=lambda m: m.volume_24h)
        logger.debug(
            "Best match for %s: '%s' (prob=%.2f, vol24h=$%.0f)",
            slug_fragments[0],
            best.question[:60],
            best.probability,
            best.volume_24h,
        )
        return best.probability

    def _compute_risk_score(self, signals: GeopoliticalRiskSignals) -> float:
        """Compute composite geopolitical risk score (0-1).

        Weighted average of available probabilities:
        - Taiwan conflict risk: 0.3 weight (most direct A-share impact)
        - US-China trade risk: 0.3 weight
        - Fed policy uncertainty: 0.2 weight (rate cut → lower risk)
        - Recession probability: 0.2 weight
        """
        weights: list[tuple[float | None, float]] = [
            (signals.taiwan_conflict_risk, 0.3),
            (signals.us_china_trade_risk, 0.3),
            # Fed rate cut is inverse risk: high cut prob = dovish = lower risk
            # So we invert: risk = 1 - cut_prob (higher if no cut expected)
            (
                1.0 - signals.fed_rate_cut_prob
                if signals.fed_rate_cut_prob is not None
                else None,
                0.2,
            ),
            (signals.recession_prob, 0.2),
        ]

        total_weight = 0.0
        weighted_sum = 0.0
        for prob, weight in weights:
            if prob is not None:
                weighted_sum += prob * weight
                total_weight += weight

        if total_weight == 0.0:
            return 0.0

        return round(weighted_sum / total_weight, 4)

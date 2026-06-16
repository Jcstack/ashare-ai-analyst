"""Association Profile Builder — unified stock association model.

Per PRD v3.4 FR-DA001: Aggregates concept boards, cross-market peers,
keyword themes, and industry profiles into a single AssociationProfile
that drives targeted holiday research data collection and analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("analysis.association_graph")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ConceptLink:
    """A concept board linked to the stock."""

    code: str = ""
    name: str = ""
    pct_change: float = 0.0
    rank_pct: float | None = None  # percentile in board (0=best)


@dataclass
class PeerLink:
    """A cross-market peer."""

    symbol: str = ""
    market: str = ""  # us | hk | commodity
    tags: list[str] = field(default_factory=list)


@dataclass
class IndustryProfile:
    """Industry-specific research dimensions from config."""

    tag: str = ""
    display: str = ""
    key_metrics: list[str] = field(default_factory=list)
    seasonal_events: dict[str, dict[str, Any]] = field(default_factory=dict)
    value_chain: list[str] = field(default_factory=list)
    research_hints: dict[str, str] = field(default_factory=dict)
    concept_keywords: list[str] = field(default_factory=list)


@dataclass
class AssociationProfile:
    """Unified multi-dimensional stock association profile."""

    symbol: str = ""
    industry: str = ""
    concepts: list[ConceptLink] = field(default_factory=list)
    resonance_level: str = "none"  # none | weak | moderate | strong
    cross_market_peers: list[PeerLink] = field(default_factory=list)
    cross_market_tags: list[str] = field(default_factory=list)
    keyword_themes: list[str] = field(default_factory=list)
    industry_profile: IndustryProfile | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API responses and LLM prompts."""
        return {
            "symbol": self.symbol,
            "industry": self.industry,
            "concepts": [
                {
                    "code": c.code,
                    "name": c.name,
                    "pct_change": c.pct_change,
                    "rank_pct": c.rank_pct,
                }
                for c in self.concepts
            ],
            "resonance_level": self.resonance_level,
            "cross_market_peers": [
                {"symbol": p.symbol, "market": p.market, "tags": p.tags}
                for p in self.cross_market_peers
            ],
            "cross_market_tags": self.cross_market_tags,
            "keyword_themes": self.keyword_themes,
            "industry_profile": (
                {
                    "tag": self.industry_profile.tag,
                    "display": self.industry_profile.display,
                    "key_metrics": self.industry_profile.key_metrics,
                    "seasonal_events": self.industry_profile.seasonal_events,
                    "value_chain": self.industry_profile.value_chain,
                    "research_hints": self.industry_profile.research_hints,
                    "concept_keywords": self.industry_profile.concept_keywords,
                }
                if self.industry_profile
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class AssociationProfileBuilder:
    """Build a unified association profile for a stock.

    Aggregates data from:
    - ConceptAnalyzer (concept boards + resonance)
    - CrossMarketAnalyzer (peer mappings + tags)
    - keywords.yaml (sector/macro keyword themes)
    - industry_profiles.yaml (industry-specific research dimensions)

    All dependencies are constructor-injected.
    """

    def __init__(
        self,
        concept_analyzer: Any | None = None,
        cross_market_analyzer: Any | None = None,
    ) -> None:
        self._concept_analyzer = concept_analyzer
        self._cross_market_analyzer = cross_market_analyzer
        self._industry_profiles = self._load_industry_profiles()
        self._keyword_config = self._load_keyword_config()

    @staticmethod
    def _load_industry_profiles() -> dict[str, dict]:
        try:
            config = load_config("industry_profiles")
            return config.get("profiles", {})
        except FileNotFoundError:
            logger.warning("industry_profiles.yaml not found; using empty profiles")
            return {}

    @staticmethod
    def _load_keyword_config() -> dict:
        try:
            return load_config("keywords")
        except FileNotFoundError:
            logger.warning("keywords.yaml not found; using empty config")
            return {}

    def build_profile(self, symbol: str) -> AssociationProfile:
        """Build a complete association profile for a stock.

        Gracefully degrades if individual data sources fail.
        """
        profile = AssociationProfile(symbol=symbol)

        # 1. Concept boards + resonance
        self._fill_concepts(profile)

        # 2. Cross-market peers + tags
        self._fill_cross_market(profile)

        # 3. Keyword themes
        self._fill_keyword_themes(profile)

        # 4. Industry profile (resolved from tags)
        self._fill_industry_profile(profile)

        return profile

    def _fill_concepts(self, profile: AssociationProfile) -> None:
        """Fill concept board data from ConceptAnalyzer."""
        if self._concept_analyzer is None:
            return
        try:
            result = self._concept_analyzer.analyze_stock_concepts(profile.symbol)
            profile.industry = result.industry or ""
            profile.resonance_level = (
                result.resonance.level if result.resonance else "none"
            )
            for c in result.concepts:
                profile.concepts.append(
                    ConceptLink(
                        code=c.code,
                        name=c.name,
                        pct_change=c.pct_change,
                        rank_pct=c.stock_rank_pct,
                    )
                )
        except Exception as exc:
            logger.debug("Concept fill failed for %s: %s", profile.symbol, exc)

    def _fill_cross_market(self, profile: AssociationProfile) -> None:
        """Fill cross-market peer data from CrossMarketAnalyzer."""
        if self._cross_market_analyzer is None:
            return
        try:
            mapping = self._cross_market_analyzer.get_mapping(profile.symbol)
            tags = mapping.get("tags", [])
            profile.cross_market_tags = tags

            for sym in mapping.get("us_peers", []):
                profile.cross_market_peers.append(
                    PeerLink(symbol=sym, market="us", tags=tags)
                )
            for sym in mapping.get("hk_peers", []):
                profile.cross_market_peers.append(
                    PeerLink(symbol=sym, market="hk", tags=tags)
                )
            for sym in mapping.get("commodities", []):
                profile.cross_market_peers.append(
                    PeerLink(symbol=sym, market="commodity", tags=tags)
                )
        except Exception as exc:
            logger.debug("Cross-market fill failed for %s: %s", profile.symbol, exc)

    def _fill_keyword_themes(self, profile: AssociationProfile) -> None:
        """Fill keyword themes from keywords.yaml sector_keywords."""
        sector_kw = self._keyword_config.get("sector_keywords", {})
        tags = profile.cross_market_tags

        matched_themes: list[str] = []
        for tag in tags:
            if tag in sector_kw:
                matched_themes.append(tag)

        # Also check if stock has explicit stock_keywords entry
        stock_kw = self._keyword_config.get("stock_keywords", {})
        if profile.symbol in stock_kw:
            matched_themes.append("stock_specific")

        profile.keyword_themes = matched_themes

    def _fill_industry_profile(self, profile: AssociationProfile) -> None:
        """Resolve industry profile from tags → industry_profiles.yaml."""
        for tag in profile.cross_market_tags:
            if tag in self._industry_profiles:
                raw = self._industry_profiles[tag]
                profile.industry_profile = IndustryProfile(
                    tag=tag,
                    display=raw.get("display", ""),
                    key_metrics=raw.get("key_metrics", []),
                    seasonal_events=raw.get("seasonal_events", {}),
                    value_chain=raw.get("value_chain", []),
                    research_hints=raw.get("research_hints", {}),
                    concept_keywords=raw.get("concept_keywords", []),
                )
                return  # Use first matching profile

    def apply_overrides(
        self, profile: AssociationProfile, overrides: dict[str, Any]
    ) -> AssociationProfile:
        """Apply user overrides to an auto-generated profile.

        Args:
            profile: The auto-generated AssociationProfile.
            overrides: Override dict from ProfileOverrideService.

        Returns:
            The same profile instance, mutated in place for convenience.
        """
        if not overrides:
            return profile

        # 1. Industry override → replace tag + reload IndustryProfile
        industry_tag = overrides.get("industry_override")
        if industry_tag and industry_tag in self._industry_profiles:
            raw = self._industry_profiles[industry_tag]
            profile.industry_profile = IndustryProfile(
                tag=industry_tag,
                display=raw.get("display", ""),
                key_metrics=raw.get("key_metrics", []),
                seasonal_events=raw.get("seasonal_events", {}),
                value_chain=raw.get("value_chain", []),
                research_hints=raw.get("research_hints", {}),
                concept_keywords=raw.get("concept_keywords", []),
            )

        # 2. Concepts: remove then add
        removed_codes = set(overrides.get("removed_concept_codes", []))
        if removed_codes:
            profile.concepts = [
                c for c in profile.concepts if c.code not in removed_codes
            ]
        for added in overrides.get("added_concepts", []):
            profile.concepts.append(
                ConceptLink(
                    code=added.get("code", ""),
                    name=added.get("name", ""),
                )
            )

        # 3. Cross-market peers: remove then add
        removed_peers = set(overrides.get("removed_peer_symbols", []))
        if removed_peers:
            profile.cross_market_peers = [
                p for p in profile.cross_market_peers if p.symbol not in removed_peers
            ]
        for added in overrides.get("added_peers", []):
            profile.cross_market_peers.append(
                PeerLink(
                    symbol=added.get("symbol", ""),
                    market=added.get("market", "us"),
                    tags=added.get("tags", []),
                )
            )

        # 4. Keywords: remove then add
        removed_kw = set(overrides.get("removed_keywords", []))
        if removed_kw:
            profile.keyword_themes = [
                k for k in profile.keyword_themes if k not in removed_kw
            ]
        for kw in overrides.get("added_keywords", []):
            if kw not in profile.keyword_themes:
                profile.keyword_themes.append(kw)

        return profile

    def get_available_industries(self) -> list[dict[str, str]]:
        """Return list of available industry profiles for UI dropdown."""
        return [
            {"tag": tag, "display": raw.get("display", tag)}
            for tag, raw in self._industry_profiles.items()
        ]

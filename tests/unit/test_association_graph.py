"""Tests for AssociationProfileBuilder.

Covers profile building, concept filling, cross-market peers, keyword themes,
industry profile resolution, graceful degradation, and to_dict serialization.
"""

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from src.analysis.association_graph import (
    AssociationProfile,
    AssociationProfileBuilder,
    ConceptLink,
    IndustryProfile,
    PeerLink,
)


# ── Helpers ──────────────────────────────────────────────────────────


@dataclass
class _FakeConceptResult:
    industry: str = "影视传媒"
    concepts: list = field(default_factory=list)
    resonance: object = None


@dataclass
class _FakeConcept:
    code: str = "BK1001"
    name: str = "影视院线"
    pct_change: float = 2.5
    stock_rank_pct: float = 0.15


@dataclass
class _FakeResonance:
    level: str = "moderate"


# ── Fixtures ─────────────────────────────────────────────────────────

MOCK_INDUSTRY_PROFILES = {
    "entertainment": {
        "display": "影视传媒",
        "key_metrics": ["票房", "排片占比"],
        "seasonal_events": {
            "spring_festival": {
                "name": "春节档",
                "months": [1, 2],
                "importance": "critical",
            }
        },
        "value_chain": ["内容制作", "宣发", "院线"],
        "research_hints": {"box_office": "猫眼专业版"},
        "concept_keywords": ["影视院线"],
    },
    "shipping": {
        "display": "航运物流",
        "key_metrics": ["BDI指数"],
        "seasonal_events": {},
        "value_chain": ["航运"],
        "research_hints": {},
        "concept_keywords": [],
    },
}

MOCK_KEYWORD_CONFIG = {
    "sector_keywords": {
        "entertainment": ["春节档", "票房"],
        "shipping": ["BDI"],
    },
    "stock_keywords": {
        "001330": ["博纳", "影视"],
    },
}


@pytest.fixture
def builder():
    """Builder with mocked dependencies and config."""
    concept_analyzer = MagicMock()
    cross_market_analyzer = MagicMock()

    with (
        patch.object(
            AssociationProfileBuilder,
            "_load_industry_profiles",
            return_value=MOCK_INDUSTRY_PROFILES,
        ),
        patch.object(
            AssociationProfileBuilder,
            "_load_keyword_config",
            return_value=MOCK_KEYWORD_CONFIG,
        ),
    ):
        b = AssociationProfileBuilder(
            concept_analyzer=concept_analyzer,
            cross_market_analyzer=cross_market_analyzer,
        )
    return b


# ── Tests ────────────────────────────────────────────────────────────


class TestAssociationProfileDataclasses:
    def test_concept_link_defaults(self):
        cl = ConceptLink()
        assert cl.code == ""
        assert cl.pct_change == 0.0
        assert cl.rank_pct is None

    def test_peer_link_defaults(self):
        pl = PeerLink()
        assert pl.symbol == ""
        assert pl.market == ""
        assert pl.tags == []

    def test_industry_profile_defaults(self):
        ip = IndustryProfile()
        assert ip.tag == ""
        assert ip.key_metrics == []
        assert ip.seasonal_events == {}

    def test_association_profile_defaults(self):
        p = AssociationProfile(symbol="001330")
        assert p.symbol == "001330"
        assert p.resonance_level == "none"
        assert p.concepts == []
        assert p.industry_profile is None


class TestToDict:
    def test_serialization_complete(self):
        profile = AssociationProfile(
            symbol="001330",
            industry="影视传媒",
            concepts=[
                ConceptLink(code="BK1", name="影视", pct_change=2.5, rank_pct=0.1)
            ],
            resonance_level="moderate",
            cross_market_peers=[
                PeerLink(symbol="IMAX", market="us", tags=["entertainment"])
            ],
            cross_market_tags=["entertainment"],
            keyword_themes=["entertainment"],
            industry_profile=IndustryProfile(
                tag="entertainment",
                display="影视传媒",
                key_metrics=["票房"],
            ),
        )
        d = profile.to_dict()
        assert d["symbol"] == "001330"
        assert d["industry"] == "影视传媒"
        assert len(d["concepts"]) == 1
        assert d["concepts"][0]["name"] == "影视"
        assert d["resonance_level"] == "moderate"
        assert len(d["cross_market_peers"]) == 1
        assert d["cross_market_peers"][0]["symbol"] == "IMAX"
        assert d["industry_profile"]["display"] == "影视传媒"

    def test_serialization_no_industry_profile(self):
        profile = AssociationProfile(symbol="000001")
        d = profile.to_dict()
        assert d["industry_profile"] is None
        assert d["concepts"] == []


class TestBuildProfile:
    def test_full_profile_build(self, builder):
        ca = builder._concept_analyzer
        ca.analyze_stock_concepts.return_value = _FakeConceptResult(
            industry="影视传媒",
            concepts=[_FakeConcept()],
            resonance=_FakeResonance(),
        )

        cma = builder._cross_market_analyzer
        cma.get_mapping.return_value = {
            "tags": ["entertainment"],
            "us_peers": ["IMAX", "DIS"],
            "hk_peers": [],
            "commodities": [],
        }

        profile = builder.build_profile("001330")

        assert profile.symbol == "001330"
        assert profile.industry == "影视传媒"
        assert profile.resonance_level == "moderate"
        assert len(profile.concepts) == 1
        assert profile.concepts[0].name == "影视院线"
        assert len(profile.cross_market_peers) == 2
        assert profile.cross_market_tags == ["entertainment"]
        assert "entertainment" in profile.keyword_themes
        assert "stock_specific" in profile.keyword_themes
        assert profile.industry_profile is not None
        assert profile.industry_profile.tag == "entertainment"
        assert profile.industry_profile.display == "影视传媒"

    def test_concept_failure_degrades_gracefully(self, builder):
        builder._concept_analyzer.analyze_stock_concepts.side_effect = Exception("fail")
        builder._cross_market_analyzer.get_mapping.return_value = {
            "tags": [],
            "us_peers": [],
            "hk_peers": [],
            "commodities": [],
        }

        profile = builder.build_profile("001330")
        assert profile.symbol == "001330"
        assert profile.concepts == []
        assert profile.resonance_level == "none"

    def test_cross_market_failure_degrades_gracefully(self, builder):
        builder._concept_analyzer.analyze_stock_concepts.return_value = (
            _FakeConceptResult()
        )
        builder._cross_market_analyzer.get_mapping.side_effect = Exception("fail")

        profile = builder.build_profile("001330")
        assert profile.cross_market_peers == []
        assert profile.cross_market_tags == []

    def test_no_concept_analyzer(self):
        with (
            patch.object(
                AssociationProfileBuilder,
                "_load_industry_profiles",
                return_value={},
            ),
            patch.object(
                AssociationProfileBuilder,
                "_load_keyword_config",
                return_value={},
            ),
        ):
            b = AssociationProfileBuilder(
                concept_analyzer=None, cross_market_analyzer=None
            )
        profile = b.build_profile("000001")
        assert profile.concepts == []
        assert profile.cross_market_peers == []

    def test_industry_profile_resolved_from_tags(self, builder):
        builder._concept_analyzer.analyze_stock_concepts.return_value = (
            _FakeConceptResult()
        )
        builder._cross_market_analyzer.get_mapping.return_value = {
            "tags": ["shipping"],
            "us_peers": [],
            "hk_peers": [],
            "commodities": ["BDI"],
        }

        profile = builder.build_profile("601872")
        assert profile.industry_profile is not None
        assert profile.industry_profile.tag == "shipping"
        assert profile.industry_profile.display == "航运物流"
        assert len(profile.cross_market_peers) == 1
        assert profile.cross_market_peers[0].market == "commodity"

    def test_no_matching_industry_profile(self, builder):
        builder._concept_analyzer.analyze_stock_concepts.return_value = (
            _FakeConceptResult()
        )
        builder._cross_market_analyzer.get_mapping.return_value = {
            "tags": ["unknown_sector"],
            "us_peers": [],
            "hk_peers": [],
            "commodities": [],
        }

        profile = builder.build_profile("600000")
        assert profile.industry_profile is None


class TestApplyOverrides:
    def test_add_concepts(self, builder):
        profile = AssociationProfile(
            symbol="001330",
            concepts=[ConceptLink(code="BK1", name="影视", pct_change=1.0)],
        )
        overrides = {
            "added_concepts": [{"code": "BK999", "name": "自定义概念"}],
        }
        builder.apply_overrides(profile, overrides)
        assert len(profile.concepts) == 2
        assert profile.concepts[1].name == "自定义概念"
        assert profile.concepts[1].code == "BK999"

    def test_remove_concepts(self, builder):
        profile = AssociationProfile(
            symbol="001330",
            concepts=[
                ConceptLink(code="BK1", name="影视"),
                ConceptLink(code="BK2", name="娱乐"),
            ],
        )
        overrides = {"removed_concept_codes": ["BK1"]}
        builder.apply_overrides(profile, overrides)
        assert len(profile.concepts) == 1
        assert profile.concepts[0].code == "BK2"

    def test_add_and_remove_peers(self, builder):
        profile = AssociationProfile(
            symbol="001330",
            cross_market_peers=[
                PeerLink(symbol="IMAX", market="us"),
                PeerLink(symbol="DIS", market="us"),
            ],
        )
        overrides = {
            "removed_peer_symbols": ["IMAX"],
            "added_peers": [{"symbol": "NFLX", "market": "us", "tags": ["streaming"]}],
        }
        builder.apply_overrides(profile, overrides)
        symbols = [p.symbol for p in profile.cross_market_peers]
        assert "IMAX" not in symbols
        assert "DIS" in symbols
        assert "NFLX" in symbols
        nflx = [p for p in profile.cross_market_peers if p.symbol == "NFLX"][0]
        assert nflx.tags == ["streaming"]

    def test_keyword_overrides(self, builder):
        profile = AssociationProfile(
            symbol="001330",
            keyword_themes=["entertainment", "stock_specific"],
        )
        overrides = {
            "removed_keywords": ["stock_specific"],
            "added_keywords": ["春节档"],
        }
        builder.apply_overrides(profile, overrides)
        assert "stock_specific" not in profile.keyword_themes
        assert "entertainment" in profile.keyword_themes
        assert "春节档" in profile.keyword_themes

    def test_industry_override(self, builder):
        profile = AssociationProfile(
            symbol="001330",
            industry_profile=IndustryProfile(tag="entertainment", display="影视传媒"),
        )
        overrides = {"industry_override": "shipping"}
        builder.apply_overrides(profile, overrides)
        assert profile.industry_profile is not None
        assert profile.industry_profile.tag == "shipping"
        assert profile.industry_profile.display == "航运物流"

    def test_empty_overrides_noop(self, builder):
        profile = AssociationProfile(
            symbol="001330",
            concepts=[ConceptLink(code="BK1", name="影视")],
        )
        builder.apply_overrides(profile, {})
        assert len(profile.concepts) == 1

    def test_none_overrides_noop(self, builder):
        profile = AssociationProfile(symbol="001330")
        result = builder.apply_overrides(profile, None)
        assert result.symbol == "001330"


class TestGetAvailableIndustries:
    def test_returns_list(self, builder):
        industries = builder.get_available_industries()
        assert len(industries) == 2
        tags = {i["tag"] for i in industries}
        assert "entertainment" in tags
        assert "shipping" in tags


class TestKeywordThemes:
    def test_keyword_themes_from_tags(self, builder):
        builder._concept_analyzer.analyze_stock_concepts.return_value = (
            _FakeConceptResult()
        )
        builder._cross_market_analyzer.get_mapping.return_value = {
            "tags": ["entertainment"],
            "us_peers": [],
            "hk_peers": [],
            "commodities": [],
        }

        profile = builder.build_profile("001330")
        assert "entertainment" in profile.keyword_themes
        assert "stock_specific" in profile.keyword_themes

    def test_no_keyword_match(self, builder):
        builder._concept_analyzer.analyze_stock_concepts.return_value = (
            _FakeConceptResult()
        )
        builder._cross_market_analyzer.get_mapping.return_value = {
            "tags": ["unknown_sector"],
            "us_peers": [],
            "hk_peers": [],
            "commodities": [],
        }

        profile = builder.build_profile("999999")  # Not in stock_keywords
        assert profile.keyword_themes == []

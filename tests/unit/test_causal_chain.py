"""Tests for src/intelligence/causal_chain.py — CausalChainConstructor."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.intelligence.causal_chain import (
    CausalChain,
    CausalChainConstructor,
    ImpactChainLink,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TEMPLATES = {
    "fed_rate_cut": {
        "event_pattern": "美联储.*降息|Fed.*cut|联邦基金利率.*下调",
        "trigger_type": "monetary",
        "chain": [
            {
                "order": 1,
                "impact": "人民币升值预期",
                "sectors": ["消费", "科技"],
                "direction": "bullish",
                "confidence_decay": 0.9,
            },
            {
                "order": 2,
                "impact": "外资回流A股",
                "sectors": ["北向重仓股"],
                "direction": "bullish",
                "confidence_decay": 0.75,
            },
            {
                "order": 3,
                "impact": "流动性改善估值扩张",
                "sectors": ["成长股", "中小盘"],
                "direction": "bullish",
                "confidence_decay": 0.5,
            },
        ],
    },
    "geopolitical_conflict": {
        "event_pattern": "战争|冲突|军事行动|military|war|制裁|sanctions",
        "trigger_type": "geopolitical",
        "chain": [
            {
                "order": 1,
                "impact": "避险情绪升温",
                "sectors": ["黄金", "军工", "石油"],
                "direction": "bullish",
                "confidence_decay": 0.85,
            },
            {
                "order": 2,
                "impact": "风险资产承压",
                "sectors": ["科技", "消费", "地产"],
                "direction": "bearish",
                "confidence_decay": 0.65,
            },
        ],
    },
    "industry_subsidy": {
        "event_pattern": "产业政策|补贴|国家.*支持",
        "trigger_type": "regulatory",
        "chain": [
            {
                "order": 1,
                "impact": "直接受益标的",
                "sectors": ["_from_event"],
                "direction": "bullish",
                "confidence_decay": 0.9,
            },
        ],
    },
}


@pytest.fixture
def constructor() -> CausalChainConstructor:
    """Create a constructor with in-memory templates (no YAML file needed)."""
    with patch.object(
        CausalChainConstructor, "_load_templates", return_value=SAMPLE_TEMPLATES
    ):
        return CausalChainConstructor(templates_path="dummy.yaml")


# ---------------------------------------------------------------------------
# Template matching tests
# ---------------------------------------------------------------------------


class TestTemplateMatching:
    def test_matches_fed_rate_cut_chinese(self, constructor: CausalChainConstructor):
        result = constructor._match_template("美联储降息50基点")
        assert result is not None
        name, _template = result
        assert name == "fed_rate_cut"

    def test_matches_fed_rate_cut_english(self, constructor: CausalChainConstructor):
        result = constructor._match_template("Fed rate cut 25bp")
        assert result is not None
        name, _template = result
        assert name == "fed_rate_cut"

    def test_matches_geopolitical_conflict(self, constructor: CausalChainConstructor):
        result = constructor._match_template("中东地区爆发军事冲突")
        assert result is not None
        name, _template = result
        assert name == "geopolitical_conflict"

    def test_matches_sanctions(self, constructor: CausalChainConstructor):
        result = constructor._match_template("US imposes new sanctions on China")
        assert result is not None
        name, _template = result
        assert name == "geopolitical_conflict"

    def test_no_match_for_unrelated_text(self, constructor: CausalChainConstructor):
        result = constructor._match_template("今天天气真好适合出去走走")
        assert result is None


# ---------------------------------------------------------------------------
# Chain construction tests
# ---------------------------------------------------------------------------


class TestChainConstruction:
    def test_construct_chain_from_template(self, constructor: CausalChainConstructor):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        chain = constructor.construct_chain(event)

        assert chain is not None
        assert isinstance(chain, CausalChain)
        assert chain.event_type == "fed_rate_cut"
        assert chain.base_confidence == 0.8
        assert len(chain.chain) == 3

    def test_chain_link_order(self, constructor: CausalChainConstructor):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        chain = constructor.construct_chain(event)
        assert chain is not None

        orders = [link.order for link in chain.chain]
        assert orders == [1, 2, 3]

    def test_chain_has_valid_until(self, constructor: CausalChainConstructor):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        chain = constructor.construct_chain(event)
        assert chain is not None
        assert chain.valid_until is not None
        assert chain.valid_until > chain.created_at

    def test_chain_event_id_from_event(self, constructor: CausalChainConstructor):
        event = {"title": "美联储降息50基点", "event_id": "custom-id-123"}
        chain = constructor.construct_chain(event)
        assert chain is not None
        assert chain.event_id == "custom-id-123"

    def test_no_chain_for_unmatched_event(self, constructor: CausalChainConstructor):
        event = {"title": "今天天气真好"}
        chain = constructor.construct_chain(event)
        assert chain is None

    def test_empty_event_returns_none(self, constructor: CausalChainConstructor):
        chain = constructor.construct_chain({})
        assert chain is None


# ---------------------------------------------------------------------------
# Confidence decay tests
# ---------------------------------------------------------------------------


class TestConfidenceDecay:
    def test_first_order_confidence(self, constructor: CausalChainConstructor):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        chain = constructor.construct_chain(event)
        assert chain is not None

        # Order 1: 0.8 * 0.9 = 0.72
        assert chain.chain[0].confidence == pytest.approx(0.72, abs=0.001)

    def test_second_order_confidence(self, constructor: CausalChainConstructor):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        chain = constructor.construct_chain(event)
        assert chain is not None

        # Order 2: 0.8 * 0.75 = 0.6
        assert chain.chain[1].confidence == pytest.approx(0.6, abs=0.001)

    def test_third_order_confidence(self, constructor: CausalChainConstructor):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        chain = constructor.construct_chain(event)
        assert chain is not None

        # Order 3: 0.8 * 0.5 = 0.4
        assert chain.chain[2].confidence == pytest.approx(0.4, abs=0.001)

    def test_confidence_decreases_with_order(self, constructor: CausalChainConstructor):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        chain = constructor.construct_chain(event)
        assert chain is not None

        confidences = [link.confidence for link in chain.chain]
        assert confidences == sorted(confidences, reverse=True)

    def test_default_confidence(self, constructor: CausalChainConstructor):
        """Default confidence 0.7 when not provided in event."""
        event = {"title": "美联储降息50基点"}
        chain = constructor.construct_chain(event)
        assert chain is not None
        assert chain.base_confidence == 0.7


# ---------------------------------------------------------------------------
# Sector resolution tests
# ---------------------------------------------------------------------------


class TestSectorResolution:
    def test_static_sectors(self, constructor: CausalChainConstructor):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        chain = constructor.construct_chain(event)
        assert chain is not None

        assert chain.chain[0].sectors == ["消费", "科技"]

    def test_from_event_sectors(self, constructor: CausalChainConstructor):
        event = {
            "title": "国家补贴新能源产业",
            "confidence": 0.8,
            "sectors": ["新能源", "光伏"],
        }
        chain = constructor.construct_chain(event)
        assert chain is not None

        # _from_event should resolve to the event's sectors
        assert "新能源" in chain.chain[0].sectors
        assert "光伏" in chain.chain[0].sectors

    def test_from_event_no_sectors(self, constructor: CausalChainConstructor):
        """When event has no sectors metadata, _from_event resolves to empty."""
        event = {"title": "国家补贴新能源产业", "confidence": 0.8}
        chain = constructor.construct_chain(event)
        assert chain is not None
        assert chain.chain[0].sectors == []

    def test_all_sectors_property(self, constructor: CausalChainConstructor):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        chain = constructor.construct_chain(event)
        assert chain is not None

        all_sectors = chain.all_sectors
        assert "消费" in all_sectors
        assert "科技" in all_sectors
        assert "北向重仓股" in all_sectors


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_chain_link_to_dict(self):
        link = ImpactChainLink(
            order=1,
            impact="test impact",
            sectors=["科技"],
            direction="bullish",
            confidence=0.72,
        )
        d = link.to_dict()
        assert d["order"] == 1
        assert d["direction"] == "bullish"
        assert d["confidence"] == 0.72

    def test_chain_to_dict(self, constructor: CausalChainConstructor):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        chain = constructor.construct_chain(event)
        assert chain is not None

        d = chain.to_dict()
        assert d["event_type"] == "fed_rate_cut"
        assert d["base_confidence"] == 0.8
        assert len(d["chain"]) == 3
        assert "created_at" in d


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_title_plus_summary_matching(self, constructor: CausalChainConstructor):
        """Template matching should consider both title and summary."""
        event = {"title": "重要经济政策", "summary": "美联储宣布降息25个基点"}
        chain = constructor.construct_chain(event)
        assert chain is not None
        assert chain.event_type == "fed_rate_cut"

    def test_multiple_templates_first_match_wins(
        self, constructor: CausalChainConstructor
    ):
        """When multiple templates match, first one wins."""
        # "军事冲突" matches geopolitical_conflict
        event = {"title": "军事冲突导致制裁升级"}
        chain = constructor.construct_chain(event)
        assert chain is not None
        assert chain.event_type == "geopolitical_conflict"

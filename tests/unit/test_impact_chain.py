"""Tests for ImpactChainEngine."""

import pytest

from src.intelligence.impact_chain import ImpactChainEngine


@pytest.fixture
def engine():
    return ImpactChainEngine()


class TestEventDetection:
    def test_war_keywords(self, engine):
        matches = engine.detect_event_type("以色列与伊朗发生军事冲突")
        assert "geopolitical_war" in matches

    def test_oil_keywords(self, engine):
        matches = engine.detect_event_type("原油价格突破100美元")
        assert "oil_surge" in matches

    def test_usd_strengthen(self, engine):
        matches = engine.detect_event_type("美元走强DXY突破105")
        assert "usd_strengthen" in matches

    def test_fed_hawkish(self, engine):
        matches = engine.detect_event_type("美联储鹰派信号暗示加息")
        assert "fed_hawkish" in matches

    def test_multi_match(self, engine):
        matches = engine.detect_event_type("中东战争导致原油价格飙升")
        assert len(matches) >= 2
        assert "geopolitical_war" in matches
        assert "oil_surge" in matches

    def test_no_match(self, engine):
        matches = engine.detect_event_type("今天天气很好")
        assert matches == []


class TestChainBuilding:
    def test_build_war_chain(self, engine):
        chain = engine.build_chain("中东战争爆发", template_key="geopolitical_war")
        assert chain is not None
        assert chain.trigger_type == "geopolitical"
        assert len(chain.transmission_paths) > 0
        assert chain.source == "template"

    def test_build_usd_chain(self, engine):
        chain = engine.build_chain("美元走强突破104", template_key="usd_strengthen")
        assert chain is not None
        # 002155 (湖南黄金) should be negatively affected
        impact = chain.get_stock_impact("002155")
        assert impact == "negative"

    def test_auto_detect_and_build(self, engine):
        chain = engine.build_chain("美联储宣布降息25个基点")
        assert chain is not None
        assert chain.trigger_type == "monetary"

    def test_no_match_returns_none(self, engine):
        chain = engine.build_chain("今天天气很好")
        assert chain is None

    def test_invalid_template_returns_none(self, engine):
        chain = engine.build_chain("test", template_key="nonexistent")
        assert chain is None

    def test_all_affected_sectors(self, engine):
        chain = engine.build_chain("战争", template_key="geopolitical_war")
        sectors = chain.all_affected_sectors
        assert "黄金" in sectors
        assert "军工" in sectors

    def test_all_affected_stocks(self, engine):
        chain = engine.build_chain("黄金大涨", template_key="gold_surge")
        stocks = chain.all_affected_stocks
        assert "002155" in stocks  # 湖南黄金


class TestMultipleChains:
    def test_build_chains_for_compound_event(self, engine):
        chains = engine.build_chains_for_event("中东战争导致原油价格飙升")
        assert len(chains) >= 2

    def test_find_stock_impact(self, engine):
        chains = engine.build_chains_for_event("美元走强黄金承压")
        impacts = engine.find_stock_impact("002155", chains)
        assert len(impacts) > 0
        assert any(i["direction"] == "negative" for i in impacts)


class TestSerialization:
    def test_chain_to_dict(self, engine):
        chain = engine.build_chain("战争", template_key="geopolitical_war")
        d = chain.to_dict()
        assert "chain_id" in d
        assert "trigger_event" in d
        assert "transmission_paths" in d
        assert len(d["transmission_paths"]) > 0
        assert "cause" in d["transmission_paths"][0]

    def test_path_to_dict(self, engine):
        chain = engine.build_chain("战争", template_key="geopolitical_war")
        path_dict = chain.transmission_paths[0].to_dict()
        assert "cause" in path_dict
        assert "direction" in path_dict
        assert "affected_sectors" in path_dict

"""Tests for ImpactChainEngine — now a thin adapter over CausalChainConstructor.

The engine delegates chain construction to Engine B (``CausalChainConstructor``,
backed by ``config/impact_chain_templates.yaml``) and re-binds per-stock impacts
using a ``sector -> [stocks]`` map inverted from the legacy ``CHAIN_TEMPLATES``.
These tests assert the *adapter* behaviour, not the old in-code templates.

Events below are chosen to actually match Engine B's YAML ``event_pattern``
regexes (e.g. ``oil_surge``: "OPEC.*减产", ``fed_rate_cut``: "美联储.*降息").
"""

import pytest

from src.intelligence.impact_chain import ImpactChain, ImpactChainEngine

# An event that matches Engine B's `oil_surge` template AND whose resolved
# sectors (石油/炼化/航运/物流/光伏/风电/新能源) overlap the legacy sector->stock
# map, so stocks get re-bound. This is the key to defusing "the trap".
OIL_EVENT = "OPEC意外减产推动油价飙升"
# 中国石化 — bound to the 石油/炼化 sectors in CHAIN_TEMPLATES; the oil_surge
# chain produces those sectors, so it must resolve via the sector->stock map.
OIL_STOCK = "600028"

# An event matching Engine B's `fed_rate_cut` template.
FED_EVENT = "美联储宣布降息25个基点"


@pytest.fixture
def engine():
    return ImpactChainEngine()


class TestEventDetection:
    def test_detect_oil_event(self, engine):
        """A known event returns its matched Engine B template name."""
        assert engine.detect_event_type(OIL_EVENT) == ["oil_surge"]

    def test_detect_fed_event(self, engine):
        assert engine.detect_event_type(FED_EVENT) == ["fed_rate_cut"]

    def test_detect_returns_single_best_match(self, engine):
        """Engine B returns one best match (semantic shift from old behaviour)."""
        matches = engine.detect_event_type("美联储宣布降息且油价飙升")
        assert len(matches) == 1

    def test_no_match_returns_empty(self, engine):
        assert engine.detect_event_type("今天天气很好") == []


class TestChainBuilding:
    def test_build_chain_returns_impact_chain(self, engine):
        chain = engine.build_chain(OIL_EVENT)
        assert isinstance(chain, ImpactChain)
        assert chain.trigger_event == OIL_EVENT
        assert chain.trigger_type == "oil_surge"
        assert chain.source == "template"

    def test_build_chain_has_non_empty_paths(self, engine):
        chain = engine.build_chain(OIL_EVENT)
        assert len(chain.transmission_paths) > 0

    def test_build_chain_bridges_direction(self, engine):
        """bullish -> positive, bearish -> negative."""
        chain = engine.build_chain(OIL_EVENT)
        directions = {p.direction for p in chain.transmission_paths}
        assert directions <= {"positive", "negative"}
        # oil_surge has both bullish (炼化) and bearish (航运) links.
        assert "positive" in directions
        assert "negative" in directions

    def test_build_chain_lag_from_order(self, engine):
        """First link (order 1) maps to the '1-3d' lag bucket."""
        chain = engine.build_chain(OIL_EVENT)
        assert chain.transmission_paths[0].lag == "1-3d"

    def test_template_key_arg_is_ignored(self, engine):
        """The legacy template_key arg is accepted but ignored (Engine B decides)."""
        chain = engine.build_chain(OIL_EVENT, template_key="nonexistent")
        assert chain is not None
        assert chain.trigger_type == "oil_surge"

    def test_no_match_returns_none(self, engine):
        assert engine.build_chain("今天天气很好") is None

    def test_build_chains_for_event_returns_single(self, engine):
        chains = engine.build_chains_for_event(OIL_EVENT)
        assert len(chains) == 1
        assert isinstance(chains[0], ImpactChain)

    def test_build_chains_for_event_empty_on_no_match(self, engine):
        assert engine.build_chains_for_event("今天天气很好") == []

    def test_affected_sectors_populated(self, engine):
        chain = engine.build_chain(OIL_EVENT)
        sectors = chain.all_affected_sectors
        # From the oil_surge YAML template.
        assert "石油" in sectors
        assert "航运" in sectors


class TestStockResolution:
    """The trap: Engine B leaves affected_stocks empty; the adapter re-binds
    them from the sector->stock map. These tests prove the trap is defused."""

    def test_stocks_resolved_from_sector_map(self, engine):
        chain = engine.build_chain(OIL_EVENT)
        # The oil chain's 石油/炼化 sectors must resolve to 中国石化 (600028).
        assert OIL_STOCK in chain.all_affected_stocks

    def test_find_stock_impact_non_empty(self, engine):
        """find_stock_impact returns >=1 impact for a re-bound stock."""
        chains = engine.build_chains_for_event(OIL_EVENT)
        impacts = engine.find_stock_impact(OIL_STOCK, chains)
        assert len(impacts) >= 1
        # The 炼化 link is bullish -> positive for 中国石化.
        assert any(i["direction"] == "positive" for i in impacts)

    def test_find_stock_impact_carries_chain_context(self, engine):
        chains = engine.build_chains_for_event(OIL_EVENT)
        impacts = engine.find_stock_impact(OIL_STOCK, chains)
        first = impacts[0]
        for key in ("chain_id", "trigger_event", "cause", "effect", "direction"):
            assert key in first

    def test_find_stock_impact_empty_for_unknown_stock(self, engine):
        chains = engine.build_chains_for_event(OIL_EVENT)
        assert engine.find_stock_impact("999999", chains) == []


class TestSerialization:
    def test_chain_to_dict_round_trips(self, engine):
        chain = engine.build_chain(OIL_EVENT)
        d = chain.to_dict()
        assert d["trigger_event"] == OIL_EVENT
        assert d["trigger_type"] == "oil_surge"
        assert d["source"] == "template"
        assert len(d["transmission_paths"]) == len(chain.transmission_paths)
        first_path = d["transmission_paths"][0]
        for key in (
            "cause",
            "effect",
            "direction",
            "magnitude",
            "affected_sectors",
            "affected_stocks",
            "lag",
        ):
            assert key in first_path

    def test_path_to_dict(self, engine):
        chain = engine.build_chain(OIL_EVENT)
        path_dict = chain.transmission_paths[0].to_dict()
        assert "cause" in path_dict
        assert "direction" in path_dict
        assert "affected_sectors" in path_dict
        assert "affected_stocks" in path_dict

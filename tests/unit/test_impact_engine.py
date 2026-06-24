"""Tests for src/intelligence/impact_engine.py — EventImpactEngine."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.intelligence.causal_chain import CausalChainConstructor
from src.intelligence.impact_engine import EventImpactEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TEMPLATES = {
    "fed_rate_cut": {
        "event_pattern": "美联储.*降息|Fed.*cut",
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
        ],
    },
    "geopolitical_conflict": {
        "event_pattern": "战争|冲突|military|war",
        "trigger_type": "geopolitical",
        "chain": [
            {
                "order": 1,
                "impact": "避险情绪升温",
                "sectors": ["黄金", "军工"],
                "direction": "bullish",
                "confidence_decay": 0.85,
            },
            {
                "order": 2,
                "impact": "风险资产承压",
                "sectors": ["科技"],
                "direction": "bearish",
                "confidence_decay": 0.65,
            },
        ],
    },
}

SAMPLE_SECTOR_MAP = {
    "消费": ["600519", "000858"],
    "科技": ["002230", "300750"],
    "北向重仓股": ["600519"],
    "黄金": ["002155", "600489"],
    "军工": ["600893"],
}


@pytest.fixture
def constructor() -> CausalChainConstructor:
    with patch.object(
        CausalChainConstructor, "_load_templates", return_value=SAMPLE_TEMPLATES
    ):
        return CausalChainConstructor(templates_path="dummy.yaml")


@pytest.fixture
def engine(constructor: CausalChainConstructor) -> EventImpactEngine:
    return EventImpactEngine(
        chain_constructor=constructor,
        stock_sector_map=SAMPLE_SECTOR_MAP,
    )


# ---------------------------------------------------------------------------
# Event → signals conversion
# ---------------------------------------------------------------------------


class TestEventToSignals:
    def test_fed_rate_cut_produces_signals(self, engine: EventImpactEngine):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        signals = engine.process_event(event)
        assert len(signals) > 0

    def test_signal_structure(self, engine: EventImpactEngine):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        signals = engine.process_event(event)

        for sig in signals:
            assert "symbol" in sig
            assert "direction" in sig
            assert "confidence" in sig
            assert "source" in sig
            assert "signal_type" in sig
            assert "metadata" in sig

    def test_signal_source_format(self, engine: EventImpactEngine):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        signals = engine.process_event(event)

        for sig in signals:
            assert sig["source"].startswith("impact_chain:")
            assert sig["signal_type"].startswith("intel/")

    def test_signal_metadata_contains_chain_info(self, engine: EventImpactEngine):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        signals = engine.process_event(event)

        for sig in signals:
            meta = sig["metadata"]
            assert "event" in meta
            assert "impact_order" in meta
            assert "impact" in meta
            assert "chain_id" in meta
            assert "base_confidence" in meta

    def test_unmatched_event_returns_empty(self, engine: EventImpactEngine):
        event = {"title": "今天天气很好"}
        signals = engine.process_event(event)
        assert signals == []

    def test_empty_event_returns_empty(self, engine: EventImpactEngine):
        signals = engine.process_event({})
        assert signals == []


# ---------------------------------------------------------------------------
# Stock resolution from sectors
# ---------------------------------------------------------------------------


class TestStockResolution:
    def test_resolves_consumer_stocks(self, engine: EventImpactEngine):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        signals = engine.process_event(event)

        symbols = [s["symbol"] for s in signals]
        # 消费 sector stocks
        assert "600519" in symbols
        assert "000858" in symbols

    def test_resolves_tech_stocks(self, engine: EventImpactEngine):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        signals = engine.process_event(event)

        symbols = [s["symbol"] for s in signals]
        assert "002230" in symbols
        assert "300750" in symbols

    def test_resolves_gold_stocks_for_geopolitical(self, engine: EventImpactEngine):
        event = {"title": "中东爆发军事冲突", "confidence": 0.9}
        signals = engine.process_event(event)

        symbols = [s["symbol"] for s in signals]
        assert "002155" in symbols
        assert "600489" in symbols

    def test_no_stocks_for_unmapped_sector(self, engine: EventImpactEngine):
        """Sectors not in the map produce no stock signals."""
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        signals = engine.process_event(event)

        # All signals should have symbols from our sector map
        for sig in signals:
            assert sig["symbol"] in [
                "600519",
                "000858",
                "002230",
                "300750",
            ]

    def test_empty_sector_map(self, constructor: CausalChainConstructor):
        engine = EventImpactEngine(
            chain_constructor=constructor,
            stock_sector_map={},
        )
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        signals = engine.process_event(event)
        # Chain matched, but no stocks resolved
        assert signals == []


# ---------------------------------------------------------------------------
# Direction propagation
# ---------------------------------------------------------------------------


class TestDirectionPropagation:
    def test_bullish_direction_propagated(self, engine: EventImpactEngine):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        signals = engine.process_event(event)

        for sig in signals:
            assert sig["direction"] == "bullish"

    def test_mixed_directions_for_geopolitical(self, engine: EventImpactEngine):
        event = {"title": "中东爆发军事冲突", "confidence": 0.9}
        signals = engine.process_event(event)

        directions = {s["direction"] for s in signals}
        assert "bullish" in directions
        assert "bearish" in directions

    def test_bearish_stocks_are_tech(self, engine: EventImpactEngine):
        event = {"title": "中东爆发军事冲突", "confidence": 0.9}
        signals = engine.process_event(event)

        bearish = [s for s in signals if s["direction"] == "bearish"]
        # Tech stocks should be bearish
        bearish_symbols = {s["symbol"] for s in bearish}
        assert "002230" in bearish_symbols or "300750" in bearish_symbols


# ---------------------------------------------------------------------------
# Confidence values in signals
# ---------------------------------------------------------------------------


class TestSignalConfidence:
    def test_first_order_confidence(self, engine: EventImpactEngine):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        signals = engine.process_event(event)

        # First-order signals: 0.8 * 0.9 = 0.72
        first_order = [s for s in signals if s["metadata"]["impact_order"] == 1]
        for sig in first_order:
            assert sig["confidence"] == pytest.approx(0.72, abs=0.001)

    def test_second_order_lower_confidence(self, engine: EventImpactEngine):
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        signals = engine.process_event(event)

        first_order = [s for s in signals if s["metadata"]["impact_order"] == 1]
        second_order = [s for s in signals if s["metadata"]["impact_order"] == 2]

        if first_order and second_order:
            assert second_order[0]["confidence"] < first_order[0]["confidence"]


# ---------------------------------------------------------------------------
# update_sector_map
# ---------------------------------------------------------------------------


class TestUpdateSectorMap:
    def test_update_changes_resolution(self, constructor: CausalChainConstructor):
        engine = EventImpactEngine(
            chain_constructor=constructor,
            stock_sector_map={},
        )

        # Initially no signals (empty map)
        event = {"title": "美联储降息50基点", "confidence": 0.8}
        assert engine.process_event(event) == []

        # After update, should produce signals
        engine.update_sector_map(SAMPLE_SECTOR_MAP)
        signals = engine.process_event(event)
        assert len(signals) > 0

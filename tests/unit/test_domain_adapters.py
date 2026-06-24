"""Unit tests for DomainAdapter implementations."""

from __future__ import annotations

import pytest

from src.agent_loop.adapters.capital_flow_adapter import CapitalFlowAdapter
from src.agent_loop.adapters.intelligence_adapter import IntelligenceAdapter
from src.agent_loop.adapters.leader_adapter import LeaderAdapter
from src.agent_loop.adapters.microstructure_adapter import MicrostructureAdapter
from src.agent_loop.adapters.technical_adapter import TechnicalAdapter
from src.agent_loop.domain_adapter import (
    DomainAdapter,
    IndependenceGroup,
    SignalDirection,
    SignalEvidence,
)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """All adapters must satisfy the DomainAdapter protocol."""

    @pytest.mark.parametrize(
        "adapter_cls",
        [
            TechnicalAdapter,
            CapitalFlowAdapter,
            IntelligenceAdapter,
            MicrostructureAdapter,
            LeaderAdapter,
        ],
    )
    def test_is_domain_adapter(self, adapter_cls: type) -> None:
        adapter = adapter_cls()
        assert isinstance(adapter, DomainAdapter)

    @pytest.mark.parametrize(
        "adapter_cls",
        [
            TechnicalAdapter,
            CapitalFlowAdapter,
            IntelligenceAdapter,
            MicrostructureAdapter,
            LeaderAdapter,
        ],
    )
    def test_has_domain_attribute(self, adapter_cls: type) -> None:
        adapter = adapter_cls()
        assert hasattr(adapter, "domain")
        assert isinstance(adapter.domain, str)
        assert len(adapter.domain) > 0

    @pytest.mark.parametrize(
        "adapter_cls",
        [
            TechnicalAdapter,
            CapitalFlowAdapter,
            IntelligenceAdapter,
            MicrostructureAdapter,
            LeaderAdapter,
        ],
    )
    def test_get_signal_types_returns_list(self, adapter_cls: type) -> None:
        adapter = adapter_cls()
        types = adapter.get_signal_types()
        assert isinstance(types, list)
        assert len(types) > 0
        assert all(isinstance(t, str) for t in types)


# ---------------------------------------------------------------------------
# TechnicalAdapter
# ---------------------------------------------------------------------------


class TestTechnicalAdapter:
    def test_converts_buy_signal(self) -> None:
        adapter = TechnicalAdapter(
            signal_dicts=[
                {
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "signal_type": "macd_cross",
                    "direction": "buy",
                    "confidence": 0.8,
                    "summary_short": "MACD golden cross",
                }
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 1
        s = signals[0]
        assert isinstance(s, SignalEvidence)
        assert s.symbol == "600519"
        assert s.direction == SignalDirection.BUY
        assert s.independence_group == IndependenceGroup.PRICE_DERIVED
        assert s.confidence == pytest.approx(0.8)
        assert "momentum_breakout" in s.signal_type

    def test_filters_by_symbol(self) -> None:
        adapter = TechnicalAdapter(
            signal_dicts=[
                {"symbol": "600519", "direction": "buy", "confidence": 0.7},
                {"symbol": "000858", "direction": "sell", "confidence": 0.6},
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 1
        assert signals[0].symbol == "600519"

    def test_skips_zero_confidence(self) -> None:
        adapter = TechnicalAdapter(
            signal_dicts=[
                {"symbol": "600519", "direction": "buy", "confidence": 0},
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 0

    def test_classifies_mean_reversion(self) -> None:
        adapter = TechnicalAdapter(
            signal_dicts=[
                {
                    "symbol": "600519",
                    "signal_type": "rsi_oversold",
                    "direction": "buy",
                    "confidence": 0.6,
                }
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert signals[0].signal_type == "technical/mean_reversion"


# ---------------------------------------------------------------------------
# CapitalFlowAdapter
# ---------------------------------------------------------------------------


class TestCapitalFlowAdapter:
    def test_sector_flow_buy(self) -> None:
        adapter = CapitalFlowAdapter(
            sector_flows=[
                {
                    "symbol": "600519",
                    "net_inflow": 5e8,
                    "sector_name": "白酒",
                }
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 1
        assert signals[0].direction == SignalDirection.BUY
        assert signals[0].independence_group == IndependenceGroup.CAPITAL_FLOW
        assert signals[0].signal_type == "flow/sector_rotation"

    def test_northbound_sell(self) -> None:
        adapter = CapitalFlowAdapter(
            northbound_flows=[{"symbol": "600519", "net_buy": -3e7}]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 1
        assert signals[0].direction == SignalDirection.SELL
        assert signals[0].signal_type == "flow/northbound"

    def test_zero_flow_ignored(self) -> None:
        adapter = CapitalFlowAdapter(
            sector_flows=[{"symbol": "600519", "net_inflow": 0}]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 0


# ---------------------------------------------------------------------------
# IntelligenceAdapter
# ---------------------------------------------------------------------------


class TestIntelligenceAdapter:
    def test_policy_signal(self) -> None:
        adapter = IntelligenceAdapter(
            intel_items=[
                {
                    "symbol": "600519",
                    "category": "policy",
                    "sentiment": "positive",
                    "confidence": 0.75,
                    "summary": "New tax policy favors liquor industry",
                }
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 1
        assert signals[0].signal_type == "intel/policy"
        assert signals[0].direction == SignalDirection.BUY
        assert signals[0].independence_group == IndependenceGroup.INTELLIGENCE

    def test_affected_symbols_expansion(self) -> None:
        adapter = IntelligenceAdapter(
            intel_items=[
                {
                    "category": "event",
                    "sentiment": "negative",
                    "confidence": 0.8,
                    "affected_symbols": ["600519", "000858"],
                }
            ]
        )
        signals = adapter.collect_signals(["600519", "000858"])
        assert len(signals) == 2
        symbols = {s.symbol for s in signals}
        assert symbols == {"600519", "000858"}

    def test_neutral_sentiment_ignored(self) -> None:
        adapter = IntelligenceAdapter(
            intel_items=[
                {"symbol": "600519", "category": "news", "sentiment": "neutral"}
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 0


# ---------------------------------------------------------------------------
# MicrostructureAdapter
# ---------------------------------------------------------------------------


class TestMicrostructureAdapter:
    def test_high_vpin_produces_sell(self) -> None:
        adapter = MicrostructureAdapter(
            vpin_results=[
                {
                    "symbol": "600519",
                    "vpin": 0.85,
                    "toxicity_level": "high",
                    "alert": True,
                    "trend": "rising",
                }
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 1
        assert signals[0].direction == SignalDirection.SELL
        assert signals[0].signal_type == "micro/vpin_toxicity"
        assert signals[0].independence_group == IndependenceGroup.MICROSTRUCTURE

    def test_low_vpin_ignored(self) -> None:
        adapter = MicrostructureAdapter(
            vpin_results=[
                {
                    "symbol": "600519",
                    "vpin": 0.3,
                    "toxicity_level": "low",
                    "alert": False,
                }
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 0

    def test_strong_seal_produces_buy(self) -> None:
        adapter = MicrostructureAdapter(
            seal_results=[{"symbol": "600519", "grade": "strong", "ratio": 0.3}]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 1
        assert signals[0].direction == SignalDirection.BUY
        assert signals[0].signal_type == "micro/seal_quality"

    def test_small_order_imbalance_ignored(self) -> None:
        adapter = MicrostructureAdapter(
            order_imbalance_results=[{"symbol": "600519", "imbalance": 0.1}]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 0


# ---------------------------------------------------------------------------
# LeaderAdapter
# ---------------------------------------------------------------------------


class TestLeaderAdapter:
    def test_leader_produces_buy(self) -> None:
        adapter = LeaderAdapter(
            leader_scores=[
                {
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "sector": "白酒",
                    "total_score": 85,
                    "is_leader": True,
                    "reason": "First mover, strong seal",
                    "confidence_level": "high",
                }
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 1
        assert signals[0].direction == SignalDirection.BUY
        assert signals[0].independence_group == IndependenceGroup.MARKET_STRUCTURE
        assert "leader/" in signals[0].signal_type

    def test_non_leader_ignored(self) -> None:
        adapter = LeaderAdapter(
            leader_scores=[{"symbol": "600519", "total_score": 50, "is_leader": False}]
        )
        signals = adapter.collect_signals(["600519"])
        assert len(signals) == 0

    def test_sector_signal_type(self) -> None:
        adapter = LeaderAdapter(
            leader_scores=[
                {
                    "symbol": "600519",
                    "sector": "白酒",
                    "total_score": 90,
                    "is_leader": True,
                }
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert signals[0].signal_type == "leader/sector"

    def test_primary_signal_type_without_sector(self) -> None:
        adapter = LeaderAdapter(
            leader_scores=[
                {
                    "symbol": "600519",
                    "sector": "",
                    "total_score": 80,
                    "is_leader": True,
                }
            ]
        )
        signals = adapter.collect_signals(["600519"])
        assert signals[0].signal_type == "leader/primary"

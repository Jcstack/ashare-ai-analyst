"""Unit tests for SignalAggregator."""

from __future__ import annotations

import pytest

from src.agent_loop.models import AggregatedSignal, SignalDirection, UrgencyTier
from src.agent_loop.signal_aggregator import SignalAggregator


@pytest.fixture()
def agg():
    return SignalAggregator()


class TestAddFromTechnical:
    def test_creates_proper_signal(self, agg):
        sig_dict = {
            "symbol": "000858",
            "name": "五粮液",
            "signal_type": "macd_cross",
            "direction": "buy",
            "confidence": 0.7,
            "summary_short": "MACD golden cross",
        }
        signal = agg.add_from_technical(sig_dict)

        assert signal is not None
        assert signal.symbol == "000858"
        assert signal.direction == SignalDirection.BUY
        assert signal.source == "technical"
        assert signal.confidence == pytest.approx(0.7)
        assert signal.metadata["signal_type"] == "macd_cross"


class TestAddFromRotation:
    def test_creates_signal_for_non_hold(self, agg):
        profile = {
            "symbol": "600519",
            "name": "贵州茅台",
            "rotation_signal": "sell",
            "rotation_reason": "Sector rotation out",
            "macro_score": 0.3,
        }
        signal = agg.add_from_rotation(profile)

        assert signal is not None
        assert signal.direction == SignalDirection.SELL
        assert signal.source == "rotation"
        assert signal.confidence == pytest.approx(0.3)

    def test_hold_rotation_still_creates_signal(self, agg):
        """Even hold signals are buffered (they just rank lower)."""
        profile = {
            "symbol": "600519",
            "name": "贵州茅台",
            "rotation_signal": "hold",
            "macro_score": 0.5,
        }
        signal = agg.add_from_rotation(profile)
        assert signal is not None
        assert signal.direction == SignalDirection.HOLD


class TestAddFromBlackSwan:
    def test_creates_critical_urgency_signal(self, agg):
        alert = {
            "alert_level": "severe",
            "message": "Circuit breaker triggered",
            "affected_symbols": [
                {"symbol": "600519", "name": "贵州茅台"},
                {"symbol": "000858", "name": "五粮液"},
            ],
        }
        signal = agg.add_from_black_swan(alert)

        assert signal is not None
        assert signal.urgency == UrgencyTier.CRITICAL
        assert signal.direction == SignalDirection.SELL
        assert signal.confidence == pytest.approx(1.0)
        assert signal.source == "black_swan"

    def test_returns_none_when_no_affected_symbols(self, agg):
        alert = {"alert_level": "severe", "message": "panic", "affected_symbols": []}
        assert agg.add_from_black_swan(alert) is None

    def test_handles_string_symbols(self, agg):
        alert = {
            "alert_level": "warning",
            "message": "Flash crash",
            "affected_symbols": ["600519"],
        }
        signal = agg.add_from_black_swan(alert)
        assert signal is not None
        assert signal.symbol == "600519"


class TestAddFromThesisInvalidation:
    def test_creates_high_urgency_sell(self, agg):
        signal = agg.add_from_thesis_invalidation(
            symbol="600519", name="贵州茅台", reason="Stop loss breached"
        )

        assert signal.direction == SignalDirection.SELL
        assert signal.urgency == UrgencyTier.HIGH
        assert signal.confidence == pytest.approx(0.9)
        assert signal.source == "thesis_invalidation"
        assert signal.reason == "Stop loss breached"


class TestAddFromLeader:
    def test_creates_buy_signal_for_leader(self, agg):
        class MockLeaderScore:
            symbol = "300059"
            name = "东方财富"
            sector = "证券"
            total_score = 85.0
            is_leader = True
            scores = {"first_mover": 30}
            reason = "首板龙头"
            confidence_level = "high"

        signal = agg.add_from_leader(MockLeaderScore())
        assert signal is not None
        assert signal.symbol == "300059"
        assert signal.direction == SignalDirection.BUY
        assert signal.source == "leader_detection"
        assert signal.confidence == pytest.approx(0.85)
        assert signal.urgency == UrgencyTier.HIGH
        assert signal.metadata["total_score"] == 85.0
        assert signal.metadata["sector"] == "证券"

    def test_ignores_non_leader(self, agg):
        class MockNonLeader:
            symbol = "000001"
            name = "平安银行"
            sector = "银行"
            total_score = 40.0
            is_leader = False
            scores = {}
            reason = ""
            confidence_level = "low"

        result = agg.add_from_leader(MockNonLeader())
        assert result is None

    def test_medium_confidence_mapping(self, agg):
        class MockMedium:
            symbol = "600519"
            name = "贵州茅台"
            sector = "白酒"
            total_score = 72.0
            is_leader = True
            scores = {}
            reason = "跟随龙头"
            confidence_level = "medium"

        signal = agg.add_from_leader(MockMedium())
        assert signal is not None
        assert signal.confidence == pytest.approx(0.70)


class TestRankAndDeduplicate:
    def test_sorted_by_priority_desc(self, agg):
        # Add signals with different urgencies
        agg.add_from_thesis_invalidation("A", "StockA", "reason1")  # HIGH
        agg.add_from_technical(
            {
                "symbol": "B",
                "name": "StockB",
                "signal_type": "macd_cross",
                "direction": "buy",
                "confidence": 0.6,
                "summary_short": "ok",
            }
        )  # NORMAL

        ranked = agg.rank_and_deduplicate()
        assert len(ranked) >= 2
        # First signal should have higher priority score
        assert ranked[0].priority_score >= ranked[1].priority_score

    def test_dedup_merges_same_symbol_direction(self, agg):
        # Two BUY signals for the same symbol
        agg.add_from_technical(
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "signal_type": "rsi",
                "direction": "buy",
                "confidence": 0.5,
                "summary_short": "first",
            }
        )
        agg.add_from_technical(
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "signal_type": "macd",
                "direction": "buy",
                "confidence": 0.9,
                "summary_short": "second",
            }
        )

        ranked = agg.rank_and_deduplicate()
        # Should be deduped to 1 signal
        buy_signals = [s for s in ranked if s.symbol == "600519"]
        assert len(buy_signals) == 1
        # Keeps the highest confidence
        assert buy_signals[0].confidence == pytest.approx(0.9)

    def test_different_directions_not_deduped(self, agg):
        agg.add_from_technical(
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "signal_type": "macd",
                "direction": "buy",
                "confidence": 0.7,
                "summary_short": "buy signal",
            }
        )
        agg.add_from_thesis_invalidation("600519", "贵州茅台", "sell reason")

        ranked = agg.rank_and_deduplicate()
        symbols_600519 = [s for s in ranked if s.symbol == "600519"]
        # BUY and SELL are different directions, should not merge
        assert len(symbols_600519) == 2


class TestClear:
    def test_clear_resets_buffer(self, agg):
        agg.add_from_technical(
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "signal_type": "macd",
                "direction": "buy",
                "confidence": 0.8,
                "summary_short": "test",
            }
        )
        agg.clear()
        ranked = agg.rank_and_deduplicate()
        assert len(ranked) == 0


class TestComputePriorityScore:
    def test_critical_has_highest_weight(self):
        sig = AggregatedSignal(
            symbol="X",
            name="X",
            direction=SignalDirection.SELL,
            source="test",
            confidence=1.0,
            urgency=UrgencyTier.CRITICAL,
            reason="test",
        )
        score = SignalAggregator.compute_priority_score(sig)
        # CRITICAL weight=10, confidence=1.0, freshness=1.0 => ~10.0
        assert score == pytest.approx(10.0, abs=0.5)

    def test_low_confidence_lowers_score(self):
        sig = AggregatedSignal(
            symbol="X",
            name="X",
            direction=SignalDirection.BUY,
            source="test",
            confidence=0.1,
            urgency=UrgencyTier.NORMAL,
            reason="test",
        )
        score = SignalAggregator.compute_priority_score(sig)
        # NORMAL weight=2, confidence=0.1 => ~0.2
        assert score < 1.0

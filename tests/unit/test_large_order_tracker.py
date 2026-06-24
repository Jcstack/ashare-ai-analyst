"""Tests for LargeOrderTracker -- institutional order merging."""

from __future__ import annotations

import pytest


def _make_ticks(
    n=10, direction="buy", base_time=1000.0, interval=0.5, volume=1000, price=10.0
):
    """Create synthetic TickTrade objects."""
    from src.data.level2_provider import TickTrade

    return [
        TickTrade(
            timestamp=base_time + i * interval,
            price=price,
            volume=volume,
            amount=price * volume,
            direction=direction,
        )
        for i in range(n)
    ]


class TestLargeOrderTracker:
    @pytest.fixture()
    def tracker(self):
        from src.data.large_order_tracker import LargeOrderTracker

        return LargeOrderTracker(merge_window_seconds=3.0)

    def test_merge_empty(self, tracker):
        result = tracker.merge_ticks([])
        assert result == []

    def test_merge_single_direction(self, tracker):
        """All same-direction ticks within window should merge into one order."""
        ticks = _make_ticks(5, direction="buy", interval=0.5)
        merged = tracker.merge_ticks(ticks)
        assert len(merged) == 1
        assert merged[0].direction == "buy"
        assert merged[0].total_volume == 5000
        assert merged[0].tick_count == 5

    def test_merge_direction_change(self, tracker):
        """Direction change should split into separate orders."""
        ticks = _make_ticks(3, "buy") + _make_ticks(3, "sell", base_time=1002.0)
        merged = tracker.merge_ticks(ticks)
        assert len(merged) == 2
        assert merged[0].direction == "buy"
        assert merged[1].direction == "sell"

    def test_merge_time_gap(self, tracker):
        """Large time gap should split even if same direction."""
        ticks = _make_ticks(3, "buy", base_time=1000.0) + _make_ticks(
            3, "buy", base_time=1010.0
        )
        merged = tracker.merge_ticks(ticks)
        assert len(merged) == 2

    def test_neutral_ticks_skipped(self, tracker):
        """Neutral ticks should not form orders."""
        ticks = _make_ticks(5, "neutral")
        merged = tracker.merge_ticks(ticks)
        assert len(merged) == 0

    def test_iceberg_detection(self, tracker):
        """5+ consecutive identical volumes should flag iceberg."""
        ticks = _make_ticks(7, "buy", volume=500, interval=0.3)  # All 500 shares
        merged = tracker.merge_ticks(ticks)
        assert len(merged) == 1
        assert merged[0].is_iceberg is True

    def test_no_iceberg_varied_volumes(self, tracker):
        from src.data.level2_provider import TickTrade

        ticks = [
            TickTrade(
                timestamp=1000 + i,
                price=10.0,
                volume=v,
                amount=10.0 * v,
                direction="buy",
            )
            for i, v in enumerate([100, 200, 300, 100, 500])
        ]
        merged = tracker.merge_ticks(ticks)
        for order in merged:
            assert order.is_iceberg is False

    def test_size_category(self):
        from src.data.large_order_tracker import MergedOrder

        assert (
            MergedOrder("x", "buy", 100, 50_000_000, 10, 1, 0, 0).size_category
            == "超大单"
        )
        assert (
            MergedOrder("x", "buy", 100, 500_000, 10, 1, 0, 0).size_category == "大单"
        )
        assert (
            MergedOrder("x", "buy", 100, 100_000, 10, 1, 0, 0).size_category == "中单"
        )
        assert MergedOrder("x", "buy", 100, 10_000, 10, 1, 0, 0).size_category == "小单"

    def test_flow_summary(self, tracker):
        ticks_buy = _make_ticks(5, "buy", volume=50000, price=10.0)  # 250万 = 超大单
        ticks_sell = _make_ticks(
            3, "sell", volume=20000, price=10.0, base_time=1010.0
        )  # 60万 = 大单
        merged = tracker.merge_ticks(ticks_buy + ticks_sell)
        flow = tracker.compute_flow_summary(merged)
        assert flow["institutional_direction"] == "买入"
        assert flow["net_large_flow"] > 0

    def test_flow_summary_empty(self, tracker):
        flow = tracker.compute_flow_summary([])
        assert flow["institutional_direction"] == "中性"
        assert flow["net_large_flow"] == 0

    def test_flow_summary_keys(self, tracker):
        ticks = _make_ticks(5, "buy", volume=50000, price=10.0)
        merged = tracker.merge_ticks(ticks)
        flow = tracker.compute_flow_summary(merged)
        expected_keys = [
            "net_large_flow",
            "net_super_large_flow",
            "buy_large_amount",
            "sell_large_amount",
            "large_buy_count",
            "large_sell_count",
            "iceberg_count",
            "institutional_direction",
            "institutional_strength",
        ]
        for key in expected_keys:
            assert key in flow, f"Missing key: {key}"

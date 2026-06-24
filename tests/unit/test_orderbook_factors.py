"""Tests for OrderBookFactorEngine -- Level-2 microstructure factors."""

from __future__ import annotations

import pytest


def _make_snapshot(bid_vol=1000, ask_vol=1000, spread=0.02, price=10.0):
    from src.data.level2_provider import OrderBookSnapshot

    return OrderBookSnapshot(
        symbol="600519",
        timestamp=1000.0,
        last_price=price,
        bid_prices=[price - spread / 2, price - spread / 2 - 0.01],
        bid_volumes=[bid_vol, bid_vol // 2],
        ask_prices=[price + spread / 2, price + spread / 2 + 0.01],
        ask_volumes=[ask_vol, ask_vol // 2],
        spread=spread,
        mid_price=price,
        total_bid_volume=bid_vol + bid_vol // 2,
        total_ask_volume=ask_vol + ask_vol // 2,
    )


class TestOrderBookFactorEngine:
    @pytest.fixture()
    def engine(self):
        from src.quant.orderbook_factors import OrderBookFactorEngine

        return OrderBookFactorEngine()

    def test_compute_returns_dict(self, engine):
        snap = _make_snapshot()
        result = engine.compute(snap)
        assert isinstance(result, dict)
        assert len(result) == 10

    def test_all_factors_present(self, engine):
        snap = _make_snapshot()
        result = engine.compute(snap)
        expected = [
            "depth_imbalance",
            "spread_normalized",
            "order_flow_imbalance",
            "bid_wall_strength",
            "ask_wall_strength",
            "trade_direction_ratio",
            "large_order_pressure",
            "depth_resilience",
            "micro_momentum",
            "volume_imbalance_ratio",
        ]
        for key in expected:
            assert key in result, f"Missing: {key}"

    def test_factors_in_range(self, engine):
        snap = _make_snapshot()
        result = engine.compute(snap)
        for key, val in result.items():
            assert 0.0 <= val <= 1.0, f"{key}={val} out of range"

    def test_neutral_on_none(self, engine):
        result = engine.compute(None)
        assert all(v == 0.5 for v in result.values())

    def test_bid_heavy_imbalance(self, engine):
        snap = _make_snapshot(bid_vol=5000, ask_vol=1000)
        result = engine.compute(snap)
        assert result["depth_imbalance"] > 0.6
        assert result["volume_imbalance_ratio"] > 0.6

    def test_ask_heavy_imbalance(self, engine):
        snap = _make_snapshot(bid_vol=1000, ask_vol=5000)
        result = engine.compute(snap)
        assert result["depth_imbalance"] < 0.4

    def test_tight_spread(self, engine):
        snap = _make_snapshot(spread=0.01)
        result = engine.compute(snap)
        assert result["spread_normalized"] > 0.7

    def test_wide_spread(self, engine):
        snap = _make_snapshot(spread=0.10)
        result = engine.compute(snap)
        assert result["spread_normalized"] < 0.5

    def test_compute_batch(self, engine):
        data = {
            "600519": {
                "snapshot": _make_snapshot(),
                "history": None,
                "ticks": None,
            },
            "000001": {
                "snapshot": _make_snapshot(bid_vol=3000),
                "history": None,
                "ticks": None,
            },
        }
        result = engine.compute_batch(data)
        assert "600519" in result
        assert "000001" in result

    def test_bid_wall_detection(self, engine):
        """Very large bid at one level should trigger wall detection."""
        from src.data.level2_provider import OrderBookSnapshot

        snap = OrderBookSnapshot(
            symbol="test",
            timestamp=1000.0,
            last_price=10.0,
            bid_prices=[9.99, 9.98, 9.97],
            bid_volumes=[50000, 100, 100],  # Wall at 9.99
            ask_prices=[10.01, 10.02],
            ask_volumes=[100, 100],
            spread=0.02,
            mid_price=10.0,
            total_bid_volume=50200,
            total_ask_volume=200,
        )
        result = engine.compute(snap)
        assert result["bid_wall_strength"] > 0.5

    def test_order_flow_imbalance_with_history(self, engine):
        """OFI should respond to bid volume changes across snapshots."""
        snap1 = _make_snapshot(bid_vol=1000, ask_vol=1000)
        snap2 = _make_snapshot(bid_vol=2000, ask_vol=1000)
        result = engine.compute(snap2, history=[snap1, snap2])
        assert result["order_flow_imbalance"] > 0.5

    def test_micro_momentum_rising(self, engine):
        """Rising mid prices across snapshots should yield >0.5 momentum."""
        from src.data.level2_provider import OrderBookSnapshot

        history = []
        for i in range(5):
            p = 10.0 + i * 0.05
            history.append(
                OrderBookSnapshot(
                    symbol="test",
                    timestamp=1000.0 + i,
                    last_price=p,
                    bid_prices=[p - 0.01],
                    bid_volumes=[100],
                    ask_prices=[p + 0.01],
                    ask_volumes=[100],
                )
            )
        result = engine.compute(history[-1], history=history)
        assert result["micro_momentum"] > 0.5

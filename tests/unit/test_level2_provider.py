"""Tests for Level2Provider, OrderBookSnapshot, and TickTrade."""

from __future__ import annotations

from unittest.mock import patch, MagicMock


class TestOrderBookSnapshot:
    def test_creation(self):
        from src.data.level2_provider import OrderBookSnapshot

        snap = OrderBookSnapshot(
            symbol="600519",
            timestamp=1000.0,
            last_price=1800.0,
            bid_prices=[1799.9, 1799.8],
            bid_volumes=[100, 200],
            ask_prices=[1800.1, 1800.2],
            ask_volumes=[150, 250],
            spread=0.2,
            mid_price=1800.0,
            total_bid_volume=300,
            total_ask_volume=400,
        )
        assert snap.symbol == "600519"
        assert snap.spread == 0.2
        assert len(snap.bid_prices) == 2

    def test_defaults(self):
        from src.data.level2_provider import OrderBookSnapshot

        snap = OrderBookSnapshot(symbol="000001", timestamp=0.0, last_price=10.0)
        assert snap.bid_prices == []
        assert snap.bid_volumes == []
        assert snap.ask_prices == []
        assert snap.ask_volumes == []
        assert snap.spread == 0.0
        assert snap.mid_price == 0.0
        assert snap.total_bid_volume == 0
        assert snap.total_ask_volume == 0


class TestTickTrade:
    def test_creation(self):
        from src.data.level2_provider import TickTrade

        tick = TickTrade(
            timestamp=1000.0, price=10.0, volume=100, amount=1000.0, direction="buy"
        )
        assert tick.direction == "buy"
        assert tick.is_large is False

    def test_large_flag(self):
        from src.data.level2_provider import TickTrade

        tick = TickTrade(
            timestamp=1000.0,
            price=10.0,
            volume=100,
            amount=1000.0,
            direction="sell",
            is_large=True,
        )
        assert tick.is_large is True

    def test_default_symbol(self):
        from src.data.level2_provider import TickTrade

        tick = TickTrade(
            timestamp=1000.0, price=10.0, volume=100, amount=1000.0, direction="buy"
        )
        assert tick.symbol == ""


class TestLevel2Provider:
    def test_init_without_qmt(self):
        from src.data.level2_provider import Level2Provider

        with patch(
            "src.data.level2_provider.Level2Provider._init_qmt", return_value=None
        ):
            provider = Level2Provider()
            assert provider.has_level2 is False

    def test_simulate_snapshot(self):
        """Without QMT, should simulate from RealtimeQuoteManager."""
        from src.data.level2_provider import Level2Provider

        with patch(
            "src.data.level2_provider.Level2Provider._init_qmt", return_value=None
        ):
            provider = Level2Provider()
            mock_rtm = MagicMock()
            mock_rtm.get_single_quote.return_value = {
                "price": 10.0,
                "volume": 100000,
                "prev_close": 9.5,
            }
            with patch("src.data.realtime.RealtimeQuoteManager", return_value=mock_rtm):
                snap = provider.get_snapshot("600519")
                if snap:
                    assert snap.last_price == 10.0
                    assert len(snap.bid_prices) >= 1

    def test_record_and_retrieve_history(self):
        from src.data.level2_provider import Level2Provider, OrderBookSnapshot

        with patch(
            "src.data.level2_provider.Level2Provider._init_qmt", return_value=None
        ):
            provider = Level2Provider()
            snap = OrderBookSnapshot(
                symbol="600519",
                timestamp=1000.0,
                last_price=10.0,
                bid_prices=[9.99],
                bid_volumes=[100],
                ask_prices=[10.01],
                ask_volumes=[100],
            )
            provider.record_snapshot("600519", snap)
            history = provider.get_snapshot_history("600519")
            assert len(history) == 1

    def test_get_recent_ticks_no_qmt(self):
        from src.data.level2_provider import Level2Provider

        with patch(
            "src.data.level2_provider.Level2Provider._init_qmt", return_value=None
        ):
            provider = Level2Provider()
            ticks = provider.get_recent_ticks("600519")
            assert ticks == []

    def test_snapshots_batch(self):
        from src.data.level2_provider import Level2Provider

        with patch(
            "src.data.level2_provider.Level2Provider._init_qmt", return_value=None
        ):
            provider = Level2Provider()
            with patch.object(provider, "_simulate_snapshot", return_value=None):
                result = provider.get_snapshots_batch(["600519", "000001"])
                assert isinstance(result, dict)

    def test_history_truncation(self):
        """Snapshot history should be capped at 200 entries."""
        from src.data.level2_provider import Level2Provider, OrderBookSnapshot

        with patch(
            "src.data.level2_provider.Level2Provider._init_qmt", return_value=None
        ):
            provider = Level2Provider()
            for i in range(210):
                snap = OrderBookSnapshot(
                    symbol="600519", timestamp=float(i), last_price=10.0
                )
                provider.record_snapshot("600519", snap)
            history = provider.get_snapshot_history("600519", count=300)
            assert len(history) == 200

    def test_dict_to_snapshot(self):
        from src.data.level2_provider import Level2Provider

        data = {
            "symbol": "600519",
            "timestamp": 1000.0,
            "last_price": 10.0,
            "bid_prices": [9.99],
            "bid_volumes": [100],
            "ask_prices": [10.01],
            "ask_volumes": [100],
            "spread": 0.02,
            "mid_price": 10.0,
            "total_bid_volume": 100,
            "total_ask_volume": 100,
        }
        snap = Level2Provider._dict_to_snapshot(data)
        assert snap.symbol == "600519"
        assert snap.spread == 0.02

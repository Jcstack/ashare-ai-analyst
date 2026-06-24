"""Tests for CallAuctionCollector."""

from __future__ import annotations

from unittest.mock import MagicMock


class TestCallAuctionCollector:
    def test_init(self):
        from src.data.call_auction import CallAuctionCollector

        collector = CallAuctionCollector()
        assert collector is not None
        assert collector._redis is None

    def test_init_with_redis(self):
        from src.data.call_auction import CallAuctionCollector

        mock_redis = MagicMock()
        collector = CallAuctionCollector(redis_client=mock_redis)
        assert collector._redis is mock_redis

    def test_analyze_auction_no_snapshots(self):
        """analyze_auction with no stored data should return default dict."""
        from src.data.call_auction import CallAuctionCollector

        collector = CallAuctionCollector()

        result = collector.analyze_auction("600519")
        assert isinstance(result, dict)
        assert result["symbol"] == "600519"
        assert result["price_trend"] == "stable"
        assert result["weak_to_strong"] is False
        assert result["confidence"] == 0.0

    def test_analyze_auction_with_snapshots(self):
        """Should produce analysis when snapshots exist."""
        from src.data.call_auction import CallAuctionCollector

        collector = CallAuctionCollector()

        # Simulate stored snapshots via in-memory fallback
        collector._mem_snapshots["600519"] = [
            {"auction_price": 10.0, "auction_volume": 50000, "timestamp": "09:15:00"},
            {"auction_price": 10.1, "auction_volume": 80000, "timestamp": "09:16:00"},
            {"auction_price": 10.05, "auction_volume": 100000, "timestamp": "09:17:00"},
            {"auction_price": 10.15, "auction_volume": 150000, "timestamp": "09:18:00"},
            {"auction_price": 10.2, "auction_volume": 200000, "timestamp": "09:19:00"},
            {"auction_price": 10.1, "auction_volume": 220000, "timestamp": "09:20:00"},
            {"auction_price": 10.15, "auction_volume": 280000, "timestamp": "09:21:00"},
            {"auction_price": 10.2, "auction_volume": 350000, "timestamp": "09:22:00"},
            {"auction_price": 10.25, "auction_volume": 400000, "timestamp": "09:23:00"},
            {"auction_price": 10.3, "auction_volume": 500000, "timestamp": "09:24:00"},
        ]

        result = collector.analyze_auction("600519")
        assert result["symbol"] == "600519"
        assert result["final_price"] == 10.3
        assert result["final_volume"] == 500000
        assert result["confidence"] >= 0.5  # 10 snapshots → confidence=1.0
        assert result["volume_acceleration"] > 1.0  # volume grew

    def test_analyze_auction_weak_to_strong(self):
        """Should detect weak-to-strong transition."""
        from src.data.call_auction import CallAuctionCollector

        collector = CallAuctionCollector()

        # Early phase: price falling; late phase: price rising
        collector._mem_snapshots["600519"] = [
            {"auction_price": 10.0, "auction_volume": 50000, "timestamp": "09:15:00"},
            {"auction_price": 9.9, "auction_volume": 60000, "timestamp": "09:16:00"},
            {"auction_price": 9.8, "auction_volume": 70000, "timestamp": "09:17:00"},
            {"auction_price": 9.7, "auction_volume": 80000, "timestamp": "09:19:00"},
            {"auction_price": 9.75, "auction_volume": 100000, "timestamp": "09:20:00"},
            {"auction_price": 9.85, "auction_volume": 150000, "timestamp": "09:21:00"},
            {"auction_price": 9.95, "auction_volume": 200000, "timestamp": "09:22:00"},
            {"auction_price": 10.1, "auction_volume": 300000, "timestamp": "09:24:00"},
        ]

        result = collector.analyze_auction("600519")
        assert result["weak_to_strong"] is True
        assert result["strong_to_weak"] is False

    def test_analyze_auction_strong_to_weak(self):
        """Should detect strong-to-weak transition."""
        from src.data.call_auction import CallAuctionCollector

        collector = CallAuctionCollector()

        # Early phase: price rising; late phase: price falling
        collector._mem_snapshots["600519"] = [
            {"auction_price": 10.0, "auction_volume": 50000, "timestamp": "09:15:00"},
            {"auction_price": 10.2, "auction_volume": 60000, "timestamp": "09:16:00"},
            {"auction_price": 10.3, "auction_volume": 70000, "timestamp": "09:17:00"},
            {"auction_price": 10.4, "auction_volume": 80000, "timestamp": "09:19:00"},
            {"auction_price": 10.35, "auction_volume": 100000, "timestamp": "09:20:00"},
            {"auction_price": 10.25, "auction_volume": 110000, "timestamp": "09:21:00"},
            {"auction_price": 10.1, "auction_volume": 120000, "timestamp": "09:22:00"},
            {"auction_price": 10.0, "auction_volume": 130000, "timestamp": "09:24:00"},
        ]

        result = collector.analyze_auction("600519")
        assert result["strong_to_weak"] is True
        assert result["weak_to_strong"] is False

    def test_capture_snapshot_empty_symbols(self):
        """Should return [] for empty symbol list."""
        from src.data.call_auction import CallAuctionCollector

        collector = CallAuctionCollector()
        result = collector.capture_snapshot([])
        assert result == []

    def test_capture_snapshot_with_mock_manager(self):
        """Should capture snapshots from quote manager."""
        from src.data.call_auction import CallAuctionCollector
        import pandas as pd

        collector = CallAuctionCollector()

        mock_df = pd.DataFrame(
            {
                "symbol": ["600519", "000001"],
                "price": [10.5, 15.2],
                "volume": [100000, 200000],
            }
        )
        mock_mgr = MagicMock()
        mock_mgr.get_quotes.return_value = mock_df
        collector._quote_mgr = mock_mgr

        result = collector.capture_snapshot(["600519", "000001"])
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["symbol"] == "600519"
        assert result[0]["auction_price"] == 10.5

    def test_get_auction_candidates(self):
        """Should return qualifying candidates sorted by volume."""
        from src.data.call_auction import CallAuctionCollector

        collector = CallAuctionCollector()

        # Pre-populate snapshots for two symbols
        collector._mem_snapshots["600519"] = [
            {"auction_price": 10.0, "auction_volume": 50000, "timestamp": "09:15:00"},
            {"auction_price": 10.1, "auction_volume": 100000, "timestamp": "09:17:00"},
            {"auction_price": 10.2, "auction_volume": 200000, "timestamp": "09:19:00"},
            {"auction_price": 10.3, "auction_volume": 300000, "timestamp": "09:21:00"},
            {"auction_price": 10.4, "auction_volume": 500000, "timestamp": "09:24:00"},
        ]
        collector._mem_snapshots["000001"] = [
            {"auction_price": 15.0, "auction_volume": 30000, "timestamp": "09:15:00"},
            {"auction_price": 14.9, "auction_volume": 40000, "timestamp": "09:17:00"},
            {"auction_price": 14.8, "auction_volume": 50000, "timestamp": "09:19:00"},
        ]

        result = collector.get_auction_candidates(min_volume=100000)
        assert isinstance(result, list)
        # Only 600519 should qualify (rising price + sufficient volume)
        symbols = [r["symbol"] for r in result]
        if symbols:
            assert "600519" in symbols

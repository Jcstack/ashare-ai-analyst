"""Unit tests for RealtimeQuoteManager + QMT integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRealtimeQMTFallback:
    """Test that QMT is used as first source and falls back correctly."""

    @pytest.fixture
    def mock_qmt(self):
        """Create a mock QmtDataAdapter."""
        adapter = MagicMock()
        adapter.is_available.return_value = True
        adapter.get_realtime_quotes.return_value = [
            {
                "symbol": "600000",
                "name": "",
                "price": 10.5,
                "change": 0.5,
                "pct_change": 5.0,
                "open": 10.0,
                "high": 10.8,
                "low": 9.9,
                "prev_close": 10.0,
                "volume": 1000000,
                "amount": 10500000,
            }
        ]
        return adapter

    @pytest.fixture
    def manager(self, mock_qmt):
        """Create a RealtimeQuoteManager with mocked QMT."""
        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.source_router.load_config") as mock_router_cfg,
        ):
            mock_cfg.return_value = {"realtime": {"cache_ttl_seconds": 0}}
            mock_router_cfg.return_value = {"data_sources": {}}
            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager(qmt_adapter=mock_qmt)
            return mgr

    def test_qmt_used_when_available(self, manager, mock_qmt):
        """QMT should be the first source tried."""
        df = manager.get_quotes(["600000"])
        assert not df.empty
        assert df.iloc[0]["symbol"] == "600000"
        assert df.iloc[0]["price"] == 10.5
        mock_qmt.get_realtime_quotes.assert_called_once()

    def test_fallback_when_qmt_unavailable(self):
        """Should fall back to other sources when QMT is unavailable."""
        mock_qmt = MagicMock()
        mock_qmt.is_available.return_value = False

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.source_router.load_config") as mock_router_cfg,
        ):
            mock_cfg.return_value = {"realtime": {"cache_ttl_seconds": 0}}
            mock_router_cfg.return_value = {"data_sources": {}}
            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager(qmt_adapter=mock_qmt)

            # All sources will fail since we haven't mocked them,
            # but QMT should not be called
            mgr.get_quotes(["600000"])
            mock_qmt.get_realtime_quotes.assert_not_called()

    def test_no_qmt_adapter(self):
        """Should work without crashing when no QMT adapter is provided."""
        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.source_router.load_config") as mock_router_cfg,
            patch("src.data.realtime._requests") as mock_requests,
            patch("src.data.realtime._HAS_ADATA", False),
        ):
            mock_cfg.side_effect = [
                {},  # stocks config validation
                {"realtime": {"cache_ttl_seconds": 0}},  # agent config
            ]
            mock_router_cfg.return_value = {"data_sources": {}}
            mock_requests.Session.side_effect = Exception("mocked")
            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager(qmt_adapter=None)
            # Should not raise — gracefully skips QMT and all fallback sources
            df = mgr.get_quotes(["600000"])
            assert df.empty


class TestStockServiceQMTMinute:
    """Test StockService minute data with QMT."""

    def test_qmt_minute_bars_used(self):
        """QMT minute bars should be tried before AKShare."""
        import pandas as pd

        mock_qmt = MagicMock()
        mock_qmt.is_available.return_value = True
        mock_qmt.get_minute_bars.return_value = pd.DataFrame(
            {
                "date": ["2024-01-01 09:35:00"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.9],
                "close": [10.3],
                "volume": [100],
            }
        )

        from src.web.services.stock_service import StockService

        with patch("src.web.services.stock_service.load_config") as mock_cfg:
            mock_cfg.return_value = {"watchlist": []}
            svc = StockService(qmt_adapter=mock_qmt)
            df = svc._fetch_minute_data("600000", "5")
            assert df is not None
            assert not df.empty
            mock_qmt.get_minute_bars.assert_called_once_with("600000", "5")

    def test_qmt_tick_data_used(self):
        """QMT tick data should be tried before AKShare."""
        mock_qmt = MagicMock()
        mock_qmt.is_available.return_value = True
        mock_qmt.get_tick_data.return_value = {
            "stats": {
                "buy_volume": 500,
                "sell_volume": 300,
                "neutral_volume": 0,
                "total_volume": 800,
                "buy_ratio": 0.625,
                "sell_ratio": 0.375,
            },
            "recent_ticks": [],
            "is_historical": False,
        }

        from src.web.services.stock_service import StockService

        with patch("src.web.services.stock_service.load_config") as mock_cfg:
            mock_cfg.return_value = {"watchlist": []}
            svc = StockService(qmt_adapter=mock_qmt)
            result = svc.get_intraday_trades("600000")
            assert result is not None
            assert result["buy_volume"] == 500
            mock_qmt.get_tick_data.assert_called_once()

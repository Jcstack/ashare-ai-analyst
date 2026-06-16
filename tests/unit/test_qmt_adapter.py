"""Unit tests for QmtDataAdapter with mocked xtdata."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.qmt_adapter import QmtDataAdapter


@pytest.fixture
def adapter():
    """Create a QmtDataAdapter with QMT enabled in config."""
    with patch("src.data.qmt_adapter.load_config") as mock_cfg:
        mock_cfg.return_value = {
            "data_sources": {
                "qmt": {"enabled": True, "mini_qmt_path": "/mock/path"},
            },
        }
        return QmtDataAdapter()


class TestSymbolConversion:
    """Test XtQuant symbol format conversion."""

    def test_to_xt_code_shanghai(self):
        assert QmtDataAdapter.to_xt_code("600000") == "600000.SH"
        assert QmtDataAdapter.to_xt_code("688001") == "688001.SH"

    def test_to_xt_code_shenzhen(self):
        assert QmtDataAdapter.to_xt_code("000001") == "000001.SZ"
        assert QmtDataAdapter.to_xt_code("300750") == "300750.SZ"

    def test_from_xt_code(self):
        assert QmtDataAdapter.from_xt_code("600000.SH") == "600000"
        assert QmtDataAdapter.from_xt_code("000001.SZ") == "000001"


class TestIsAvailable:
    """Test availability checking."""

    def test_not_available_when_xtdata_missing(self, adapter):
        with patch("src.data.qmt_adapter._HAS_XTDATA", False):
            assert adapter.is_available() is False

    def test_not_available_when_disabled(self):
        with patch("src.data.qmt_adapter.load_config") as mock_cfg:
            mock_cfg.return_value = {
                "data_sources": {"qmt": {"enabled": False}},
            }
            a = QmtDataAdapter()
            assert a.is_available() is False


class TestConnect:
    """Test connection lifecycle."""

    def test_connect_success(self, adapter):
        with (
            patch("src.data.qmt_adapter._HAS_XTDATA", True),
            patch("src.data.qmt_adapter.xtdata") as mock_xt,
        ):
            mock_xt.connect = MagicMock()
            assert adapter.connect() is True
            assert adapter._connected is True

    def test_connect_failure(self, adapter):
        with (
            patch("src.data.qmt_adapter._HAS_XTDATA", True),
            patch("src.data.qmt_adapter.xtdata") as mock_xt,
        ):
            mock_xt.connect = MagicMock(side_effect=Exception("Connection refused"))
            assert adapter.connect() is False
            assert adapter._connected is False

    def test_connect_returns_false_when_not_installed(self, adapter):
        with patch("src.data.qmt_adapter._HAS_XTDATA", False):
            assert adapter.connect() is False


class TestGetRealtimeQuotes:
    """Test real-time quote fetching."""

    def test_returns_empty_when_unavailable(self, adapter):
        with patch("src.data.qmt_adapter._HAS_XTDATA", False):
            result = adapter.get_realtime_quotes(["600000"])
            assert result == []

    def test_returns_quotes_with_computed_change(self, adapter):
        adapter._connected = True
        mock_tick = {
            "600000.SH": {
                "lastPrice": 10.5,
                "open": 10.0,
                "high": 10.8,
                "low": 9.9,
                "lastClose": 10.0,
                "volume": 1000000,
                "amount": 10500000,
            },
        }
        with (
            patch("src.data.qmt_adapter._HAS_XTDATA", True),
            patch("src.data.qmt_adapter.xtdata") as mock_xt,
        ):
            mock_xt.get_full_tick = MagicMock(return_value=mock_tick)
            result = adapter.get_realtime_quotes(["600000"])

            assert len(result) == 1
            q = result[0]
            assert q["symbol"] == "600000"
            assert q["price"] == 10.5
            assert q["prev_close"] == 10.0
            assert q["change"] == 0.5
            assert q["pct_change"] == 5.0

    def test_handles_exception_gracefully(self, adapter):
        adapter._connected = True
        with (
            patch("src.data.qmt_adapter._HAS_XTDATA", True),
            patch("src.data.qmt_adapter.xtdata") as mock_xt,
        ):
            mock_xt.get_full_tick = MagicMock(side_effect=Exception("Network error"))
            result = adapter.get_realtime_quotes(["600000"])
            assert result == []
            assert adapter._connected is False


class TestGetMinuteBars:
    """Test minute K-line data."""

    def test_returns_none_when_unavailable(self, adapter):
        with patch("src.data.qmt_adapter._HAS_XTDATA", False):
            result = adapter.get_minute_bars("600000", "5")
            assert result is None

    def test_returns_dataframe_with_correct_columns(self, adapter):
        adapter._connected = True
        mock_df = pd.DataFrame(
            {
                "time": [1700000000000, 1700000300000],
                "open": [10.0, 10.1],
                "high": [10.2, 10.3],
                "low": [9.9, 10.0],
                "close": [10.1, 10.2],
                "volume": [100, 200],
                "amount": [1010, 2040],
            }
        )
        with (
            patch("src.data.qmt_adapter._HAS_XTDATA", True),
            patch("src.data.qmt_adapter.xtdata") as mock_xt,
        ):
            mock_xt.get_market_data_ex = MagicMock(return_value={"600000.SH": mock_df})
            result = adapter.get_minute_bars("600000", "5")
            assert result is not None
            assert "date" in result.columns
            assert "close" in result.columns

    def test_invalid_period_returns_none(self, adapter):
        adapter._connected = True
        with patch("src.data.qmt_adapter._HAS_XTDATA", True):
            result = adapter.get_minute_bars("600000", "99")
            assert result is None


class TestGetDailyOhlcv:
    """Test daily OHLCV data."""

    def test_returns_none_when_unavailable(self, adapter):
        with patch("src.data.qmt_adapter._HAS_XTDATA", False):
            result = adapter.get_daily_ohlcv("600000")
            assert result is None

    def test_returns_dataframe(self, adapter):
        adapter._connected = True
        mock_df = pd.DataFrame(
            {
                "time": [1700000000000],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.3],
                "volume": [5000],
                "amount": [51500],
            }
        )
        with (
            patch("src.data.qmt_adapter._HAS_XTDATA", True),
            patch("src.data.qmt_adapter.xtdata") as mock_xt,
        ):
            mock_xt.get_market_data_ex = MagicMock(return_value={"600000.SH": mock_df})
            result = adapter.get_daily_ohlcv("600000")
            assert result is not None
            assert "date" in result.columns
            assert "close" in result.columns


class TestGetTickData:
    """Test tick data retrieval."""

    def test_returns_none_when_unavailable(self, adapter):
        with patch("src.data.qmt_adapter._HAS_XTDATA", False):
            result = adapter.get_tick_data("600000")
            assert result is None

    def test_returns_stats_dict(self, adapter):
        adapter._connected = True
        mock_tick = {
            "600000.SH": {
                "lastPrice": 10.5,
                "volume": 1000,
                "askPrice": [10.6, 10.7],
                "bidPrice": [10.4, 10.3],
            },
        }
        with (
            patch("src.data.qmt_adapter._HAS_XTDATA", True),
            patch("src.data.qmt_adapter.xtdata") as mock_xt,
        ):
            mock_xt.get_full_tick = MagicMock(return_value=mock_tick)
            result = adapter.get_tick_data("600000")
            assert result is not None
            assert "stats" in result
            assert "recent_ticks" in result
            assert result["stats"]["total_volume"] > 0


class TestHealthInfo:
    """Test health info output."""

    def test_health_info_structure(self, adapter):
        info = adapter.get_health_info()
        assert "installed" in info
        assert "enabled" in info
        assert "connected" in info
        assert "active_subscriptions" in info


class TestSourceRouterQMT:
    """Test that QMT is included in the source router."""

    def test_qmt_in_source_domain(self):
        from src.data.source_router import SourceDomain

        assert hasattr(SourceDomain, "QMT")
        assert SourceDomain.QMT.value == "qmt"

    def test_qmt_first_in_realtime_sources(self):
        from src.data.source_router import DataSourceRouter

        with patch("src.data.source_router.load_config") as mock_cfg:
            mock_cfg.return_value = {"data_sources": {}}
            router = DataSourceRouter()
            sources = router.get_realtime_sources()
            from src.data.source_router import SourceDomain

            assert sources[0] == SourceDomain.QMT

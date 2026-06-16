"""Tests for StockService — the web service layer wrapping core modules.

Mocks external dependencies (AKShare) to test service logic in isolation.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


@pytest.fixture
def mock_ohlcv_30d():
    """30-day OHLCV DataFrame for testing service methods."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-02", periods=30, freq="B"),
            "open": [10.0 + i * 0.1 for i in range(30)],
            "close": [10.1 + i * 0.1 for i in range(30)],
            "high": [10.3 + i * 0.1 for i in range(30)],
            "low": [9.9 + i * 0.1 for i in range(30)],
            "volume": [1000000 + i * 10000 for i in range(30)],
            "amount": [1e7 + i * 1e5 for i in range(30)],
        }
    )


@pytest.fixture
def stock_service(mock_ohlcv_30d):
    """Create a StockService with mocked fetcher."""
    with patch("src.web.services.stock_service.StockDataFetcher") as mock_cls:
        mock_fetcher = MagicMock()
        mock_fetcher.config = {
            "watchlist": [
                {"symbol": "000001", "name": "平安银行", "board": "main"},
                {"symbol": "600519", "name": "贵州茅台", "board": "main"},
                {"symbol": "300750", "name": "宁德时代", "board": "chinext"},
            ],
        }
        mock_fetcher.fetch_daily_ohlcv.return_value = mock_ohlcv_30d
        mock_cls.return_value = mock_fetcher

        with patch("src.web.services.stock_service.load_config") as mock_cfg:
            mock_cfg.return_value = mock_fetcher.config

            from src.web.services.stock_service import StockService

            svc = StockService()
            yield svc


class TestGetWatchlist:
    """Tests for StockService.get_watchlist."""

    def test_returns_list(self, stock_service):
        """Should return a list of watchlist entries."""
        result = stock_service.get_watchlist()
        assert isinstance(result, list)

    def test_watchlist_count(self, stock_service):
        """Should return all configured watchlist items."""
        result = stock_service.get_watchlist()
        assert len(result) == 3

    def test_watchlist_entry_keys(self, stock_service):
        """Each entry should have symbol, name, board keys."""
        result = stock_service.get_watchlist()
        for entry in result:
            assert "symbol" in entry
            assert "name" in entry
            assert "board" in entry


class TestGetStockData:
    """Tests for StockService.get_stock_data."""

    def test_returns_dataframe(self, stock_service):
        """Should return a pandas DataFrame."""
        df = stock_service.get_stock_data("000001")
        assert isinstance(df, pd.DataFrame)

    def test_has_ohlcv_columns(self, stock_service):
        """Returned DataFrame should have OHLCV columns."""
        df = stock_service.get_stock_data("000001")
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in df.columns

    def test_returns_none_on_error(self, stock_service):
        """Should return None when fetcher raises an error."""
        from src.data.fetcher import DataCollectionError

        stock_service._fetcher.fetch_daily_ohlcv.side_effect = DataCollectionError(
            "fail"
        )
        result = stock_service.get_stock_data("999999")
        assert result is None


class TestGetLatestPriceInfo:
    """Tests for StockService.get_latest_price_info."""

    def test_returns_dict(self, stock_service):
        """Should return a dict with price info."""
        info = stock_service.get_latest_price_info("000001")
        assert isinstance(info, dict)

    def test_has_required_keys(self, stock_service):
        """Dict should contain all required price fields."""
        info = stock_service.get_latest_price_info("000001")
        for key in ["close", "open", "high", "low", "change", "pct_change", "volume"]:
            assert key in info

    def test_close_is_float(self, stock_service):
        """Close price should be a float."""
        info = stock_service.get_latest_price_info("000001")
        assert isinstance(info["close"], float)

    def test_volume_is_int(self, stock_service):
        """Volume should be an integer."""
        info = stock_service.get_latest_price_info("000001")
        assert isinstance(info["volume"], int)


class TestGetStockWithIndicators:
    """Tests for StockService.get_stock_with_indicators."""

    def test_returns_dataframe_with_indicators(self, stock_service):
        """Should return a DataFrame with indicator columns added."""
        df = stock_service.get_stock_with_indicators("000001")
        assert isinstance(df, pd.DataFrame)
        # Should have at least some indicator columns
        indicator_cols = [
            c
            for c in df.columns
            if c.startswith(("MA_", "EMA_", "MACD", "RSI", "KDJ", "BB_"))
        ]
        assert len(indicator_cols) > 0


class TestGenerateChartHtml:
    """Tests for StockService.generate_candlestick_chart_html."""

    def test_returns_html_string(self, stock_service):
        """Should return an HTML string."""
        html = stock_service.generate_candlestick_chart_html("000001")
        assert isinstance(html, str)
        assert len(html) > 0

    def test_contains_plotly_div(self, stock_service):
        """HTML should contain a Plotly chart div."""
        html = stock_service.generate_candlestick_chart_html("000001")
        assert "plotly" in html.lower() or "chart-container" in html

    def test_error_on_missing_data(self, stock_service):
        """Should return error div when data is unavailable."""
        from src.data.fetcher import DataCollectionError

        stock_service._fetcher.fetch_daily_ohlcv.side_effect = DataCollectionError(
            "fail"
        )
        html = stock_service.generate_candlestick_chart_html("999999")
        assert "alert" in html or "无法加载" in html


class TestFindStockName:
    """Tests for StockService._find_stock_name."""

    def test_finds_known_stock(self, stock_service):
        """Should return Chinese name for known symbols."""
        name = stock_service._find_stock_name("600519")
        assert name == "贵州茅台"

    def test_returns_symbol_for_unknown(self, stock_service):
        """Should return the symbol itself for unknown stocks."""
        name = stock_service._find_stock_name("999999")
        assert name == "999999"


class TestGetIndicatorsSummary:
    """Tests for StockService.get_indicators_summary."""

    def test_returns_dict(self, stock_service):
        """Should return a dict of indicator values."""
        summary = stock_service.get_indicators_summary("000001")
        assert isinstance(summary, dict)

    def test_contains_rsi(self, stock_service):
        """Summary should include RSI value."""
        summary = stock_service.get_indicators_summary("000001")
        assert "RSI" in summary

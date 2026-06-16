"""Tests for GlobalMarketFetcher.

Per PRD v3.2 FR-GM001.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.data.global_market import GlobalMarketFetcher


@pytest.fixture
def fetcher():
    """Create a GlobalMarketFetcher with mock config."""
    with patch("src.data.global_market.load_config") as mock_cfg:
        mock_cfg.return_value = {
            "indices": [
                {"symbol": "^GSPC", "name": "S&P500", "region": "US"},
                {"symbol": "^DJI", "name": "Dow", "region": "US"},
            ],
            "commodities": [
                {"symbol": "GC=F", "name": "Gold", "unit": "USD/oz"},
            ],
            "currencies": [
                {"symbol": "CNY=X", "name": "USD/CNY"},
            ],
            "cache_ttl": 300,
            "rate_limit_interval": 0.01,  # fast for tests
        }
        yield GlobalMarketFetcher()


def _make_mock_ticker(last_price=100.0, prev_close=98.0):
    """Create a mock ticker with fast_info."""
    ticker = MagicMock()
    ticker.fast_info = MagicMock()
    ticker.fast_info.last_price = last_price
    ticker.fast_info.previous_close = prev_close
    return ticker


class TestFetchGlobalIndices:
    def test_returns_indices(self, fetcher):
        """Should return all configured indices with price data."""
        mock_yf = MagicMock()
        mock_tickers = MagicMock()
        mock_tickers.tickers = {
            "^GSPC": _make_mock_ticker(4500.0, 4480.0),
            "^DJI": _make_mock_ticker(35000.0, 34900.0),
        }
        mock_yf.Tickers.return_value = mock_tickers
        fetcher._yf = mock_yf

        result = fetcher.fetch_global_indices()
        assert len(result) == 2
        assert result[0]["name"] == "S&P500"
        assert result[0]["price"] == 4500.0
        assert result[0]["pct_change"] is not None

    def test_cache_hit(self, fetcher):
        """Second call should return cached data."""
        mock_yf = MagicMock()
        mock_tickers = MagicMock()
        mock_tickers.tickers = {
            "^GSPC": _make_mock_ticker(),
            "^DJI": _make_mock_ticker(),
        }
        mock_yf.Tickers.return_value = mock_tickers
        fetcher._yf = mock_yf

        result1 = fetcher.fetch_global_indices()
        result2 = fetcher.fetch_global_indices()
        assert result1 == result2
        # yfinance should only be called once
        assert mock_yf.Tickers.call_count == 1

    def test_handles_yfinance_failure(self, fetcher):
        """Should return partial results when some tickers fail."""
        mock_yf = MagicMock()
        mock_tickers = MagicMock()
        good_ticker = _make_mock_ticker(4500.0, 4480.0)
        mock_tickers.tickers = {
            "^GSPC": good_ticker,
            "^DJI": None,  # Not found
        }
        mock_yf.Tickers.return_value = mock_tickers
        fetcher._yf = mock_yf

        result = fetcher.fetch_global_indices()
        assert len(result) == 2
        # ^GSPC has data, ^DJI does not
        assert result[0]["price"] == 4500.0
        assert result[1]["price"] is None


class TestFetchCommodities:
    def test_returns_commodities(self, fetcher):
        mock_yf = MagicMock()
        mock_tickers = MagicMock()
        mock_tickers.tickers = {
            "GC=F": _make_mock_ticker(2050.0, 2040.0),
        }
        mock_yf.Tickers.return_value = mock_tickers
        fetcher._yf = mock_yf

        result = fetcher.fetch_commodities()
        assert len(result) == 1
        assert result[0]["name"] == "Gold"
        assert result[0]["unit"] == "USD/oz"


class TestFetchCurrencies:
    def test_returns_currencies(self, fetcher):
        mock_yf = MagicMock()
        mock_tickers = MagicMock()
        mock_tickers.tickers = {
            "CNY=X": _make_mock_ticker(7.25, 7.24),
        }
        mock_yf.Tickers.return_value = mock_tickers
        fetcher._yf = mock_yf

        result = fetcher.fetch_currencies()
        assert len(result) == 1
        assert result[0]["name"] == "USD/CNY"


class TestFetchGlobalSnapshot:
    def test_returns_all_categories(self, fetcher):
        mock_yf = MagicMock()
        mock_tickers = MagicMock()
        mock_tickers.tickers = {
            "^GSPC": _make_mock_ticker(),
            "^DJI": _make_mock_ticker(),
            "GC=F": _make_mock_ticker(),
            "CNY=X": _make_mock_ticker(),
        }
        mock_yf.Tickers.return_value = mock_tickers
        fetcher._yf = mock_yf

        result = fetcher.fetch_global_snapshot()
        assert "indices" in result
        assert "commodities" in result
        assert "currencies" in result

    def test_empty_config(self):
        """Should handle empty config gracefully."""
        with patch("src.data.global_market.load_config") as mock_cfg:
            mock_cfg.return_value = {}
            f = GlobalMarketFetcher()
            result = f.fetch_global_snapshot()
            assert result == {"indices": [], "commodities": [], "currencies": []}

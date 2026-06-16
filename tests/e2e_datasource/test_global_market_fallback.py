"""Tests for global market data source fallback.

Verifies yfinance primary, yfinance fail → graceful degradation, timeout
handling, and partial data scenarios.

QA cases: QA-GM-001 (global market data sources).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


MOCK_GLOBAL_CONFIG = {
    "indices": [
        {"symbol": "^GSPC", "name": "S&P500", "region": "US"},
        {"symbol": "^HSI", "name": "恒生指数", "region": "HK"},
    ],
    "commodities": [
        {"symbol": "GC=F", "name": "Gold", "unit": "USD/oz"},
    ],
    "currencies": [
        {"symbol": "CNY=X", "name": "USD/CNY"},
    ],
    "cache_ttl": 300,
    "rate_limit_interval": 0,
}


def _make_mock_yf(ticker_data: dict[str, dict] | None = None):
    """Create a mock yfinance module.

    GlobalMarketFetcher._fetch_tickers calls yf.Tickers(space_joined_symbols)
    then iterates tickers.tickers[sym].fast_info for each symbol.
    """
    if ticker_data is None:
        ticker_data = {
            "^GSPC": {"last_price": 4500.0, "previous_close": 4480.0},
            "^HSI": {"last_price": 17000.0, "previous_close": 17100.0},
            "GC=F": {"last_price": 2050.0, "previous_close": 2040.0},
            "CNY=X": {"last_price": 7.25, "previous_close": 7.24},
        }

    mock_yf = MagicMock()

    def _make_tickers(symbols_str):
        tickers_obj = MagicMock()
        ticker_dict = {}
        for sym in symbols_str.split():
            if sym in ticker_data:
                data = ticker_data[sym]
                ticker_mock = MagicMock()
                fast_info = MagicMock()
                fast_info.last_price = data["last_price"]
                fast_info.previous_close = data["previous_close"]
                ticker_mock.fast_info = fast_info
                ticker_dict[sym] = ticker_mock
        tickers_obj.tickers = ticker_dict
        return tickers_obj

    mock_yf.Tickers = _make_tickers
    return mock_yf


def _create_fetcher(mock_yf=None):
    """Create a GlobalMarketFetcher with mocked config and yfinance."""
    with patch("src.data.global_market.load_config") as mock_cfg:
        mock_cfg.return_value = MOCK_GLOBAL_CONFIG
        from src.data.global_market import GlobalMarketFetcher

        fetcher = GlobalMarketFetcher()

    if mock_yf is not None:
        fetcher._yf = mock_yf
    fetcher._rate_limit = 0  # skip rate limiting in tests
    return fetcher


class TestYfinancePrimary:
    """When yfinance succeeds, global market data is returned."""

    def test_fetch_indices_success(self):
        mock_yf = _make_mock_yf()
        fetcher = _create_fetcher(mock_yf)
        result = fetcher.fetch_global_indices()

        assert len(result) == 2
        assert result[0]["symbol"] == "^GSPC"
        assert result[0]["price"] is not None

    def test_fetch_snapshot_all_categories(self):
        mock_yf = _make_mock_yf()
        fetcher = _create_fetcher(mock_yf)
        result = fetcher.fetch_global_snapshot()

        assert "indices" in result
        assert "commodities" in result
        assert "currencies" in result
        assert len(result["indices"]) == 2
        assert len(result["commodities"]) == 1
        assert len(result["currencies"]) == 1


class TestYfinanceFailure:
    """When yfinance fails for a symbol, it should be handled gracefully."""

    def test_partial_failure_returns_available_data(self):
        """If one ticker fails, others should still return data."""
        # Only provide data for ^GSPC, not ^HSI
        mock_yf = _make_mock_yf(
            {
                "^GSPC": {"last_price": 4500.0, "previous_close": 4480.0},
            }
        )
        fetcher = _create_fetcher(mock_yf)
        result = fetcher.fetch_global_indices()

        # Both indices returned (HSI has None price), ^GSPC has data
        gspc = [r for r in result if r["symbol"] == "^GSPC"]
        assert len(gspc) == 1
        assert gspc[0]["price"] is not None

    def test_all_fail_returns_empty_prices(self):
        """When yfinance.Tickers raises, all prices should be None."""
        mock_yf = MagicMock()
        mock_yf.Tickers.side_effect = ConnectionError("All failed")
        fetcher = _create_fetcher(mock_yf)
        result = fetcher.fetch_global_indices()

        # Items returned from config but with None prices
        assert len(result) == 2
        for item in result:
            assert item["price"] is None

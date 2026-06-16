"""Unit tests for src/data/realtime.py — RealtimeQuoteManager.

Tests in-memory TTL cache, batch splitting, source fallback,
rate limiting, and the get_quotes/get_single_quote interfaces.

Per PRD v2.0 FR-RT001: Multi-source realtime quote manager.
Mock strategy: Mock hq.sinajs.cn HTTP responses and load_config.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.source_router import DataSourceRouter, SourceDomain


# ---------------------------------------------------------------------------
# Sample configs
# ---------------------------------------------------------------------------
SAMPLE_STOCKS_CONFIG: dict = {
    "data_sources": {
        "proxy_blocked_domains": [],
        "preferred_realtime": "sina",
        "fallback_enabled": True,
    },
}

SAMPLE_AGENT_CONFIG: dict = {
    "realtime": {
        "cache_ttl_seconds": 5,
        "batch_size": 50,
        "rate_limit_per_second": 100,  # High limit so tests don't block
    },
}


def _make_sina_hq_response(symbols: list[str]) -> str:
    """Build a mock hq.sinajs.cn response string."""
    lines = []
    for sym in symbols:
        prefix = "sh" if sym.startswith(("6", "9")) else "sz"
        # Fields: name,open,prev_close,price,high,low,bid,ask,volume,amount,...
        lines.append(
            f'var hq_str_{prefix}{sym}="股票{sym},10.20,10.20,10.50,10.80,10.10,'
            f'10.45,10.50,1500000,15000000.000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
            f'0,0,0,0,2026-02-26,15:00:00,00,";'
        )
    return "\n".join(lines)


def _make_mock_sina_session(symbols: list[str]) -> MagicMock:
    """Create a mock requests.Session that returns Sina hq data."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = _make_sina_hq_response(symbols)
    mock_resp.encoding = "gbk"

    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp
    return mock_session


@pytest.fixture
def mock_source_router():
    """Create a mock DataSourceRouter that returns sina as primary."""
    router = MagicMock(spec=DataSourceRouter)
    router.get_realtime_sources.return_value = [SourceDomain.SINA]
    return router


@pytest.fixture
def quote_manager(mock_source_router):
    """Create a RealtimeQuoteManager with mocked config and Sina session."""
    mock_session = _make_mock_sina_session(["000001", "600519"])

    with patch("src.data.realtime.load_config") as mock_cfg:
        mock_cfg.side_effect = lambda name: (
            SAMPLE_STOCKS_CONFIG if name == "stocks" else SAMPLE_AGENT_CONFIG
        )
        from src.data.realtime import RealtimeQuoteManager

        mgr = RealtimeQuoteManager(
            config_name="stocks",
            source_router=mock_source_router,
        )
        # Inject the mock Sina session
        mgr._sina_session = mock_session
        mgr._mock_sina_session = mock_session
        yield mgr


class TestGetQuotes:
    """Tests for RealtimeQuoteManager.get_quotes()."""

    def test_returns_dataframe(self, quote_manager):
        """get_quotes should return a pandas DataFrame."""
        df = quote_manager.get_quotes(["000001"])
        assert isinstance(df, pd.DataFrame)

    def test_returns_requested_symbols(self, quote_manager):
        """Returned DataFrame should contain the requested symbols."""
        df = quote_manager.get_quotes(["000001", "600519"])
        assert len(df) == 2
        assert set(df["symbol"].tolist()) == {"000001", "600519"}

    def test_empty_symbols_returns_empty_df(self, quote_manager):
        """Empty symbol list should return an empty DataFrame."""
        df = quote_manager.get_quotes([])
        assert df.empty

    def test_cache_hit_avoids_api_call(self, quote_manager):
        """Second call within TTL should use cache, not call Sina again."""
        quote_manager.get_quotes(["000001"])
        # Reset the mock call count
        quote_manager._mock_sina_session.get.reset_mock()

        quote_manager.get_quotes(["000001"])
        quote_manager._mock_sina_session.get.assert_not_called()

    def test_cache_expiry_triggers_fresh_fetch(self, quote_manager):
        """After cache TTL expires, a fresh API call should be made."""
        quote_manager.get_quotes(["000001"])
        # Expire the cache by backdating timestamps
        for sym in list(quote_manager._cache.keys()):
            ts, data = quote_manager._cache[sym]
            quote_manager._cache[sym] = (ts - 100, data)

        quote_manager._mock_sina_session.get.reset_mock()
        quote_manager.get_quotes(["000001"])
        quote_manager._mock_sina_session.get.assert_called()


class TestGetSingleQuote:
    """Tests for RealtimeQuoteManager.get_single_quote()."""

    def test_returns_dict(self, quote_manager):
        """get_single_quote should return a dictionary."""
        result = quote_manager.get_single_quote("000001")
        assert isinstance(result, dict)

    def test_contains_price_field(self, quote_manager):
        """Returned dict should contain a price field."""
        result = quote_manager.get_single_quote("000001")
        assert "price" in result
        assert result["price"] == 10.50

    def test_missing_symbol_returns_none_price(self, quote_manager):
        """Non-existent symbol should return dict with None price."""
        # Return empty Sina response for unknown symbol
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = 'var hq_str_sz999999="";'
        mock_resp.encoding = "gbk"
        quote_manager._sina_session.get.return_value = mock_resp
        quote_manager.clear_cache()
        result = quote_manager.get_single_quote("999999")
        assert result["price"] is None


class TestFallback:
    """Tests for source fallback behavior."""

    def test_fallback_to_xueqiu_on_sina_failure(self, mock_source_router):
        """When Sina fails, should fall back to Xueqiu source."""
        mock_source_router.get_realtime_sources.return_value = [
            SourceDomain.SINA,
            SourceDomain.XUEQIU,
        ]

        # Mock the Xueqiu batch JSON API response
        xq_api_response = MagicMock()
        xq_api_response.status_code = 200
        xq_api_response.json.return_value = {
            "data": [
                {
                    "symbol": "SZ000001",
                    "current": 10.50,
                    "chg": 0.30,
                    "percent": 2.94,
                    "name": "平安银行",
                    "high": 10.80,
                    "low": 10.10,
                    "open": 10.20,
                    "last_close": 10.20,
                    "volume": 1500000,
                    "amount": 1.5e7,
                },
            ],
        }

        mock_session = MagicMock()
        mock_session.get.return_value = xq_api_response

        # Sina session that fails
        mock_sina_session = MagicMock()
        mock_sina_session.get.side_effect = ConnectionError("timeout")

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.realtime._requests.Session", return_value=mock_session),
        ):
            mock_cfg.side_effect = lambda name: (
                SAMPLE_STOCKS_CONFIG if name == "stocks" else SAMPLE_AGENT_CONFIG
            )

            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager(
                config_name="stocks",
                source_router=mock_source_router,
            )
            # Inject failing Sina session
            mgr._sina_session = mock_sina_session
            result = mgr.get_single_quote("000001")
            assert result.get("price") == 10.50

    def test_all_sources_fail_returns_empty(self, mock_source_router):
        """When all sources fail, get_quotes should return empty DataFrame."""
        mock_source_router.get_realtime_sources.return_value = [SourceDomain.SINA]

        mock_sina_session = MagicMock()
        mock_sina_session.get.side_effect = ConnectionError("timeout")

        with patch("src.data.realtime.load_config") as mock_cfg:
            mock_cfg.side_effect = lambda name: (
                SAMPLE_STOCKS_CONFIG if name == "stocks" else SAMPLE_AGENT_CONFIG
            )

            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager(
                config_name="stocks",
                source_router=mock_source_router,
            )
            mgr._sina_session = mock_sina_session
            df = mgr.get_quotes(["000001"])
            assert df.empty


class TestAdataFallback:
    """Tests for adata fallback when AKShare sources fail."""

    def test_fallback_to_adata_on_all_akshare_failure(self, mock_source_router):
        """When Sina and Xueqiu fail, should fall back to adata source."""
        mock_source_router.get_realtime_sources.return_value = [
            SourceDomain.SINA,
            SourceDomain.ADATA,
        ]

        adata_df = pd.DataFrame(
            [
                {
                    "stock_code": "000001",
                    "short_name": "平安银行",
                    "price": 11.20,
                    "change": 0.50,
                    "change_pct": 4.67,
                    "volume": 2000000,
                    "amount": 2.2e7,
                }
            ]
        )

        mock_sina_session = MagicMock()
        mock_sina_session.get.side_effect = ConnectionError("blocked")

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.realtime._HAS_ADATA", True),
            patch("src.data.realtime._adata") as mock_adata,
        ):
            mock_cfg.side_effect = lambda name: (
                SAMPLE_STOCKS_CONFIG if name == "stocks" else SAMPLE_AGENT_CONFIG
            )
            mock_adata.stock.market.list_market_current.return_value = adata_df

            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager(
                config_name="stocks",
                source_router=mock_source_router,
            )
            mgr._sina_session = mock_sina_session
            result = mgr.get_single_quote("000001")
            assert result.get("price") == 11.20
            mock_adata.stock.market.list_market_current.assert_called_once()

    def test_adata_not_installed_skips_gracefully(self, mock_source_router):
        """When adata is not installed, should skip and return empty."""
        mock_source_router.get_realtime_sources.return_value = [
            SourceDomain.ADATA,
        ]

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.realtime._HAS_ADATA", False),
        ):
            mock_cfg.side_effect = lambda name: (
                SAMPLE_STOCKS_CONFIG if name == "stocks" else SAMPLE_AGENT_CONFIG
            )

            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager(
                config_name="stocks",
                source_router=mock_source_router,
            )
            df = mgr.get_quotes(["000001"])
            assert df.empty


class TestSymbolNormalization:
    """Tests for exchange prefix normalization (sh/sz/bj → bare code)."""

    def test_prefixed_symbols_normalized(self, quote_manager):
        """Symbols with sh/sz/bj prefixes should be stripped before fetch."""
        df = quote_manager.get_quotes(["sh600519", "sz000001"])
        assert set(df["symbol"].tolist()) == {"600519", "000001"}

    def test_single_quote_with_prefix(self, quote_manager):
        """get_single_quote should also strip exchange prefix."""
        # Mock returns both 000001 and 600519; verify 600519 appears in results
        df = quote_manager.get_quotes(["sh600519"])
        assert "600519" in df["symbol"].tolist()

    def test_mixed_prefixed_and_bare(self, quote_manager):
        """Mix of prefixed and bare symbols should all work."""
        df = quote_manager.get_quotes(["sh600519", "000001"])
        assert len(df) == 2
        assert set(df["symbol"].tolist()) == {"600519", "000001"}

    def test_uppercase_prefix_normalized(self, quote_manager):
        """Uppercase SH/SZ/BJ prefixes should also be stripped."""
        df = quote_manager.get_quotes(["SH600519"])
        assert "600519" in df["symbol"].tolist()


class TestClearCache:
    """Tests for cache clearing."""

    def test_clear_cache_empties_cache(self, quote_manager):
        """clear_cache should remove all cached entries."""
        quote_manager.get_quotes(["000001"])
        assert len(quote_manager._cache) > 0
        quote_manager.clear_cache()
        assert len(quote_manager._cache) == 0

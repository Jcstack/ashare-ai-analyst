"""Tests for realtime quote multi-source fallback chain.

Verifies the Sina → Xueqiu → adata fallback chain behavior:
primary success, primary fail → fallback, all fail → empty, cache behavior.

QA cases: QA-DATA-004 (realtime quotes multi-source).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from src.data.source_router import DataSourceRouter, SourceDomain
from tests.e2e_datasource.conftest import (
    SAMPLE_AGENT_CONFIG,
    SAMPLE_STOCKS_CONFIG,
    make_adata_df,
    make_sina_spot_df,
    make_xueqiu_session,
)


def _create_manager(source_router, mock_ak, mock_cfg):
    """Helper to create a RealtimeQuoteManager with mocked deps."""
    mock_cfg.side_effect = lambda name: (
        SAMPLE_STOCKS_CONFIG if name == "stocks" else SAMPLE_AGENT_CONFIG
    )
    from src.data.realtime import RealtimeQuoteManager

    return RealtimeQuoteManager(config_name="stocks", source_router=source_router)


class TestSinaPrimarySuccess:
    """When Sina (primary) succeeds, data is returned without fallback."""

    def test_sina_returns_quotes(self):
        router = MagicMock(spec=DataSourceRouter)
        router.get_realtime_sources.return_value = [SourceDomain.SINA]

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.realtime.ak") as mock_ak,
        ):
            mock_ak.stock_zh_a_spot.return_value = make_sina_spot_df(["000001"])
            mgr = _create_manager(router, mock_ak, mock_cfg)
            df = mgr.get_quotes(["000001"])

        assert not df.empty
        assert df.iloc[0]["symbol"] == "000001"
        assert df.iloc[0]["price"] == 10.50

    def test_sina_batch_multiple_symbols(self):
        router = MagicMock(spec=DataSourceRouter)
        router.get_realtime_sources.return_value = [SourceDomain.SINA]

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.realtime.ak") as mock_ak,
        ):
            mock_ak.stock_zh_a_spot.return_value = make_sina_spot_df(
                ["000001", "600519"]
            )
            mgr = _create_manager(router, mock_ak, mock_cfg)
            df = mgr.get_quotes(["000001", "600519"])

        assert len(df) == 2
        assert set(df["symbol"].tolist()) == {"000001", "600519"}


class TestSinaFailXueqiuFallback:
    """When Sina fails, system falls back to Xueqiu."""

    def test_fallback_to_xueqiu(self):
        router = MagicMock(spec=DataSourceRouter)
        router.get_realtime_sources.return_value = [
            SourceDomain.SINA,
            SourceDomain.XUEQIU,
        ]
        mock_session = make_xueqiu_session(["000001"])

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.realtime.ak") as mock_ak,
            patch("src.data.realtime._requests.Session", return_value=mock_session),
        ):
            mock_ak.stock_zh_a_spot.side_effect = ConnectionError("Sina timeout")
            mgr = _create_manager(router, mock_ak, mock_cfg)
            result = mgr.get_single_quote("000001")

        assert result.get("price") == 10.50


class TestAllSourcesFailEmpty:
    """When all sources fail, return empty DataFrame."""

    def test_all_fail_returns_empty(self):
        router = MagicMock(spec=DataSourceRouter)
        router.get_realtime_sources.return_value = [SourceDomain.SINA]

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.realtime.ak") as mock_ak,
        ):
            mock_ak.stock_zh_a_spot.side_effect = ConnectionError("fail")
            mgr = _create_manager(router, mock_ak, mock_cfg)
            df = mgr.get_quotes(["000001"])

        assert df.empty


class TestAdataFallback:
    """When Sina fails, adata fallback is used if available."""

    def test_fallback_to_adata(self):
        router = MagicMock(spec=DataSourceRouter)
        router.get_realtime_sources.return_value = [
            SourceDomain.SINA,
            SourceDomain.ADATA,
        ]

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.realtime.ak") as mock_ak,
            patch("src.data.realtime._HAS_ADATA", True),
            patch("src.data.realtime._adata") as mock_adata,
        ):
            mock_ak.stock_zh_a_spot.side_effect = ConnectionError("blocked")
            mock_adata.stock.market.list_market_current.return_value = make_adata_df(
                ["000001"]
            )
            mgr = _create_manager(router, mock_ak, mock_cfg)
            result = mgr.get_single_quote("000001")

        assert result.get("price") == 11.20

    def test_adata_not_installed_graceful(self):
        router = MagicMock(spec=DataSourceRouter)
        router.get_realtime_sources.return_value = [SourceDomain.ADATA]

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.realtime.ak"),
            patch("src.data.realtime._HAS_ADATA", False),
        ):
            mgr = _create_manager(router, MagicMock(), mock_cfg)
            df = mgr.get_quotes(["000001"])

        assert df.empty


class TestCacheBehavior:
    """Cache should serve data within TTL and refresh after expiry."""

    def test_cache_hit_avoids_api(self):
        router = MagicMock(spec=DataSourceRouter)
        router.get_realtime_sources.return_value = [SourceDomain.SINA]

        with (
            patch("src.data.realtime.load_config") as mock_cfg,
            patch("src.data.realtime.ak") as mock_ak,
        ):
            mock_ak.stock_zh_a_spot.return_value = make_sina_spot_df(["000001"])
            mgr = _create_manager(router, mock_ak, mock_cfg)

            mgr.get_quotes(["000001"])
            mock_ak.stock_zh_a_spot.reset_mock()

            # Second call within TTL should use cache
            mgr.get_quotes(["000001"])
            mock_ak.stock_zh_a_spot.assert_not_called()

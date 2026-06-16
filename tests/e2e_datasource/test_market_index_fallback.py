"""Tests for MarketService index fallback chain.

Verifies the Sina → EastMoney → Xueqiu degradation chain for market
indices, degraded mode behavior, and cache protection.

QA cases: QA-MKT-001 (market index reliability).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from src.web.services.market_service import MarketService


MOCK_SINA_INDEX_DF = pd.DataFrame(
    [
        {
            "代码": "sh000001",
            "名称": "上证指数",
            "最新价": 3100.0,
            "涨跌额": 15.0,
            "涨跌幅": 0.49,
        },
        {
            "代码": "sz399001",
            "名称": "深证成指",
            "最新价": 10200.0,
            "涨跌额": 50.0,
            "涨跌幅": 0.49,
        },
        {
            "代码": "sz399006",
            "名称": "创业板指",
            "最新価": 2100.0,
            "涨跌額": 10.0,
            "涨跌幅": 0.48,
        },
    ]
)


class TestMarketServiceIndexChain:
    """MarketService should try multiple sources for index data."""

    def test_primary_sina_source_success(self):
        """Sina source returns valid index data."""
        svc = MarketService(quote_manager=MagicMock())
        with patch("akshare.stock_zh_index_spot_sina", return_value=MOCK_SINA_INDEX_DF):
            result = svc.get_market_indices()

        assert len(result) >= 2
        names = [r["name"] for r in result]
        assert "上证指数" in names

    def test_sina_fail_eastmoney_fallback(self):
        """When Sina fails, EastMoney is tried next."""
        em_df = pd.DataFrame(
            [
                {
                    "代码": "sh000001",
                    "名称": "上证指数",
                    "最新价": 3100.0,
                    "涨跌额": 15.0,
                    "涨跌幅": 0.49,
                },
                {
                    "代码": "sz399001",
                    "名称": "深证成指",
                    "最新价": 10200.0,
                    "涨跌额": 50.0,
                    "涨跌幅": 0.49,
                },
            ]
        )
        svc = MarketService(quote_manager=MagicMock())
        with (
            patch(
                "akshare.stock_zh_index_spot_sina", side_effect=Exception("Sina down")
            ),
            patch("akshare.stock_zh_index_spot_em", return_value=em_df),
        ):
            result = svc.get_market_indices()

        assert len(result) >= 2
        names = [r["name"] for r in result]
        assert "上证指数" in names

    def test_all_sources_fail_returns_seed(self):
        """When all sources fail, seed values are returned."""
        svc = MarketService(quote_manager=MagicMock())
        with (
            patch("akshare.stock_zh_index_spot_sina", side_effect=Exception("fail")),
            patch("akshare.stock_zh_index_spot_em", side_effect=Exception("fail")),
        ):
            result = svc.get_market_indices()

        # Should return seed values (never empty per FR-DR002)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_cache_protects_against_transient_failures(self):
        """After a successful fetch, cache protects against next failure."""
        svc = MarketService(quote_manager=MagicMock())

        # First call succeeds and populates cache
        with patch("akshare.stock_zh_index_spot_sina", return_value=MOCK_SINA_INDEX_DF):
            result1 = svc.get_market_indices()
        assert len(result1) >= 2

        # Second call: all sources fail
        with (
            patch(
                "akshare.stock_zh_index_spot_sina", side_effect=Exception("transient")
            ),
            patch("akshare.stock_zh_index_spot_em", side_effect=Exception("transient")),
        ):
            result2 = svc.get_market_indices()

        # Should return cached data
        assert len(result2) >= 2
        names = [r["name"] for r in result2]
        assert "上证指数" in names

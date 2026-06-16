"""Unit tests for src/data/news_fetcher.py — NewsFetcher.

Tests news fetching, anomaly fetching, hot rank retrieval,
caching behavior, and error handling with fallback to empty DataFrames.

Per PRD v2.0 FR-NF001/NF002, FR-AD001.
Mock strategy: Mock AKShare functions and load_config only.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.source_router import DataSourceRouter, SourceDomain


# ---------------------------------------------------------------------------
# Sample config and data
# ---------------------------------------------------------------------------
SAMPLE_AGENT_CONFIG: dict = {
    "news": {
        "max_items_per_stock": 5,
        "hot_rank_limit": 10,
        "cache_ttl_seconds": 300,
    },
}


def _make_news_df(count: int = 3) -> pd.DataFrame:
    """Build a mock ak.stock_news_em() response (Chinese columns)."""
    return pd.DataFrame(
        {
            "新闻标题": [f"新闻标题{i}" for i in range(count)],
            "新闻内容": [f"内容{i}" for i in range(count)],
            "发布时间": [f"2024-01-0{i + 1} 10:00" for i in range(count)],
            "文章来源": ["东方财富"] * count,
            "新闻链接": [f"https://example.com/{i}" for i in range(count)],
        }
    )


def _make_anomaly_df() -> pd.DataFrame:
    """Build a mock ak.stock_changes_em() response (Chinese columns)."""
    return pd.DataFrame(
        {
            "时间": ["2024-01-05 14:30"],
            "代码": ["000001"],
            "名称": ["平安银行"],
            "板块": ["银行"],
            "相关信息": ["大单买入"],
        }
    )


def _make_hot_rank_df(count: int = 5) -> pd.DataFrame:
    """Build a mock ak.stock_hot_rank_em() response (Chinese columns)."""
    return pd.DataFrame(
        {
            "当前排名": list(range(1, count + 1)),
            "代码": [f"00000{i}" for i in range(1, count + 1)],
            "股票名称": [f"股票{i}" for i in range(1, count + 1)],
            "最新价": [10.0 + i for i in range(count)],
            "涨跌幅": [1.0 + i * 0.5 for i in range(count)],
        }
    )


@pytest.fixture
def mock_source_router():
    """Create a mock DataSourceRouter."""
    router = MagicMock(spec=DataSourceRouter)
    return router


@pytest.fixture
def news_fetcher(mock_source_router):
    """Create a NewsFetcher with mocked config and AKShare."""
    with (
        patch("src.data.news_fetcher.load_config") as mock_cfg,
        patch("src.data.news_fetcher.ak") as mock_ak,
    ):
        mock_cfg.return_value = SAMPLE_AGENT_CONFIG
        mock_ak.stock_news_em.return_value = _make_news_df()
        mock_ak.stock_changes_em.return_value = _make_anomaly_df()
        mock_ak.stock_hot_rank_em.return_value = _make_hot_rank_df()

        from src.data.news_fetcher import NewsFetcher

        fetcher = NewsFetcher(
            config_name="agent",
            source_router=mock_source_router,
        )
        fetcher._mock_ak = mock_ak
        yield fetcher


class TestFetchStockNews:
    """Tests for NewsFetcher.fetch_stock_news()."""

    def test_returns_dataframe(self, news_fetcher):
        """fetch_stock_news should return a DataFrame."""
        df = news_fetcher.fetch_stock_news("000001")
        assert isinstance(df, pd.DataFrame)

    def test_columns_renamed_to_english(self, news_fetcher):
        """Returned DataFrame should have English column names."""
        df = news_fetcher.fetch_stock_news("000001")
        expected_cols = {"title", "content", "datetime", "source", "url"}
        assert expected_cols.issubset(set(df.columns))

    def test_max_items_respected(self, news_fetcher):
        """Returned news should not exceed max_items_per_stock config."""
        news_fetcher._mock_ak.stock_news_em.return_value = _make_news_df(20)
        news_fetcher._cache.clear()
        df = news_fetcher.fetch_stock_news("000001")
        assert len(df) <= 5  # max_items_per_stock = 5

    def test_cache_hit_avoids_api_call(self, news_fetcher):
        """Second call within TTL should use cache."""
        news_fetcher.fetch_stock_news("000001")
        news_fetcher._mock_ak.stock_news_em.reset_mock()
        news_fetcher.fetch_stock_news("000001")
        news_fetcher._mock_ak.stock_news_em.assert_not_called()

    def test_error_returns_empty_dataframe(self, news_fetcher):
        """AKShare failure should return empty DataFrame with correct columns."""
        news_fetcher._mock_ak.stock_news_em.side_effect = ConnectionError("fail")
        news_fetcher._cache.clear()
        df = news_fetcher.fetch_stock_news("999999")
        assert df.empty
        assert "title" in df.columns

    def test_records_success_on_router(self, news_fetcher, mock_source_router):
        """Successful fetch should report success to source router."""
        news_fetcher._cache.clear()
        news_fetcher.fetch_stock_news("000001")
        mock_source_router.record_success.assert_called_with(
            SourceDomain.EASTMONEY_DATACENTER,
        )


class TestFetchStockAnomalies:
    """Tests for NewsFetcher.fetch_stock_anomalies()."""

    def test_returns_dataframe(self, news_fetcher):
        """fetch_stock_anomalies should return a DataFrame."""
        df = news_fetcher.fetch_stock_anomalies("000001")
        assert isinstance(df, pd.DataFrame)

    def test_columns_renamed(self, news_fetcher):
        """Returned DataFrame should have English column names."""
        df = news_fetcher.fetch_stock_anomalies("000001")
        assert "datetime" in df.columns or df.empty

    def test_error_returns_empty(self, news_fetcher):
        """AKShare failure should return empty DataFrame."""
        news_fetcher._mock_ak.stock_changes_em.side_effect = ConnectionError("fail")
        news_fetcher._cache.clear()
        df = news_fetcher.fetch_stock_anomalies("000001")
        assert df.empty


class TestFetchHotRank:
    """Tests for NewsFetcher.fetch_hot_rank()."""

    def test_returns_dataframe(self, news_fetcher):
        """fetch_hot_rank should return a DataFrame."""
        df = news_fetcher.fetch_hot_rank()
        assert isinstance(df, pd.DataFrame)

    def test_limit_respected(self, news_fetcher):
        """Returned DataFrame should not exceed hot_rank_limit config."""
        news_fetcher._mock_ak.stock_hot_rank_em.return_value = _make_hot_rank_df(100)
        news_fetcher._cache.clear()
        df = news_fetcher.fetch_hot_rank()
        assert len(df) <= 10  # hot_rank_limit = 10

    def test_columns_include_rank_and_symbol(self, news_fetcher):
        """Hot rank DataFrame should have rank and symbol columns."""
        df = news_fetcher.fetch_hot_rank()
        assert "rank" in df.columns
        assert "symbol" in df.columns

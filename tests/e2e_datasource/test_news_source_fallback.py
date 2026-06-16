"""Tests for news data source failure isolation.

Verifies that individual news source failures don't cascade,
and that the system degrades gracefully.

QA cases: QA-NEWS-001 (news source reliability).
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd


MOCK_NEWS_DF = pd.DataFrame(
    [
        {
            "title": "平安银行发布年报",
            "time": "2024-01-15 10:00",
            "source": "东方财富",
            "url": "https://example.com/1",
        },
        {
            "title": "银行板块走强",
            "time": "2024-01-15 11:00",
            "source": "新浪财经",
            "url": "https://example.com/2",
        },
    ]
)

MOCK_HOT_RANK_DF = pd.DataFrame(
    [
        {"rank": 1, "symbol": "sz000001", "name": "平安银行", "热度": 95},
        {"rank": 2, "symbol": "sh600519", "name": "贵州茅台", "热度": 90},
    ]
)


class TestNewsFetcherResilience:
    """News fetcher should isolate failures between sources."""

    def test_stock_news_success(self):
        with patch("src.data.news_fetcher.ak") as mock_ak:
            mock_ak.stock_news_em.return_value = MOCK_NEWS_DF

            from src.data.news_fetcher import NewsFetcher

            fetcher = NewsFetcher()
            result = fetcher.fetch_stock_news("000001")

        assert isinstance(result, pd.DataFrame)
        assert len(result) >= 1

    def test_stock_news_failure_returns_empty(self):
        with patch("src.data.news_fetcher.ak") as mock_ak:
            mock_ak.stock_news_em.side_effect = Exception("API down")

            from src.data.news_fetcher import NewsFetcher

            fetcher = NewsFetcher()
            result = fetcher.fetch_stock_news("000001")

        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_hot_rank_success(self):
        with patch("src.data.news_fetcher.ak") as mock_ak:
            mock_ak.stock_hot_rank_em.return_value = MOCK_HOT_RANK_DF

            from src.data.news_fetcher import NewsFetcher

            fetcher = NewsFetcher()
            result = fetcher.fetch_hot_rank()

        assert isinstance(result, pd.DataFrame)
        assert len(result) >= 1

    def test_hot_rank_failure_returns_empty(self):
        with patch("src.data.news_fetcher.ak") as mock_ak:
            mock_ak.stock_hot_rank_em.side_effect = Exception("Timeout")

            from src.data.news_fetcher import NewsFetcher

            fetcher = NewsFetcher()
            result = fetcher.fetch_hot_rank()

        assert isinstance(result, pd.DataFrame)
        assert result.empty

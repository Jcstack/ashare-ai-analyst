"""Tests for TrendNewsAggregator and KeywordMatcher.

Per PRD v3.2 FR-TN001~002.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from src.data.trend_news import KeywordMatcher, TrendItem, TrendNewsAggregator


# --- TrendNewsAggregator ---


class TestTrendNewsAggregator:
    def test_init(self):
        agg = TrendNewsAggregator()
        assert agg._cache_ttl == 1800.0

    @patch("src.data.trend_news.ak")
    def test_fetch_from_akshare_hot_success(self, mock_ak):
        df = pd.DataFrame({"股票名称": ["贵州茅台", "宁德时代"], "当前排名": [1, 2]})
        mock_ak.stock_hot_rank_em.return_value = df

        agg = TrendNewsAggregator()
        items = agg.fetch_from_akshare_hot("stock_hot_rank_em")

        assert len(items) == 2
        assert items[0].title == "贵州茅台"
        assert items[0].platform == "eastmoney"
        assert items[0].rank == 1
        assert items[0].heat_score > items[1].heat_score

    @patch("src.data.trend_news.ak")
    def test_fetch_from_akshare_hot_empty(self, mock_ak):
        mock_ak.stock_hot_rank_em.return_value = pd.DataFrame()

        agg = TrendNewsAggregator()
        items = agg.fetch_from_akshare_hot("stock_hot_rank_em")
        assert items == []

    @patch("src.data.trend_news.ak")
    def test_fetch_from_akshare_hot_exception(self, mock_ak):
        mock_ak.stock_hot_rank_em.side_effect = Exception("API error")

        agg = TrendNewsAggregator()
        items = agg.fetch_from_akshare_hot("stock_hot_rank_em")
        assert items == []

    @patch("src.data.trend_news.ak")
    def test_fetch_all_aggregates(self, mock_ak):
        df1 = pd.DataFrame({"股票名称": ["茅台"], "当前排名": [1]})
        df2 = pd.DataFrame({"关键词": ["白酒"], "排名": [1]})

        mock_ak.stock_hot_rank_em.return_value = df1
        mock_ak.stock_hot_keyword_em.return_value = df2
        mock_ak.stock_board_concept_name_ths.return_value = pd.DataFrame()

        agg = TrendNewsAggregator()
        items = agg.fetch_all()
        assert len(items) >= 2

    def test_cache_hit(self):
        agg = TrendNewsAggregator()
        test_items = [TrendItem(platform="test", title="cached")]
        agg._set_cached("all_trends", test_items)

        result = agg.get_cached_trends()
        assert len(result) == 1
        assert result[0].title == "cached"

    def test_cache_miss_returns_empty(self):
        agg = TrendNewsAggregator()
        result = agg.get_cached_trends()
        assert result == []


# --- KeywordMatcher ---


class TestKeywordMatcher:
    @pytest.fixture
    def matcher(self):
        with patch("src.data.trend_news.load_config") as mock_load:
            mock_load.return_value = {
                "global_filters": ["!广告", "!直播带货"],
                "stock_keywords": {
                    "600519": {
                        "required": ["+茅台"],
                        "normal": ["白酒", "酱香", "贵州"],
                        "display": "贵州茅台",
                    },
                    "300750": {
                        "required": ["+宁德时代"],
                        "normal": ["锂电", "电池", "储能"],
                        "display": "宁德时代",
                    },
                },
                "sector_keywords": {
                    "liquor": ["白酒", "酱香"],
                    "new_energy": ["锂电", "储能"],
                },
                "macro_keywords": {
                    "policy": ["央行", "降准"],
                },
            }
            return KeywordMatcher()

    def test_match_stock_required_hit(self, matcher):
        match, score = matcher.match_stock("茅台涨价白酒行业受益", "600519")
        assert match is True
        assert score > 0

    def test_match_stock_required_miss(self, matcher):
        match, score = matcher.match_stock("白酒行业受益", "600519")
        assert match is False
        assert score == 0.0

    def test_match_stock_normal_scoring(self, matcher):
        # "茅台" required + "白酒" and "酱香" normal
        _, score1 = matcher.match_stock("茅台白酒酱香型提价", "600519")
        _, score2 = matcher.match_stock("茅台提价", "600519")
        assert score1 > score2

    def test_match_stock_global_exclude(self, matcher):
        match, _ = matcher.match_stock("茅台广告投放", "600519")
        assert match is False

    def test_match_stock_unknown_symbol(self, matcher):
        match, score = matcher.match_stock("任何新闻", "999999")
        assert match is False
        assert score == 0.0

    def test_match_all_stocks(self, matcher):
        items = [
            TrendItem(platform="test", title="茅台白酒提价消息"),
            TrendItem(platform="test", title="宁德时代锂电新技术"),
            TrendItem(platform="test", title="无关新闻"),
        ]
        result = matcher.match_all_stocks(items, ["600519", "300750"])
        assert len(result["600519"]) == 1
        assert len(result["300750"]) == 1

    def test_match_sector(self, matcher):
        sectors = matcher.match_sector("白酒行业酱香型")
        assert "liquor" in sectors

    def test_match_sector_no_match(self, matcher):
        sectors = matcher.match_sector("无关新闻")
        assert sectors == []

    def test_match_macro(self, matcher):
        cats = matcher.match_macro("央行降准消息")
        assert "policy" in cats

    def test_auto_generate_keywords(self, matcher):
        result = matcher.auto_generate_keywords("600519", "贵州茅台")
        assert result["display"] == "贵州茅台"
        assert len(result["required"]) > 0

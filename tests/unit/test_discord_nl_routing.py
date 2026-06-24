"""Unit tests for Discord natural-language intent routing."""

from __future__ import annotations

from unittest.mock import patch

from src.discord_bot.cogs.natural_language import classify_message


def _classify(text: str) -> str:
    """Helper — classify and return just the intent string."""
    with patch("src.web.dependencies.get_symbol_extractor") as mock:
        mock.return_value.extract.return_value = []
        intent, _ = classify_message(text)
        return intent


class TestSentimentKeywords:
    def test_舆情(self):
        assert _classify("最近舆情怎么样") == "sentiment"

    def test_情绪(self):
        assert _classify("市场情绪如何") == "sentiment"

    def test_看涨(self):
        assert _classify("大家看涨还是看跌") == "sentiment"

    def test_恐慌(self):
        assert _classify("恐慌指数多少") == "sentiment"

    def test_脉搏(self):
        assert _classify("市场脉搏") == "sentiment"


class TestGlobalKeywords:
    def test_美股(self):
        assert _classify("美股怎么样") == "global_market"

    def test_港股(self):
        assert _classify("港股今天表现") == "global_market"

    def test_纳指(self):
        assert _classify("纳指涨了多少") == "global_market"

    def test_黄金(self):
        assert _classify("黄金价格多少") == "global_market"

    def test_VIX(self):
        assert _classify("VIX指数") == "global_market"

    def test_全球(self):
        assert _classify("全球市场") == "global_market"


class TestConceptKeywords:
    def test_概念(self):
        assert _classify("概念板块排行") == "concept"

    def test_板块(self):
        assert _classify("热点板块有哪些") == "concept"

    def test_题材(self):
        assert _classify("今日题材") == "concept"

    def test_板块轮动(self):
        assert _classify("板块轮动情况") == "concept"

    def test_热度(self):
        assert _classify("板块热度排行") == "concept"


class TestExistingIntentsPreserved:
    """Existing routing should not be affected by new keywords."""

    def test_recommend(self):
        assert _classify("推荐几只好股") == "agent_qa"

    def test_flow(self):
        assert _classify("北向资金流入多少") == "flow"

    def test_portfolio(self):
        assert _classify("我的持仓怎么样") == "portfolio"

    def test_intel(self):
        assert _classify("有什么新闻") == "intel"

    def test_agent_fallback(self):
        assert _classify("什么是量化交易") == "agent_qa"


class TestStockIntentWithSymbol:
    """When a symbol is detected, stock_analysis or trade_intent should win."""

    def test_stock_analysis(self):
        with patch("src.web.dependencies.get_symbol_extractor") as mock:
            mock.return_value.extract.return_value = ["600519"]
            intent, ctx = classify_message("分析600519")
            assert intent == "stock_analysis"
            assert ctx["symbol"] == "600519"

    def test_trade_intent(self):
        with patch("src.web.dependencies.get_symbol_extractor") as mock:
            mock.return_value.extract.return_value = ["600519"]
            intent, ctx = classify_message("买入600519")
            assert intent == "trade_intent"
            assert ctx["symbol"] == "600519"

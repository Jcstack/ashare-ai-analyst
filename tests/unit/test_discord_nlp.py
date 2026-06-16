"""Unit tests for Discord natural language message classification."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestClassifyMessage:
    """Test the ``classify_message`` pure function."""

    def _classify(self, text: str, extracted_symbols: list[str] | None = None):
        """Helper that patches SymbolExtractor for deterministic tests."""
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = extracted_symbols or []

        with patch(
            "src.web.dependencies.get_symbol_extractor",
            return_value=mock_extractor,
        ):
            from src.discord_bot.cogs.natural_language import classify_message

            return classify_message(text)

    # ── Stock analysis ────────────────────────────────────────────

    def test_stock_code_analysis(self):
        intent, ctx = self._classify("600519怎么样", ["600519"])
        assert intent == "stock_analysis"
        assert ctx["symbol"] == "600519"

    def test_stock_code_with_name(self):
        intent, ctx = self._classify("分析一下宁德时代", ["300750"])
        assert intent == "stock_analysis"
        assert ctx["symbol"] == "300750"

    # ── Trade intent ──────────────────────────────────────────────

    def test_buy_intent(self):
        intent, ctx = self._classify("我想买入300750", ["300750"])
        assert intent == "trade_intent"
        assert ctx["symbol"] == "300750"

    def test_sell_intent(self):
        intent, ctx = self._classify("卖出600519", ["600519"])
        assert intent == "trade_intent"

    def test_add_position(self):
        intent, _ = self._classify("加仓000858", ["000858"])
        assert intent == "trade_intent"

    def test_stop_loss(self):
        intent, _ = self._classify("止损300750", ["300750"])
        assert intent == "trade_intent"

    # ── Market overview ───────────────────────────────────────────

    def test_market_keyword_dapan(self):
        intent, ctx = self._classify("今天大盘走势如何")
        assert intent == "market_overview"
        assert ctx == {}

    def test_market_keyword_hangqing(self):
        intent, _ = self._classify("最近行情怎么样")
        assert intent == "market_overview"

    def test_market_keyword_zhishu(self):
        intent, _ = self._classify("指数还会涨吗")
        assert intent == "market_overview"

    # ── Recommend ───────────────────────────────────────────────

    def test_recommend_keyword(self):
        intent, _ = self._classify("股票推荐")
        assert intent == "recommend"

    def test_recommend_keyword_xuangu(self):
        intent, _ = self._classify("今天选股有什么好的")
        assert intent == "recommend"

    def test_recommend_keyword_niugu(self):
        intent, _ = self._classify("有什么好股推荐")
        assert intent == "recommend"

    # ── Intel / news ─────────────────────────────────────────────

    def test_intel_keyword_qingbao(self):
        intent, ctx = self._classify("最新情报")
        assert intent == "intel"

    def test_intel_keyword_news(self):
        intent, _ = self._classify("今天有什么新闻")
        assert intent == "intel"

    def test_intel_keyword_policy(self):
        intent, _ = self._classify("最新政策消息")
        assert intent == "intel"

    # ── Capital flow ─────────────────────────────────────────────

    def test_flow_keyword_zijin(self):
        intent, _ = self._classify("今天资金面怎么样")
        assert intent == "flow"

    def test_flow_keyword_northbound(self):
        intent, _ = self._classify("北向资金流入多少")
        assert intent == "flow"

    # ── Portfolio ────────────────────────────────────────────────

    def test_portfolio_keyword(self):
        intent, _ = self._classify("帮我诊断一下持仓")
        assert intent == "portfolio"

    def test_portfolio_keyword_cangwei(self):
        intent, _ = self._classify("我的仓位情况")
        assert intent == "portfolio"

    # ── Agent QA (default) ────────────────────────────────────────

    def test_general_question(self):
        intent, ctx = self._classify("分析一下最近的经济走向")
        assert intent == "agent_qa"
        assert "question" in ctx

    def test_empty_text(self):
        intent, _ = self._classify("")
        assert intent == "agent_qa"

    def test_unrelated_text(self):
        intent, _ = self._classify("今天天气不错")
        assert intent == "agent_qa"

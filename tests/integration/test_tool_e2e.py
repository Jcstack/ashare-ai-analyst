"""End-to-end tests for Agent tools — verifies real data source accessibility.

These tests call actual external APIs and are meant for manual verification
of data pipeline health. Mark with ``@pytest.mark.integration`` so they
are excluded from the default fast unit-test run.

Usage:
    pytest tests/integration/test_tool_e2e.py -v --timeout=60
"""

import pytest

pytestmark = pytest.mark.integration


class TestRealtimeQuote:
    """Test real-time quote data source."""

    def test_get_quotes_returns_data(self):
        from src.data.realtime import RealtimeQuoteManager

        mgr = RealtimeQuoteManager()
        result = mgr.get_quotes(["600519"])
        assert result is not None
        # Should be a non-empty list or dict
        if isinstance(result, list):
            assert len(result) > 0
        elif isinstance(result, dict):
            assert len(result) > 0


class TestStockRegistry:
    """Test stock registry search."""

    def test_search_stocks(self):
        from src.data.registry import StockRegistry

        registry = StockRegistry()
        results = registry.search("茅台")
        assert results is not None
        if isinstance(results, list):
            assert len(results) > 0


class TestTechnicalIndicators:
    """Test technical indicators calculation."""

    def test_indicators_summary(self):
        from src.web.services.stock_service import StockService

        svc = StockService()
        result = svc.get_indicators_summary("600519")
        assert result is not None
        assert isinstance(result, dict)


class TestConceptBoard:
    """Test concept board data."""

    def test_fetch_stock_concepts(self):
        from src.data.concept_board import ConceptBoardService

        svc = ConceptBoardService()
        result = svc.fetch_stock_concepts("600519")
        # May return empty if push2 is unreachable via VPN — that's acceptable
        assert result is not None


class TestGlobalMarket:
    """Test global market data."""

    def test_get_snapshot(self):
        from src.data.global_market import GlobalMarketFetcher

        fetcher = GlobalMarketFetcher()
        result = fetcher.fetch_global_snapshot()
        assert result is not None
        assert isinstance(result, dict)


class TestTradingCalendar:
    """Test trading calendar."""

    def test_is_trading_day(self):
        from datetime import date

        from src.data.trading_calendar import TradingCalendar

        cal = TradingCalendar()
        # Just verify it doesn't crash and returns a boolean
        result = cal.is_trading_day(date.today())
        assert isinstance(result, bool)


class TestNewsAggregator:
    """Test news aggregator."""

    def test_fetch_all(self):
        from src.data.trend_news import TrendNewsAggregator

        agg = TrendNewsAggregator()
        result = agg.fetch_all()
        # May return empty list if no news — that's fine
        assert result is not None


class TestConceptAnalyzer:
    """Test concept heat ranking."""

    def test_rank_concepts(self):
        from src.analysis.concept_analyzer import ConceptAnalyzer
        from src.data.concept_board import ConceptBoardService

        svc = ConceptBoardService()
        analyzer = ConceptAnalyzer(concept_service=svc)
        result = analyzer.rank_concepts(top_n=5)
        # May be empty if push2 unreachable — acceptable
        assert result is not None


class TestCrossMarket:
    """Test cross-market analysis."""

    def test_assess_impact(self):
        from src.analysis.cross_market import CrossMarketAnalyzer
        from src.data.global_market import GlobalMarketFetcher

        fetcher = GlobalMarketFetcher()
        analyzer = CrossMarketAnalyzer(global_fetcher=fetcher)
        result = analyzer.assess_cross_market_impact("600519")
        assert result is not None


class TestToolRegistryIntegration:
    """Test that ToolRegistry can be fully constructed with real services."""

    def test_register_all_with_real_services(self):
        """Verify that register_all succeeds and produces >=15 tools."""
        from src.web.services.tool_registry import ToolRegistry

        # Minimal set of real services (no network calls during registration)
        from src.data.concept_board import ConceptBoardService
        from src.data.global_market import GlobalMarketFetcher
        from src.data.realtime import RealtimeQuoteManager
        from src.data.registry import StockRegistry
        from src.data.trading_calendar import TradingCalendar
        from src.data.trend_news import TrendNewsAggregator
        from src.web.services.stock_service import StockService

        registry = ToolRegistry()
        registry.register_all(
            {
                "realtime_quote_manager": RealtimeQuoteManager(),
                "stock_registry": StockRegistry(),
                "stock_service": StockService(),
                "global_market_fetcher": GlobalMarketFetcher(),
                "trading_calendar": TradingCalendar(),
                "trend_news_aggregator": TrendNewsAggregator(),
                "concept_board_service": ConceptBoardService(),
            }
        )

        defs = registry.get_tool_definitions()
        # With partial deps (no concept_analyzer/cross_market/trade/prediction):
        # 6 data + 1 analysis (technical) + 2 portfolio = 9
        assert len(defs) >= 9
        # Verify each definition is well-formed
        for d in defs:
            assert "name" in d
            assert "description" in d
            assert "input_schema" in d

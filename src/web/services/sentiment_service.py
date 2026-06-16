"""Sentiment analysis and cross-market service.

Orchestrates data from TrendNewsAggregator, ResonanceDetector,
SentimentReportGenerator, CrossMarketAnalyzer, and GlobalMarketFetcher
to provide unified API for sentiment/cross-market endpoints.

Per PRD v3.2 FR-TN003, FR-TN004, FR-GM004.
"""

import time
from typing import Any

from src.utils.logger import get_logger
from src.web.services.stock_service import StockService

logger = get_logger("web.sentiment_service")


class SentimentService:
    """Sentiment analysis and cross-market correlation service.

    Args:
        stock_service: Optional shared StockService instance.
    """

    def __init__(self, stock_service: StockService | None = None) -> None:
        self._stock_service = stock_service
        self._aggregator = None
        self._matcher = None
        self._detector = None
        self._report_gen = None
        self._cross_market = None
        self._global_fetcher = None

    def _get_aggregator(self):
        if self._aggregator is None:
            from src.data.trend_news import TrendNewsAggregator

            self._aggregator = TrendNewsAggregator()
        return self._aggregator

    def _get_matcher(self):
        if self._matcher is None:
            from src.data.trend_news import KeywordMatcher

            self._matcher = KeywordMatcher()
        return self._matcher

    def _get_detector(self):
        if self._detector is None:
            from src.data.trend_news import ResonanceDetector

            self._detector = ResonanceDetector(keyword_matcher=self._get_matcher())
        return self._detector

    def _get_report_generator(self):
        if self._report_gen is None:
            from src.prediction.sentiment_report import SentimentReportGenerator

            self._report_gen = SentimentReportGenerator()
        return self._report_gen

    def _get_cross_market(self):
        if self._cross_market is None:
            from src.analysis.cross_market import CrossMarketAnalyzer

            self._cross_market = CrossMarketAnalyzer(
                global_fetcher=self._get_global_fetcher(),
            )
        return self._cross_market

    def _get_global_fetcher(self):
        if self._global_fetcher is None:
            from src.data.global_market import GlobalMarketFetcher

            self._global_fetcher = GlobalMarketFetcher()
        return self._global_fetcher

    def get_resonance_events(
        self,
        watchlist: list[str] | None = None,
    ) -> dict[str, Any]:
        """Detect cross-platform resonance events.

        Args:
            watchlist: Stock symbols to check for related stocks.

        Returns:
            Dict with events list and metadata.
        """
        aggregator = self._get_aggregator()
        detector = self._get_detector()

        items = aggregator.fetch_all()
        events = detector.detect(items, watchlist=watchlist)

        return {
            "status": "success",
            "events": [_resonance_to_dict(evt) for evt in events],
            "total": len(events),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def get_sentiment_report(
        self,
        *,
        watchlist: list[str] | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Generate structured sentiment analysis report.

        Args:
            watchlist: User watchlist symbols.
            positions: User position dicts.

        Returns:
            Structured 6-part sentiment report.
        """
        aggregator = self._get_aggregator()
        detector = self._get_detector()
        report_gen = self._get_report_generator()

        # Fetch trend data
        items = aggregator.fetch_all()
        events = detector.detect(items, watchlist=watchlist)

        # Fetch global snapshot
        try:
            global_snapshot = self._get_global_fetcher().fetch_global_snapshot()
        except Exception:
            global_snapshot = None

        # Cross-market data for watchlist symbols
        cross_data = None
        if watchlist:
            try:
                analyzer = self._get_cross_market()
                cross_data = analyzer.assess_batch(
                    watchlist[:10],
                    global_snapshot=global_snapshot,
                )
            except Exception:
                pass

        # Convert trend items to dicts for the report generator
        trend_dicts = [
            {
                "title": item.title,
                "platform": item.platform,
                "heat_score": item.heat_score,
                "category": item.category,
            }
            for item in items[:20]
        ]

        event_dicts = [_resonance_to_dict(evt) for evt in events[:10]]

        return report_gen.generate_report(
            trend_items=trend_dicts,
            resonance_events=event_dicts,
            global_snapshot=global_snapshot,
            cross_market_data=cross_data,
            watchlist=watchlist,
            positions=positions,
        )

    def get_cross_market_analysis(
        self,
        symbol: str,
    ) -> dict[str, Any]:
        """Get cross-market correlation analysis for a stock.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Cross-market impact assessment.
        """
        analyzer = self._get_cross_market()

        try:
            global_snapshot = self._get_global_fetcher().fetch_global_snapshot()
        except Exception:
            global_snapshot = None

        return analyzer.assess_cross_market_impact(
            symbol,
            global_snapshot=global_snapshot,
        )

    def get_market_pulse(
        self,
        *,
        watchlist: list[str] | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Get combined market pulse data for the dashboard.

        Aggregates hot events, holdings-related news, sentiment analysis,
        and global linkage into a single response.

        Args:
            watchlist: User watchlist symbols.
            positions: User position dicts.

        Returns:
            Combined market pulse dict.
        """
        aggregator = self._get_aggregator()
        detector = self._get_detector()
        matcher = self._get_matcher()

        # Fetch trend data
        items = aggregator.fetch_all()
        events = detector.detect(items, watchlist=watchlist)

        # Match items to holdings
        holding_symbols = [p.get("symbol", "") for p in (positions or [])] + (
            watchlist or []
        )
        holdings_news: dict[str, list[dict]] = {}

        if holding_symbols:
            matched = matcher.match_all_stocks(items, holding_symbols)
            for sym, sym_items in matched.items():
                if sym_items:
                    holdings_news[sym] = [
                        {
                            "title": item.title,
                            "platform": item.platform,
                            "heat_score": item.heat_score,
                            "sentiment": _infer_sentiment_simple(item.title),
                        }
                        for item in sym_items[:5]
                    ]

        # Global snapshot summary
        try:
            snapshot = self._get_global_fetcher().fetch_global_snapshot()
        except Exception:
            snapshot = None

        return {
            "status": "success",
            "hot_events": [_resonance_to_dict(evt) for evt in events[:8]],
            "holdings_news": holdings_news,
            "global_snapshot": snapshot,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }


def _resonance_to_dict(evt) -> dict[str, Any]:
    """Convert ResonanceEvent dataclass to dict, excluding merged_items."""
    return {
        "event_id": evt.event_id,
        "title": evt.title,
        "resonance_level": evt.resonance_level,
        "platforms": evt.platforms,
        "rank_timeline": evt.rank_timeline,
        "related_stocks": evt.related_stocks,
        "sentiment": evt.sentiment,
        "first_appeared": evt.first_appeared,
        "last_updated": evt.last_updated,
        "heat_score": evt.heat_score,
    }


_POS_KW = {"利好", "上涨", "突破", "新高", "增长", "回暖", "复苏", "大涨"}
_NEG_KW = {"利空", "下跌", "暴跌", "亏损", "退市", "制裁", "减持", "爆雷"}


def _infer_sentiment_simple(title: str) -> str:
    pos = any(kw in title for kw in _POS_KW)
    neg = any(kw in title for kw in _NEG_KW)
    if pos and neg:
        return "mixed"
    if pos:
        return "positive"
    if neg:
        return "negative"
    return "neutral"

"""Service layer for AI Trading Advisor.

Orchestrates data aggregation from multiple sources and delegates to
TradingAdvisor for dual-layer quant + AI recommendations.

Per PRD v3.2 FR-TA001~004, FR-HS003~004.
Redis caching added per I-107 — prevents redundant LLM calls within agent tool loops.
"""

from __future__ import annotations

import json
from typing import Any

from src.utils.logger import get_logger
from src.web.services.stock_service import StockService

logger = get_logger("web.advisor_service")

# Cache TTLs (seconds)
_ADVICE_CACHE_TTL = 300  # 5 min for stock advice
_HOLIDAY_CACHE_TTL = 1800  # 30 min for holiday impact
_PORTFOLIO_CACHE_TTL = 300  # 5 min for portfolio advice


def _get_redis():
    """Lazy Redis connection (returns None if unavailable)."""
    try:
        import redis

        return redis.Redis(
            host="redis",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    except Exception:
        return None


def _cache_get(key: str) -> dict | None:
    """Read from Redis cache."""
    try:
        r = _get_redis()
        if r:
            val = r.get(key)
            if val:
                logger.debug("Cache HIT: %s", key)
                return json.loads(val)
    except Exception:
        pass
    return None


def _cache_set(key: str, value: Any, ttl: int) -> None:
    """Write to Redis cache."""
    try:
        r = _get_redis()
        if r:
            r.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        pass


class AdvisorService:
    """Aggregates stock data and invokes TradingAdvisor.

    Constructor injection of StockService follows the PredictionService pattern.
    Internal components (TradingAdvisor, TrendNewsAggregator, etc.) are lazily
    initialized to avoid import-time heavy lifting.
    """

    def __init__(self, stock_service: StockService | None = None) -> None:
        self._stock_service = stock_service or StockService()
        self._advisor = None
        self._trend_aggregator = None
        self._keyword_matcher = None
        self._global_fetcher = None

    def _get_advisor(self):
        if self._advisor is None:
            from src.prediction.trading_advisor import TradingAdvisor

            self._advisor = TradingAdvisor()
        return self._advisor

    def _get_trend_aggregator(self):
        if self._trend_aggregator is None:
            from src.data.trend_news import TrendNewsAggregator

            self._trend_aggregator = TrendNewsAggregator()
        return self._trend_aggregator

    def _get_keyword_matcher(self):
        if self._keyword_matcher is None:
            from src.data.trend_news import KeywordMatcher

            self._keyword_matcher = KeywordMatcher()
        return self._keyword_matcher

    def _get_global_fetcher(self):
        if self._global_fetcher is None:
            from src.data.global_market import GlobalMarketFetcher

            self._global_fetcher = GlobalMarketFetcher()
        return self._global_fetcher

    def get_stock_advice(self, symbol: str) -> dict[str, Any]:
        """Generate operation advice for a single stock.

        Aggregates: quote, indicators, fund_flow, strategy signals,
        bayesian analysis, news context, global context.
        Results are cached in Redis for 5 min to avoid redundant LLM calls
        when the agent tool loop invokes this multiple times.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Advice dict from TradingAdvisor.advise_stock().
        """
        cache_key = f"advisor:stock_advice:{symbol}"
        cached = _cache_get(cache_key)
        if cached:
            return cached

        advisor = self._get_advisor()

        # Gather data
        quote = self._fetch_quote(symbol)
        indicators = self._fetch_indicators(symbol)
        fund_flow = self._fetch_fund_flow(symbol)
        strategy_signals = self._fetch_strategy_signals(symbol)
        bayesian = self._fetch_bayesian(symbol)
        news_context = self._fetch_news_context(symbol)
        global_context = self._fetch_global_context()
        board_type, price_limit = self._get_board_info(symbol)

        sector_info = self._fetch_sector_info(symbol)

        result = advisor.advise_stock(
            symbol,
            quote=quote,
            indicators=indicators,
            fund_flow=fund_flow,
            strategy_signals=strategy_signals,
            bayesian_analysis=bayesian,
            news_context=news_context,
            global_context=global_context,
            board_type=board_type,
            price_limit=price_limit,
            sector_info=sector_info,
        )

        # Enrich with stock name
        stock_detail = self._stock_service.get_stock_detail(symbol)
        if stock_detail:
            result["name"] = stock_detail.get("name", "")

        _cache_set(cache_key, result, _ADVICE_CACHE_TTL)
        return result

    def get_watchlist_strategy(self, symbols: list[str]) -> dict[str, Any]:
        """Generate strategy report for watchlist stocks.

        Args:
            symbols: List of stock codes.

        Returns:
            Watchlist strategy result.
        """
        advisor = self._get_advisor()
        stock_data = {}

        for sym in symbols:
            stock_data[sym] = self._gather_stock_data(sym)

        return advisor.advise_watchlist(symbols, stock_data=stock_data)

    def get_portfolio_advice(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        """Generate add/reduce advice for held positions.

        Args:
            positions: List of position dicts.

        Returns:
            Portfolio advice result.
        """
        advisor = self._get_advisor()
        stock_data = {}

        for pos in positions:
            sym = pos.get("symbol", "")
            if sym:
                stock_data[sym] = self._gather_stock_data(sym)

        return advisor.advise_portfolio(positions, stock_data=stock_data)

    def get_holiday_impact(self, symbol: str) -> dict[str, Any]:
        """Assess holiday impact for a held stock.

        Results cached in Redis for 30 min (holiday impact changes slowly).

        Args:
            symbol: 6-digit stock code.

        Returns:
            Holiday impact assessment.
        """
        cache_key = f"advisor:holiday_impact:{symbol}"
        cached = _cache_get(cache_key)
        if cached:
            return cached

        advisor = self._get_advisor()

        global_snapshot = self._fetch_global_context()
        news_items = self._fetch_news_context(symbol)
        cross_market = self._fetch_cross_market(symbol)

        result = advisor.assess_holiday_impact(
            symbol,
            global_snapshot=global_snapshot,
            news_items=[
                {"title": n.get("title", ""), "platform": n.get("platform", "")}
                for n in (news_items or [])
            ],
            cross_market_data=cross_market,
        )

        _cache_set(cache_key, result, _HOLIDAY_CACHE_TTL)
        return result

    def get_reopen_briefing(self) -> dict[str, Any]:
        """Generate pre-open briefing report.

        Returns:
            Reopen briefing result.
        """
        advisor = self._get_advisor()

        global_snapshot = self._fetch_global_context()

        # Fetch trending news for context
        try:
            aggregator = self._get_trend_aggregator()
            trends = aggregator.fetch_all()
            news_context = [
                {"title": t.title, "platform": t.platform} for t in trends[:15]
            ]
        except Exception:
            news_context = []

        return advisor.generate_reopen_briefing(
            global_snapshot=global_snapshot,
            news_context=news_context,
        )

    # --- Data fetching helpers ---

    def _gather_stock_data(self, symbol: str) -> dict[str, Any]:
        """Gather all available data for a stock."""
        board_type, price_limit = self._get_board_info(symbol)
        return {
            "quote": self._fetch_quote(symbol),
            "indicators": self._fetch_indicators(symbol),
            "fund_flow": self._fetch_fund_flow(symbol),
            "strategy_signals": self._fetch_strategy_signals(symbol),
            "bayesian_analysis": self._fetch_bayesian(symbol),
            "news_context": self._fetch_news_context(symbol),
            "global_context": self._fetch_global_context(),
            "board_type": board_type,
            "price_limit": price_limit,
            "sector_info": self._fetch_sector_info(symbol),
        }

    def _fetch_quote(self, symbol: str) -> dict[str, Any] | None:
        # Primary: real-time quote
        try:
            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager()
            quote = mgr.get_single_quote(symbol)
            if quote and quote.get("price"):
                return quote
        except Exception as exc:
            logger.debug("Realtime quote failed for %s: %s", symbol, exc)

        # Fallback: last EOD close (stale but better than nothing)
        try:
            from src.data.fetcher import StockDataFetcher

            fetcher = StockDataFetcher()
            df = fetcher.fetch_daily_ohlcv(symbol)
            if df is not None and not df.empty:
                last = df.iloc[-1]
                return {
                    "symbol": symbol,
                    "price": float(last["close"]),
                    "high": float(last["high"]),
                    "low": float(last["low"]),
                    "volume": float(last.get("volume", 0)),
                    "pct_change": float(last.get("pct_change", 0)),
                    "_source": "eod_fallback",
                }
        except Exception as exc:
            logger.debug("EOD fallback failed for %s: %s", symbol, exc)

        return None

    def _fetch_indicators(self, symbol: str) -> dict[str, Any] | None:
        try:
            return self._stock_service.get_indicators_summary(symbol)
        except Exception as exc:
            logger.debug("Indicators fetch failed for %s: %s", symbol, exc)
            return None

    def _fetch_fund_flow(self, symbol: str) -> list[dict[str, Any]] | None:
        try:
            from src.data.fetcher import StockDataFetcher

            fetcher = StockDataFetcher()
            df = fetcher.fetch_fund_flow(symbol)
            if df is not None and not df.empty:
                return df.tail(5).to_dict(orient="records")
        except Exception as exc:
            logger.debug("Fund flow fetch failed for %s: %s", symbol, exc)
        return None

    def _fetch_strategy_signals(self, symbol: str) -> dict[str, Any] | None:
        try:
            from src.web.services.strategy_context_service import StrategyContextService

            svc = StrategyContextService()
            return svc.get_strategy_context(symbol)
        except Exception as exc:
            logger.debug("Strategy signals failed for %s: %s", symbol, exc)
            return None

    def _fetch_bayesian(self, symbol: str) -> dict[str, Any] | None:
        try:
            from src.analysis.bayesian import BayesianIndicatorAnalyzer

            ba = BayesianIndicatorAnalyzer()
            df = self._stock_service.get_stock_with_indicators(symbol)
            if df is not None and not df.empty:
                return ba.analyze(df)
        except Exception as exc:
            logger.debug("Bayesian failed for %s: %s", symbol, exc)
        return None

    def _fetch_news_context(self, symbol: str) -> list[dict[str, Any]] | None:
        try:
            aggregator = self._get_trend_aggregator()
            matcher = self._get_keyword_matcher()
            trends = aggregator.fetch_all()
            matched = matcher.match_all_stocks(trends, [symbol])
            items = matched.get(symbol, [])
            return [
                {"title": t.title, "platform": t.platform, "heat_score": t.heat_score}
                for t in items[:8]
            ]
        except Exception as exc:
            logger.debug("News context failed for %s: %s", symbol, exc)
            return None

    def _fetch_global_context(self) -> dict[str, Any] | None:
        try:
            fetcher = self._get_global_fetcher()
            return fetcher.fetch_global_snapshot()
        except Exception as exc:
            logger.debug("Global context failed: %s", exc)
            return None

    def _fetch_sector_info(self, symbol: str) -> dict[str, Any] | None:
        """Fetch concept sector info for a stock."""
        try:
            return self._stock_service.get_stock_sector_info(symbol)
        except Exception as exc:
            logger.debug("Sector info fetch failed for %s: %s", symbol, exc)
            return None

    def _fetch_cross_market(self, symbol: str) -> dict[str, Any] | None:
        try:
            from src.utils.config import load_config

            config = load_config("cross_market_map")
            mappings = config.get("mappings", {})
            return mappings.get(symbol)
        except Exception:
            return None

    def _get_board_info(self, symbol: str) -> tuple[str, str]:
        try:
            detail = self._stock_service.get_stock_detail(symbol)
            if detail:
                board = detail.get("board", "")
                # Registry returns English: "chinext", "star", "main"
                # Watchlist may return Chinese: "创业板", "科创板", "主板"
                board_lower = board.lower()
                if "创业" in board or board_lower == "chinext":
                    return board, "±20%"
                elif "科创" in board or board_lower == "star":
                    return board, "±20%"
                elif "北交所" in board or board_lower == "bse":
                    return board, "±30%"
                else:
                    return board, "±10%"
        except Exception:
            pass
        return "", ""

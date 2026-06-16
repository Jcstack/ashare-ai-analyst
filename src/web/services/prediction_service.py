"""Service layer for Claude AI stock prediction.

Wraps the prediction layer modules for use by web routes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


from src.llm.base import LLMProviderError
from src.prediction.analyzer import StockAnalyzer, AnalyzerError
from src.web.services.stock_service import StockService
from src.utils.logger import get_logger

logger = get_logger("web.prediction_service")


class PredictionService:
    """Service for running Claude-powered stock predictions.

    Orchestrates data fetching, indicator computation, pattern detection,
    and Claude API analysis through the prediction layer.
    """

    def __init__(self, stock_service: StockService | None = None) -> None:
        self._stock_service = stock_service or StockService()
        self._analyzer: StockAnalyzer | None = None

    def _get_analyzer(self) -> StockAnalyzer:
        """Lazily initialize the StockAnalyzer (requires API key).

        Returns:
            Initialized StockAnalyzer instance.

        Raises:
            ValueError: If ANTHROPIC_API_KEY is not set.
        """
        if self._analyzer is None:
            self._analyzer = StockAnalyzer()
        return self._analyzer

    def predict(self, symbol: str) -> dict[str, Any]:
        """Run a full Claude prediction analysis on a stock.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Prediction result dict with keys: trend, signal, confidence,
            risk_level, reasoning, target_price_range, key_factors,
            risk_warnings. Returns error dict on failure.
        """
        try:
            analyzer = self._get_analyzer()
        except ValueError as exc:
            logger.error("Cannot initialize analyzer: %s", exc)
            return {"status": "error", "message": str(exc)}

        # Fetch data with indicators
        df = self._stock_service.get_stock_with_indicators(symbol)
        if df is None or df.empty:
            return {
                "status": "error",
                "message": f"无法获取 {symbol} 的数据",
            }

        # Get indicators summary
        indicators = self._stock_service.get_indicators_summary(symbol)

        # Get patterns
        patterns_df = self._stock_service.get_stock_with_patterns(symbol)
        patterns: list[dict[str, Any]] = []
        if patterns_df is not None and not patterns_df.empty:
            pattern_cols = [c for c in patterns_df.columns if c.startswith("pattern_")]
            last_row = patterns_df.iloc[-1]
            for col in pattern_cols:
                if last_row[col] != 0:
                    patterns.append(
                        {
                            "name": col.replace("pattern_", ""),
                            "value": int(last_row[col]),
                        }
                    )

        # Get support/resistance levels
        sr_levels = self._stock_service.get_support_resistance(symbol)

        try:
            result = analyzer.analyze(
                symbol=symbol,
                ohlcv_df=df,
                indicators=indicators,
                patterns=patterns,
                sr_levels=sr_levels,
            )
            result["status"] = "success"
            result["symbol"] = symbol
            _normalize_prediction(result)
            return result
        except (AnalyzerError, LLMProviderError) as exc:
            logger.error("Prediction failed for %s: %s", symbol, exc)
            return {"status": "error", "message": f"预测分析失败: {exc}"}
        except Exception as exc:
            logger.error("Unexpected error predicting %s: %s", symbol, exc)
            return {"status": "error", "message": f"系统错误: {exc}"}

    def predict_enhanced(
        self,
        symbol: str,
        sources: list[str] | None = None,
        include_bayesian: bool = False,
        include_risk: bool = False,
    ) -> dict[str, Any]:
        """Run enhanced prediction with selectable data sources.

        Args:
            symbol: 6-digit stock code.
            sources: List of data source names to include.
            include_bayesian: Whether to include Bayesian analysis.
            include_risk: Whether to include risk assessment.

        Returns:
            Enhanced prediction result dict.
        """
        sources = sources or ["indicators", "fund_flow"]
        used_sources: list[str] = []
        extra_context: dict[str, Any] = {}

        # Always get base prediction data
        result = self.predict(symbol)
        if result.get("status") == "error":
            return result

        # Gather additional data based on sources
        if "fund_flow" in sources:
            try:
                from src.data.fetcher import StockDataFetcher

                fetcher = StockDataFetcher()
                ff_df = fetcher.fetch_fund_flow(symbol)
                if ff_df is not None and not ff_df.empty:
                    extra_context["fund_flow"] = ff_df.tail(10).to_dict(
                        orient="records"
                    )
                    used_sources.append("fund_flow")
            except Exception as exc:
                logger.warning("Fund flow fetch failed for %s: %s", symbol, exc)

        if "dragon_tiger" in sources:
            try:
                from src.data.fetcher import StockDataFetcher

                fetcher = StockDataFetcher()
                dt_df = fetcher.fetch_dragon_tiger_stock_stats(symbol)
                if dt_df is not None and not dt_df.empty:
                    extra_context["dragon_tiger"] = dt_df.to_dict(orient="records")
                    used_sources.append("dragon_tiger")
            except Exception as exc:
                logger.warning("Dragon tiger fetch failed for %s: %s", symbol, exc)

        if "news" in sources:
            try:
                from src.data.news_fetcher import NewsFetcher

                nf = NewsFetcher()
                news_df = nf.fetch_stock_news(symbol)
                if news_df is not None and not news_df.empty:
                    extra_context["news"] = news_df.head(5).to_dict(orient="records")
                    used_sources.append("news")
            except Exception as exc:
                logger.warning("News fetch failed for %s: %s", symbol, exc)

        if "bayesian" in sources or include_bayesian:
            try:
                from src.analysis.bayesian import BayesianIndicatorAnalyzer

                ba = BayesianIndicatorAnalyzer()
                df = self._stock_service.get_stock_with_indicators(symbol)
                if df is not None and not df.empty:
                    bay_result = ba.analyze(df)
                    extra_context["bayesian"] = bay_result
                    used_sources.append("bayesian")
            except Exception as exc:
                logger.warning("Bayesian analysis failed for %s: %s", symbol, exc)

        if "indicators" in sources:
            used_sources.append("indicators")

        result["data_sources"] = used_sources
        result["generated_at"] = datetime.now(timezone.utc).isoformat()
        return result

    def predict_comparison(
        self,
        symbols: list[str],
        sources: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run comparison prediction across multiple stocks.

        Args:
            symbols: List of stock codes to compare.
            sources: Data sources to use.

        Returns:
            Comparison result with per-stock analyses and summary.
        """
        analyses = []
        for sym in symbols:
            result = self.predict_enhanced(sym, sources=sources)
            analyses.append(result)

        # Simple ranking by confidence
        ranked = sorted(
            [a for a in analyses if a.get("status") == "success"],
            key=lambda a: a.get("confidence") or 0,
            reverse=True,
        )
        recommendation_order = [a.get("symbol", "") for a in ranked]

        return {
            "status": "success",
            "analyses": analyses,
            "comparison_summary": f"共分析 {len(symbols)} 只股票，按置信度排序推荐",
            "recommendation_order": recommendation_order,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


def _normalize_prediction(result: dict[str, Any]) -> None:
    """Normalize LLM output fields to match the API response schema.

    The LLM prompt instructs Claude to return ``reasoning`` as a list of
    strings and ``target_price_range`` as ``{low, high}`` dict, but the
    Pydantic response models expect ``reasoning: str`` (newline-joined)
    and ``target_price_range: list[float]`` ([low, high]).
    """
    # reasoning: list[str] → str (newline-joined)
    reasoning = result.get("reasoning")
    if isinstance(reasoning, list):
        result["reasoning"] = "\n".join(str(r) for r in reasoning)

    # target_price_range: {low, high} → [low, high]
    tpr = result.get("target_price_range")
    if isinstance(tpr, dict):
        low = tpr.get("low") or tpr.get("min") or 0
        high = tpr.get("high") or tpr.get("max") or 0
        result["target_price_range"] = [float(low), float(high)]

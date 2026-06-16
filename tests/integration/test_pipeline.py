"""Integration tests: data-to-analysis and analysis-to-prediction pipelines.

Tests cross-module data flow from data fetching through preprocessing,
technical analysis, and prediction generation. All external dependencies
(AKShare, LLM APIs) are mocked.

Per PRD Section 6: Integration tests with external mocking only.
"""

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.llm.base import LLMProviderError, LLMResponse, ProviderName
from tests.integration.conftest import (
    PREDICTION_CONFIG,
    PROMPT_CONFIG,
)


# ---------------------------------------------------------------------------
# TestDataToAnalysisPipeline
# ---------------------------------------------------------------------------


class TestDataToAnalysisPipeline:
    """Test data fetch -> preprocessing -> indicator calculation flow."""

    def test_fetch_preprocess_and_add_indicators(
        self,
        mock_akshare: MagicMock,
        stocks_config: dict,
    ) -> None:
        """Verify data flows from fetcher through preprocessor to indicators."""
        with patch("src.data.fetcher.load_config", return_value=stocks_config):
            from src.data.fetcher import StockDataFetcher
            from src.data.preprocessor import DataPreprocessor

            fetcher = StockDataFetcher()
            preprocessor = DataPreprocessor()

            raw_df = fetcher.fetch_daily_ohlcv("000001")
            assert not raw_df.empty
            assert "close" in raw_df.columns

            clean_df = preprocessor.clean_ohlcv(raw_df)
            assert len(clean_df) > 0
            assert clean_df["close"].dtype == np.float64

            enriched_df = preprocessor.add_returns(clean_df)
            assert "daily_return" in enriched_df.columns
            assert "log_return" in enriched_df.columns

        from src.analysis.indicators import TechnicalIndicators

        indicators = TechnicalIndicators()
        df_with_indicators = indicators.add_all(enriched_df)

        expected_cols = {"MACD", "MACD_signal", "RSI", "KDJ_K", "BB_upper"}
        actual_cols = set(df_with_indicators.columns)
        assert expected_cols.issubset(actual_cols), (
            f"Missing indicator columns: {expected_cols - actual_cols}"
        )

    def test_fetch_preprocess_and_detect_patterns(
        self,
        mock_akshare: MagicMock,
        stocks_config: dict,
    ) -> None:
        """Verify pattern detection works on preprocessed data."""
        with patch("src.data.fetcher.load_config", return_value=stocks_config):
            from src.data.fetcher import StockDataFetcher
            from src.data.preprocessor import DataPreprocessor

            fetcher = StockDataFetcher()
            preprocessor = DataPreprocessor()
            raw_df = fetcher.fetch_daily_ohlcv("000001")
            clean_df = preprocessor.clean_ohlcv(raw_df)

        from src.analysis.patterns import PatternRecognizer

        recognizer = PatternRecognizer()
        df_with_patterns = recognizer.detect_candlestick_patterns(clean_df)

        pattern_cols = [c for c in df_with_patterns.columns if c.startswith("pattern_")]
        assert len(pattern_cols) >= 5
        assert "pattern_hammer" in df_with_patterns.columns
        assert "pattern_engulfing" in df_with_patterns.columns

    def test_support_resistance_on_preprocessed_data(
        self,
        mock_akshare: MagicMock,
        stocks_config: dict,
    ) -> None:
        """Verify S/R level detection returns valid structure."""
        with patch("src.data.fetcher.load_config", return_value=stocks_config):
            from src.data.fetcher import StockDataFetcher
            from src.data.preprocessor import DataPreprocessor

            fetcher = StockDataFetcher()
            preprocessor = DataPreprocessor()
            raw_df = fetcher.fetch_daily_ohlcv("000001")
            clean_df = preprocessor.clean_ohlcv(raw_df)

        from src.analysis.patterns import PatternRecognizer

        recognizer = PatternRecognizer()
        sr_levels = recognizer.find_support_resistance(clean_df)

        assert isinstance(sr_levels, list)
        for level in sr_levels:
            assert "level" in level
            assert "type" in level
            assert level["type"] in ("support", "resistance")
            assert "touches" in level
            assert level["touches"] >= 2

    def test_full_data_to_analysis_multiple_symbols(
        self,
        mock_akshare: MagicMock,
        stocks_config: dict,
        tmp_path,
    ) -> None:
        """Verify the pipeline handles multiple stocks in the watchlist."""
        with (
            patch(
                "src.data.fetcher.load_config",
                return_value=stocks_config,
            ),
            patch(
                "src.data.preprocessor.get_data_dir",
                return_value=tmp_path,
            ),
        ):
            from src.data.fetcher import StockDataFetcher
            from src.data.preprocessor import DataPreprocessor

            fetcher = StockDataFetcher()
            preprocessor = DataPreprocessor()

            raw_data = fetcher.fetch_all_watchlist()
            assert len(raw_data) == 2
            assert "000001" in raw_data
            assert "600519" in raw_data

            processed = preprocessor.process_all(raw_data)
            assert len(processed) == 2

        from src.analysis.indicators import TechnicalIndicators

        indicators = TechnicalIndicators()
        for symbol, df in processed.items():
            df_ind = indicators.add_all(df)
            assert "MACD" in df_ind.columns, f"MACD missing for {symbol}"
            assert "RSI" in df_ind.columns, f"RSI missing for {symbol}"


# ---------------------------------------------------------------------------
# TestAnalysisToPredictionPipeline
# ---------------------------------------------------------------------------


class TestAnalysisToPredictionPipeline:
    """Test analysis -> prediction flow with mocked LLM router."""

    def test_analysis_to_prediction_produces_required_fields(
        self,
        mock_akshare: MagicMock,
        stocks_config: dict,
        prediction_result: dict,
    ) -> None:
        """Verify prediction dict contains all required output fields."""
        mock_router = MagicMock()
        mock_router.complete.return_value = LLMResponse(
            text=json.dumps(prediction_result, ensure_ascii=False),
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.003,
        )
        mock_router.available_providers = [ProviderName.ANTHROPIC]

        with (
            patch(
                "src.data.fetcher.load_config",
                return_value=stocks_config,
            ),
            patch(
                "src.prediction.analyzer.load_config",
                return_value=PREDICTION_CONFIG,
            ),
            patch(
                "src.prediction.prompts.load_config",
                return_value=PROMPT_CONFIG,
            ),
        ):
            from src.data.fetcher import StockDataFetcher
            from src.data.preprocessor import DataPreprocessor

            fetcher = StockDataFetcher()
            preprocessor = DataPreprocessor()
            raw_df = fetcher.fetch_daily_ohlcv("000001")
            clean_df = preprocessor.clean_ohlcv(raw_df)
            enriched_df = preprocessor.add_returns(clean_df)

            from src.analysis.indicators import TechnicalIndicators
            from src.analysis.patterns import PatternRecognizer

            indicators = TechnicalIndicators()
            recognizer = PatternRecognizer()
            df_ind = indicators.add_all(enriched_df)
            df_pat = recognizer.detect_candlestick_patterns(df_ind)
            sr_levels = recognizer.find_support_resistance(df_pat)

            last_row = df_pat.iloc[-1]
            indicator_values = {
                col: (
                    float(last_row[col])
                    if hasattr(last_row[col], "item")
                    else last_row[col]
                )
                for col in df_pat.columns
                if col
                not in (
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                )
            }
            pattern_cols = [c for c in df_pat.columns if c.startswith("pattern_")]
            active_patterns = [
                {"name": col, "value": float(last_row[col])}
                for col in pattern_cols
                if last_row[col] != 0
            ]

            from src.prediction.analyzer import StockAnalyzer

            analyzer = StockAnalyzer(router=mock_router)
            result = analyzer.analyze(
                symbol="000001",
                ohlcv_df=df_pat,
                indicators=indicator_values,
                patterns=active_patterns,
                sr_levels=sr_levels,
            )

        required_fields = [
            "trend",
            "signal",
            "confidence",
            "risk_level",
            "reasoning",
            "target_price_range",
            "key_factors",
            "risk_warnings",
        ]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"

        assert result["symbol"] == "000001"
        assert "timestamp" in result
        assert "model" in result
        assert result["signal"] in ("buy", "sell", "hold", "watch")
        assert 0.0 <= result["confidence"] <= 1.0
        assert isinstance(result["reasoning"], list)

    def test_prediction_handles_api_error_gracefully(
        self,
        mock_akshare: MagicMock,
        stocks_config: dict,
    ) -> None:
        """Verify AnalyzerError is raised when all LLM providers fail."""
        mock_router = MagicMock()
        mock_router.complete.side_effect = LLMProviderError("All providers failed")
        mock_router.available_providers = [ProviderName.ANTHROPIC]

        with (
            patch(
                "src.data.fetcher.load_config",
                return_value=stocks_config,
            ),
            patch(
                "src.prediction.analyzer.load_config",
                return_value=PREDICTION_CONFIG,
            ),
            patch(
                "src.prediction.prompts.load_config",
                return_value=PROMPT_CONFIG,
            ),
        ):
            from src.data.fetcher import StockDataFetcher
            from src.data.preprocessor import DataPreprocessor

            fetcher = StockDataFetcher()
            preprocessor = DataPreprocessor()
            raw_df = fetcher.fetch_daily_ohlcv("000001")
            clean_df = preprocessor.clean_ohlcv(raw_df)
            enriched_df = preprocessor.add_returns(clean_df)

            from src.analysis.indicators import TechnicalIndicators
            from src.analysis.patterns import PatternRecognizer

            indicators = TechnicalIndicators()
            recognizer = PatternRecognizer()
            df_ind = indicators.add_all(enriched_df)
            df_pat = recognizer.detect_candlestick_patterns(df_ind)

            from src.prediction.analyzer import AnalyzerError, StockAnalyzer

            analyzer = StockAnalyzer(router=mock_router)

            with pytest.raises(AnalyzerError, match="LLM call failed"):
                analyzer.analyze(
                    symbol="000001",
                    ohlcv_df=df_pat,
                    indicators={},
                    patterns=[],
                    sr_levels=[],
                )

"""Unit tests for src/prediction/prompts.py — PromptBuilder.

Test cases per PRD Section 6.2:
  - Verify prompt structure conforms to Anthropic Messages API format
  - Verify system prompt includes output JSON schema with required fields
  - Verify OHLCV summary formatting produces readable text
  - Verify user prompt includes all provided data sections

Per PRD Section 6.3 mock strategy:
  - Mock config loading (external I/O) only
  - Use realistic sample data structures
"""

import pandas as pd
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PREDICTION_CONFIG = {
    "model": {
        "name": "claude-sonnet-4-5-20250929",
        "max_tokens": 4096,
        "temperature": 0.3,
    },
    "retry": {
        "max_attempts": 3,
        "base_delay_seconds": 1,
        "max_delay_seconds": 30,
    },
    "evaluation": {
        "direction_accuracy_threshold": 0.6,
        "price_range_tolerance": 0.05,
        "min_confidence": 0.5,
    },
    "output_schema": {
        "required_fields": [
            "trend",
            "signal",
            "confidence",
            "risk_level",
            "reasoning",
            "target_price_range",
            "key_factors",
            "risk_warnings",
        ],
    },
}


@pytest.fixture
def sample_indicators():
    """Sample technical indicator values for testing."""
    return {
        "ma5": 10.85,
        "ma20": 10.42,
        "rsi": 65.2,
        "macd": {
            "dif": 0.12,
            "dea": 0.08,
            "histogram": 0.04,
        },
        "volume_ratio": 1.35,
    }


@pytest.fixture
def sample_patterns():
    """Sample candlestick pattern detections for testing."""
    return [
        {
            "name": "锤子线",
            "type": "bullish",
            "date": "2024-01-15",
            "reliability": "high",
        },
        {
            "name": "吞没形态",
            "type": "bearish",
            "date": "2024-01-12",
            "reliability": "medium",
        },
    ]


@pytest.fixture
def sample_sr_levels():
    """Sample support/resistance levels for testing."""
    return [
        {"level": 10.20, "type": "support", "strength": "strong"},
        {"level": 11.50, "type": "resistance", "strength": "medium"},
        {"level": 9.80, "type": "support", "strength": "weak"},
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildAnalysisPrompt:
    """Tests for PromptBuilder.build_analysis_prompt()."""

    @patch("src.prediction.prompts.load_config")
    def test_build_analysis_prompt_returns_messages_list(
        self,
        mock_load_config,
        sample_ohlcv_df,
        sample_indicators,
        sample_patterns,
        sample_sr_levels,
    ):
        """Verify returns a list of dicts with role/content keys."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.prompts import PromptBuilder

        builder = PromptBuilder()
        messages = builder.build_analysis_prompt(
            symbol="000001",
            ohlcv_df=sample_ohlcv_df,
            indicators=sample_indicators,
            patterns=sample_patterns,
            sr_levels=sample_sr_levels,
        )

        assert isinstance(messages, list)
        assert len(messages) == 2

        for msg in messages:
            assert isinstance(msg, dict)
            assert "role" in msg
            assert "content" in msg

        # First message should be system, second should be user
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    @patch("src.prediction.prompts.load_config")
    def test_system_prompt_contains_schema(
        self,
        mock_load_config,
        sample_ohlcv_df,
        sample_indicators,
        sample_patterns,
        sample_sr_levels,
    ):
        """Verify system message contains all required output fields."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.prompts import PromptBuilder

        builder = PromptBuilder()
        messages = builder.build_analysis_prompt(
            symbol="000001",
            ohlcv_df=sample_ohlcv_df,
            indicators=sample_indicators,
            patterns=sample_patterns,
            sr_levels=sample_sr_levels,
        )

        system_content = messages[0]["content"]

        # All required fields from the schema must appear
        required_fields = SAMPLE_PREDICTION_CONFIG["output_schema"]["required_fields"]
        for field in required_fields:
            assert field in system_content, (
                f"Required field '{field}' not found in system prompt"
            )

        # Check for key instructions
        assert "A股" in system_content
        assert "JSON" in system_content

    @patch("src.prediction.prompts.load_config")
    def test_prompt_includes_all_data(
        self,
        mock_load_config,
        sample_ohlcv_df,
        sample_indicators,
        sample_patterns,
        sample_sr_levels,
    ):
        """Verify user message includes indicators, patterns, and S/R levels."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.prompts import PromptBuilder

        builder = PromptBuilder()
        messages = builder.build_analysis_prompt(
            symbol="000001",
            ohlcv_df=sample_ohlcv_df,
            indicators=sample_indicators,
            patterns=sample_patterns,
            sr_levels=sample_sr_levels,
        )

        user_content = messages[1]["content"]

        # Symbol must appear
        assert "000001" in user_content

        # Indicator values must appear
        assert "ma5" in user_content
        assert "rsi" in user_content
        assert "macd" in user_content

        # Pattern names must appear
        assert "锤子线" in user_content
        assert "吞没形态" in user_content

        # S/R levels must appear
        assert "10.20" in user_content
        assert "11.50" in user_content
        assert "支撑位" in user_content
        assert "阻力位" in user_content

    @patch("src.prediction.prompts.load_config")
    def test_prompt_with_empty_patterns(
        self,
        mock_load_config,
        sample_ohlcv_df,
        sample_indicators,
        sample_sr_levels,
    ):
        """Verify prompt handles empty patterns list gracefully."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.prompts import PromptBuilder

        builder = PromptBuilder()
        messages = builder.build_analysis_prompt(
            symbol="600519",
            ohlcv_df=sample_ohlcv_df,
            indicators=sample_indicators,
            patterns=[],
            sr_levels=sample_sr_levels,
        )

        user_content = messages[1]["content"]
        assert "未检测到明显K线形态" in user_content

    @patch("src.prediction.prompts.load_config")
    def test_prompt_with_empty_indicators(
        self,
        mock_load_config,
        sample_ohlcv_df,
        sample_patterns,
        sample_sr_levels,
    ):
        """Verify prompt handles empty indicators dict gracefully."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.prompts import PromptBuilder

        builder = PromptBuilder()
        messages = builder.build_analysis_prompt(
            symbol="600519",
            ohlcv_df=sample_ohlcv_df,
            indicators={},
            patterns=sample_patterns,
            sr_levels=sample_sr_levels,
        )

        user_content = messages[1]["content"]
        assert "无技术指标数据" in user_content


class TestFormatOHLCVSummary:
    """Tests for PromptBuilder._format_ohlcv_summary()."""

    @patch("src.prediction.prompts.load_config")
    def test_ohlcv_summary_formatting(self, mock_load_config, sample_ohlcv_df):
        """Verify _format_ohlcv_summary produces readable text."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.prompts import PromptBuilder

        builder = PromptBuilder()
        result = builder._format_ohlcv_summary(sample_ohlcv_df)

        # Result should be a non-empty string
        assert isinstance(result, str)
        assert len(result) > 0

        # Should contain header keywords
        assert "日期" in result
        assert "开盘" in result
        assert "收盘" in result
        assert "成交量" in result

        # Should contain data values from sample data
        lines = result.strip().split("\n")
        # Header + separator + 10 data rows
        assert len(lines) == 12

    @patch("src.prediction.prompts.load_config")
    def test_ohlcv_summary_with_short_df(self, mock_load_config):
        """Verify summary handles DataFrame with fewer than 10 rows."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.prompts import PromptBuilder

        builder = PromptBuilder()
        short_df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-02", periods=3, freq="B"),
                "open": [10.0, 10.2, 10.1],
                "high": [10.3, 10.3, 10.5],
                "low": [9.9, 9.9, 10.0],
                "close": [10.1, 10.0, 10.4],
                "volume": [1000000, 1200000, 900000],
            }
        )

        result = builder._format_ohlcv_summary(short_df)
        lines = result.strip().split("\n")
        # Header + separator + 3 data rows
        assert len(lines) == 5


class TestFormatPatterns:
    """Tests for PromptBuilder._format_patterns()."""

    @patch("src.prediction.prompts.load_config")
    def test_format_patterns_with_data(self, mock_load_config, sample_patterns):
        """Verify patterns are formatted with name, type, date, reliability."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.prompts import PromptBuilder

        builder = PromptBuilder()
        result = builder._format_patterns(sample_patterns)

        assert "锤子线" in result
        assert "bullish" in result
        assert "2024-01-15" in result
        assert "high" in result

    @patch("src.prediction.prompts.load_config")
    def test_format_patterns_empty(self, mock_load_config):
        """Verify empty pattern list returns placeholder text."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.prompts import PromptBuilder

        builder = PromptBuilder()
        result = builder._format_patterns([])

        assert "未检测到明显K线形态" in result


class TestFormatSRLevels:
    """Tests for PromptBuilder._format_sr_levels()."""

    @patch("src.prediction.prompts.load_config")
    def test_format_sr_levels_with_data(self, mock_load_config, sample_sr_levels):
        """Verify S/R levels include type label and strength."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.prompts import PromptBuilder

        builder = PromptBuilder()
        result = builder._format_sr_levels(sample_sr_levels)

        assert "支撑位" in result
        assert "阻力位" in result
        assert "10.20" in result
        assert "11.50" in result

    @patch("src.prediction.prompts.load_config")
    def test_format_sr_levels_empty(self, mock_load_config):
        """Verify empty S/R levels returns placeholder text."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.prompts import PromptBuilder

        builder = PromptBuilder()
        result = builder._format_sr_levels([])

        assert "无支撑/阻力位数据" in result

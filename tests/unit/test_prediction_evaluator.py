"""Unit tests for src/prediction/evaluator.py — PredictionEvaluator.

Test cases per PRD Section 6.2:
  - Direction accuracy evaluation (correct and incorrect)
  - Price range hit/miss detection
  - Signal accuracy assessment
  - Chinese-language report generation
  - Neutral prediction handling
  - Prediction persistence (save/load)
  - Complete report generation with per-symbol breakdown

Per PRD Section 6.3 mock strategy:
  - Mock config loading (external I/O) only
  - Use realistic sample data structures from conftest.py
  - Use tmp_path for file I/O tests
"""

import json
from datetime import date, datetime, timezone

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
def bullish_prediction():
    """Prediction dict with bullish trend and buy signal."""
    return {
        "trend": "bullish",
        "signal": "buy",
        "confidence": 0.8,
        "risk_level": "medium",
        "reasoning": ["趋势向上", "指标看涨", "形态良好", "综合看多"],
        "target_price_range": {"low": 10.50, "high": 11.50},
        "key_factors": ["均线多头"],
        "risk_warnings": ["系统性风险"],
        "symbol": "000001",
    }


@pytest.fixture
def bearish_prediction():
    """Prediction dict with bearish trend and sell signal."""
    return {
        "trend": "bearish",
        "signal": "sell",
        "confidence": 0.7,
        "risk_level": "high",
        "reasoning": ["趋势向下", "指标看跌", "形态破位", "综合看空"],
        "target_price_range": {"low": 9.00, "high": 9.80},
        "key_factors": ["均线空头"],
        "risk_warnings": ["个股风险"],
        "symbol": "000001",
    }


@pytest.fixture
def neutral_prediction():
    """Prediction dict with neutral trend and hold signal."""
    return {
        "trend": "neutral",
        "signal": "hold",
        "confidence": 0.5,
        "risk_level": "low",
        "reasoning": ["趋势横盘", "指标中性", "无明显形态", "建议观望"],
        "target_price_range": {"low": 10.00, "high": 10.20},
        "key_factors": ["震荡整理"],
        "risk_warnings": ["方向不明"],
        "symbol": "000001",
    }


@pytest.fixture
def actual_data_price_up():
    """Actual data showing price increase (bullish movement)."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-16", periods=5, freq="B"),
            "close": [10.10, 10.30, 10.50, 10.80, 11.00],
            "open": [10.00, 10.15, 10.35, 10.55, 10.75],
            "high": [10.35, 10.45, 10.60, 10.90, 11.10],
            "low": [9.95, 10.10, 10.30, 10.50, 10.70],
            "volume": [1000000, 1100000, 1200000, 1300000, 1400000],
        }
    )


@pytest.fixture
def actual_data_price_down():
    """Actual data showing price decrease (bearish movement)."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-16", periods=5, freq="B"),
            "close": [10.10, 9.90, 9.70, 9.50, 9.30],
            "open": [10.20, 10.00, 9.85, 9.65, 9.45],
            "high": [10.25, 10.05, 9.90, 9.70, 9.55],
            "low": [10.00, 9.85, 9.65, 9.45, 9.25],
            "volume": [1000000, 1100000, 1200000, 1300000, 1400000],
        }
    )


@pytest.fixture
def actual_data_flat():
    """Actual data showing minimal price change (neutral movement)."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-16", periods=5, freq="B"),
            "close": [10.10, 10.12, 10.08, 10.11, 10.10],
            "open": [10.08, 10.10, 10.11, 10.09, 10.10],
            "high": [10.15, 10.15, 10.14, 10.14, 10.13],
            "low": [10.05, 10.08, 10.05, 10.06, 10.07],
            "volume": [1000000, 900000, 800000, 850000, 900000],
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEvaluateDirectionAccuracy:
    """Tests for direction accuracy evaluation."""

    @patch("src.prediction.evaluator.load_config")
    def test_evaluate_direction_accuracy_correct(
        self,
        mock_load_config,
        bullish_prediction,
        actual_data_price_up,
    ):
        """Bullish prediction + price up = direction_accuracy True."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        result = evaluator.evaluate(bullish_prediction, actual_data_price_up)

        assert result["direction_accuracy"] is True
        assert result["predicted_trend"] == "bullish"
        assert result["actual_trend"] == "bullish"
        assert result["actual_return"] > 0

    @patch("src.prediction.evaluator.load_config")
    def test_evaluate_direction_accuracy_wrong(
        self,
        mock_load_config,
        bullish_prediction,
        actual_data_price_down,
    ):
        """Bullish prediction + price down = direction_accuracy False."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        result = evaluator.evaluate(bullish_prediction, actual_data_price_down)

        assert result["direction_accuracy"] is False
        assert result["predicted_trend"] == "bullish"
        assert result["actual_trend"] == "bearish"
        assert result["actual_return"] < 0

    @patch("src.prediction.evaluator.load_config")
    def test_evaluate_bearish_direction_correct(
        self,
        mock_load_config,
        bearish_prediction,
        actual_data_price_down,
    ):
        """Bearish prediction + price down = direction_accuracy True."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        result = evaluator.evaluate(bearish_prediction, actual_data_price_down)

        assert result["direction_accuracy"] is True
        assert result["predicted_trend"] == "bearish"
        assert result["actual_trend"] == "bearish"


class TestEvaluatePriceRange:
    """Tests for price range hit/miss evaluation."""

    @patch("src.prediction.evaluator.load_config")
    def test_evaluate_price_range_hit(
        self,
        mock_load_config,
        bullish_prediction,
        actual_data_price_up,
    ):
        """Actual close within predicted range = price_range_hit True."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        # actual end close = 11.00, target range = [10.50, 11.50]
        result = evaluator.evaluate(bullish_prediction, actual_data_price_up)

        assert result["price_range_hit"] is True

    @patch("src.prediction.evaluator.load_config")
    def test_evaluate_price_range_miss(
        self,
        mock_load_config,
        bearish_prediction,
        actual_data_price_up,
    ):
        """Actual close outside predicted range = price_range_hit False."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        # actual end close = 11.00, target range = [9.00, 9.80]
        result = evaluator.evaluate(bearish_prediction, actual_data_price_up)

        assert result["price_range_hit"] is False

    @patch("src.prediction.evaluator.load_config")
    def test_evaluate_price_range_no_target(self, mock_load_config):
        """Missing target_price_range returns price_range_hit False."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        prediction = {
            "trend": "bullish",
            "signal": "buy",
            "confidence": 0.7,
            "symbol": "000001",
        }
        actual_data = pd.DataFrame(
            {
                "close": [10.0, 10.5],
                "date": pd.date_range("2024-01-16", periods=2, freq="B"),
            }
        )
        result = evaluator.evaluate(prediction, actual_data)

        assert result["price_range_hit"] is False


class TestEvaluateSignalAccuracy:
    """Tests for signal accuracy evaluation."""

    @patch("src.prediction.evaluator.load_config")
    def test_buy_signal_correct_when_price_up(
        self,
        mock_load_config,
        bullish_prediction,
        actual_data_price_up,
    ):
        """Buy signal is correct when actual return is positive."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        result = evaluator.evaluate(bullish_prediction, actual_data_price_up)

        assert result["signal_accuracy"] is True

    @patch("src.prediction.evaluator.load_config")
    def test_sell_signal_correct_when_price_down(
        self,
        mock_load_config,
        bearish_prediction,
        actual_data_price_down,
    ):
        """Sell signal is correct when actual return is negative."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        result = evaluator.evaluate(bearish_prediction, actual_data_price_down)

        assert result["signal_accuracy"] is True

    @patch("src.prediction.evaluator.load_config")
    def test_buy_signal_wrong_when_price_down(
        self,
        mock_load_config,
        bullish_prediction,
        actual_data_price_down,
    ):
        """Buy signal is wrong when actual return is negative."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        result = evaluator.evaluate(bullish_prediction, actual_data_price_down)

        assert result["signal_accuracy"] is False


class TestEvaluateWithNeutralPrediction:
    """Tests for neutral trend prediction handling."""

    @patch("src.prediction.evaluator.load_config")
    def test_evaluate_with_neutral_prediction(
        self,
        mock_load_config,
        neutral_prediction,
        actual_data_flat,
    ):
        """Handle neutral trend prediction with flat actual data."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        result = evaluator.evaluate(neutral_prediction, actual_data_flat)

        assert isinstance(result, dict)
        assert "direction_accuracy" in result
        assert "price_range_hit" in result
        assert "signal_accuracy" in result
        assert "confidence_calibration" in result
        assert result["predicted_trend"] == "neutral"

    @patch("src.prediction.evaluator.load_config")
    def test_neutral_direction_matches_flat_market(
        self,
        mock_load_config,
        neutral_prediction,
        actual_data_flat,
    ):
        """Neutral prediction is correct when market is flat."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        result = evaluator.evaluate(neutral_prediction, actual_data_flat)

        # Flat data should classify as neutral (< 0.5% movement)
        assert result["actual_trend"] == "neutral"
        assert result["direction_accuracy"] is True


class TestGenerateReport:
    """Tests for PredictionEvaluator.generate_report()."""

    @patch("src.prediction.evaluator.load_config")
    def test_generate_report_in_chinese(self, mock_load_config):
        """Verify report output is Chinese text."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        evaluations = [
            {
                "direction_accuracy": True,
                "price_range_hit": True,
                "signal_accuracy": True,
                "confidence_calibration": 0.85,
                "actual_return": 0.05,
                "confidence": 0.8,
                "symbol": "000001",
            },
            {
                "direction_accuracy": False,
                "price_range_hit": False,
                "signal_accuracy": False,
                "confidence_calibration": 0.30,
                "actual_return": -0.03,
                "confidence": 0.7,
                "symbol": "600519",
            },
        ]

        report = evaluator.generate_report(evaluations)

        assert isinstance(report, str)
        assert len(report) > 0

        # Report must contain Chinese text
        assert "评估报告" in report
        assert "方向准确率" in report
        assert "价格区间命中率" in report
        assert "信号准确率" in report
        assert "置信度" in report
        assert "综合评分" in report
        assert "评级" in report

        # Report must contain actual metrics
        assert "1/2" in report  # 1 out of 2 correct
        assert "2" in report  # total samples

    @patch("src.prediction.evaluator.load_config")
    def test_generate_report_empty_evaluations(self, mock_load_config):
        """Verify report handles empty evaluation list."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        report = evaluator.generate_report([])

        assert "暂无评估数据" in report

    @patch("src.prediction.evaluator.load_config")
    def test_generate_report_all_correct(self, mock_load_config):
        """Verify excellent rating for all-correct predictions."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        evaluations = [
            {
                "direction_accuracy": True,
                "price_range_hit": True,
                "signal_accuracy": True,
                "confidence_calibration": 0.95,
                "actual_return": 0.08,
                "confidence": 0.9,
                "symbol": "000001",
            },
            {
                "direction_accuracy": True,
                "price_range_hit": True,
                "signal_accuracy": True,
                "confidence_calibration": 0.90,
                "actual_return": 0.06,
                "confidence": 0.85,
                "symbol": "600519",
            },
        ]

        report = evaluator.generate_report(evaluations)

        assert "优秀" in report
        assert "通过" in report

    @patch("src.prediction.evaluator.load_config")
    def test_generate_report_threshold_check(self, mock_load_config):
        """Verify threshold pass/fail messages appear in report."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        # All wrong predictions -> below threshold
        evaluations = [
            {
                "direction_accuracy": False,
                "price_range_hit": False,
                "signal_accuracy": False,
                "confidence_calibration": 0.20,
                "actual_return": -0.05,
                "confidence": 0.8,
                "symbol": "000001",
            },
        ]

        report = evaluator.generate_report(evaluations)

        assert "未通过" in report


class TestEvaluationValidation:
    """Tests for input validation in evaluate()."""

    @patch("src.prediction.evaluator.load_config")
    def test_evaluate_empty_dataframe_raises(self, mock_load_config):
        """Verify error when actual data is empty."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import EvaluationError, PredictionEvaluator

        evaluator = PredictionEvaluator()

        prediction = {
            "trend": "bullish",
            "signal": "buy",
            "confidence": 0.7,
        }
        empty_df = pd.DataFrame()

        with pytest.raises(EvaluationError, match="empty"):
            evaluator.evaluate(prediction, empty_df)

    @patch("src.prediction.evaluator.load_config")
    def test_evaluate_missing_close_column_raises(self, mock_load_config):
        """Verify error when actual data has no close column."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import EvaluationError, PredictionEvaluator

        evaluator = PredictionEvaluator()

        prediction = {
            "trend": "bullish",
            "signal": "buy",
            "confidence": 0.7,
        }
        no_close_df = pd.DataFrame({"open": [10.0, 10.5], "volume": [1000, 2000]})

        with pytest.raises(EvaluationError, match="close"):
            evaluator.evaluate(prediction, no_close_df)

    @patch("src.prediction.evaluator.load_config")
    def test_evaluate_single_row_raises(self, mock_load_config):
        """Verify error when actual data has only 1 row."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import EvaluationError, PredictionEvaluator

        evaluator = PredictionEvaluator()

        prediction = {
            "trend": "bullish",
            "signal": "buy",
            "confidence": 0.7,
        }
        single_row_df = pd.DataFrame({"close": [10.0]})

        with pytest.raises(EvaluationError, match="at least 2 rows"):
            evaluator.evaluate(prediction, single_row_df)

    @patch("src.prediction.evaluator.load_config")
    def test_evaluate_missing_prediction_fields_raises(self, mock_load_config):
        """Verify error when prediction is missing required fields."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import EvaluationError, PredictionEvaluator

        evaluator = PredictionEvaluator()

        incomplete_prediction = {"trend": "bullish"}
        actual_data = pd.DataFrame({"close": [10.0, 10.5]})

        with pytest.raises(EvaluationError, match="missing required"):
            evaluator.evaluate(incomplete_prediction, actual_data)


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_classify_trend_bullish(self):
        """Positive return above threshold -> bullish."""
        from src.prediction.evaluator import _classify_trend

        assert _classify_trend(0.02) == "bullish"
        assert _classify_trend(0.006) == "bullish"

    def test_classify_trend_bearish(self):
        """Negative return below threshold -> bearish."""
        from src.prediction.evaluator import _classify_trend

        assert _classify_trend(-0.02) == "bearish"
        assert _classify_trend(-0.006) == "bearish"

    def test_classify_trend_neutral(self):
        """Small absolute return -> neutral."""
        from src.prediction.evaluator import _classify_trend

        assert _classify_trend(0.003) == "neutral"
        assert _classify_trend(-0.003) == "neutral"
        assert _classify_trend(0.0) == "neutral"

    def test_check_signal_accuracy_watch(self):
        """Watch signal is always correct."""
        from src.prediction.evaluator import _check_signal_accuracy

        assert _check_signal_accuracy("watch", 0.05) is True
        assert _check_signal_accuracy("watch", -0.05) is True
        assert _check_signal_accuracy("watch", 0.0) is True

    def test_check_signal_accuracy_hold(self):
        """Hold signal is correct when absolute return < 2%."""
        from src.prediction.evaluator import _check_signal_accuracy

        assert _check_signal_accuracy("hold", 0.01) is True
        assert _check_signal_accuracy("hold", -0.01) is True
        assert _check_signal_accuracy("hold", 0.05) is False

    def test_compute_accuracy_score(self):
        """Verify weighted accuracy score computation."""
        from src.prediction.evaluator import _compute_accuracy_score

        # All correct: 0.4 + 0.3 + 0.3 = 1.0
        assert _compute_accuracy_score(True, True, True) == 1.0

        # All wrong: 0.0
        assert _compute_accuracy_score(False, False, False) == 0.0

        # Direction only: 0.4
        assert abs(_compute_accuracy_score(True, False, False) - 0.4) < 1e-9

    def test_check_price_range_hit_with_tolerance(self):
        """Price range with tolerance buffer expands boundaries."""
        from src.prediction.evaluator import _check_price_range_hit

        target = {"low": 10.0, "high": 11.0}
        # Within range
        assert _check_price_range_hit(10.5, target, 0.05) is True
        # Just outside range but within tolerance
        # range_width = 1.0, buffer = 0.05
        # adjusted_low = 9.95, adjusted_high = 11.05
        assert _check_price_range_hit(11.04, target, 0.05) is True
        # Far outside range
        assert _check_price_range_hit(12.0, target, 0.05) is False


class TestSavePrediction:
    """Tests for PredictionEvaluator.save_prediction()."""

    @patch("src.prediction.evaluator.load_config")
    @patch("src.prediction.evaluator.get_data_dir")
    def test_save_prediction_creates_file(
        self, mock_get_data_dir, mock_load_config, tmp_path
    ):
        """Verify save_prediction creates JSON file at correct path."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG
        mock_get_data_dir.return_value = tmp_path

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        prediction = {
            "trend": "bullish",
            "signal": "buy",
            "confidence": 0.8,
        }
        ts = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)

        result_path = evaluator.save_prediction("000001", prediction, ts)

        assert result_path.exists()
        assert result_path.name == "000001_20240315.json"
        assert "predictions" in str(result_path)
        assert "000001" in str(result_path)
        assert "2024" in str(result_path)
        assert "03" in str(result_path)

        # Verify JSON content
        with open(result_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["trend"] == "bullish"
        assert saved["confidence"] == 0.8
        assert "save_timestamp" in saved

    @patch("src.prediction.evaluator.load_config")
    @patch("src.prediction.evaluator.get_data_dir")
    def test_save_prediction_default_timestamp(
        self, mock_get_data_dir, mock_load_config, tmp_path
    ):
        """Verify save_prediction uses UTC now when timestamp is None."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG
        mock_get_data_dir.return_value = tmp_path

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        prediction = {"trend": "bearish", "signal": "sell", "confidence": 0.6}

        result_path = evaluator.save_prediction("600519", prediction)

        assert result_path.exists()
        assert "600519" in result_path.name

    @patch("src.prediction.evaluator.load_config")
    @patch("src.prediction.evaluator.get_data_dir")
    def test_save_prediction_creates_directories(
        self, mock_get_data_dir, mock_load_config, tmp_path
    ):
        """Verify save_prediction creates nested directories as needed."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG
        mock_get_data_dir.return_value = tmp_path

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        prediction = {"trend": "neutral", "signal": "hold", "confidence": 0.5}
        ts = datetime(2025, 12, 1, tzinfo=timezone.utc)

        result_path = evaluator.save_prediction("300750", prediction, ts)

        expected_dir = tmp_path / "predictions" / "300750" / "2025" / "12"
        assert expected_dir.exists()
        assert result_path.parent == expected_dir


class TestLoadPredictions:
    """Tests for PredictionEvaluator.load_predictions()."""

    @patch("src.prediction.evaluator.load_config")
    @patch("src.prediction.evaluator.get_data_dir")
    def test_load_predictions_date_range_filtering(
        self, mock_get_data_dir, mock_load_config, tmp_path
    ):
        """Verify load_predictions filters by date range correctly."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG
        mock_get_data_dir.return_value = tmp_path

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        # Save predictions across different dates
        dates = [
            datetime(2024, 1, 10, tzinfo=timezone.utc),
            datetime(2024, 1, 15, tzinfo=timezone.utc),
            datetime(2024, 1, 20, tzinfo=timezone.utc),
            datetime(2024, 2, 5, tzinfo=timezone.utc),
        ]
        for ts in dates:
            evaluator.save_prediction(
                "000001",
                {"trend": "bullish", "signal": "buy", "confidence": 0.7},
                ts,
            )

        # Load only January 12-18
        results = evaluator.load_predictions(
            "000001",
            start_date=date(2024, 1, 12),
            end_date=date(2024, 1, 18),
        )

        assert len(results) == 1
        assert results[0]["_file_date"] == "2024-01-15"

    @patch("src.prediction.evaluator.load_config")
    @patch("src.prediction.evaluator.get_data_dir")
    def test_load_predictions_full_range(
        self, mock_get_data_dir, mock_load_config, tmp_path
    ):
        """Verify loading all predictions in a wide range."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG
        mock_get_data_dir.return_value = tmp_path

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        for day in [5, 10, 15]:
            evaluator.save_prediction(
                "600519",
                {"trend": "bullish", "signal": "buy", "confidence": 0.8},
                datetime(2024, 3, day, tzinfo=timezone.utc),
            )

        results = evaluator.load_predictions(
            "600519",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )

        assert len(results) == 3

    @patch("src.prediction.evaluator.load_config")
    @patch("src.prediction.evaluator.get_data_dir")
    def test_load_predictions_empty_when_no_dir(
        self, mock_get_data_dir, mock_load_config, tmp_path
    ):
        """Verify empty list when symbol directory does not exist."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG
        mock_get_data_dir.return_value = tmp_path

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()
        results = evaluator.load_predictions(
            "999999",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )

        assert results == []

    @patch("src.prediction.evaluator.load_config")
    @patch("src.prediction.evaluator.get_data_dir")
    def test_load_predictions_sorted_by_date(
        self, mock_get_data_dir, mock_load_config, tmp_path
    ):
        """Verify loaded predictions are sorted by date ascending."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG
        mock_get_data_dir.return_value = tmp_path

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        # Save in reverse chronological order
        for day in [20, 10, 5, 15]:
            evaluator.save_prediction(
                "000001",
                {"trend": "bullish", "signal": "buy", "confidence": 0.7},
                datetime(2024, 6, day, tzinfo=timezone.utc),
            )

        results = evaluator.load_predictions(
            "000001",
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 30),
        )

        assert len(results) == 4
        file_dates = [r["_file_date"] for r in results]
        assert file_dates == sorted(file_dates)


class TestGenerateReportComplete:
    """Tests for complete report generation with per-symbol breakdown."""

    @patch("src.prediction.evaluator.load_config")
    def test_generate_report_has_per_symbol_breakdown(self, mock_load_config):
        """Verify report includes per-symbol accuracy breakdown."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        evaluations = [
            {
                "direction_accuracy": True,
                "price_range_hit": True,
                "signal_accuracy": True,
                "confidence_calibration": 0.9,
                "actual_return": 0.05,
                "confidence": 0.8,
                "symbol": "000001",
            },
            {
                "direction_accuracy": False,
                "price_range_hit": False,
                "signal_accuracy": True,
                "confidence_calibration": 0.5,
                "actual_return": -0.02,
                "confidence": 0.6,
                "symbol": "600519",
            },
        ]

        report = evaluator.generate_report(evaluations)

        # Per-symbol breakdown section
        assert "个股明细" in report
        assert "000001" in report
        assert "600519" in report

    @patch("src.prediction.evaluator.load_config")
    def test_generate_report_has_disclaimer(self, mock_load_config):
        """Verify report includes Chinese disclaimer text."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        evaluations = [
            {
                "direction_accuracy": True,
                "price_range_hit": True,
                "signal_accuracy": True,
                "confidence_calibration": 0.9,
                "actual_return": 0.05,
                "confidence": 0.8,
                "symbol": "000001",
            },
        ]

        report = evaluator.generate_report(evaluations)

        assert "免责声明" in report
        assert "不构成任何投资建议" in report
        assert "股市有风险" in report

    @patch("src.prediction.evaluator.load_config")
    def test_generate_report_complete_format(self, mock_load_config):
        """Verify complete report has all required sections."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        evaluations = [
            {
                "direction_accuracy": True,
                "price_range_hit": True,
                "signal_accuracy": True,
                "confidence_calibration": 0.95,
                "actual_return": 0.08,
                "confidence": 0.9,
                "symbol": "000001",
            },
            {
                "direction_accuracy": True,
                "price_range_hit": False,
                "signal_accuracy": True,
                "confidence_calibration": 0.70,
                "actual_return": 0.03,
                "confidence": 0.7,
                "symbol": "600519",
            },
            {
                "direction_accuracy": False,
                "price_range_hit": False,
                "signal_accuracy": False,
                "confidence_calibration": 0.30,
                "actual_return": -0.05,
                "confidence": 0.8,
                "symbol": "300750",
            },
        ]

        report = evaluator.generate_report(evaluations)

        # Overall accuracy summary
        assert "方向准确率" in report
        assert "价格区间命中率" in report
        assert "信号准确率" in report

        # Rating (评级)
        assert "评级" in report

        # One of the four ratings should appear
        has_rating = any(r in report for r in ["优秀", "良好", "一般", "较差"])
        assert has_rating

        # Per-symbol breakdown
        assert "个股明细" in report
        assert "000001" in report
        assert "600519" in report
        assert "300750" in report

        # Disclaimer
        assert "免责声明" in report

    @patch("src.prediction.evaluator.load_config")
    def test_generate_report_rating_levels(self, mock_load_config):
        """Verify correct rating for different accuracy levels."""
        mock_load_config.return_value = SAMPLE_PREDICTION_CONFIG

        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        # All wrong -> 较差
        poor_evals = [
            {
                "direction_accuracy": False,
                "price_range_hit": False,
                "signal_accuracy": False,
                "confidence_calibration": 0.1,
                "actual_return": -0.1,
                "confidence": 0.9,
                "symbol": "000001",
            },
        ]
        report = evaluator.generate_report(poor_evals)
        assert "较差" in report

        # All correct -> 优秀
        excellent_evals = [
            {
                "direction_accuracy": True,
                "price_range_hit": True,
                "signal_accuracy": True,
                "confidence_calibration": 0.95,
                "actual_return": 0.05,
                "confidence": 0.9,
                "symbol": "000001",
            },
        ]
        report = evaluator.generate_report(excellent_evals)
        assert "优秀" in report

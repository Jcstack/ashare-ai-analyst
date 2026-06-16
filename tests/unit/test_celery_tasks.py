"""Unit tests for the OpenClaw Celery tasks and app configuration.

Tests the daily pipeline tasks (fetch, analyze, predict, weekly report)
with all external dependencies mocked. Verifies task orchestration,
error handling, retry behavior, and Discord notification integration.

Per PRD Section 6: Mock external dependencies only.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_openclaw_config():
    """Minimal openclaw.yaml config for testing."""
    return {
        "celery": {
            "broker_url": "redis://test-redis:6379/0",
            "result_backend": "redis://test-redis:6379/1",
            "timezone": "Asia/Shanghai",
        },
        "beat_schedule": {
            "daily_fetch": {
                "task": "openclaw.tasks.daily_pipeline.task_fetch_all",
                "schedule": {
                    "crontab": {"hour": 16, "minute": 0, "day_of_week": "1-5"}
                },
            },
            "daily_analysis": {
                "task": "openclaw.tasks.daily_pipeline.task_analyze_all",
                "schedule": {
                    "crontab": {"hour": 16, "minute": 30, "day_of_week": "1-5"}
                },
            },
            "daily_prediction": {
                "task": "openclaw.tasks.daily_pipeline.task_predict_all",
                "schedule": {
                    "crontab": {"hour": 17, "minute": 0, "day_of_week": "1-5"}
                },
            },
            "weekly_report": {
                "task": "openclaw.tasks.daily_pipeline.task_weekly_report",
                "schedule": {"crontab": {"hour": 18, "minute": 0, "day_of_week": "5"}},
            },
        },
        "pipeline": {"max_retries": 3, "retry_delay_seconds": 60},
    }


@pytest.fixture
def mock_stocks_config():
    """Minimal stocks.yaml config for testing."""
    return {
        "watchlist": [
            {"symbol": "000001", "name": "平安银行", "board": "main"},
            {"symbol": "600519", "name": "贵州茅台", "board": "main"},
        ],
        "data_collection": {"daily": {"enabled": True, "start_date": "20240101"}},
        "cache": {"enabled": True, "directory": "data/raw", "ttl_hours": 12},
        "request": {
            "interval_seconds": 0,
            "max_retries": 3,
            "retry_delay_seconds": 0,
            "timeout_seconds": 10,
        },
    }


@pytest.fixture
def sample_df():
    """Fixed sample OHLCV data for testing."""
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [10.0, 10.2, 10.1, 10.5, 10.3],
            "close": [10.1, 10.0, 10.4, 10.2, 10.7],
            "high": [10.3, 10.3, 10.5, 10.6, 10.8],
            "low": [9.9, 9.9, 10.0, 10.1, 10.2],
            "volume": [1000000, 1200000, 900000, 1500000, 1100000],
            "amount": [1e7, 1.2e7, 9e6, 1.5e7, 1.1e7],
        }
    )


@pytest.fixture
def sample_prediction():
    """Sample prediction result dict."""
    return {
        "trend": "bullish",
        "signal": "buy",
        "confidence": 0.75,
        "risk_level": "medium",
        "target_price_range": {"low": 10.5, "high": 11.5},
        "reasoning": ["Strong uptrend"],
        "key_factors": ["MA crossover"],
        "risk_warnings": ["Market volatility"],
    }


def _config_side_effect(stocks_cfg):
    """Return a load_config side_effect that serves stocks and openclaw."""

    def _side_effect(name):
        if name == "stocks":
            return stocks_cfg
        if name == "openclaw":
            return {"pipeline": {"max_retries": 3, "retry_delay_seconds": 60}}
        return {}

    return _side_effect


def _make_pipeline_mocks(sample_df, patterns_col="pattern_hammer"):
    """Build common data-pipeline mocks (fetcher, preprocessor, etc.).

    Returns:
        Tuple of (fetcher, preprocessor, indicators, pattern_recognizer,
        df_with_patterns) mock instances.
    """
    fetcher = MagicMock()
    fetcher.fetch_daily_ohlcv.return_value = sample_df
    fetcher.fetch_all_watchlist.return_value = {
        "000001": sample_df,
        "600519": sample_df,
    }

    preprocessor = MagicMock()
    preprocessor.clean_ohlcv.return_value = sample_df
    preprocessor.add_returns.return_value = sample_df
    preprocessor.process_all.return_value = {
        "000001": sample_df,
        "600519": sample_df,
    }

    indicators = MagicMock()
    indicators.add_all.return_value = sample_df

    df_with_patterns = sample_df.copy()
    df_with_patterns[patterns_col] = [0, 0, 0, 0, 0]
    pattern_recognizer = MagicMock()
    pattern_recognizer.detect_candlestick_patterns.return_value = df_with_patterns
    pattern_recognizer.find_support_resistance.return_value = [
        {"level": 10.0, "type": "support", "touches": 3}
    ]

    return fetcher, preprocessor, indicators, pattern_recognizer, df_with_patterns


# ---------------------------------------------------------------------------
# Tests: task_fetch_all
# ---------------------------------------------------------------------------


class TestTaskFetchAll:
    """Tests for the task_fetch_all Celery task."""

    @patch("openclaw.tasks.daily_pipeline._should_execute", return_value=True)
    @patch("openclaw.tasks.daily_pipeline._create_notifier")
    @patch("src.data.preprocessor.DataPreprocessor")
    @patch("src.data.fetcher.StockDataFetcher")
    def test_task_fetch_all_calls_fetcher(
        self,
        mock_fetcher_cls,
        mock_preproc_cls,
        mock_notif,
        _mock_sched,
        sample_df,
    ):
        """Verify fetch_all_watchlist is called on the fetcher."""
        fetcher, preprocessor, *_ = _make_pipeline_mocks(sample_df)
        mock_fetcher_cls.return_value = fetcher
        mock_preproc_cls.return_value = preprocessor
        mock_notif.return_value = MagicMock()

        from openclaw.tasks.daily_pipeline import task_fetch_all

        result = task_fetch_all.apply(args=[]).get(timeout=5)

        fetcher.fetch_all_watchlist.assert_called_once()
        preprocessor.process_all.assert_called_once()
        assert result == {"000001": "fetched", "600519": "fetched"}

    @patch("openclaw.tasks.daily_pipeline._should_execute", return_value=True)
    @patch("openclaw.tasks.daily_pipeline._create_notifier")
    @patch("src.data.fetcher.StockDataFetcher")
    def test_task_fetch_all_sends_error_alert_on_failure(
        self,
        mock_fetcher_cls,
        mock_notif,
        _mock_sched,
    ):
        """Verify send_error_alert is called when fetching fails."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_all_watchlist.side_effect = RuntimeError(
            "Connection refused"
        )
        mock_fetcher_cls.return_value = mock_fetcher
        notifier = MagicMock()
        mock_notif.return_value = notifier

        from openclaw.tasks.daily_pipeline import task_fetch_all

        with pytest.raises(RuntimeError, match="Connection refused"):
            task_fetch_all.apply(args=[]).get(timeout=5)

        notifier.send_error_alert.assert_called()
        assert "task_fetch_all failed" in notifier.send_error_alert.call_args[0][0]

    @patch("openclaw.tasks.daily_pipeline._should_execute", return_value=True)
    @patch("openclaw.tasks.daily_pipeline._create_notifier")
    @patch("src.data.preprocessor.DataPreprocessor")
    @patch("src.data.fetcher.StockDataFetcher")
    def test_task_fetch_all_empty_watchlist(
        self,
        mock_fetcher_cls,
        mock_preproc_cls,
        mock_notif,
        _mock_sched,
    ):
        """Verify graceful handling when the watchlist is empty."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_all_watchlist.return_value = {}
        mock_fetcher_cls.return_value = mock_fetcher
        mock_preproc = MagicMock()
        mock_preproc_cls.return_value = mock_preproc
        mock_notif.return_value = MagicMock()

        from openclaw.tasks.daily_pipeline import task_fetch_all

        result = task_fetch_all.apply(args=[]).get(timeout=5)
        assert result == {}
        mock_preproc.process_all.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: task_analyze_all
# ---------------------------------------------------------------------------


class TestTaskAnalyzeAll:
    """Tests for the task_analyze_all Celery task."""

    @patch("openclaw.tasks.daily_pipeline._should_execute", return_value=True)
    @patch("openclaw.tasks.daily_pipeline._create_notifier")
    @patch("openclaw.tasks.daily_pipeline.load_config")
    @patch("src.analysis.patterns.PatternRecognizer")
    @patch("src.analysis.indicators.TechnicalIndicators")
    @patch("src.data.preprocessor.DataPreprocessor")
    @patch("src.data.fetcher.StockDataFetcher")
    def test_task_analyze_all_returns_results(
        self,
        mock_f_cls,
        mock_p_cls,
        mock_i_cls,
        mock_pat_cls,
        mock_load_config,
        mock_notif,
        _mock_sched,
        sample_df,
        mock_stocks_config,
    ):
        """Verify analysis returns results for each watchlist stock."""
        mock_load_config.side_effect = _config_side_effect(mock_stocks_config)
        fetcher, preprocessor, indicators, pattern_rec, _ = _make_pipeline_mocks(
            sample_df, "pattern_hammer"
        )
        mock_f_cls.return_value = fetcher
        mock_p_cls.return_value = preprocessor
        mock_i_cls.return_value = indicators
        mock_pat_cls.return_value = pattern_rec
        mock_notif.return_value = MagicMock()

        from openclaw.tasks.daily_pipeline import task_analyze_all

        result = task_analyze_all.apply(args=[]).get(timeout=5)

        assert "000001" in result and "600519" in result
        for sym in ["000001", "600519"]:
            assert result[sym]["indicators_added"] is True
            assert result[sym]["sr_levels_found"] == 1


# ---------------------------------------------------------------------------
# Tests: task_predict_all
# ---------------------------------------------------------------------------


class TestTaskPredictAll:
    """Tests for the task_predict_all Celery task."""

    @patch("openclaw.tasks.daily_pipeline._should_execute", return_value=True)
    @patch("openclaw.tasks.daily_pipeline._create_notifier")
    @patch("openclaw.tasks.daily_pipeline.load_config")
    @patch("src.prediction.analyzer.StockAnalyzer")
    @patch("src.analysis.patterns.PatternRecognizer")
    @patch("src.analysis.indicators.TechnicalIndicators")
    @patch("src.data.preprocessor.DataPreprocessor")
    @patch("src.data.fetcher.StockDataFetcher")
    def test_task_predict_all_sends_discord_alerts(
        self,
        mock_f_cls,
        mock_p_cls,
        mock_i_cls,
        mock_pat_cls,
        mock_a_cls,
        mock_load_config,
        mock_notif,
        _mock_sched,
        sample_df,
        mock_stocks_config,
        sample_prediction,
    ):
        """Verify send_analysis_alert is called for each stock."""
        mock_load_config.side_effect = _config_side_effect(mock_stocks_config)
        fetcher, preprocessor, indicators, pattern_rec, _ = _make_pipeline_mocks(
            sample_df
        )
        mock_f_cls.return_value = fetcher
        mock_p_cls.return_value = preprocessor
        mock_i_cls.return_value = indicators
        mock_pat_cls.return_value = pattern_rec

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = sample_prediction
        mock_a_cls.return_value = mock_analyzer

        notifier = MagicMock()
        notifier.send_analysis_alert.return_value = True
        notifier.send_daily_summary.return_value = True
        mock_notif.return_value = notifier

        from openclaw.tasks.daily_pipeline import task_predict_all

        result = task_predict_all.apply(args=[]).get(timeout=5)

        assert notifier.send_analysis_alert.call_count == 2
        alert_symbols = [
            c.kwargs.get("symbol", c.args[0] if c.args else None)
            for c in notifier.send_analysis_alert.call_args_list
        ]
        assert "000001" in alert_symbols and "600519" in alert_symbols
        assert result["000001"]["signal"] == "buy"

    @patch("openclaw.tasks.daily_pipeline._should_execute", return_value=True)
    @patch("openclaw.tasks.daily_pipeline._create_notifier")
    @patch("openclaw.tasks.daily_pipeline.load_config")
    @patch("src.prediction.analyzer.StockAnalyzer")
    @patch("src.analysis.patterns.PatternRecognizer")
    @patch("src.analysis.indicators.TechnicalIndicators")
    @patch("src.data.preprocessor.DataPreprocessor")
    @patch("src.data.fetcher.StockDataFetcher")
    def test_task_predict_all_sends_daily_summary(
        self,
        mock_f_cls,
        mock_p_cls,
        mock_i_cls,
        mock_pat_cls,
        mock_a_cls,
        mock_load_config,
        mock_notif,
        _mock_sched,
        sample_df,
        mock_stocks_config,
        sample_prediction,
    ):
        """Verify send_daily_summary is called after all predictions."""
        mock_load_config.side_effect = _config_side_effect(mock_stocks_config)
        fetcher, preprocessor, indicators, pattern_rec, _ = _make_pipeline_mocks(
            sample_df
        )
        mock_f_cls.return_value = fetcher
        mock_p_cls.return_value = preprocessor
        mock_i_cls.return_value = indicators
        mock_pat_cls.return_value = pattern_rec

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = sample_prediction
        mock_a_cls.return_value = mock_analyzer

        notifier = MagicMock()
        notifier.send_analysis_alert.return_value = True
        notifier.send_daily_summary.return_value = True
        mock_notif.return_value = notifier

        from openclaw.tasks.daily_pipeline import task_predict_all

        task_predict_all.apply(args=[]).get(timeout=5)

        notifier.send_daily_summary.assert_called_once()
        summary_arg = notifier.send_daily_summary.call_args
        results_list = summary_arg.kwargs.get(
            "results", summary_arg.args[0] if summary_arg.args else []
        )
        assert len(results_list) == 2
        symbols = [r["symbol"] for r in results_list]
        assert "000001" in symbols and "600519" in symbols


# ---------------------------------------------------------------------------
# Tests: task_weekly_report
# ---------------------------------------------------------------------------


class TestTaskWeeklyReport:
    """Tests for the task_weekly_report Celery task."""

    @patch("openclaw.tasks.daily_pipeline._should_execute", return_value=True)
    @patch("openclaw.tasks.daily_pipeline._create_notifier")
    @patch("src.prediction.evaluator.PredictionEvaluator")
    def test_task_weekly_report_generates_report(
        self,
        mock_eval_cls,
        mock_notif,
        _mock_sched,
    ):
        """Verify generate_report is called on PredictionEvaluator."""
        mock_evaluator = MagicMock()
        mock_evaluator.generate_report.return_value = "本周预测评估报告：准确率 80%"
        mock_eval_cls.return_value = mock_evaluator
        mock_notif.return_value = MagicMock(
            send_daily_summary=MagicMock(return_value=True)
        )

        from openclaw.tasks.daily_pipeline import task_weekly_report

        result = task_weekly_report.apply(args=[]).get(timeout=5)

        mock_evaluator.generate_report.assert_called_once()
        assert "本周预测评估报告" in result

    @patch("openclaw.tasks.daily_pipeline._should_execute", return_value=True)
    @patch("openclaw.tasks.daily_pipeline._create_notifier")
    @patch("src.prediction.evaluator.PredictionEvaluator")
    def test_task_weekly_report_sends_error_alert_on_failure(
        self,
        mock_eval_cls,
        mock_notif,
        _mock_sched,
    ):
        """Verify send_error_alert is called when report fails."""
        mock_evaluator = MagicMock()
        mock_evaluator.generate_report.side_effect = RuntimeError(
            "Database unavailable"
        )
        mock_eval_cls.return_value = mock_evaluator
        notifier = MagicMock()
        mock_notif.return_value = notifier

        from openclaw.tasks.daily_pipeline import task_weekly_report

        with pytest.raises(RuntimeError, match="Database unavailable"):
            task_weekly_report.apply(args=[]).get(timeout=5)

        notifier.send_error_alert.assert_called()
        assert "task_weekly_report failed" in notifier.send_error_alert.call_args[0][0]


# ---------------------------------------------------------------------------
# Tests: Celery App Configuration
# ---------------------------------------------------------------------------


class TestCeleryAppConfig:
    """Tests for the Celery app factory and configuration."""

    @patch("openclaw.celery_app.load_config")
    def test_celery_app_loads_config(self, mock_lc, mock_openclaw_config):
        """Verify app is created with correct broker_url and timezone."""
        mock_lc.return_value = mock_openclaw_config
        from openclaw.celery_app import create_celery_app

        app = create_celery_app()
        assert app.main == "astock"
        assert app.conf.timezone == "Asia/Shanghai"

    @patch("openclaw.celery_app.load_config")
    def test_celery_app_beat_schedule_loaded(self, mock_lc, mock_openclaw_config):
        """Verify all four beat schedule entries are registered."""
        mock_lc.return_value = mock_openclaw_config
        from openclaw.celery_app import create_celery_app

        app = create_celery_app()

        bs = app.conf.beat_schedule
        assert all(
            k in bs
            for k in [
                "daily_fetch",
                "daily_analysis",
                "daily_prediction",
                "weekly_report",
            ]
        )
        assert (
            bs["daily_fetch"]["task"] == "openclaw.tasks.daily_pipeline.task_fetch_all"
        )
        assert (
            bs["weekly_report"]["task"]
            == "openclaw.tasks.daily_pipeline.task_weekly_report"
        )

    @patch.dict("os.environ", {"CELERY_BROKER_URL": "redis://custom:6379/9"})
    @patch("openclaw.celery_app.load_config")
    def test_celery_app_env_var_overrides_broker(self, mock_lc, mock_openclaw_config):
        """Verify CELERY_BROKER_URL env var overrides config."""
        mock_lc.return_value = mock_openclaw_config
        from openclaw.celery_app import create_celery_app

        app = create_celery_app()
        assert app.conf.broker_url == "redis://custom:6379/9"

    @patch("openclaw.celery_app.load_config")
    def test_celery_app_handles_missing_config(self, mock_lc):
        """Verify graceful degradation when openclaw.yaml is missing."""
        mock_lc.side_effect = FileNotFoundError("config/openclaw.yaml not found")
        from openclaw.celery_app import create_celery_app

        app = create_celery_app()
        assert app.main == "astock"
        assert app.conf.timezone == "Asia/Shanghai"

    @patch("openclaw.celery_app.load_config")
    def test_build_beat_schedule_skips_empty_task(self, mock_lc):
        """Verify schedule entries without a task field are skipped."""
        config = {
            "beat_schedule": {
                "valid_entry": {
                    "task": "some.task.name",
                    "schedule": {"crontab": {"hour": 10, "minute": 0}},
                },
                "invalid_entry": {
                    "schedule": {"crontab": {"hour": 12, "minute": 0}},
                },
            },
        }
        from openclaw.celery_app import _build_beat_schedule

        result = _build_beat_schedule(config)
        assert "valid_entry" in result
        assert "invalid_entry" not in result


# ---------------------------------------------------------------------------
# Tests: Backfill Pipeline
# ---------------------------------------------------------------------------


class TestTaskBackfillPredictions:
    """Tests for the task_backfill_predictions Celery task."""

    @patch("openclaw.tasks.backfill_pipeline._should_execute", return_value=True)
    @patch("src.web.services.stock_service.StockService")
    @patch("src.intelligence.model_monitor.ModelMonitor")
    def test_backfill_fills_pending_predictions(
        self, mock_monitor_cls, mock_stock_cls, _mock_sched
    ):
        """Verify pending predictions are backfilled with price changes."""
        monitor = MagicMock()
        monitor.get_pending_backfills.side_effect = [
            # T+3: 1 pending
            [{"prediction_id": "p1", "symbol": "600519", "predicted_at": "2026-02-01"}],
            # T+5: empty
            [],
            # T+10: empty
            [],
        ]
        monitor.backfill_outcome.return_value = True
        mock_monitor_cls.return_value = monitor

        stock_svc = MagicMock()
        stock_svc.get_price_change.return_value = 0.035  # +3.5%
        mock_stock_cls.return_value = stock_svc

        from openclaw.tasks.backfill_pipeline import task_backfill_predictions

        result = task_backfill_predictions.apply(args=[]).get(timeout=5)

        assert result["t3"]["filled"] == 1
        assert result["t5"]["pending"] == 0
        monitor.backfill_outcome.assert_called_once_with("p1", 3, 0.035)

    @patch("openclaw.tasks.backfill_pipeline._should_execute", return_value=True)
    @patch("src.web.services.stock_service.StockService")
    @patch("src.intelligence.model_monitor.ModelMonitor")
    def test_backfill_handles_no_price_data(
        self, mock_monitor_cls, mock_stock_cls, _mock_sched
    ):
        """When price data is None, skip backfill without error."""
        monitor = MagicMock()
        monitor.get_pending_backfills.side_effect = [
            [{"prediction_id": "p1", "symbol": "600519", "predicted_at": "2026-02-01"}],
            [],
            [],
        ]
        mock_monitor_cls.return_value = monitor

        stock_svc = MagicMock()
        stock_svc.get_price_change.return_value = None
        mock_stock_cls.return_value = stock_svc

        from openclaw.tasks.backfill_pipeline import task_backfill_predictions

        result = task_backfill_predictions.apply(args=[]).get(timeout=5)

        assert result["t3"]["filled"] == 0
        assert result["t3"]["errors"] == 0
        monitor.backfill_outcome.assert_not_called()

    @patch("openclaw.tasks.backfill_pipeline._should_execute", return_value=False)
    def test_backfill_skipped_by_timeline(self, _mock_sched):
        """Task skipped when timeline guard returns False."""
        from openclaw.tasks.backfill_pipeline import task_backfill_predictions

        result = task_backfill_predictions.apply(args=[]).get(timeout=5)
        assert result.get("_skipped") is True


class TestTaskDetectDrift:
    """Tests for the task_detect_drift Celery task."""

    @patch("openclaw.tasks.backfill_pipeline._should_execute", return_value=True)
    @patch("src.intelligence.model_monitor.ModelMonitor")
    def test_drift_detection_no_drift(self, mock_monitor_cls, _mock_sched):
        """No drift detected returns drift_detected=False."""
        from src.intelligence.model_monitor import DriftReport

        monitor = MagicMock()
        monitor.detect_drift.return_value = DriftReport(
            window_days=30,
            total_predictions=50,
            accuracy_t3=0.60,
            accuracy_t5=0.58,
            accuracy_t10=0.55,
            baseline_accuracy=0.50,
            drift_detected=False,
            drift_amount=0.0,
        )
        mock_monitor_cls.return_value = monitor

        from openclaw.tasks.backfill_pipeline import task_detect_drift

        result = task_detect_drift.apply(args=[]).get(timeout=5)

        assert result["drift_detected"] is False
        assert result["total_predictions"] == 50

    @patch("openclaw.tasks.backfill_pipeline._should_execute", return_value=True)
    @patch("src.intelligence.model_monitor.ModelMonitor")
    def test_drift_detection_with_drift(self, mock_monitor_cls, _mock_sched):
        """Drift detected returns drift_detected=True with warnings."""
        from src.intelligence.model_monitor import DriftReport

        monitor = MagicMock()
        monitor.detect_drift.return_value = DriftReport(
            window_days=30,
            total_predictions=50,
            accuracy_t3=0.30,
            accuracy_t5=0.28,
            accuracy_t10=0.25,
            baseline_accuracy=0.50,
            drift_detected=True,
            drift_amount=0.22,
            warnings=["准确率漂移告警"],
        )
        mock_monitor_cls.return_value = monitor

        from openclaw.tasks.backfill_pipeline import task_detect_drift

        result = task_detect_drift.apply(args=[]).get(timeout=5)

        assert result["drift_detected"] is True
        assert result["drift_amount"] == 0.22
        assert len(result["warnings"]) == 1

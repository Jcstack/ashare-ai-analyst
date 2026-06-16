"""Tests for src/intelligence/model_monitor.py."""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.intelligence.model_monitor import (
    ModelMonitor,
    MonitorConfig,
    _calc_accuracy,
    _check_direction_correct,
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_monitor.db")


@pytest.fixture
def monitor(db_path: str) -> ModelMonitor:
    config = MonitorConfig(
        db_path=db_path,
        min_predictions=3,  # Low for testing
        drift_threshold=0.15,
        baseline_accuracy=0.50,
    )
    return ModelMonitor(config)


class TestDatabaseInit:
    def test_creates_tables(self, monitor: ModelMonitor, db_path: str):
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        assert "predictions" in table_names

    def test_creates_index(self, monitor: ModelMonitor, db_path: str):
        conn = sqlite3.connect(db_path)
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        conn.close()
        index_names = [i[0] for i in indexes]
        assert "idx_predictions_symbol_date" in index_names


class TestRecordPrediction:
    def test_basic_record(self, monitor: ModelMonitor):
        pid = monitor.record_prediction(
            symbol="600519",
            direction="bullish",
            confidence=0.72,
            agent_name="analyst",
        )
        assert pid
        assert len(pid) == 12

    def test_record_retrieval(self, monitor: ModelMonitor):
        monitor.record_prediction(symbol="600519", direction="bullish", confidence=0.72)
        records = monitor.get_predictions(symbol="600519")
        assert len(records) == 1
        assert records[0].symbol == "600519"
        assert records[0].predicted_direction == "bullish"
        assert records[0].predicted_confidence == 0.72

    def test_record_with_context(self, monitor: ModelMonitor):
        ctx = {"dimensions": [{"name": "技术面", "signal": "bullish"}]}
        monitor.record_prediction(
            symbol="300750",
            direction="bearish",
            confidence=0.60,
            context=ctx,
        )
        records = monitor.get_predictions(symbol="300750")
        assert len(records) == 1
        assert "技术面" in records[0].context_snapshot

    def test_record_with_custom_date(self, monitor: ModelMonitor):
        custom_date = date(2026, 1, 15)
        monitor.record_prediction(
            symbol="600519",
            direction="neutral",
            confidence=0.50,
            prediction_date=custom_date,
        )
        records = monitor.get_predictions(symbol="600519")
        assert records[0].predicted_at == "2026-01-15"


class TestBackfillOutcome:
    def test_backfill_t3(self, monitor: ModelMonitor):
        pid = monitor.record_prediction(
            symbol="600519", direction="bullish", confidence=0.72
        )
        result = monitor.backfill_outcome(pid, window=3, actual_pct_change=0.05)
        assert result is True

        records = monitor.get_predictions(symbol="600519")
        assert records[0].actual_pct_t3 == 0.05
        assert records[0].correct_t3 is True

    def test_backfill_t5(self, monitor: ModelMonitor):
        pid = monitor.record_prediction(
            symbol="600519", direction="bearish", confidence=0.65
        )
        result = monitor.backfill_outcome(pid, window=5, actual_pct_change=-0.03)
        assert result is True

        records = monitor.get_predictions(symbol="600519")
        assert records[0].actual_pct_t5 == -0.03
        assert records[0].correct_t5 is True

    def test_backfill_incorrect_prediction(self, monitor: ModelMonitor):
        pid = monitor.record_prediction(
            symbol="600519", direction="bullish", confidence=0.80
        )
        monitor.backfill_outcome(pid, window=5, actual_pct_change=-0.10)

        records = monitor.get_predictions(symbol="600519")
        assert records[0].correct_t5 is False

    def test_backfill_invalid_window(self, monitor: ModelMonitor):
        pid = monitor.record_prediction(
            symbol="600519", direction="bullish", confidence=0.72
        )
        result = monitor.backfill_outcome(pid, window=7, actual_pct_change=0.05)
        assert result is False

    def test_backfill_nonexistent_prediction(self, monitor: ModelMonitor):
        result = monitor.backfill_outcome(
            "nonexistent", window=3, actual_pct_change=0.05
        )
        assert result is False


class TestDriftDetection:
    def _populate_predictions(
        self, monitor: ModelMonitor, n: int, correct_ratio: float
    ):
        """Helper to create predictions with known accuracy."""
        n_correct = int(n * correct_ratio)
        for i in range(n):
            pred_date = date.today() - timedelta(days=i)
            pid = monitor.record_prediction(
                symbol="600519",
                direction="bullish",
                confidence=0.70,
                prediction_date=pred_date,
            )
            pct = 0.05 if i < n_correct else -0.05
            monitor.backfill_outcome(pid, window=5, actual_pct_change=pct)

    def test_no_drift_high_accuracy(self, monitor: ModelMonitor):
        self._populate_predictions(monitor, n=5, correct_ratio=0.80)
        report = monitor.detect_drift()
        assert report.drift_detected is False

    def test_drift_detected_low_accuracy(self, monitor: ModelMonitor):
        self._populate_predictions(monitor, n=5, correct_ratio=0.20)
        report = monitor.detect_drift()
        assert report.drift_detected is True
        assert len(report.warnings) > 0

    def test_insufficient_predictions(self, db_path: str):
        config = MonitorConfig(db_path=db_path, min_predictions=100)
        mon = ModelMonitor(config)
        mon.record_prediction(symbol="600519", direction="bullish", confidence=0.72)
        report = mon.detect_drift()
        assert report.drift_detected is False
        assert any("样本不足" in w for w in report.warnings)

    def test_drift_per_symbol(self, monitor: ModelMonitor):
        for i in range(5):
            pred_date = date.today() - timedelta(days=i)
            pid = monitor.record_prediction(
                symbol="300750",
                direction="bearish",
                confidence=0.60,
                prediction_date=pred_date,
            )
            monitor.backfill_outcome(pid, window=5, actual_pct_change=0.10)

        report = monitor.detect_drift(symbol="300750")
        assert report.total_predictions == 5


class TestAccuracySummary:
    def test_empty_summary(self, monitor: ModelMonitor):
        summary = monitor.get_accuracy_summary()
        assert summary["total_predictions"] == 0
        assert summary["accuracy_t5"] is None

    def test_summary_with_data(self, monitor: ModelMonitor):
        for i in range(3):
            pid = monitor.record_prediction(
                symbol="600519",
                direction="bullish",
                confidence=0.70,
                prediction_date=date.today() - timedelta(days=i),
            )
            pct = 0.05 if i < 2 else -0.05
            monitor.backfill_outcome(pid, window=5, actual_pct_change=pct)

        summary = monitor.get_accuracy_summary(symbol="600519")
        assert summary["total_predictions"] == 3
        # 2 out of 3 correct
        assert summary["accuracy_t5"] == pytest.approx(2 / 3, abs=0.01)


class TestHelpers:
    @pytest.mark.parametrize(
        "direction,pct,expected",
        [
            ("bullish", 0.05, True),
            ("bullish", -0.05, False),
            ("bearish", -0.05, True),
            ("bearish", 0.05, False),
            ("neutral", 0.01, True),
            ("neutral", 0.05, False),
        ],
    )
    def test_check_direction_correct(self, direction, pct, expected):
        assert _check_direction_correct(direction, pct) == expected

    def test_calc_accuracy_all_correct(self):
        assert _calc_accuracy([1, 1, 1]) == 1.0

    def test_calc_accuracy_mixed(self):
        assert _calc_accuracy([1, 0, 1, 0]) == 0.5

    def test_calc_accuracy_with_none(self):
        assert _calc_accuracy([1, None, 0, None]) == 0.5

    def test_calc_accuracy_all_none(self):
        assert _calc_accuracy([None, None]) is None

    def test_calc_accuracy_empty(self):
        assert _calc_accuracy([]) is None

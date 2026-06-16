"""Tests for Phase 5 — ConfidenceCalibrator adaptive learning."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.agent_loop.confidence_calibrator import ConfidenceCalibrator


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """Create a decisions DB with sample data for calibration tests."""
    path = tmp_path / "decisions.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE decisions (
            decision_id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            decided_at TEXT NOT NULL,
            decided_price REAL NOT NULL,
            t1_price REAL,
            t3_price REAL,
            t5_price REAL,
            t1_return_pct REAL,
            t3_return_pct REAL,
            t5_return_pct REAL,
            direction_correct INTEGER
        )
        """
    )
    conn.commit()
    conn.close()
    return str(path)


def _insert_decisions(
    db_path: str,
    action: str,
    count: int,
    correct_ratio: float,
) -> None:
    """Insert mock decisions with specified accuracy."""
    conn = sqlite3.connect(db_path)
    correct_count = int(count * correct_ratio)
    # Use a recent timestamp so rows fall within the calibrator's lookback window
    # (must be relative to "now", not a hardcoded date, or the test rots over time).
    decided_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    for i in range(count):
        is_correct = 1 if i < correct_count else 0
        conn.execute(
            """
            INSERT INTO decisions (
                decision_id, proposal_id, symbol, action,
                decided_at, decided_price, t1_return_pct, direction_correct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"d-{action}-{i}",
                f"p-{action}-{i}",
                "600519",
                action,
                decided_at,
                1800.0,
                2.0 if is_correct else -2.0,
                is_correct,
            ),
        )
    conn.commit()
    conn.close()


class TestCalibrate:
    """Tests for the calibrate() method."""

    def test_no_db_returns_raw_confidence(self, tmp_path: Path) -> None:
        cal = ConfidenceCalibrator(db_path=str(tmp_path / "nonexistent.db"))
        result = cal.calibrate(0.75, "600519", "buy")
        assert result == 0.75  # No adjustment when no data

    def test_high_accuracy_boosts_confidence(self, db_path: str) -> None:
        _insert_decisions(db_path, "buy", 20, correct_ratio=0.85)
        cal = ConfidenceCalibrator(db_path=db_path)
        result = cal.calibrate(0.70, "600519", "buy")
        assert result > 0.70  # Should be boosted

    def test_low_accuracy_penalizes_confidence(self, db_path: str) -> None:
        _insert_decisions(db_path, "buy", 20, correct_ratio=0.25)
        cal = ConfidenceCalibrator(db_path=db_path)
        result = cal.calibrate(0.70, "600519", "buy")
        assert result < 0.70  # Should be penalized

    def test_confidence_clamped_to_0_1(self, db_path: str) -> None:
        _insert_decisions(db_path, "buy", 20, correct_ratio=0.95)
        cal = ConfidenceCalibrator(db_path=db_path)
        result = cal.calibrate(0.98, "600519", "buy")
        assert result <= 1.0

    def test_insufficient_samples_no_adjustment(self, db_path: str) -> None:
        _insert_decisions(db_path, "buy", 2, correct_ratio=0.0)
        cal = ConfidenceCalibrator(
            db_path=db_path, config={"min_samples_for_calibration": 5}
        )
        result = cal.calibrate(0.70, "600519", "buy")
        assert result == 0.70  # Too few samples → no adjustment

    def test_regime_adjustment_bear_penalizes_buy(self, db_path: str) -> None:
        cal = ConfidenceCalibrator(db_path=db_path)
        result = cal.calibrate(0.70, "600519", "buy", regime="bear")
        assert result < 0.70  # Bear regime penalizes buys

    def test_regime_adjustment_bull_boosts_buy(self, db_path: str) -> None:
        cal = ConfidenceCalibrator(db_path=db_path)
        result = cal.calibrate(0.70, "600519", "buy", regime="bull")
        assert result > 0.70  # Bull regime boosts buys


class TestCalibrationReport:
    """Tests for get_calibration_report()."""

    def test_no_db_returns_no_data(self, tmp_path: Path) -> None:
        cal = ConfidenceCalibrator(db_path=str(tmp_path / "missing.db"))
        report = cal.get_calibration_report()
        assert report["status"] == "no_data"

    def test_report_with_data(self, db_path: str) -> None:
        _insert_decisions(db_path, "buy", 10, correct_ratio=0.7)
        _insert_decisions(db_path, "sell", 5, correct_ratio=0.6)
        cal = ConfidenceCalibrator(db_path=db_path)
        report = cal.get_calibration_report()
        assert report["status"] == "ok"
        assert report["total_decisions"] == 15
        assert "buy" in report["by_action"]
        assert "sell" in report["by_action"]


class TestRegimeParams:
    """Tests for get_regime_params()."""

    def test_bear_regime_reduces_position_size(self) -> None:
        cal = ConfidenceCalibrator()
        params = cal.get_regime_params("bear")
        assert params["position_size_factor"] < 1.0
        assert params["max_position_pct"] < 0.30

    def test_bull_regime_allows_larger_positions(self) -> None:
        cal = ConfidenceCalibrator()
        params = cal.get_regime_params("bull")
        assert params["position_size_factor"] > 1.0

    def test_unknown_regime_is_conservative(self) -> None:
        cal = ConfidenceCalibrator()
        params = cal.get_regime_params("unknown")
        assert params["position_size_factor"] <= 1.0

    def test_high_vol_uses_wider_stops(self) -> None:
        cal = ConfidenceCalibrator()
        params = cal.get_regime_params("high_volatility")
        assert params["stop_loss_factor"] > 1.0

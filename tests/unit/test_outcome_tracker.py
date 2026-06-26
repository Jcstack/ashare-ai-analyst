"""Tests for OutcomeTracker — the calibration feedback heart.

Covers #55 (trading-day T+N horizons) and #54 (proper Bayesian likelihoods,
P(evidence | state) by conditional frequency — not the old hit-rate / 1-p form).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.agent_loop.outcome_tracker import OutcomeTracker


@pytest.fixture
def tracker(tmp_path):
    return OutcomeTracker(db_path=tmp_path / "ot.db")


def _insert(tracker, *, source, confidence, direction, correct, n):
    created = datetime.now(UTC).isoformat()
    with tracker._conn() as conn:
        for i in range(n):
            conn.execute(
                """INSERT INTO tracked_signals
                   (signal_id, symbol, direction, source, confidence,
                    created_at, status, direction_correct)
                   VALUES (?, '600519', ?, ?, ?, ?, 'complete', ?)""",
                (
                    f"{source}-{direction}-{correct}-{confidence}-{i}",
                    direction,
                    source,
                    confidence,
                    created,
                    correct,
                ),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# #55 — trading-day horizons
# ---------------------------------------------------------------------------


class _FakeCal:
    def next_trading_day(self, d):
        nxt = d + timedelta(days=1)
        while nxt.weekday() >= 5:  # skip Sat/Sun
            nxt += timedelta(days=1)
        return nxt


class _BrokenCal:
    def next_trading_day(self, d):
        raise RuntimeError("calendar unavailable")


class TestTradingDayHorizons:
    def test_horizons_use_trading_days(self, tracker):
        tracker._calendar = _FakeCal()
        fri = datetime(2024, 1, 5, tzinfo=UTC)  # a Friday
        assert tracker._add_trading_days(fri, 1) == date(2024, 1, 8)  # → Monday
        assert tracker._add_trading_days(fri, 5) == date(2024, 1, 12)  # 5 sessions

    def test_fallback_to_calendar_days_when_calendar_breaks(self, tracker):
        tracker._calendar = _BrokenCal()
        start = datetime(2024, 1, 5, tzinfo=UTC)
        assert tracker._add_trading_days(start, 3) == date(2024, 1, 8)


# ---------------------------------------------------------------------------
# #54 — Bayesian likelihoods are real conditional frequencies
# ---------------------------------------------------------------------------


class TestBayesianLikelihood:
    def test_discriminating_source_pbull_far_above_pbear(self, tracker):
        # Predicts up in bull states, down in bear states → highly informative.
        _insert(tracker, source="good", confidence=0.8, direction="buy", correct=1, n=8)
        _insert(
            tracker, source="good", confidence=0.8, direction="sell", correct=1, n=8
        )
        p_bull, p_bear = tracker.get_calibration_data(min_samples=10)["good/strong"]
        assert p_bull > 0.8 and p_bear < 0.2  # strong positive log-likelihood-ratio

    def test_useless_source_pbull_near_pbear(self, tracker):
        # Random: equally right/wrong in both directions → no edge.
        for direction in ("buy", "sell"):
            _insert(
                tracker,
                source="rng",
                confidence=0.8,
                direction=direction,
                correct=1,
                n=5,
            )
            _insert(
                tracker,
                source="rng",
                confidence=0.8,
                direction=direction,
                correct=0,
                n=5,
            )
        p_bull, p_bear = tracker.get_calibration_data(min_samples=10)["rng/strong"]
        assert abs(p_bull - p_bear) < 0.05  # LLR ≈ 0

    def test_likelihoods_are_not_complementary(self, tracker):
        # A bull-biased source: high P(bull-read|bull) AND high P(bull-read|bear).
        # The old code forced p_bear = 1 - p_bull; proper likelihoods need not.
        _insert(tracker, source="bias", confidence=0.8, direction="buy", correct=1, n=8)
        _insert(tracker, source="bias", confidence=0.8, direction="buy", correct=0, n=4)
        p_bull, p_bear = tracker.get_calibration_data(min_samples=10)["bias/strong"]
        assert p_bull > p_bear
        assert (p_bull + p_bear) > 1.1  # would be exactly 1.0 under the old bug

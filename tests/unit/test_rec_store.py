"""Tests for RecStore — SQLite-backed recommendation persistence.

Part of v28.0 Smart Stock Recommendation System.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.recommendation.models import Recommendation
from src.recommendation.rec_store import RecStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rec(
    *,
    symbol: str = "600519",
    name: str = "贵州茅台",
    style: str = "value",
    session: str = "mid",
    score: float = 0.85,
    status: str = "active",
    created_at: str | None = None,
    run_id: str | None = None,
) -> Recommendation:
    """Build a Recommendation for testing."""
    return Recommendation(
        id=str(uuid.uuid4()),
        symbol=symbol,
        name=name,
        action="buy",
        style=style,
        session=session,
        score=score,
        confidence="high",
        reason="测试推荐理由",
        risk_notes="测试风险提示",
        entry_price=50.0,
        target_price=100.0,
        stop_loss=90.0,
        factors={"pe_score": 0.8, "pb_score": 0.7},
        created_at=created_at or datetime.now(UTC).isoformat(),
        status=status,
        run_id=run_id,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecStore:
    """Tests for RecStore operations."""

    @pytest.fixture()
    def store(self, tmp_path) -> RecStore:
        """Create a RecStore with a temp database."""
        return RecStore(db_path=str(tmp_path / "test_recs.db"))

    def test_save_and_retrieve(self, store: RecStore) -> None:
        """Save a recommendation and retrieve it."""
        rec = _make_rec()
        store.save_recommendation(rec)

        results = store.get_recommendations(style="value")
        assert len(results) == 1
        assert results[0]["symbol"] == "600519"
        assert results[0]["score"] == 0.85
        assert isinstance(results[0]["factors"], dict)

    def test_save_batch(self, store: RecStore) -> None:
        """Save multiple recommendations in batch."""
        recs = [
            _make_rec(symbol="600519", score=0.9),
            _make_rec(symbol="000858", name="五粮液", score=0.8),
            _make_rec(symbol="000333", name="美的集团", score=0.7),
        ]
        count = store.save_batch(recs)
        assert count == 3

        results = store.get_recommendations(style="value")
        assert len(results) == 3
        # Should be sorted by score DESC
        assert results[0]["score"] == 0.9

    def test_duplicate_ignored(self, store: RecStore) -> None:
        """Duplicate IDs should be silently ignored."""
        rec = _make_rec()
        store.save_recommendation(rec)
        store.save_recommendation(rec)  # Same ID

        results = store.get_recommendations(style="value")
        assert len(results) == 1

    def test_filter_by_style(self, store: RecStore) -> None:
        """Filter recommendations by style."""
        store.save_recommendation(_make_rec(style="value"))
        store.save_recommendation(_make_rec(style="momentum"))

        value_recs = store.get_recommendations(style="value")
        assert len(value_recs) == 1
        assert value_recs[0]["style"] == "value"

    def test_filter_by_session(self, store: RecStore) -> None:
        """Filter recommendations by session."""
        store.save_recommendation(_make_rec(session="early"))
        store.save_recommendation(_make_rec(session="mid"))

        early = store.get_recommendations(session="early")
        assert len(early) == 1
        assert early[0]["session"] == "early"

    def test_get_today_recommendations(self, store: RecStore) -> None:
        """Get today's recommendations only."""
        store.save_recommendation(_make_rec())
        # Old recommendation
        old = _make_rec(created_at="2020-01-01T00:00:00")
        store.save_recommendation(old)

        today = store.get_today_recommendations()
        assert len(today) == 1

    def test_dismiss(self, store: RecStore) -> None:
        """Dismiss a recommendation."""
        rec = _make_rec()
        store.save_recommendation(rec)

        ok = store.dismiss_recommendation(rec.id)
        assert ok is True

        # Should not appear in active results
        results = store.get_recommendations(style="value")
        assert len(results) == 0

    def test_dismiss_nonexistent(self, store: RecStore) -> None:
        """Dismiss a non-existent recommendation returns False."""
        ok = store.dismiss_recommendation("nonexistent")
        assert ok is False

    def test_expire_old(self, store: RecStore) -> None:
        """Expire old recommendations."""
        # Recent
        store.save_recommendation(_make_rec())
        # Old (5 days ago)
        old_time = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        store.save_recommendation(_make_rec(created_at=old_time))

        expired = store.expire_old_recommendations(days=3)
        assert expired == 1

        active = store.get_recommendations()
        assert len(active) == 1

    def test_save_feedback(self, store: RecStore) -> None:
        """Save user feedback for a recommendation."""
        rec = _make_rec()
        store.save_recommendation(rec)
        # Should not raise
        store.save_feedback(rec.id, "user1", "like", "好推荐")

    def test_get_recommendation_by_id(self, store: RecStore) -> None:
        """Get a single recommendation by ID."""
        rec = _make_rec()
        store.save_recommendation(rec)

        result = store.get_recommendation(rec.id)
        assert result is not None
        assert result["symbol"] == "600519"
        assert result["confidence"] == "high"
        assert result["entry_price"] == 50.0

    def test_get_recommendation_not_found(self, store: RecStore) -> None:
        """Non-existent ID returns None."""
        result = store.get_recommendation("nonexistent")
        assert result is None

    def test_count_today_active(self, store: RecStore) -> None:
        """Count today's active recommendations."""
        store.save_recommendation(_make_rec())
        store.save_recommendation(_make_rec(symbol="000858", name="五粮液"))

        count = store.count_today_active()
        assert count == 2

    def test_count_today_active_deduplicates_symbols(self, store: RecStore) -> None:
        """Same symbol under different styles should count as 1."""
        store.save_recommendation(_make_rec(symbol="600519", style="value", score=0.9))
        store.save_recommendation(_make_rec(symbol="600519", style="growth", score=0.8))
        store.save_recommendation(
            _make_rec(symbol="000858", name="五粮液", style="value")
        )

        count = store.count_today_active()
        assert count == 2  # 600519 counted once

    def test_limit(self, store: RecStore) -> None:
        """Limit parameter is respected."""
        for i in range(10):
            store.save_recommendation(_make_rec(score=0.7 + i * 0.01))

        results = store.get_recommendations(limit=3)
        assert len(results) == 3


class TestRunIdFiltering:
    """Tests for run_id-based latest-run filtering."""

    @pytest.fixture()
    def store(self, tmp_path) -> RecStore:
        return RecStore(db_path=str(tmp_path / "test_recs.db"))

    def test_today_returns_latest_run_only(self, store: RecStore) -> None:
        """Multiple runs today → only the latest run's results are returned."""
        run1 = "run-aaa"
        run2 = "run-bbb"
        # Run 1: 3 stocks
        store.save_batch([
            _make_rec(symbol="600519", run_id=run1),
            _make_rec(symbol="000858", name="五粮液", run_id=run1),
            _make_rec(symbol="000333", name="美的集团", run_id=run1),
        ])
        # Run 2: 2 stocks (the latest)
        store.save_batch([
            _make_rec(symbol="601318", name="中国平安", run_id=run2),
            _make_rec(symbol="600036", name="招商银行", run_id=run2),
        ])

        today = store.get_today_recommendations()
        symbols = {r["symbol"] for r in today}
        assert symbols == {"601318", "600036"}

    def test_today_fallback_no_run_id(self, store: RecStore) -> None:
        """Old data without run_id → returns all of today's records (backward compat)."""
        store.save_batch([
            _make_rec(symbol="600519"),
            _make_rec(symbol="000858", name="五粮液"),
        ])

        today = store.get_today_recommendations()
        assert len(today) == 2

    def test_count_today_active_uses_latest_run(self, store: RecStore) -> None:
        """count_today_active should count only the latest run's symbols."""
        run1 = "run-old"
        run2 = "run-new"
        store.save_batch([
            _make_rec(symbol="600519", run_id=run1),
            _make_rec(symbol="000858", name="五粮液", run_id=run1),
            _make_rec(symbol="000333", name="美的集团", run_id=run1),
        ])
        store.save_batch([
            _make_rec(symbol="601318", name="中国平安", run_id=run2),
        ])

        count = store.count_today_active()
        assert count == 1  # only run2's single stock

    def test_run_id_persisted(self, store: RecStore) -> None:
        """run_id should be stored and returned in the recommendation dict."""
        rec = _make_rec(run_id="run-test-123")
        store.save_recommendation(rec)

        result = store.get_recommendation(rec.id)
        assert result is not None
        assert result["run_id"] == "run-test-123"


class TestRecStoreOutcomes:
    """Tests for recommendation outcomes table and backfill methods."""

    @pytest.fixture()
    def store(self, tmp_path) -> RecStore:
        return RecStore(db_path=str(tmp_path / "test_recs.db"))

    def test_backfill_outcome(self, store: RecStore) -> None:
        """Backfill a T+1 outcome."""
        rec = _make_rec()
        store.save_recommendation(rec)

        ok = store.backfill_outcome(rec.id, 1, 52.0, 4.0)
        assert ok is True

        outcome = store.get_outcome(rec.id)
        assert outcome is not None
        assert outcome["actual_price_t1"] == 52.0
        assert outcome["actual_change_t1"] == 4.0
        assert outcome["correct_t1"] == 1  # positive change

    def test_backfill_negative(self, store: RecStore) -> None:
        """Negative change should mark correct=0."""
        rec = _make_rec()
        store.save_recommendation(rec)

        ok = store.backfill_outcome(rec.id, 3, 48.0, -4.0)
        assert ok is True

        outcome = store.get_outcome(rec.id)
        assert outcome["correct_t3"] == 0

    def test_backfill_multiple_windows(self, store: RecStore) -> None:
        """Can backfill different windows for same recommendation."""
        rec = _make_rec()
        store.save_recommendation(rec)

        store.backfill_outcome(rec.id, 1, 51.0, 2.0)
        store.backfill_outcome(rec.id, 5, 55.0, 10.0)

        outcome = store.get_outcome(rec.id)
        assert outcome["actual_price_t1"] == 51.0
        assert outcome["actual_price_t5"] == 55.0
        # t3 and t10 should be None
        assert outcome["actual_price_t3"] is None
        assert outcome["actual_price_t10"] is None

    def test_get_pending_backfills(self, store: RecStore) -> None:
        """Get recommendations needing backfill."""
        # Create an old recommendation (5 days ago)
        old_time = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        rec = _make_rec(created_at=old_time)
        store.save_recommendation(rec)

        # Should be pending for T+1 (old enough)
        pending = store.get_pending_backfills(1)
        assert len(pending) >= 1
        assert pending[0]["symbol"] == "600519"

    def test_pending_after_backfill(self, store: RecStore) -> None:
        """After backfilling T+1, it should not appear in T+1 pending."""
        old_time = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        rec = _make_rec(created_at=old_time)
        store.save_recommendation(rec)

        store.backfill_outcome(rec.id, 1, 52.0, 4.0)

        pending = store.get_pending_backfills(1)
        rec_ids = [p["id"] for p in pending]
        assert rec.id not in rec_ids

    def test_performance_stats_empty(self, store: RecStore) -> None:
        """Performance stats with no data returns zeros."""
        stats = store.get_performance_stats()
        assert stats["total_recs"] == 0
        for w in ["t1", "t3", "t5", "t10"]:
            assert stats["windows"][w]["filled"] == 0
            assert stats["windows"][w]["win_rate"] is None

    def test_performance_stats_with_data(self, store: RecStore) -> None:
        """Performance stats aggregate correctly."""
        for i in range(5):
            rec = _make_rec(symbol=f"6005{i:02d}", score=0.8)
            store.save_recommendation(rec)
            # Backfill T+3: 3 wins, 2 losses
            change = 5.0 if i < 3 else -3.0
            store.backfill_outcome(rec.id, 3, 52.0 if i < 3 else 48.0, change)

        stats = store.get_performance_stats()
        assert stats["total_recs"] == 5
        t3 = stats["windows"]["t3"]
        assert t3["filled"] == 5
        assert t3["wins"] == 3
        assert t3["win_rate"] == 60.0

    def test_performance_stats_filter_by_style(self, store: RecStore) -> None:
        """Performance stats can be filtered by style."""
        store.save_recommendation(_make_rec(style="value"))
        store.save_recommendation(_make_rec(style="momentum"))

        stats = store.get_performance_stats(style="value")
        assert stats["total_recs"] == 1

    def test_get_outcome_not_found(self, store: RecStore) -> None:
        """Non-existent outcome returns None."""
        assert store.get_outcome("nonexistent") is None


class TestDeduplicateBySymbol:
    """Tests for RecommendationService._deduplicate_by_symbol (I-034)."""

    def test_removes_duplicate_symbols(self) -> None:
        """Same symbol from different styles → keep highest score only."""
        from src.web.services.recommendation_service import RecommendationService

        recs = [
            {"symbol": "600519", "score": 0.95, "style": "value"},
            {"symbol": "000858", "score": 0.90, "style": "value"},
            {"symbol": "600519", "score": 0.80, "style": "growth"},  # dup
            {"symbol": "000333", "score": 0.75, "style": "momentum"},
            {"symbol": "000858", "score": 0.70, "style": "momentum"},  # dup
        ]
        result = RecommendationService._deduplicate_by_symbol(recs)

        symbols = [r["symbol"] for r in result]
        assert symbols == ["600519", "000858", "000333"]
        # Kept highest score for 600519
        assert result[0]["score"] == 0.95
        assert result[1]["score"] == 0.90

    def test_empty_list(self) -> None:
        from src.web.services.recommendation_service import RecommendationService

        assert RecommendationService._deduplicate_by_symbol([]) == []

    def test_no_duplicates(self) -> None:
        from src.web.services.recommendation_service import RecommendationService

        recs = [
            {"symbol": "600519", "score": 0.9},
            {"symbol": "000858", "score": 0.8},
        ]
        result = RecommendationService._deduplicate_by_symbol(recs)
        assert len(result) == 2

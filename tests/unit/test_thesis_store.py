"""Unit tests for ThesisStore (SQLite-backed investment thesis management)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.agent_loop.models import InvestmentThesis
from src.agent_loop.thesis_store import ThesisStore


def _make_thesis(
    symbol: str = "600519",
    name: str = "贵州茅台",
    direction: str = "bullish",
    conviction: float = 0.8,
    **kwargs,
) -> InvestmentThesis:
    defaults = dict(
        thesis_text="Strong brand moat",
        key_assumptions=["Premiumisation trend continues"],
        invalidation_conditions=["Revenue miss > 10%"],
        entry_price_target=1800.0,
        stop_loss_pct=-5.0,
        sector="消费",
    )
    defaults.update(kwargs)
    return InvestmentThesis(
        symbol=symbol,
        name=name,
        direction=direction,
        conviction=conviction,
        **defaults,
    )


@pytest.fixture()
def store(tmp_path):
    db = tmp_path / "test_thesis.db"
    return ThesisStore(db_path=str(db))


class TestThesisStoreCreate:
    def test_save_and_get_by_symbol(self, store):
        thesis = _make_thesis()
        store.save(thesis)

        result = store.get("600519")
        assert result is not None
        assert result.symbol == "600519"
        assert result.name == "贵州茅台"
        assert result.direction == "bullish"
        assert result.conviction == pytest.approx(0.8)

    def test_get_returns_none_for_missing(self, store):
        assert store.get("999999") is None


class TestThesisStoreGetActive:
    def test_get_active_returns_only_active(self, store):
        t1 = _make_thesis(symbol="600519")
        t2 = _make_thesis(symbol="000858", name="五粮液")
        store.save(t1)
        store.save(t2)

        active = store.get_active()
        assert len(active) == 2
        symbols = {t.symbol for t in active}
        assert symbols == {"600519", "000858"}

    def test_get_active_excludes_invalidated(self, store):
        t = _make_thesis(symbol="600519")
        store.save(t)
        store.invalidate("600519", "stop loss hit")

        active = store.get_active()
        assert len(active) == 0


class TestThesisStoreSaveUpdate:
    def test_upsert_overwrites_existing(self, store):
        t1 = _make_thesis(conviction=0.7)
        store.save(t1)

        t2 = _make_thesis(conviction=0.9, thesis_text="Updated thesis")
        store.save(t2)

        result = store.get("600519")
        assert result is not None
        assert result.conviction == pytest.approx(0.9)
        assert result.thesis_text == "Updated thesis"

        # Should still be one record, not two
        assert len(store.get_active()) == 1


class TestThesisStoreInvalidate:
    def test_invalidate_marks_status(self, store):
        store.save(_make_thesis())
        store.invalidate("600519", "price broke support")

        # Active query should not return it
        assert store.get("600519") is None

        # But get_all with include_invalidated should
        all_theses = store.get_all(include_invalidated=True)
        assert len(all_theses) == 1
        assert all_theses[0].status == "invalidated"
        assert all_theses[0].invalidation_reason == "price broke support"

    def test_invalidate_nonexistent_is_noop(self, store):
        # Should not raise
        store.invalidate("999999", "whatever")


class TestThesisStoreUpdateConviction:
    def test_increase_conviction(self, store):
        store.save(_make_thesis(conviction=0.5))
        store.update_conviction("600519", delta=0.2, reason="Earnings beat")

        result = store.get("600519")
        assert result is not None
        assert result.conviction == pytest.approx(0.7)
        assert "Earnings beat" in result.thesis_text

    def test_conviction_clamped_to_1(self, store):
        store.save(_make_thesis(conviction=0.9))
        store.update_conviction("600519", delta=0.5, reason="Very bullish")

        result = store.get("600519")
        assert result.conviction == pytest.approx(1.0)

    def test_conviction_clamped_to_0(self, store):
        store.save(_make_thesis(conviction=0.2))
        store.update_conviction("600519", delta=-0.5, reason="Bad news")

        result = store.get("600519")
        assert result.conviction == pytest.approx(0.0)

    def test_update_conviction_missing_symbol_is_noop(self, store):
        store.update_conviction("999999", delta=0.1, reason="no-op")


class TestThesisStoreDecayStale:
    def test_decay_stale_reduces_conviction(self, store):
        t = _make_thesis(conviction=0.8)
        # Manually set updated_at to 4 days ago so it's beyond 72h cutoff
        t.updated_at = datetime.now(UTC) - timedelta(days=4)
        store.save(t)

        # Force the updated_at in DB to the old timestamp
        import sqlite3

        conn = sqlite3.connect(str(store._db_path))
        old_ts = (datetime.now(UTC) - timedelta(days=4)).isoformat()
        conn.execute("UPDATE theses SET updated_at = ? WHERE symbol = ?", (old_ts, "600519"))
        conn.commit()
        conn.close()

        decayed_count = store.decay_stale(max_age_hours=72, decay_rate=0.05)
        assert decayed_count == 1

        result = store.get("600519")
        # conviction should have been reduced
        assert result is not None
        assert result.conviction < 0.8

    def test_decay_auto_invalidates_below_threshold(self, store):
        t = _make_thesis(conviction=0.05)
        store.save(t)

        # Force old timestamp
        import sqlite3

        conn = sqlite3.connect(str(store._db_path))
        old_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        conn.execute("UPDATE theses SET updated_at = ? WHERE symbol = ?", (old_ts, "600519"))
        conn.commit()
        conn.close()

        decayed_count = store.decay_stale(max_age_hours=72, decay_rate=0.05)
        assert decayed_count == 1

        # Should be invalidated (conviction was already low + decay)
        assert store.get("600519") is None
        all_t = store.get_all(include_invalidated=True)
        assert len(all_t) == 1
        assert all_t[0].status == "invalidated"
        assert "Auto-invalidated" in all_t[0].invalidation_reason

    def test_decay_stale_returns_zero_when_nothing_stale(self, store):
        store.save(_make_thesis())
        assert store.decay_stale() == 0

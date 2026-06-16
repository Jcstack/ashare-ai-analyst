"""Tests for InfoStore CRUD, cleanup, and bookmark retention."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.intelligence_hub.info_store import InfoStore
from src.intelligence_hub.models import InfoItem


@pytest.fixture()
def store(tmp_path: Path) -> InfoStore:
    """Create a temp InfoStore for each test."""
    return InfoStore(db_path=str(tmp_path / "test_info.db"))


def _make_item(**overrides) -> InfoItem:
    defaults = {
        "source_id": "test_source",
        "source_name": "Test Source",
        "title": "Test Title",
        "summary": "Test summary text",
        "url": "https://example.com/test",
        "category": "market",
        "priority": "normal",
        "published_at": "2026-02-15 10:00:00",
    }
    defaults.update(overrides)
    return InfoItem(**defaults)


class TestInfoStoreBasic:
    def test_store_and_get(self, store: InfoStore) -> None:
        item = _make_item()
        store.store(item)

        result = store.get_item(item.item_id)
        assert result is not None
        assert result["title"] == "Test Title"
        assert result["source_id"] == "test_source"

    def test_store_duplicate_ignored(self, store: InfoStore) -> None:
        item = _make_item()
        store.store(item)
        store.store(item)  # should not raise

        feed = store.get_feed(days=365)
        assert len(feed) == 1

    def test_store_batch(self, store: InfoStore) -> None:
        items = [
            _make_item(title=f"Item {i}", url=f"https://example.com/{i}")
            for i in range(5)
        ]
        count, new_ids = store.store_batch(items)
        assert count >= 0  # rowcount may vary by driver
        feed = store.get_feed(days=365)
        assert len(feed) == 5

    def test_store_batch_empty(self, store: InfoStore) -> None:
        count, new_ids = store.store_batch([])
        assert count == 0
        assert new_ids == []

    def test_get_item_not_found(self, store: InfoStore) -> None:
        assert store.get_item("nonexistent") is None


class TestInfoStoreFeed:
    def test_filter_by_category(self, store: InfoStore) -> None:
        store.store(_make_item(title="Policy News", category="policy", url="u1"))
        store.store(_make_item(title="Market News", category="market", url="u2"))

        feed = store.get_feed(category="policy", days=365)
        assert len(feed) == 1
        assert feed[0]["title"] == "Policy News"

    def test_filter_by_priority(self, store: InfoStore) -> None:
        store.store(_make_item(title="Breaking", priority="breaking", url="u1"))
        store.store(_make_item(title="Normal", priority="normal", url="u2"))

        feed = store.get_feed(priority="breaking", days=365)
        assert len(feed) == 1
        assert feed[0]["title"] == "Breaking"

    def test_filter_by_search(self, store: InfoStore) -> None:
        store.store(_make_item(title="央行降息", url="u1"))
        store.store(_make_item(title="股市涨停", url="u2"))

        feed = store.get_feed(search="降息", days=365)
        assert len(feed) == 1
        assert "降息" in feed[0]["title"]

    def test_filter_by_bookmarked(self, store: InfoStore) -> None:
        item = _make_item(title="Bookmarked")
        store.store(item)
        store.toggle_bookmark(item.item_id)

        feed = store.get_feed(bookmarked=True, days=365)
        assert len(feed) == 1

    def test_filter_by_symbol(self, store: InfoStore) -> None:
        item = _make_item(
            title="Symbol News",
            related_symbols=["600036"],
        )
        store.store(item)

        feed = store.get_feed(symbol="600036", days=365)
        assert len(feed) == 1

    def test_pagination(self, store: InfoStore) -> None:
        for i in range(10):
            store.store(_make_item(title=f"Item {i}", url=f"https://e.com/{i}"))

        page1 = store.get_feed(limit=3, offset=0, days=365)
        page2 = store.get_feed(limit=3, offset=3, days=365)
        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0]["item_id"] != page2[0]["item_id"]


class TestInfoStoreBookmarkRead:
    def test_toggle_bookmark(self, store: InfoStore) -> None:
        item = _make_item()
        store.store(item)

        result = store.toggle_bookmark(item.item_id)
        assert result is True

        result = store.toggle_bookmark(item.item_id)
        assert result is False

    def test_toggle_bookmark_not_found(self, store: InfoStore) -> None:
        assert store.toggle_bookmark("nonexistent") is None

    def test_mark_read(self, store: InfoStore) -> None:
        item = _make_item()
        store.store(item)

        assert store.mark_read(item.item_id) is True

        row = store.get_item(item.item_id)
        assert row is not None
        assert row["is_read"] == 1

    def test_mark_read_not_found(self, store: InfoStore) -> None:
        assert store.mark_read("nonexistent") is False


class TestInfoStoreOverview:
    def test_get_category_counts(self, store: InfoStore) -> None:
        store.store(_make_item(title="P1", category="policy", url="u1"))
        store.store(_make_item(title="P2", category="policy", url="u2"))
        store.store(_make_item(title="M1", category="market", url="u3"))

        counts = store.get_category_counts(days=365)
        assert counts["policy"]["total"] == 2
        assert counts["market"]["total"] == 1

    def test_get_overview(self, store: InfoStore) -> None:
        store.store(_make_item(title="A", url="u1"))
        store.store(_make_item(title="B", url="u2", source_id="other"))

        overview = store.get_overview(days=365)
        assert overview["total_items"] == 2
        assert overview["sources_count"] == 2
        assert "market" in overview["categories"]


class TestInfoStoreScore:
    def test_store_and_get_with_score(self, store: InfoStore) -> None:
        item = _make_item(
            content_score=75.5, score_explain={"source_weight": {"points": 33.75}}
        )
        store.store(item)

        result = store.get_item(item.item_id)
        assert result is not None
        assert result["content_score"] == 75.5
        import json

        explain = (
            json.loads(result["score_explain"])
            if isinstance(result["score_explain"], str)
            else result["score_explain"]
        )
        assert explain["source_weight"]["points"] == 33.75

    def test_store_batch_with_scores(self, store: InfoStore) -> None:
        items = [
            _make_item(
                title=f"Scored {i}",
                url=f"https://e.com/s{i}",
                content_score=float(50 + i * 10),
            )
            for i in range(3)
        ]
        store.store_batch(items)
        feed = store.get_feed(days=365)
        assert len(feed) == 3
        scores = [r["content_score"] for r in feed]
        assert all(s is not None for s in scores)

    def test_sort_by_score(self, store: InfoStore) -> None:
        store.store(_make_item(title="Low", url="u1", content_score=20.0))
        store.store(_make_item(title="High", url="u2", content_score=90.0))
        store.store(_make_item(title="Mid", url="u3", content_score=55.0))

        feed = store.get_feed(sort_by="score", days=365)
        assert len(feed) == 3
        assert feed[0]["content_score"] == 90.0
        assert feed[1]["content_score"] == 55.0
        assert feed[2]["content_score"] == 20.0

    def test_sort_by_score_nulls_last(self, store: InfoStore) -> None:
        store.store(_make_item(title="Scored", url="u1", content_score=50.0))
        store.store(_make_item(title="Unscored", url="u2"))

        feed = store.get_feed(sort_by="score", days=365)
        assert len(feed) == 2
        assert feed[0]["content_score"] == 50.0
        assert feed[1]["content_score"] is None


class TestInfoStoreBackfill:
    def test_update_related_symbols(self, store: InfoStore) -> None:
        item = _make_item(title="比亚迪新能源大涨", related_symbols=[])
        store.store(item)

        result = store.update_related_symbols(item.item_id, ["002594"])
        assert result is True

        row = store.get_item(item.item_id)
        assert row is not None
        import json

        symbols = json.loads(row["related_symbols"])
        assert symbols == ["002594"]

    def test_update_related_symbols_not_found(self, store: InfoStore) -> None:
        assert store.update_related_symbols("nonexistent", ["600036"]) is False

    def test_get_items_missing_symbols(self, store: InfoStore) -> None:
        store.store(_make_item(title="Empty symbols", related_symbols=[], url="u1"))
        store.store(
            _make_item(
                title="Has symbols",
                related_symbols=["600036"],
                url="u2",
            )
        )

        missing = store.get_items_missing_symbols(limit=100, days=365)
        assert len(missing) == 1
        assert missing[0]["title"] == "Empty symbols"

    def test_get_items_missing_symbols_respects_limit(self, store: InfoStore) -> None:
        for i in range(5):
            store.store(_make_item(title=f"Item {i}", related_symbols=[], url=f"u{i}"))

        missing = store.get_items_missing_symbols(limit=2, days=365)
        assert len(missing) == 2

    def test_get_items_missing_symbols_empty_store(self, store: InfoStore) -> None:
        assert store.get_items_missing_symbols(limit=100, days=365) == []


class TestInfoStoreCleanup:
    def test_cleanup_old_items(self, store: InfoStore) -> None:
        old_item = _make_item(
            title="Old",
            fetched_at="2020-01-01 00:00:00",
            url="u1",
        )
        new_item = _make_item(title="New", url="u2")

        store.store(old_item)
        store.store(new_item)

        deleted = store.cleanup(days=30)
        assert deleted == 1

        feed = store.get_feed(days=365)
        assert len(feed) == 1
        assert feed[0]["title"] == "New"

    def test_cleanup_preserves_bookmarked(self, store: InfoStore) -> None:
        old_item = _make_item(
            title="Old Bookmarked",
            fetched_at="2020-01-01 00:00:00",
        )
        store.store(old_item)
        store.toggle_bookmark(old_item.item_id)

        deleted = store.cleanup(days=30)
        assert deleted == 0

        row = store.get_item(old_item.item_id)
        assert row is not None

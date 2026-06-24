"""Tests for DedupChecker — URL and title normalization dedup."""

from __future__ import annotations

from urllib.parse import urlparse

from src.intelligence_hub.dedup import DedupChecker, _normalize_title, _normalize_url
from src.intelligence_hub.models import InfoItem


def _make_item(**overrides) -> InfoItem:
    defaults = {
        "source_id": "test_src",
        "source_name": "Test",
        "title": "Test Title",
        "url": "https://example.com/article",
    }
    defaults.update(overrides)
    return InfoItem(**defaults)


class TestNormalization:
    def test_normalize_url_strips_utm(self) -> None:
        url = "https://example.com/news?utm_source=twitter&utm_medium=social&id=123"
        assert "utm_source" not in _normalize_url(url)
        assert "id=123" in _normalize_url(url)

    def test_normalize_url_strips_fragment(self) -> None:
        url = "https://example.com/article#comments"
        assert "#" not in _normalize_url(url)

    def test_normalize_url_lowercase_host(self) -> None:
        url = "https://Example.COM/Path"
        normalized = _normalize_url(url)
        assert urlparse(normalized).hostname == "example.com"

    def test_normalize_url_trailing_slash(self) -> None:
        url1 = _normalize_url("https://example.com/path/")
        url2 = _normalize_url("https://example.com/path")
        assert url1 == url2

    def test_normalize_url_empty(self) -> None:
        assert _normalize_url("") == ""

    def test_normalize_title_case_insensitive(self) -> None:
        assert _normalize_title("Hello World") == _normalize_title("hello world")

    def test_normalize_title_strips_punctuation(self) -> None:
        assert _normalize_title("Hello, World!") == _normalize_title("Hello World")

    def test_normalize_title_preserves_cjk(self) -> None:
        result = _normalize_title("央行降息政策")
        assert "央行" in result
        assert "降息" in result


class TestDedupChecker:
    def test_first_item_not_duplicate(self) -> None:
        checker = DedupChecker()
        item = _make_item()
        assert checker.is_duplicate(item) is False

    def test_same_url_is_duplicate(self) -> None:
        checker = DedupChecker()
        item1 = _make_item(title="Title A", url="https://example.com/1")
        item2 = _make_item(title="Title B", url="https://example.com/1")
        assert checker.is_duplicate(item1) is False
        assert checker.is_duplicate(item2) is True

    def test_same_url_different_utm_is_duplicate(self) -> None:
        checker = DedupChecker()
        item1 = _make_item(title="Title A", url="https://example.com/1?utm_source=rss")
        item2 = _make_item(title="Title B", url="https://example.com/1?utm_source=web")
        checker.is_duplicate(item1)
        assert checker.is_duplicate(item2) is True

    def test_same_title_is_duplicate(self) -> None:
        checker = DedupChecker()
        item1 = _make_item(title="央行降息 最新消息", url="https://a.com/1")
        item2 = _make_item(title="央行降息 最新消息", url="https://b.com/2")
        checker.is_duplicate(item1)
        assert checker.is_duplicate(item2) is True

    def test_different_items_not_duplicate(self) -> None:
        checker = DedupChecker()
        item1 = _make_item(title="Title A", url="https://a.com/1")
        item2 = _make_item(title="Title B", url="https://b.com/2")
        assert checker.is_duplicate(item1) is False
        assert checker.is_duplicate(item2) is False

    def test_filter_batch(self) -> None:
        checker = DedupChecker()
        items = [
            _make_item(title="Unique A", url="https://a.com/1"),
            _make_item(title="Unique B", url="https://b.com/2"),
            _make_item(title="Unique A", url="https://c.com/3"),  # dup by title
        ]
        filtered = checker.filter_batch(items)
        assert len(filtered) == 2

    def test_reset_clears_state(self) -> None:
        checker = DedupChecker()
        item = _make_item()
        checker.is_duplicate(item)
        checker.reset()
        # After reset, same item should not be seen as duplicate
        assert checker.is_duplicate(item) is False

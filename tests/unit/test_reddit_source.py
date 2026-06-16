"""Tests for RedditSource adapter (public JSON API)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.sources.reddit_source import RedditSource

# Sample Reddit JSON API response structure
_REDDIT_RESPONSE = {
    "data": {
        "children": [
            {
                "data": {
                    "title": "AAPL earnings beat expectations",
                    "selftext": "Apple reported strong Q4 results",
                    "permalink": "/r/stocks/comments/abc123/aapl_earnings/",
                    "score": 1500,
                    "num_comments": 230,
                    "subreddit": "stocks",
                    "stickied": False,
                }
            },
            {
                "data": {
                    "title": "Market crash incoming?",
                    "selftext": "Yield curve inverted again",
                    "permalink": "/r/stocks/comments/def456/market_crash/",
                    "score": 800,
                    "num_comments": 150,
                    "subreddit": "stocks",
                    "stickied": False,
                }
            },
            {
                "data": {
                    "title": "Weekly Discussion Thread",
                    "selftext": "Post your trades here",
                    "permalink": "/r/stocks/comments/ghi789/weekly/",
                    "score": 50,
                    "num_comments": 500,
                    "subreddit": "stocks",
                    "stickied": True,
                }
            },
        ]
    }
}


def _make_source(**overrides) -> RedditSource:
    cfg = {
        "display_name": "Test Reddit",
        "default_category": "social",
        "subreddits": ["stocks"],
        "max_items_per_sub": 10,
        "request_delay_seconds": 0,  # no delay in tests
        **overrides,
    }
    return RedditSource("reddit_test", cfg)


class TestRedditSourceFetch:
    def test_fetch_converts_posts_to_info_items(self) -> None:
        source = _make_source()
        mock_resp = MagicMock()
        mock_resp.json.return_value = _REDDIT_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "src.intelligence_hub.sources.reddit_source.requests.get",
            return_value=mock_resp,
        ):
            items = source.fetch()

        # 3 posts minus 1 stickied = 2
        assert len(items) == 2
        assert all(isinstance(i, InfoItem) for i in items)
        assert items[0].title == "AAPL earnings beat expectations"
        assert items[0].source_id == "reddit_test"
        assert items[0].category == "social"

    def test_stickied_posts_are_skipped(self) -> None:
        source = _make_source()
        mock_resp = MagicMock()
        mock_resp.json.return_value = _REDDIT_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "src.intelligence_hub.sources.reddit_source.requests.get",
            return_value=mock_resp,
        ):
            items = source.fetch()

        titles = [i.title for i in items]
        assert "Weekly Discussion Thread" not in titles

    def test_extra_fields_populated(self) -> None:
        source = _make_source()
        mock_resp = MagicMock()
        mock_resp.json.return_value = _REDDIT_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "src.intelligence_hub.sources.reddit_source.requests.get",
            return_value=mock_resp,
        ):
            items = source.fetch()

        assert items[0].extra["score"] == 1500
        assert items[0].extra["num_comments"] == 230
        assert items[0].extra["subreddit"] == "stocks"

    def test_url_constructed_from_permalink(self) -> None:
        source = _make_source()
        mock_resp = MagicMock()
        mock_resp.json.return_value = _REDDIT_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "src.intelligence_hub.sources.reddit_source.requests.get",
            return_value=mock_resp,
        ):
            items = source.fetch()

        assert (
            items[0].url
            == "https://www.reddit.com/r/stocks/comments/abc123/aapl_earnings/"
        )


class TestRedditSourceEdgeCases:
    def test_no_subreddits_returns_empty(self) -> None:
        source = _make_source(subreddits=[])
        items = source.fetch()
        assert items == []

    def test_network_error_returns_empty(self) -> None:
        source = _make_source()

        with patch(
            "src.intelligence_hub.sources.reddit_source.requests.get",
            side_effect=ConnectionError("timeout"),
        ):
            items = source.fetch()

        assert items == []

    def test_multiple_subreddits_combined(self) -> None:
        source = _make_source(subreddits=["stocks", "investing"])
        mock_resp = MagicMock()
        mock_resp.json.return_value = _REDDIT_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "src.intelligence_hub.sources.reddit_source.requests.get",
            return_value=mock_resp,
        ):
            items = source.fetch()

        # 2 non-stickied posts per sub × 2 subs = 4
        assert len(items) == 4

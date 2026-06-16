"""Tests for Intelligence Hub source adapters (mock AKShare/Policy/RSS)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.sources.akshare_news_source import AkshareNewsSource
from src.intelligence_hub.sources.policy_source import PolicySource
from src.intelligence_hub.sources.rss_source import RssSource


# ---------------------------------------------------------------------------
# AkshareNewsSource
# ---------------------------------------------------------------------------


class TestAkshareNewsSource:
    def test_fetch_converts_to_info_items(self) -> None:
        import pandas as pd

        source = AkshareNewsSource(
            "akshare_test",
            {
                "display_name": "Test AKShare",
                "default_category": "market",
                "max_items": 5,
            },
        )
        mock_df = pd.DataFrame(
            [
                {
                    "tag": "快讯",
                    "summary": "新闻标题1详情内容",
                    "url": "https://example.com/1",
                },
                {"tag": "CCI", "summary": "新闻标题2", "url": "https://example.com/2"},
            ]
        )
        mock_ak = MagicMock()
        mock_ak.stock_news_main_cx.return_value = mock_df

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            items = source.fetch()

        assert len(items) == 2
        assert "新闻标题1" in items[0].title
        assert items[0].source_id == "akshare_test"
        assert items[0].category == "market"
        assert isinstance(items[0], InfoItem)

    def test_fetch_handles_exception(self) -> None:
        source = AkshareNewsSource("akshare_err", {"display_name": "Err"})
        mock_ak = MagicMock()
        mock_ak.stock_news_main_cx.side_effect = RuntimeError("network error")

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            items = source.fetch()
        assert items == []

    def test_fetch_respects_max_items(self) -> None:
        import pandas as pd

        source = AkshareNewsSource(
            "akshare_max",
            {"display_name": "Max", "max_items": 2},
        )
        mock_df = pd.DataFrame(
            [
                {"tag": f"T{i}", "summary": f"News {i}", "url": f"u{i}"}
                for i in range(10)
            ]
        )
        mock_ak = MagicMock()
        mock_ak.stock_news_main_cx.return_value = mock_df

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            items = source.fetch()
        assert len(items) == 2


# ---------------------------------------------------------------------------
# PolicySource
# ---------------------------------------------------------------------------


@dataclass
class _MockPolicyItem:
    title: str = "政策公告"
    source: str = "csrc"
    source_name: str = "证监会"
    url: str = "https://csrc.gov.cn/1"
    date: str = "2026-02-15"
    impact_category: str = "regulatory"


class TestPolicySource:
    def test_fetch_converts_to_info_items(self) -> None:
        source = PolicySource(
            "policy_csrc",
            {
                "display_name": "证监会",
                "default_category": "policy",
                "source_key": "csrc",
            },
        )
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_source.return_value = [_MockPolicyItem()]
        source._fetcher = mock_fetcher

        items = source.fetch()

        assert len(items) == 1
        assert items[0].title == "政策公告"
        assert items[0].source_id == "policy_csrc"
        assert items[0].category == "policy"

    def test_fetch_no_source_key(self) -> None:
        source = PolicySource("policy_empty", {"display_name": "Empty"})
        items = source.fetch()
        assert items == []

    def test_fetch_handles_exception(self) -> None:
        source = PolicySource(
            "policy_err",
            {"display_name": "Err", "source_key": "csrc"},
        )
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_source.side_effect = RuntimeError("fail")
        source._fetcher = mock_fetcher

        items = source.fetch()
        assert items == []


# ---------------------------------------------------------------------------
# RssSource
# ---------------------------------------------------------------------------


class TestRssSource:
    def test_fetch_converts_entries(self) -> None:
        source = RssSource(
            "rss_test",
            {
                "display_name": "Test RSS",
                "default_category": "global",
                "feed_url": "https://example.com/rss",
                "max_items": 5,
            },
        )

        mock_entry1 = MagicMock()
        mock_entry1.title = "RSS Entry 1"
        mock_entry1.link = "https://example.com/1"
        mock_entry1.summary = "Summary 1"
        mock_entry1.published = "2026-02-15"

        mock_entry2 = MagicMock()
        mock_entry2.title = "RSS Entry 2"
        mock_entry2.link = "https://example.com/2"
        mock_entry2.summary = "Summary 2"
        mock_entry2.published = "2026-02-14"

        mock_feed = MagicMock()
        mock_feed.entries = [mock_entry1, mock_entry2]

        with patch.dict(
            "sys.modules",
            {"feedparser": MagicMock(parse=MagicMock(return_value=mock_feed))},
        ):
            items = source.fetch()

        assert len(items) == 2
        assert items[0].title == "RSS Entry 1"
        assert items[0].category == "global"
        assert items[0].source_id == "rss_test"

    def test_fetch_no_url(self) -> None:
        source = RssSource("rss_empty", {"display_name": "Empty"})
        items = source.fetch()
        assert items == []

    def test_fetch_handles_parse_error(self) -> None:
        source = RssSource(
            "rss_err",
            {"display_name": "Err", "feed_url": "https://example.com/rss"},
        )

        mock_fp = MagicMock()
        mock_fp.parse.side_effect = RuntimeError("parse error")
        with patch.dict("sys.modules", {"feedparser": mock_fp}):
            items = source.fetch()

        assert items == []

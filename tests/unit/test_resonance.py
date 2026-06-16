"""Tests for cross-platform resonance detection (FR-TN003)."""

from datetime import datetime
from unittest.mock import MagicMock

from src.data.trend_news import (
    KeywordMatcher,
    ResonanceDetector,
    TrendItem,
    _title_similarity,
    _infer_sentiment,
)


def _make_item(
    title: str, platform: str = "eastmoney", rank: int = 1, heat: float = 0.8
) -> TrendItem:
    return TrendItem(
        platform=platform,
        title=title,
        rank=rank,
        heat_score=heat,
        category="finance",
        fetched_at=datetime(2026, 2, 13, 10, 0),
    )


class TestTitleSimilarity:
    def test_identical(self):
        assert _title_similarity("春节档票房突破50亿", "春节档票房突破50亿") == 1.0

    def test_similar(self):
        score = _title_similarity("春节档票房突破50亿", "春节档票房已突破50亿大关")
        assert score > 0.4

    def test_different(self):
        score = _title_similarity("央行降准50个基点", "锂电池行业暴跌")
        assert score < 0.2

    def test_empty(self):
        assert _title_similarity("", "test") == 0.0
        assert _title_similarity("test", "") == 0.0
        assert _title_similarity("", "") == 0.0

    def test_single_char(self):
        assert _title_similarity("a", "b") == 0.0  # no bigrams


class TestInferSentiment:
    def test_positive(self):
        assert _infer_sentiment("春节档票房突破新高") == "positive"

    def test_negative(self):
        assert _infer_sentiment("公司暴跌亏损严重") == "negative"

    def test_mixed(self):
        assert _infer_sentiment("利好消息但暴跌不止") == "mixed"

    def test_neutral(self):
        assert _infer_sentiment("今日A股收盘情况") == "neutral"


class TestResonanceDetector:
    def test_detect_groups_similar_titles(self):
        items = [
            _make_item("春节档票房突破50亿", platform="eastmoney"),
            _make_item("春节档票房已突破50亿大关", platform="cls"),
            _make_item("春节档票房创纪录突破50亿", platform="toutiao"),
            _make_item("央行降准50个基点", platform="eastmoney"),
        ]
        detector = ResonanceDetector(similarity_threshold=0.3)
        events = detector.detect(items)

        # Should produce 2 groups: ticket box office group + central bank
        assert len(events) >= 2
        # The box office group should have multiple platforms
        box_office_evt = [e for e in events if "票房" in e.title]
        assert len(box_office_evt) == 1
        assert len(box_office_evt[0].platforms) >= 2

    def test_resonance_levels(self):
        # 5+ platforms = L3
        items = [_make_item("热点话题", platform=f"platform_{i}") for i in range(6)]
        detector = ResonanceDetector(similarity_threshold=0.3)
        events = detector.detect(items)
        # All identical titles → single group with 6 platforms → L3
        assert events[0].resonance_level == "L3"

    def test_l2_level(self):
        items = [_make_item("相同标题内容", platform=f"platform_{i}") for i in range(3)]
        detector = ResonanceDetector(similarity_threshold=0.3)
        events = detector.detect(items)
        assert events[0].resonance_level == "L2"

    def test_l1_level(self):
        items = [_make_item("独特标题内容")]
        detector = ResonanceDetector()
        events = detector.detect(items)
        assert events[0].resonance_level == "L1"

    def test_related_stocks_with_matcher(self):
        matcher = MagicMock(spec=KeywordMatcher)
        matcher.match_stock.return_value = (True, 0.8)

        items = [_make_item("茅台白酒涨价")]
        detector = ResonanceDetector(keyword_matcher=matcher)
        events = detector.detect(items, watchlist=["600519"])

        assert "600519" in events[0].related_stocks

    def test_empty_input(self):
        detector = ResonanceDetector()
        events = detector.detect([])
        assert events == []

    def test_sort_order(self):
        l3_items = [_make_item("L3话题B", platform=f"p{i}") for i in range(6)]
        flat = [_make_item("L1话题A", platform="p1")]
        flat.extend(l3_items)

        detector = ResonanceDetector(similarity_threshold=0.3)
        events = detector.detect(flat)
        # L3 should come first
        if len(events) >= 2:
            levels = [e.resonance_level for e in events]
            assert levels.index("L3") < levels.index("L1") if "L1" in levels else True

    def test_event_has_required_fields(self):
        items = [_make_item("测试话题")]
        detector = ResonanceDetector()
        events = detector.detect(items)
        evt = events[0]
        assert evt.event_id.startswith("evt-")
        assert evt.title == "测试话题"
        assert evt.first_appeared
        assert evt.last_updated
        assert isinstance(evt.rank_timeline, list)

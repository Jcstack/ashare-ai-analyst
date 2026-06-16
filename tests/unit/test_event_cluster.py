"""Tests for Intelligence Hub event clustering and cross-verification scoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.intelligence_hub.event_cluster import EventCluster, EventClusterer
from src.intelligence_hub.models import InfoItem


def _make_item(**overrides) -> InfoItem:
    defaults = {
        "source_id": "src_a",
        "source_name": "Source A",
        "title": "Default Title",
        "published_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
    }
    defaults.update(overrides)
    return InfoItem(**defaults)


class TestClusterEmpty:
    def test_empty_items_returns_empty(self) -> None:
        clusterer = EventClusterer()
        result = clusterer.cluster([])
        assert result == []


class TestClusterSingleton:
    def test_single_item_singleton_cluster(self) -> None:
        clusterer = EventClusterer()
        item = _make_item(title="Some unique news headline")
        result = clusterer.cluster([item])
        assert len(result) == 1
        assert len(result[0].items) == 1
        assert result[0].items[0] is item


class TestTitleClustering:
    def test_similar_titles_clustered(self) -> None:
        """Items with overlapping title words should be grouped."""
        clusterer = EventClusterer()
        items = [
            _make_item(
                title="Fed cuts rates by 25bps",
                source_id="src_a",
            ),
            _make_item(
                title="Federal Reserve cuts interest rates 25 basis points",
                source_id="src_b",
            ),
        ]
        result = clusterer.cluster(items)
        # Both items share enough words (cuts, rates, 25) to cluster
        assert len(result) == 1
        assert len(result[0].items) == 2

    def test_different_titles_separate_clusters(self) -> None:
        """Items with distinct titles should not be grouped."""
        clusterer = EventClusterer()
        items = [
            _make_item(title="Apple releases new iPhone model"),
            _make_item(title="China GDP growth exceeds expectations"),
        ]
        result = clusterer.cluster(items)
        assert len(result) == 2
        assert len(result[0].items) == 1
        assert len(result[1].items) == 1


class TestCrossVerificationScore:
    def test_cross_verification_score_single_source(self) -> None:
        cluster = EventCluster(
            cluster_id="test",
            items=[
                _make_item(source_id="src_a", title="News A"),
                _make_item(source_id="src_a", title="News A variant"),
            ],
        )
        assert cluster.cross_verification_score == 0.0

    def test_cross_verification_score_two_sources(self) -> None:
        cluster = EventCluster(
            cluster_id="test",
            items=[
                _make_item(source_id="src_a", title="News A"),
                _make_item(source_id="src_b", title="News A variant"),
            ],
        )
        assert cluster.cross_verification_score == 0.3

    def test_cross_verification_score_three_sources(self) -> None:
        cluster = EventCluster(
            cluster_id="test",
            items=[
                _make_item(source_id="src_a"),
                _make_item(source_id="src_b"),
                _make_item(source_id="src_c"),
            ],
        )
        assert cluster.cross_verification_score == 0.6

    def test_cross_verification_score_four_sources(self) -> None:
        cluster = EventCluster(
            cluster_id="test",
            items=[
                _make_item(source_id="src_a"),
                _make_item(source_id="src_b"),
                _make_item(source_id="src_c"),
                _make_item(source_id="src_d"),
            ],
        )
        assert cluster.cross_verification_score == 1.0


class TestTimeWindow:
    def test_time_window_respected(self) -> None:
        """Items more than 48h apart should not be clustered even with similar titles."""
        now = datetime.now(UTC)
        recent = now.strftime("%Y-%m-%d %H:%M:%S")
        old = (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")

        clusterer = EventClusterer(window_hours=48)
        items = [
            _make_item(
                title="Fed cuts rates by 25bps",
                published_at=recent,
            ),
            _make_item(
                title="Fed cuts rates by 25bps again",
                published_at=old,  # 5 days earlier
            ),
        ]
        result = clusterer.cluster(items)
        # The old item should be filtered out by the time window
        assert len(result) == 1
        assert len(result[0].items) == 1


class TestCJKClustering:
    def test_cjk_title_clustering(self) -> None:
        """Chinese titles about the same event should cluster."""
        clusterer = EventClusterer()
        items = [
            _make_item(
                title="央行降息25基点",
                source_id="src_a",
            ),
            _make_item(
                title="央行宣布降息决定",
                source_id="src_b",
            ),
        ]
        result = clusterer.cluster(items)
        # Shared CJK tokens: 央, 行, 降, 息 (at minimum)
        assert len(result) == 1
        assert len(result[0].items) == 2


class TestGetCrossVerificationMap:
    def test_get_cross_verification_map(self) -> None:
        clusterer = EventClusterer()
        items = [
            _make_item(
                title="Fed cuts rates by 25bps",
                source_id="src_a",
            ),
            _make_item(
                title="Federal Reserve cuts interest rates 25 basis points",
                source_id="src_b",
            ),
            _make_item(
                title="Apple releases new iPhone model",
                source_id="src_c",
            ),
        ]
        result = clusterer.get_cross_verification_map(items)
        assert len(result) == 3
        # The two Fed items should have score 0.3 (2 unique sources)
        assert result[items[0].item_id] == 0.3
        assert result[items[1].item_id] == 0.3
        # Apple item is a singleton, score 0.0
        assert result[items[2].item_id] == 0.0


class TestTokenize:
    def test_tokenize_english(self) -> None:
        tokens = EventClusterer._tokenize("Fed cuts rates by 25bps")
        assert "fed" in tokens
        assert "cuts" in tokens
        assert "rates" in tokens
        assert "25bps" in tokens
        # "by" is only 2 chars, should be included
        assert "by" in tokens

    def test_tokenize_cjk(self) -> None:
        tokens = EventClusterer._tokenize("央行降息25基点")
        # Each CJK character should be an individual token
        assert "央" in tokens
        assert "行" in tokens
        assert "降" in tokens
        assert "息" in tokens
        assert "基" in tokens
        assert "点" in tokens
        # "25" is a non-CJK part, len >= 2
        assert "25" in tokens

    def test_tokenize_empty(self) -> None:
        tokens = EventClusterer._tokenize("")
        assert tokens == set()

    def test_tokenize_filters_short(self) -> None:
        tokens = EventClusterer._tokenize("a I am good")
        # "a" and "I" are single chars (non-CJK), should be filtered
        assert "a" not in tokens
        assert "i" not in tokens
        assert "am" in tokens
        assert "good" in tokens


class TestJaccardSimilarity:
    def test_jaccard_similarity(self) -> None:
        assert EventClusterer._jaccard_similarity(set(), set()) == 0.0
        assert EventClusterer._jaccard_similarity({"a", "b"}, set()) == 0.0
        assert EventClusterer._jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0
        # {"a", "b"} & {"b", "c"} = {"b"}, union = {"a", "b", "c"} => 1/3
        result = EventClusterer._jaccard_similarity({"a", "b"}, {"b", "c"})
        assert abs(result - 1.0 / 3.0) < 1e-9


class TestRepresentativeTitle:
    def test_representative_title_from_highest_score(self) -> None:
        cluster = EventCluster(
            cluster_id="test",
            items=[
                _make_item(title="Low score title", content_score=30.0),
                _make_item(title="High score title", content_score=85.0),
                _make_item(title="Medium score title", content_score=60.0),
            ],
        )
        assert cluster.representative_title == "High score title"

    def test_representative_title_no_scores(self) -> None:
        cluster = EventCluster(
            cluster_id="test",
            items=[
                _make_item(title="First item"),
                _make_item(title="Second item"),
            ],
        )
        # No content_score set, falls back to first item
        assert cluster.representative_title == "First item"

    def test_representative_title_empty_cluster(self) -> None:
        cluster = EventCluster(cluster_id="test", items=[])
        assert cluster.representative_title == ""

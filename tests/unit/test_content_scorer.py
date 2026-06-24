"""Tests for ContentScorer — scoring formula and explain payload."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.scorer import ContentScorer
from src.intelligence_hub.source_registry import SourceRegistry


def _registry(
    source_id: str = "test_src",
    layer: str = "L3",
    base_weight: float = 0.75,
) -> SourceRegistry:
    return SourceRegistry(
        [
            {
                "source_id": source_id,
                "layer": layer,
                "base_weight": base_weight,
                "compliance_level": "MEDIUM",
                "domain_tags": ["global", "macro"],
            }
        ]
    )


def _now_str(offset_hours: float = 0) -> str:
    dt = datetime.now(UTC) - timedelta(hours=offset_hours)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _make_item(**overrides) -> InfoItem:
    defaults = {
        "source_id": "test_src",
        "source_name": "Test Source",
        "title": "A meaningful headline about markets",
        "summary": "Some summary text",
        "url": "https://example.com/article",
        "published_at": _now_str(0.5),
    }
    defaults.update(overrides)
    return InfoItem(**defaults)


class TestContentScorer:
    def test_score_returns_0_to_100(self) -> None:
        scorer = ContentScorer(_registry())
        result = scorer.score(_make_item())
        assert 0 <= result.score <= 100

    def test_score_high_weight_source(self) -> None:
        scorer = ContentScorer(_registry(base_weight=1.0))
        result = scorer.score(_make_item())
        assert result.score > 50

    def test_score_low_weight_source(self) -> None:
        scorer = ContentScorer(_registry(base_weight=0.1))
        result = scorer.score(_make_item())
        # Low source weight reduces overall score
        high_scorer = ContentScorer(_registry(base_weight=1.0))
        high_result = high_scorer.score(_make_item())
        assert result.score < high_result.score

    def test_score_old_item_lower(self) -> None:
        scorer = ContentScorer(_registry())
        fresh = scorer.score(_make_item(published_at=_now_str(0.5)))
        old = scorer.score(_make_item(published_at=_now_str(48)))
        assert fresh.score > old.score

    def test_score_timeliness_decay(self) -> None:
        scorer = ContentScorer(_registry())
        r1 = scorer.score(_make_item(published_at=_now_str(0.5)))
        r6 = scorer.score(_make_item(published_at=_now_str(5)))
        r24 = scorer.score(_make_item(published_at=_now_str(20)))
        r72 = scorer.score(_make_item(published_at=_now_str(50)))
        assert r1.score >= r6.score >= r24.score >= r72.score

    def test_score_with_user_domains_match(self) -> None:
        scorer = ContentScorer(_registry())
        result = scorer.score(_make_item(), user_domains=["global", "equities"])
        explain = result.explain["domain_relevance"]
        assert explain["factor"] == 1.0

    def test_score_with_user_domains_no_match(self) -> None:
        scorer = ContentScorer(_registry())
        result = scorer.score(_make_item(), user_domains=["sports"])
        explain = result.explain["domain_relevance"]
        assert explain["factor"] == 0.2

    def test_score_no_user_domains_neutral(self) -> None:
        scorer = ContentScorer(_registry())
        result = scorer.score(_make_item(), user_domains=None)
        explain = result.explain["domain_relevance"]
        assert explain["factor"] == 0.5

    def test_quality_bonus_all_present(self) -> None:
        scorer = ContentScorer(_registry())
        item = _make_item(
            summary="Good summary",
            url="https://example.com",
            related_symbols=["600036"],
        )
        result = scorer.score(item)
        assert result.explain["quality_signals"]["factor"] == 1.0

    def test_quality_bonus_none_present(self) -> None:
        scorer = ContentScorer(_registry())
        item = _make_item(summary="", url="", related_symbols=[])
        result = scorer.score(item)
        assert result.explain["quality_signals"]["factor"] == 0.0

    def test_noise_penalty_short_title(self) -> None:
        scorer = ContentScorer(_registry())
        item = _make_item(title="短标题")
        result = scorer.score(item)
        assert result.explain["noise_penalty"]["factor"] > 0

    def test_noise_penalty_low_reddit_score(self) -> None:
        scorer = ContentScorer(_registry())
        item = _make_item(extra={"score": 1})
        result = scorer.score(item)
        assert result.explain["noise_penalty"]["factor"] > 0

    def test_explain_payload_keys(self) -> None:
        scorer = ContentScorer(_registry())
        result = scorer.score(_make_item())
        assert set(result.explain.keys()) == {
            "source_weight",
            "timeliness",
            "cross_verification",
            "domain_relevance",
            "quality_signals",
            "noise_penalty",
            "sentiment_bonus",
        }

    def test_cross_verification_boost(self) -> None:
        scorer = ContentScorer(_registry())
        item = _make_item()
        cv_map = {item.item_id: 1.0}  # max cross-verification
        with_cv = scorer.score(item, cross_verification_map=cv_map)
        without_cv = scorer.score(item)
        assert with_cv.score > without_cv.score
        assert with_cv.explain["cross_verification"]["factor"] == 1.0
        assert without_cv.explain["cross_verification"]["factor"] == 0.0

    def test_score_batch(self) -> None:
        scorer = ContentScorer(_registry())
        items = [
            _make_item(title=f"Item {i}", url=f"https://e.com/{i}") for i in range(3)
        ]
        results = scorer.score_batch(items)
        assert len(results) == 3
        assert all(0 <= r.score <= 100 for r in results)

    def test_score_unknown_source_fallback(self) -> None:
        scorer = ContentScorer(_registry())
        item = _make_item(source_id="unknown")
        result = scorer.score(item)
        # Falls back to 0.5 weight
        assert result.explain["source_weight"]["effective_weight"] == 0.5
        assert 0 <= result.score <= 100

    def test_score_invalid_published_at(self) -> None:
        scorer = ContentScorer(_registry())
        item = _make_item(published_at="invalid-date")
        result = scorer.score(item)
        # Should treat as very old
        assert result.explain["timeliness"]["factor"] == 0.05

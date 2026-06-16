"""Tests for Intelligence Hub social guardrails (L5 source protection)."""

from __future__ import annotations

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.social_guardrails import SocialGuardrails
from src.intelligence_hub.source_registry import SourceRegistry


def _registry() -> SourceRegistry:
    """Create a registry with L5 (social) and L3 (media) sources."""
    return SourceRegistry(
        [
            {
                "source_id": "reddit_fin",
                "layer": "L5",
                "base_weight": 0.3,
                "compliance_level": "LOW",
                "domain_tags": ["social"],
            },
            {
                "source_id": "wsj",
                "layer": "L3",
                "base_weight": 0.8,
                "compliance_level": "MEDIUM",
                "domain_tags": ["global"],
            },
        ]
    )


def _make(
    source_id: str = "reddit_fin",
    title: str = "Test post",
    priority: str = "normal",
) -> InfoItem:
    return InfoItem(
        source_id=source_id,
        source_name="Test",
        title=title,
        priority=priority,
    )


class TestL5Downgrade:
    """L5 sources should have breaking/high priority downgraded."""

    def test_l5_breaking_downgraded_to_normal(self) -> None:
        guard = SocialGuardrails(_registry())
        item = _make(source_id="reddit_fin", priority="breaking")
        guard.apply(item)
        assert item.priority == "normal"

    def test_l5_high_downgraded_to_normal(self) -> None:
        guard = SocialGuardrails(_registry())
        item = _make(source_id="reddit_fin", priority="high")
        guard.apply(item)
        assert item.priority == "normal"

    def test_l5_normal_unchanged(self) -> None:
        guard = SocialGuardrails(_registry())
        item = _make(source_id="reddit_fin", priority="normal")
        guard.apply(item)
        assert item.priority == "normal"


class TestUnverifiedTag:
    """L5 items should get the unverified tag."""

    def test_l5_unverified_tag_added(self) -> None:
        guard = SocialGuardrails(_registry())
        item = _make(source_id="reddit_fin", priority="normal")
        guard.apply(item)
        assert item.extra.get("unverified") is True


class TestNonL5Preserved:
    """Non-L5 sources should be left untouched."""

    def test_non_l5_breaking_preserved(self) -> None:
        guard = SocialGuardrails(_registry())
        item = _make(source_id="wsj", priority="breaking")
        guard.apply(item)
        assert item.priority == "breaking"
        assert "unverified" not in item.extra

    def test_non_l5_high_preserved(self) -> None:
        guard = SocialGuardrails(_registry())
        item = _make(source_id="wsj", priority="high")
        guard.apply(item)
        assert item.priority == "high"
        assert "unverified" not in item.extra


class TestEdgeCases:
    """Edge cases: unknown sources and batch processing."""

    def test_unknown_source_unchanged(self) -> None:
        guard = SocialGuardrails(_registry())
        item = _make(source_id="unknown_src", priority="breaking")
        guard.apply(item)
        assert item.priority == "breaking"
        assert "unverified" not in item.extra

    def test_apply_batch(self) -> None:
        guard = SocialGuardrails(_registry())
        items = [
            _make(source_id="reddit_fin", priority="breaking"),
            _make(source_id="wsj", priority="high"),
            _make(source_id="reddit_fin", priority="normal"),
        ]
        result = guard.apply_batch(items)
        assert len(result) == 3
        # L5 breaking -> normal, tagged unverified
        assert result[0].priority == "normal"
        assert result[0].extra.get("unverified") is True
        # L3 high -> preserved
        assert result[1].priority == "high"
        assert "unverified" not in result[1].extra
        # L5 normal -> stays normal, tagged unverified
        assert result[2].priority == "normal"
        assert result[2].extra.get("unverified") is True

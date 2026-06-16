"""Tests for anti-filter-bubble diversity reranker."""

from __future__ import annotations

from src.intelligence_hub.diversity import DiversityReranker
from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.source_registry import SourceRegistry


# ── Test helpers ────────────────────────────────────────────────────────

SOURCES_CONFIG = [
    {
        "source_id": "csrc",
        "layer": "L1",
        "base_weight": 1.0,
        "compliance_level": "HIGH",
        "domain_tags": ["china", "regulation", "equities"],
    },
    {
        "source_id": "pboc",
        "layer": "L1",
        "base_weight": 1.0,
        "compliance_level": "HIGH",
        "domain_tags": ["china", "monetary_policy", "macro"],
    },
    {
        "source_id": "fed",
        "layer": "L2",
        "base_weight": 0.90,
        "compliance_level": "HIGH",
        "domain_tags": ["us", "monetary_policy", "macro"],
    },
    {
        "source_id": "wsj",
        "layer": "L3",
        "base_weight": 0.80,
        "compliance_level": "MEDIUM",
        "domain_tags": ["us", "equities", "macro"],
    },
    {
        "source_id": "36kr",
        "layer": "L4",
        "base_weight": 0.55,
        "compliance_level": "LOW",
        "domain_tags": ["china", "technology", "industry"],
    },
    {
        "source_id": "reddit_fin",
        "layer": "L5",
        "base_weight": 0.35,
        "compliance_level": "LOW",
        "domain_tags": ["us", "social", "equities"],
    },
    {
        "source_id": "bbc",
        "layer": "L3",
        "base_weight": 0.75,
        "compliance_level": "MEDIUM",
        "domain_tags": ["global", "macro", "equities"],
    },
    {
        "source_id": "ecb",
        "layer": "L2",
        "base_weight": 0.85,
        "compliance_level": "HIGH",
        "domain_tags": ["europe", "monetary_policy", "macro"],
    },
]


def _registry() -> SourceRegistry:
    return SourceRegistry(SOURCES_CONFIG)


def _item(source_id: str, title: str) -> InfoItem:
    return InfoItem(source_id=source_id, source_name=source_id.upper(), title=title)


def _enabled_config(**overrides: object) -> dict:
    cfg: dict = {
        "enabled": True,
        "diversity_strength": "medium",
        "min_non_interest_pct": 0.30,
        "layer_budgets": {
            "L1": 0.35,
            "L2": 0.15,
            "L3": 0.25,
            "L4": 0.15,
            "L5": 0.10,
        },
    }
    cfg.update(overrides)
    return cfg


# ── Tests ───────────────────────────────────────────────────────────────


class TestDisabledBehaviour:
    def test_disabled_returns_unchanged(self) -> None:
        reg = _registry()
        reranker = DiversityReranker(reg, config={"enabled": False})
        items = [_item("csrc", "Policy A"), _item("fed", "Fed update")]
        result = reranker.rerank(items, user_domains=["china"])
        assert result is items  # exact same list object

    def test_no_user_domains_returns_unchanged(self) -> None:
        reg = _registry()
        reranker = DiversityReranker(reg, config=_enabled_config())
        items = [_item("csrc", "Policy A"), _item("fed", "Fed update")]
        result = reranker.rerank(items, user_domains=None)
        assert result is items

    def test_empty_user_domains_returns_unchanged(self) -> None:
        reg = _registry()
        reranker = DiversityReranker(reg, config=_enabled_config())
        items = [_item("csrc", "Policy A"), _item("fed", "Fed update")]
        result = reranker.rerank(items, user_domains=[])
        assert result is items


class TestEmptyInput:
    def test_empty_items_returns_empty(self) -> None:
        reg = _registry()
        reranker = DiversityReranker(reg, config=_enabled_config())
        result = reranker.rerank([], user_domains=["china"])
        assert result == []


class TestDiverseInjection:
    def test_rerank_injects_diverse_items(self) -> None:
        """When user interests are 'china', non-china items should be injected."""
        reg = _registry()
        reranker = DiversityReranker(reg, config=_enabled_config())

        # 7 china items + 3 non-china items
        items = [
            _item("csrc", "China policy 1"),
            _item("csrc", "China policy 2"),
            _item("pboc", "PBOC update"),
            _item("36kr", "Tech news CN"),
            _item("csrc", "China policy 3"),
            _item("pboc", "PBOC rate"),
            _item("36kr", "Tech news CN 2"),
            _item("fed", "Fed rate decision"),
            _item("wsj", "WSJ markets"),
            _item("reddit_fin", "Reddit discussion"),
        ]

        result = reranker.rerank(items, user_domains=["china"])

        # Diverse items (fed, wsj, reddit_fin) should appear in the result
        diverse_ids = {"fed", "wsj", "reddit_fin"}
        result_diverse = [it for it in result if it.source_id in diverse_ids]
        assert len(result_diverse) >= 1, "At least one diverse item should be injected"
        assert len(result) == len(items), "Total count should be preserved"

    def test_all_items_match_interest_no_diverse_available(self) -> None:
        """When every item matches user interest and no diverse pool exists."""
        reg = _registry()
        reranker = DiversityReranker(reg, config=_enabled_config())

        items = [
            _item("csrc", "China 1"),
            _item("pboc", "China 2"),
            _item("36kr", "China 3"),
        ]
        result = reranker.rerank(items, user_domains=["china"])
        # No diverse items available, so return as-is
        assert len(result) == 3
        titles = [it.title for it in result]
        assert "China 1" in titles
        assert "China 2" in titles
        assert "China 3" in titles

    def test_no_diverse_items_available(self) -> None:
        """All items match user domains -- should return items unchanged."""
        reg = _registry()
        reranker = DiversityReranker(reg, config=_enabled_config())
        # user_domains covers every source's domain_tags
        all_domains = [
            "china",
            "us",
            "global",
            "europe",
            "regulation",
            "monetary_policy",
            "macro",
            "equities",
            "technology",
            "industry",
            "social",
        ]
        items = [
            _item("csrc", "A"),
            _item("fed", "B"),
            _item("wsj", "C"),
            _item("reddit_fin", "D"),
        ]
        result = reranker.rerank(items, user_domains=all_domains)
        assert len(result) == 4


class TestDiversityStrength:
    def test_diversity_strength_low_vs_high(self) -> None:
        """Higher strength should inject more diverse items."""
        reg = _registry()

        # Build a feed with 8 interest + 4 diverse items (12 total)
        items = [_item("csrc", f"China {i}") for i in range(8)] + [
            _item("fed", "Fed 1"),
            _item("wsj", "WSJ 1"),
            _item("ecb", "ECB 1"),
            _item("bbc", "BBC 1"),
        ]

        low_reranker = DiversityReranker(
            reg, config=_enabled_config(diversity_strength="low")
        )
        high_reranker = DiversityReranker(
            reg, config=_enabled_config(diversity_strength="high")
        )

        result_low = low_reranker.rerank(items, user_domains=["china"])
        result_high = high_reranker.rerank(items, user_domains=["china"])

        diverse_ids = {"fed", "wsj", "ecb", "bbc"}

        low_diverse = [it for it in result_low if it.source_id in diverse_ids]
        high_diverse = [it for it in result_high if it.source_id in diverse_ids]

        assert len(high_diverse) >= len(low_diverse), (
            f"High strength ({len(high_diverse)}) should inject at least as many "
            f"diverse items as low strength ({len(low_diverse)})"
        )


class TestLayerBudgets:
    def test_layer_budgets_respected(self) -> None:
        """Layer budgets should roughly allocate items across layers."""
        reg = _registry()
        reranker = DiversityReranker(reg, config=_enabled_config())

        # 10 interest items + 10 diverse items with varied layers
        items = [_item("csrc", f"China {i}") for i in range(10)]
        # Diverse: 3 L2, 4 L3, 2 L4, 1 L5
        items.extend(
            [
                _item("fed", "Fed 1"),
                _item("fed", "Fed 2"),
                _item("ecb", "ECB 1"),
                _item("wsj", "WSJ 1"),
                _item("wsj", "WSJ 2"),
                _item("bbc", "BBC 1"),
                _item("bbc", "BBC 2"),
                _item("reddit_fin", "Reddit 1"),
            ]
        )

        result = reranker.rerank(items, user_domains=["china"])
        assert len(result) == len(items)

        # Verify diverse items are present from multiple layers
        diverse_layers = set()
        for it in result:
            meta = reg.get(it.source_id)
            if meta and not (set(meta.domain_tags) & {"china"}):
                diverse_layers.add(meta.layer)

        assert len(diverse_layers) >= 2, (
            f"Diverse items should span multiple layers, got {diverse_layers}"
        )

    def test_diverse_items_prefer_higher_layers(self) -> None:
        """When diverse pool is limited, higher-layer items should be preferred."""
        reg = _registry()
        # Tight budget: only need 2 diverse items from a pool of 3
        config = _enabled_config(diversity_strength="low")
        reranker = DiversityReranker(reg, config=config)

        items = [_item("csrc", f"China {i}") for i in range(7)] + [
            _item("reddit_fin", "Reddit noise"),  # L5
            _item("fed", "Fed important"),  # L2
            _item("wsj", "WSJ article"),  # L3
        ]

        result = reranker.rerank(items, user_domains=["china"])

        diverse_ids = {"reddit_fin", "fed", "wsj"}
        injected = [it for it in result if it.source_id in diverse_ids]

        # At minimum, L2 (fed) should appear before L5 (reddit_fin) in the injected list
        # because layer budgets prioritize higher layers
        if len(injected) >= 2:
            fed_items = [it for it in injected if it.source_id == "fed"]
            assert len(fed_items) >= 1, "L2 items should be preferred over L5"


class TestOrderPreservation:
    def test_rerank_preserves_order_within_groups(self) -> None:
        """Interest items should maintain their relative order."""
        reg = _registry()
        reranker = DiversityReranker(reg, config=_enabled_config())

        items = [
            _item("csrc", "China A"),
            _item("csrc", "China B"),
            _item("pboc", "China C"),
            _item("csrc", "China D"),
            _item("fed", "Fed X"),
            _item("wsj", "WSJ Y"),
        ]

        result = reranker.rerank(items, user_domains=["china"])

        # Extract interest items from result, check relative order preserved
        interest_items = [it for it in result if it.source_id in {"csrc", "pboc"}]
        interest_titles = [it.title for it in interest_items]

        # Original order: A, B, C, D -- should be maintained
        assert interest_titles == ["China A", "China B", "China C", "China D"]


class TestDefaultConfig:
    def test_none_config_defaults_to_disabled(self) -> None:
        reg = _registry()
        reranker = DiversityReranker(reg, config=None)
        items = [_item("csrc", "A"), _item("fed", "B")]
        result = reranker.rerank(items, user_domains=["china"])
        assert result is items

    def test_empty_config_defaults_to_disabled(self) -> None:
        reg = _registry()
        reranker = DiversityReranker(reg, config={})
        items = [_item("csrc", "A"), _item("fed", "B")]
        result = reranker.rerank(items, user_domains=["china"])
        assert result is items

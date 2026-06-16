"""Rule-based category and priority classifier for InfoItem.

Part of v21.0 Intelligence Hub. Applies classification rules from
config/intelligence_hub.yaml to assign category and priority to items.
"""

from __future__ import annotations

import logging
from typing import Any

from src.intelligence_hub.models import CATEGORIES, PRIORITIES, InfoItem

logger = logging.getLogger(__name__)


class InfoClassifier:
    """Applies rule-based classification to InfoItem instances."""

    def __init__(self, rules_config: dict[str, Any] | None = None) -> None:
        if rules_config is None:
            rules_config = {}
        self._category_rules: list[dict[str, Any]] = rules_config.get(
            "category_rules", []
        )
        self._priority_rules: list[dict[str, Any]] = rules_config.get(
            "priority_rules", []
        )

    def classify(self, item: InfoItem, source_type: str = "") -> InfoItem:
        """Apply classification rules to an item, mutating it in place.

        Rules are evaluated top-to-bottom; first match wins for each dimension.

        Args:
            item: The InfoItem to classify.
            source_type: The source type string (e.g. "policy", "akshare_news").

        Returns:
            The same InfoItem with category/priority potentially updated.
        """
        item.category = self._match_category(item, source_type)
        item.priority = self._match_priority(item, source_type)
        return item

    def classify_batch(
        self, items: list[InfoItem], source_type: str = ""
    ) -> list[InfoItem]:
        """Classify a batch of items."""
        for item in items:
            self.classify(item, source_type)
        return items

    def _match_category(self, item: InfoItem, source_type: str) -> str:
        """Find the first matching category rule."""
        text = f"{item.title} {item.summary}"
        for rule in self._category_rules:
            if self._rule_matches(rule, text, source_type):
                cat = rule.get("category", item.category)
                if cat in CATEGORIES:
                    return cat
        return item.category

    def _match_priority(self, item: InfoItem, source_type: str) -> str:
        """Find the first matching priority rule."""
        text = f"{item.title} {item.summary}"
        for rule in self._priority_rules:
            if self._rule_matches(rule, text, source_type):
                pri = rule.get("priority", item.priority)
                if pri in PRIORITIES:
                    return pri
        return item.priority

    def _rule_matches(self, rule: dict[str, Any], text: str, source_type: str) -> bool:
        """Check if a rule matches the given text and source type."""
        # match_source_type rule
        if "match_source_type" in rule:
            if rule["match_source_type"] == source_type:
                return True
            return False

        # match_keywords rule
        if "match_keywords" in rule:
            keywords = rule["match_keywords"]
            return any(kw in text for kw in keywords)

        return False

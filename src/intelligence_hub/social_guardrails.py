"""Social guardrails — prevents L5 sources from triggering high-priority alone.

Part of v23.0 Phase 2. L5 (social/community) items:
1. Cannot have priority "breaking" or "high" — downgraded to "normal"
2. Get extra.unverified = True tag for UI display

Applied as a post-classification step after InfoClassifier runs.
"""

from __future__ import annotations

import logging

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.source_registry import SourceRegistry

logger = logging.getLogger(__name__)

# Priorities that L5 sources are not allowed to have independently
_RESTRICTED_PRIORITIES = frozenset({"breaking", "high"})


class SocialGuardrails:
    """Post-classification guardrails for L5 (social/community) sources."""

    def __init__(self, registry: SourceRegistry) -> None:
        self._registry = registry

    def apply(self, item: InfoItem) -> InfoItem:
        """Apply social guardrails to a single item. Mutates in place.

        If the item comes from an L5 source:
        - Downgrades "breaking"/"high" priority to "normal"
        - Sets extra["unverified"] = True

        Returns:
            The same InfoItem, potentially modified.
        """
        meta = self._registry.get(item.source_id)
        if meta is None or meta.layer != "L5":
            return item

        # Downgrade restricted priorities
        if item.priority in _RESTRICTED_PRIORITIES:
            logger.debug(
                "Downgrading L5 item %s priority %s -> normal",
                item.item_id,
                item.priority,
            )
            item.priority = "normal"

        # Mark as unverified for UI display
        item.extra = {**item.extra, "unverified": True}
        return item

    def apply_batch(self, items: list[InfoItem]) -> list[InfoItem]:
        """Apply social guardrails to a batch of items."""
        for item in items:
            self.apply(item)
        return items

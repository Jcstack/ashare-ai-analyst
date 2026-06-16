"""Anti-filter-bubble diversity reranker.

Part of v23.0 Phase 2. Ensures feed diversity by:
1. Enforcing minimum % of items from non-user-interest domains
2. Applying layer budget quotas (L1-L5)
3. Diversity strength controls injection aggressiveness
"""

from __future__ import annotations

import logging
from typing import Any

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.source_registry import SourceRegistry

logger = logging.getLogger(__name__)

# Strength -> fraction of total feed reserved for diverse (non-interest) items
DIVERSITY_STRENGTH = {
    "low": 0.15,
    "medium": 0.30,
    "high": 0.50,
}

_DEFAULT_LAYER_BUDGETS = {
    "L1": 0.35,
    "L2": 0.15,
    "L3": 0.25,
    "L4": 0.15,
    "L5": 0.10,
}

# Layer priority order for preferring higher-trust items
_LAYER_PRIORITY = {"L1": 0, "L2": 1, "L3": 2, "L4": 3, "L5": 4}


class DiversityReranker:
    """Reranks a scored feed to ensure topical and layer diversity."""

    def __init__(
        self,
        registry: SourceRegistry,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config or {}
        self._registry = registry
        self._enabled = cfg.get("enabled", False)
        strength_key = cfg.get("diversity_strength", "medium")
        self._strength = DIVERSITY_STRENGTH.get(strength_key, 0.30)
        self._min_non_interest_pct = cfg.get("min_non_interest_pct", 0.30)
        self._layer_budgets: dict[str, float] = cfg.get(
            "layer_budgets", _DEFAULT_LAYER_BUDGETS
        )

    def rerank(
        self,
        items: list[InfoItem],
        user_domains: list[str] | None = None,
    ) -> list[InfoItem]:
        """Rerank items to ensure diversity.

        Algorithm:
        1. Split items into "interest" (matching user_domains) and "diverse" (non-matching)
        2. Calculate target diverse count based on strength
        3. Fill from diverse pool, preferring higher-layer items (L1>L2>L3)
        4. Merge: interleave diverse items into the interest-sorted list
        """
        if not self._enabled or not items:
            return items
        if not user_domains:
            return items

        interest, diverse = self._split_by_interest(items, user_domains)

        if not diverse:
            return items

        total = len(items)
        target_diverse = max(1, int(total * self._strength))
        # Respect min_non_interest_pct as a floor
        min_diverse = max(1, int(total * self._min_non_interest_pct))
        target_diverse = max(target_diverse, min_diverse)
        # Cannot inject more diverse items than available
        target_diverse = min(target_diverse, len(diverse))

        # Apply layer budgets to select the priority diverse items
        selected_diverse = self._apply_layer_budgets(diverse, target_diverse)

        # Build final list preserving total count:
        # - Priority diverse items get interleaved
        # - Interest items fill the bulk
        # - Any remaining diverse items not selected go at the tail
        selected_set = set(id(it) for it in selected_diverse)
        remaining_diverse = [it for it in diverse if id(it) not in selected_set]

        interest_slots = total - len(selected_diverse)
        trimmed_interest = interest[:interest_slots]
        # If interest doesn't fill all non-diverse slots, append remaining diverse
        shortfall = interest_slots - len(trimmed_interest)
        if shortfall > 0 and remaining_diverse:
            trimmed_interest.extend(remaining_diverse[:shortfall])

        # Interleave diverse items into the interest list
        return self._interleave(trimmed_interest, selected_diverse)

    def _split_by_interest(
        self,
        items: list[InfoItem],
        user_domains: list[str],
    ) -> tuple[list[InfoItem], list[InfoItem]]:
        """Split into interest-matching and diverse items."""
        domain_set = set(user_domains)
        interest: list[InfoItem] = []
        diverse: list[InfoItem] = []

        for item in items:
            meta = self._registry.get(item.source_id)
            if meta and meta.domain_tags and (set(meta.domain_tags) & domain_set):
                interest.append(item)
            else:
                diverse.append(item)

        return interest, diverse

    def _apply_layer_budgets(
        self,
        items: list[InfoItem],
        total: int,
    ) -> list[InfoItem]:
        """Select items respecting layer budget quotas.

        Within each layer, items retain their original order (score-sorted).
        Higher layers (L1) are preferred when budget slots are unfilled.
        """
        # Group items by layer
        by_layer: dict[str, list[InfoItem]] = {}
        for item in items:
            meta = self._registry.get(item.source_id)
            layer = meta.layer if meta else "L4"
            by_layer.setdefault(layer, []).append(item)

        selected: list[InfoItem] = []

        # First pass: fill each layer up to its budget
        layer_order = sorted(
            self._layer_budgets.keys(),
            key=lambda k: _LAYER_PRIORITY.get(k, 99),
        )
        leftover: list[InfoItem] = []

        for layer in layer_order:
            budget_pct = self._layer_budgets.get(layer, 0.0)
            budget_count = max(1, int(total * budget_pct))
            pool = by_layer.get(layer, [])
            take = pool[:budget_count]
            selected.extend(take)
            leftover.extend(pool[budget_count:])

        # If we haven't reached total, fill from leftover (prefer higher layers)
        if len(selected) < total:
            leftover.sort(
                key=lambda it: _LAYER_PRIORITY.get(
                    (
                        self._registry.get(it.source_id)
                        or type("X", (), {"layer": "L4"})
                    ).layer,
                    99,
                )
            )
            needed = total - len(selected)
            selected.extend(leftover[:needed])

        return selected[:total]

    @staticmethod
    def _interleave(
        interest: list[InfoItem],
        diverse: list[InfoItem],
    ) -> list[InfoItem]:
        """Interleave diverse items evenly into the interest list."""
        if not interest:
            return list(diverse)
        if not diverse:
            return list(interest)

        result: list[InfoItem] = []
        # Calculate spacing: insert one diverse item every N interest items
        spacing = max(1, len(interest) // (len(diverse) + 1))

        interest_idx = 0
        diverse_idx = 0

        while interest_idx < len(interest) or diverse_idx < len(diverse):
            # Add a chunk of interest items
            chunk_end = min(interest_idx + spacing, len(interest))
            result.extend(interest[interest_idx:chunk_end])
            interest_idx = chunk_end

            # Inject one diverse item
            if diverse_idx < len(diverse):
                result.append(diverse[diverse_idx])
                diverse_idx += 1

        return result

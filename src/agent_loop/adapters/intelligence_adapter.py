"""Intelligence adapter — wraps intelligence pipeline output (news, policy, events).

Produces SignalEvidence with independence_group=INTELLIGENCE.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent_loop.domain_adapter import (
    IndependenceGroup,
    SignalDirection,
    SignalEvidence,
)

logger = logging.getLogger(__name__)

# Map intelligence categories to signal types
_CATEGORY_TYPE_MAP: dict[str, str] = {
    "policy": "intel/policy",
    "event": "intel/event",
    "social": "intel/social_sentiment",
    "news": "intel/event",
    "breaking": "intel/event",
    "regulatory": "intel/policy",
    "sentiment": "intel/social_sentiment",
}

# Map sentiment strings to direction
_SENTIMENT_MAP: dict[str, SignalDirection] = {
    "positive": SignalDirection.BUY,
    "bullish": SignalDirection.BUY,
    "negative": SignalDirection.SELL,
    "bearish": SignalDirection.SELL,
    "neutral": SignalDirection.HOLD,
}


class IntelligenceAdapter:
    """Adapter that converts intelligence items to SignalEvidence.

    Accepts pre-processed intelligence items from InfoAggregator or
    intel_bridge output.
    """

    domain: str = "intelligence"

    def __init__(self, intel_items: list[dict[str, Any]] | None = None) -> None:
        """Pre-load intelligence items for batch conversion.

        Args:
            intel_items: Dicts with keys: symbol, category, sentiment,
                confidence, summary, affected_symbols (optional).
        """
        self._items = intel_items or []

    def collect_signals(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None = None,
    ) -> list[SignalEvidence]:
        """Convert intelligence items to SignalEvidence."""
        results: list[SignalEvidence] = []
        symbol_set = set(symbols)

        for item in self._items:
            # An intel item may affect multiple symbols
            affected = item.get("affected_symbols", [])
            if not affected:
                sym = item.get("symbol", "")
                affected = [sym] if sym else []

            category = item.get("category", "event").lower()
            signal_type = _CATEGORY_TYPE_MAP.get(category, "intel/event")
            sentiment = item.get("sentiment", "neutral").lower()
            direction = _SENTIMENT_MAP.get(sentiment, SignalDirection.HOLD)
            confidence = float(item.get("confidence", 0.5))

            if direction == SignalDirection.HOLD:
                continue

            for sym in affected:
                if symbol_set and sym not in symbol_set:
                    continue

                results.append(
                    SignalEvidence(
                        domain=self.domain,
                        signal_type=signal_type,
                        symbol=sym,
                        direction=direction,
                        confidence=min(1.0, max(0.0, confidence)),
                        independence_group=IndependenceGroup.INTELLIGENCE,
                        metadata={
                            "category": category,
                            "sentiment": sentiment,
                            "title": item.get("title", ""),
                        },
                        source_description=item.get("summary", ""),
                    )
                )

        logger.debug("IntelligenceAdapter produced %d signals", len(results))
        return results

    def get_signal_types(self) -> list[str]:
        """Return signal types this adapter produces."""
        return [
            "intel/policy",
            "intel/event",
            "intel/social_sentiment",
        ]

"""Leader detection adapter — wraps LeaderDetector output.

Produces SignalEvidence with independence_group=MARKET_STRUCTURE.
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


class LeaderAdapter:
    """Adapter that converts LeaderDetector results to SignalEvidence.

    Accepts pre-computed LeaderScore dicts (from LeaderDetector.rank()).
    A leader stock with high score is a BUY signal; low-scoring former
    leaders are not actionable (no SELL generated here).
    """

    domain: str = "leader_detection"

    def __init__(self, leader_scores: list[dict[str, Any]] | None = None) -> None:
        """Pre-load leader detection results.

        Args:
            leader_scores: Dicts with keys matching LeaderScore fields:
                symbol, name, sector, total_score, is_leader, reason,
                confidence_level, scores (breakdown dict).
        """
        self._scores = leader_scores or []

    def collect_signals(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None = None,
    ) -> list[SignalEvidence]:
        """Convert leader scores to SignalEvidence."""
        results: list[SignalEvidence] = []
        symbol_set = set(symbols)

        for score in self._scores:
            symbol = score.get("symbol", "")
            if symbol_set and symbol not in symbol_set:
                continue

            is_leader = score.get("is_leader", False)
            total_score = float(score.get("total_score", 0))

            if not is_leader or total_score < 70:
                continue

            # Map leader score (70-100) to confidence (0.6-1.0)
            confidence = min(1.0, 0.6 + (total_score - 70) / 75.0)

            # Determine signal type based on sector context
            sector = score.get("sector", "")
            signal_type = "leader/sector" if sector else "leader/primary"

            results.append(
                SignalEvidence(
                    domain=self.domain,
                    signal_type=signal_type,
                    symbol=symbol,
                    direction=SignalDirection.BUY,
                    confidence=confidence,
                    independence_group=IndependenceGroup.MARKET_STRUCTURE,
                    metadata={
                        "total_score": total_score,
                        "sector": sector,
                        "name": score.get("name", ""),
                        "scores_breakdown": score.get("scores", {}),
                        "confidence_level": score.get("confidence_level", ""),
                    },
                    source_description=score.get("reason", ""),
                )
            )

        logger.debug("LeaderAdapter produced %d signals", len(results))
        return results

    def get_signal_types(self) -> list[str]:
        """Return signal types this adapter produces."""
        return [
            "leader/primary",
            "leader/sector",
        ]

"""Convergence engine — enforces convergence-before-action invariant.

Groups SignalEvidence by (symbol, direction), checks that multiple
independence groups agree before allowing a BUY action. Sell signals
are exempt from convergence requirements for risk management.

Part of v50.0 Trading Agent OS — Signal Engine refactor.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from src.agent_loop.domain_adapter import (
    ConvergenceResult,
    IndependenceGroup,
    SignalDirection,
    SignalEvidence,
)

logger = logging.getLogger(__name__)


class ConvergenceEngine:
    """Enforces convergence-before-action invariant.

    System invariant: BUY signals require confirmation from at least
    :attr:`MIN_INDEPENDENT_GROUPS` independence groups. SELL signals
    pass without convergence (risk management takes priority).
    """

    MIN_INDEPENDENT_GROUPS: int = 2

    def analyze(self, signals: list[SignalEvidence]) -> list[ConvergenceResult]:
        """Group signals by (symbol, direction) and check convergence.

        Returns one :class:`ConvergenceResult` per unique (symbol, direction)
        pair that has at least one signal.
        """
        # Group by (symbol, direction)
        groups: dict[tuple[str, SignalDirection], list[SignalEvidence]] = defaultdict(
            list
        )
        for sig in signals:
            groups[(sig.symbol, sig.direction)].append(sig)

        results: list[ConvergenceResult] = []
        for (symbol, direction), group_signals in groups.items():
            independence_groups = {s.independence_group for s in group_signals}
            converged = len(independence_groups) >= self.MIN_INDEPENDENT_GROUPS
            convergence_score = self._compute_convergence_score(group_signals)

            result = ConvergenceResult(
                symbol=symbol,
                direction=direction,
                signals=group_signals,
                independence_groups=independence_groups,
                converged=converged,
                convergence_score=convergence_score,
            )
            results.append(result)

            logger.debug(
                "Convergence %s %s: %d signals, %d groups, converged=%s (score=%.3f)",
                direction.value,
                symbol,
                len(group_signals),
                len(independence_groups),
                converged,
                convergence_score,
            )

        # Sort by convergence score descending
        results.sort(key=lambda r: r.convergence_score, reverse=True)
        return results

    def _compute_convergence_score(self, signals: list[SignalEvidence]) -> float:
        """Compute convergence score based on diversity and strength.

        Score components:
        1. Base: ratio of unique independence groups to total possible groups
        2. Strength: average confidence across groups (one representative per group)
        3. Within-group: mild boost for multiple confirming signals in same group,
           using sqrt diminishing returns (independence correction)

        Returns a score in [0, 1].
        """
        if not signals:
            return 0.0

        # Group signals by independence group
        by_group: dict[IndependenceGroup, list[SignalEvidence]] = defaultdict(list)
        for sig in signals:
            by_group[sig.independence_group].append(sig)

        num_groups = len(by_group)
        total_possible = len(IndependenceGroup)

        # Diversity ratio: what fraction of all independence groups are present
        diversity = num_groups / total_possible

        # Per-group effective confidence: use highest confidence in each group,
        # with sqrt correction for additional signals (diminishing returns)
        group_scores: list[float] = []
        for _group, group_sigs in by_group.items():
            # Sort by confidence descending
            sorted_sigs = sorted(group_sigs, key=lambda s: s.confidence, reverse=True)
            best = sorted_sigs[0].confidence
            # Additional signals add diminishing value
            bonus = sum(math.sqrt(s.confidence) * 0.1 for s in sorted_sigs[1:])
            group_scores.append(min(1.0, best + bonus))

        avg_strength = sum(group_scores) / len(group_scores) if group_scores else 0.0

        # Final score: weighted combination
        # 60% diversity (most important — independent groups),
        # 40% average strength
        score = 0.6 * diversity + 0.4 * avg_strength
        return min(1.0, score)

    def filter_actionable(
        self, results: list[ConvergenceResult]
    ) -> list[ConvergenceResult]:
        """Return only actionable results.

        BUY signals must be converged. SELL signals always pass.
        HOLD signals are filtered out.
        """
        actionable: list[ConvergenceResult] = []
        for r in results:
            if r.direction == SignalDirection.HOLD:
                continue
            if r.direction == SignalDirection.SELL:
                actionable.append(r)
            elif r.converged:
                actionable.append(r)
        return actionable

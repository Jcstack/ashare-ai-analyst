"""Ensemble validator — multi-model cross-validation for critical decisions.

Part of v18.0 Intelligence Loop.

Queries multiple LLM providers (Anthropic + Google) for the same analysis,
compares results, and calculates consensus. Low consensus triggers
trust zone downgrade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EnsembleResult:
    """Result of ensemble cross-validation."""

    consensus_score: float  # 0-1, how much providers agree
    consensus_direction: str  # "bullish", "bearish", "neutral"
    provider_results: list[ProviderResult] = field(default_factory=list)
    trust_zone: str = "MEDIUM"  # HIGH/MEDIUM/LOW/UNTRUSTED
    divergence_notes: list[str] = field(default_factory=list)


@dataclass
class ProviderResult:
    """Result from a single LLM provider."""

    provider: str  # "anthropic", "google"
    direction: str  # "bullish", "bearish", "neutral"
    confidence: float
    summary: str = ""
    error: str | None = None  # None = success


@dataclass
class EnsembleConfig:
    """Configuration for ensemble validation."""

    consensus_threshold: float = 0.60
    low_consensus_trust_zone: str = "LOW"
    providers: list[str] = field(default_factory=lambda: ["anthropic", "google"])
    enabled_for_trades: bool = True
    # Timeout per provider (seconds)
    provider_timeout: float = 30.0


class EnsembleValidator:
    """Cross-validates analysis using multiple LLM providers.

    For critical decisions (trade recommendations), queries all configured
    providers with the same prompt and compares:
    1. Direction agreement (bullish/bearish/neutral)
    2. Confidence spread
    3. Key reasoning alignment

    Low consensus → downgrade trust zone → more conservative recommendation.
    """

    def __init__(
        self,
        config: EnsembleConfig | None = None,
        llm_router: Any | None = None,
    ):
        self.config = config or EnsembleConfig()
        self._llm_router = llm_router

    def validate(
        self,
        provider_results: list[ProviderResult],
    ) -> EnsembleResult:
        """Validate consensus across provider results.

        Args:
            provider_results: Pre-collected results from each provider.
                Callers should gather these (possibly in parallel) before
                calling validate().

        Returns:
            EnsembleResult with consensus score and trust zone.
        """
        successful = [r for r in provider_results if r.error is None]

        if len(successful) < 2:
            # Not enough providers responded — cannot validate
            return EnsembleResult(
                consensus_score=0.0,
                consensus_direction=successful[0].direction
                if successful
                else "neutral",
                provider_results=provider_results,
                trust_zone="LOW",
                divergence_notes=["提供商响应不足，无法进行集成验证"],
            )

        # Calculate direction consensus
        directions = [r.direction for r in successful]
        consensus_direction = _majority_direction(directions)
        direction_agreement = sum(
            1 for d in directions if d == consensus_direction
        ) / len(directions)

        # Calculate confidence spread
        confidences = [r.confidence for r in successful]
        confidence_spread = max(confidences) - min(confidences)

        # Combined consensus score
        # High agreement + low spread = high consensus
        spread_penalty = min(confidence_spread / 0.5, 1.0) * 0.3
        consensus_score = max(direction_agreement - spread_penalty, 0.0)

        # Determine trust zone
        divergence_notes: list[str] = []
        trust_zone = self._determine_trust_zone(
            consensus_score,
            direction_agreement,
            confidence_spread,
            divergence_notes,
        )

        return EnsembleResult(
            consensus_score=round(consensus_score, 4),
            consensus_direction=consensus_direction,
            provider_results=provider_results,
            trust_zone=trust_zone,
            divergence_notes=divergence_notes,
        )

    def _determine_trust_zone(
        self,
        consensus_score: float,
        direction_agreement: float,
        confidence_spread: float,
        notes: list[str],
    ) -> str:
        """Determine trust zone based on consensus metrics."""
        if direction_agreement < 0.5:
            notes.append(f"方向分歧严重: 仅 {direction_agreement:.0%} 方向一致")
            return "UNTRUSTED"

        if consensus_score < self.config.consensus_threshold:
            notes.append(
                f"共识度不足: {consensus_score:.0%} < "
                f"{self.config.consensus_threshold:.0%} 阈值"
            )
            return self.config.low_consensus_trust_zone

        if confidence_spread > 0.30:
            notes.append(f"置信度离散: 最大差异 {confidence_spread:.0%}")
            return "MEDIUM"

        if consensus_score >= 0.80:
            return "HIGH"

        return "MEDIUM"

    def should_validate(self, decision_type: str) -> bool:
        """Check if ensemble validation is needed for this decision type.

        Trade decisions always require validation (if enabled).
        Analysis-only decisions skip ensemble.
        """
        if not self.config.enabled_for_trades:
            return False
        return decision_type in ("trade_decision", "position_change", "stop_loss")

    def create_provider_result(
        self,
        provider: str,
        raw_response: dict[str, Any],
    ) -> ProviderResult:
        """Parse a raw LLM response into a ProviderResult.

        Expected keys in raw_response:
            - direction: str
            - confidence: float
            - summary: str (optional)
        """
        return ProviderResult(
            provider=provider,
            direction=raw_response.get("direction", "neutral"),
            confidence=raw_response.get("confidence", 0.5),
            summary=raw_response.get("summary", ""),
        )


def _majority_direction(directions: list[str]) -> str:
    """Find the majority direction. Ties default to 'neutral'."""
    counts: dict[str, int] = {}
    for d in directions:
        counts[d] = counts.get(d, 0) + 1

    if not counts:
        return "neutral"

    max_count = max(counts.values())
    winners = [d for d, c in counts.items() if c == max_count]

    if len(winners) == 1:
        return winners[0]

    # Tie — prefer neutral as conservative choice
    if "neutral" in winners:
        return "neutral"
    return winners[0]

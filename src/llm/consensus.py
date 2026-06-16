"""Multi-LLM consensus analysis for stock predictions.

Collects predictions from multiple providers and produces a weighted
consensus result with agreement scoring.
"""

from dataclasses import dataclass, field
from typing import Any

from src.llm.base import (
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    ProviderName,
)
from src.utils.logger import get_logger

logger = get_logger("llm.consensus")

# Default provider weights for consensus voting
_DEFAULT_WEIGHTS: dict[str, float] = {
    "anthropic": 0.4,
    "openai": 0.35,
    "google": 0.25,
}


@dataclass
class IndividualResult:
    """Result from a single provider in consensus analysis.

    Attributes:
        provider: Provider that produced this result.
        model: Model used.
        trend: Predicted trend (bullish/bearish/neutral).
        signal: Trading signal (buy/sell/hold).
        confidence: Confidence score (0-1).
        cost_usd: Cost of this call.
        latency_ms: Latency of this call.
        raw_response: Full response object.
    """

    provider: ProviderName
    model: str
    trend: str = ""
    signal: str = ""
    confidence: float = 0.0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    raw_response: LLMResponse | None = None


@dataclass
class ConsensusResult:
    """Aggregated consensus from multiple LLM providers.

    Attributes:
        consensus_trend: Weighted consensus trend.
        consensus_signal: Weighted consensus signal.
        consensus_confidence: Average weighted confidence.
        agreement_score: Agreement level (0.0 to 1.0).
        individual_results: Per-provider results.
        total_cost: Combined cost across all providers.
    """

    consensus_trend: str
    consensus_signal: str
    consensus_confidence: float
    agreement_score: float
    individual_results: list[IndividualResult] = field(default_factory=list)
    total_cost: float = 0.0


class ConsensusAnalyzer:
    """Analyzes stock data using multiple LLM providers and combines results.

    Executes analysis sequentially across providers and uses weighted
    voting to determine consensus trend and signal.

    Args:
        providers: Dict mapping provider names to their instances.
        weights: Dict mapping provider name strings to vote weights.
        parse_fn: Callable to parse raw LLM text into prediction dict.
    """

    def __init__(
        self,
        providers: dict[ProviderName, Any],
        weights: dict[str, float] | None = None,
        parse_fn: Any = None,
    ) -> None:
        self._providers = providers
        self._weights = weights or _DEFAULT_WEIGHTS
        self._parse_fn = parse_fn

    def analyze_with_consensus(
        self,
        messages: list[LLMMessage],
        provider_names: list[ProviderName] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> ConsensusResult:
        """Run analysis across multiple providers and compute consensus.

        Args:
            messages: Provider-neutral chat messages.
            provider_names: Specific providers to use (defaults to all).
            max_tokens: Maximum output tokens per provider.
            temperature: Sampling temperature.

        Returns:
            ConsensusResult with weighted consensus and agreement score.
        """
        targets = provider_names or list(self._providers.keys())
        individual: list[IndividualResult] = []
        total_cost = 0.0

        for pname in targets:
            provider = self._providers.get(pname)
            if not provider:
                logger.warning(
                    "Provider %s not available for consensus",
                    pname.value,
                )
                continue

            try:
                response = provider.complete(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                result = self._parse_individual(pname, response)
                individual.append(result)
                total_cost += response.cost_usd
            except LLMProviderError as exc:
                logger.warning("Consensus: %s failed: %s", pname.value, exc)
            except Exception as exc:
                logger.warning(
                    "Consensus: unexpected error from %s: %s",
                    pname.value,
                    exc,
                )

        if not individual:
            return ConsensusResult(
                consensus_trend="unknown",
                consensus_signal="hold",
                consensus_confidence=0.0,
                agreement_score=0.0,
                total_cost=total_cost,
            )

        trend = self._weighted_vote_trend(individual)
        signal = self._weighted_vote_signal(individual)
        confidence = self._weighted_confidence(individual)
        agreement = self._calculate_agreement(individual)

        return ConsensusResult(
            consensus_trend=trend,
            consensus_signal=signal,
            consensus_confidence=confidence,
            agreement_score=agreement,
            individual_results=individual,
            total_cost=total_cost,
        )

    def _parse_individual(
        self, provider: ProviderName, response: LLMResponse
    ) -> IndividualResult:
        """Parse a single provider's response into IndividualResult.

        Args:
            provider: Provider that generated the response.
            response: Raw LLM response.

        Returns:
            Parsed IndividualResult.
        """
        result = IndividualResult(
            provider=provider,
            model=response.model,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            raw_response=response,
        )

        if self._parse_fn:
            try:
                parsed = self._parse_fn(response.text)
                result.trend = parsed.get("trend", "")
                result.signal = parsed.get("signal", "")
                result.confidence = parsed.get("confidence", 0.0)
            except Exception as exc:
                logger.warning(
                    "Failed to parse %s response: %s",
                    provider.value,
                    exc,
                )

        return result

    def _weighted_vote_trend(self, results: list[IndividualResult]) -> str:
        """Compute weighted consensus trend.

        Args:
            results: Individual provider results.

        Returns:
            Consensus trend string.
        """
        votes: dict[str, float] = {}
        for r in results:
            if not r.trend:
                continue
            weight = self._weights.get(r.provider.value, 0.25)
            votes[r.trend] = votes.get(r.trend, 0.0) + weight

        if not votes:
            return "unknown"
        return max(votes, key=votes.get)  # type: ignore[arg-type]

    def _weighted_vote_signal(self, results: list[IndividualResult]) -> str:
        """Compute weighted consensus signal.

        Args:
            results: Individual provider results.

        Returns:
            Consensus signal string.
        """
        votes: dict[str, float] = {}
        for r in results:
            if not r.signal:
                continue
            weight = self._weights.get(r.provider.value, 0.25)
            votes[r.signal] = votes.get(r.signal, 0.0) + weight

        if not votes:
            return "hold"
        return max(votes, key=votes.get)  # type: ignore[arg-type]

    def _weighted_confidence(self, results: list[IndividualResult]) -> float:
        """Compute weighted average confidence.

        Args:
            results: Individual provider results.

        Returns:
            Weighted average confidence (0-1).
        """
        total_weight = 0.0
        weighted_sum = 0.0
        for r in results:
            weight = self._weights.get(r.provider.value, 0.25)
            weighted_sum += r.confidence * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0
        return round(weighted_sum / total_weight, 4)

    def _calculate_agreement(self, results: list[IndividualResult]) -> float:
        """Calculate agreement score across providers.

        Returns:
            1.0 if all agree on trend + signal,
            0.5 if all agree on trend only,
            0.0 if no agreement.
        """
        if len(results) < 2:
            return 1.0

        trends = [r.trend for r in results if r.trend]
        signals = [r.signal for r in results if r.signal]

        trend_agree = len(set(trends)) == 1 if trends else False
        signal_agree = len(set(signals)) == 1 if signals else False

        if trend_agree and signal_agree:
            return 1.0
        if trend_agree:
            return 0.5
        return 0.0

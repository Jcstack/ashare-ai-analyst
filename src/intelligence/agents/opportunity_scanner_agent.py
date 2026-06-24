"""Opportunity Scanner Agent — identifies actionable trading opportunities.

Converts causal chains + scenarios + risk assessment into concrete
stock-level signals that feed into the existing SignalAggregator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.opportunity_scanner")


@dataclass
class IntelligenceSignal:
    """A trading signal derived from global intelligence."""

    stock_code: str
    stock_name: str
    direction: str  # "long" | "short" | "avoid"
    strength: float  # 0-1
    source_event: str
    causal_path: str  # brief description of cause -> effect
    scenario: str  # which scenario supports this
    time_horizon: str
    confidence: float
    risk_factors: list[str]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class OpportunityScannerAgent:
    """Strategist team: converts intelligence into actionable signals."""

    def __init__(
        self,
        event_bus: Any | None = None,
        llm_router: Any | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._llm_router = llm_router

    async def scan_opportunities(
        self,
        event: dict[str, Any],
        causal_chains: list[dict[str, Any]],
        scenarios: dict[str, Any] | None = None,
        risk: dict[str, Any] | None = None,
    ) -> list[IntelligenceSignal]:
        """Extract actionable signals from intelligence analysis.

        Args:
            event: EventUnderstanding dict.
            causal_chains: List of causal chain dicts.
            scenarios: Optional ScenarioSet dict (from ScenarioPlannerAgent).
            risk: Optional CompoundRisk dict (from CrossEventRiskAgent).

        Returns:
            List of IntelligenceSignal, deduplicated by stock code.
        """
        signals: list[IntelligenceSignal] = []

        # Skip if compound risk is critical
        if risk and risk.get("risk_level") == "critical":
            logger.info("Skipping opportunity scan — compound risk is critical")
            return signals

        # Extract stock signals from causal chains
        for chain in causal_chains:
            paths = chain.get("paths", [])
            for path in paths:
                stocks = path.get("affected_stocks", [])
                direction = "long" if path.get("direction") == "positive" else "short"
                strength = {"strong": 0.8, "moderate": 0.6, "weak": 0.4}.get(
                    path.get("magnitude", "weak"), 0.4
                )

                # Adjust strength based on scenario probability
                if scenarios:
                    bull_prob = 0.33
                    for s in scenarios.get("scenarios", []):
                        if s.get("name") == "bull":
                            bull_prob = s.get("probability", 0.33)
                    if direction == "long":
                        # Boost if bull scenario is likely
                        strength *= 0.5 + bull_prob

                # Adjust strength based on risk
                if risk:
                    risk_score = risk.get("risk_score", 0)
                    # Dampen by risk
                    strength *= 1.0 - risk_score * 0.5

                for stock_code in stocks:
                    if not self._validate_stock_code(stock_code):
                        continue
                    signal = IntelligenceSignal(
                        stock_code=stock_code,
                        stock_name="",  # filled by downstream
                        direction=direction,
                        strength=round(min(strength, 1.0), 3),
                        source_event=event.get("one_line_summary", ""),
                        causal_path=(
                            f"{path.get('cause', '')} -> {path.get('effect', '')}"
                        ),
                        scenario=(
                            scenarios.get("recommended_action", "") if scenarios else ""
                        ),
                        time_horizon=path.get("lag", "1-3d"),
                        confidence=float(chain.get("confidence", 0.5)),
                        risk_factors=([risk.get("alert_message", "")] if risk else []),
                    )
                    signals.append(signal)

        # Deduplicate by stock code, keep highest strength
        seen: dict[str, IntelligenceSignal] = {}
        for sig in signals:
            existing = seen.get(sig.stock_code)
            if not existing or sig.strength > existing.strength:
                seen[sig.stock_code] = sig
        signals = list(seen.values())

        # Publish signals to event bus
        if self._event_bus:
            for sig in signals:
                if sig.strength >= 0.5:  # only publish meaningful signals
                    await self._event_bus.publish(
                        "strategist:signal",
                        {
                            "stock_code": sig.stock_code,
                            "direction": sig.direction,
                            "strength": sig.strength,
                            "source_event": sig.source_event,
                            "causal_path": sig.causal_path,
                            "time_horizon": sig.time_horizon,
                            "confidence": sig.confidence,
                        },
                    )

        logger.info(
            "Scanned %d opportunities from event: %s",
            len(signals),
            event.get("one_line_summary", "")[:60],
        )
        return signals

    @staticmethod
    def _validate_stock_code(code: str) -> bool:
        """Validate A-share stock code format (6 digits)."""
        if not isinstance(code, str):
            return False
        code = code.strip()
        return len(code) == 6 and code.isdigit()


@lru_cache(maxsize=1)
def get_opportunity_scanner_agent() -> OpportunityScannerAgent:
    """Singleton factory for OpportunityScannerAgent."""
    from src.intelligence.event_bus import get_event_bus
    from src.web.dependencies import get_llm_router

    return OpportunityScannerAgent(
        event_bus=get_event_bus(), llm_router=get_llm_router()
    )

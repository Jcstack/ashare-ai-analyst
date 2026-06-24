"""Scenario Planner Agent — generates probability-weighted market scenarios.

Uses causal chains + event state + historical analogies to build
bull/base/bear scenarios with probability estimates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.scenario_planner")


@dataclass
class Scenario:
    """A single scenario (bull/base/bear) with probability and impact."""

    name: str  # "bull" | "base" | "bear"
    probability: float  # 0-1
    description: str
    trigger_conditions: list[str]
    affected_sectors: list[str]
    sector_direction: dict[str, str]  # sector -> "positive" | "negative"
    time_horizon: str  # "1-3d" | "1-2w" | "1-3m"
    confidence: float


@dataclass
class ScenarioSet:
    """A complete set of bull/base/bear scenarios for an event."""

    event_summary: str
    scenarios: list[Scenario]
    recommended_action: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ScenarioPlannerAgent:
    """Strategist team: generates bull/base/bear scenarios for events."""

    LLM_SYSTEM_PROMPT = (
        "You are a quantitative strategy analyst. Generate scenario analysis based on "
        "events and causal chains. Output strict JSON. All text values must be in Chinese."
    )

    def __init__(
        self,
        event_bus: Any | None = None,
        llm_router: Any | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._llm_router = llm_router

    async def plan_scenarios(
        self,
        event: dict[str, Any],
        causal_chains: list[dict[str, Any]],
        analogies: list[dict[str, Any]] | None = None,
    ) -> ScenarioSet | None:
        """Generate scenario set for an understood event.

        Args:
            event: EventUnderstanding dict (must contain one_line_summary).
            causal_chains: List of causal chain dicts from CausalChainAgent.
            analogies: Optional list of historical analogy dicts.

        Returns:
            ScenarioSet or None if event is irrelevant or LLM call fails.
        """
        if event.get("a_share_relevance", 0) < 0.3:
            return None

        prompt = self._build_prompt(event, causal_chains, analogies or [])
        try:
            response = self._llm_router.generate(
                model="deepseek-chat",
                system=self.LLM_SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=1500,
            )
            parsed = json.loads(response) if isinstance(response, str) else response
            scenario_set = self._parse_scenarios(event, parsed)

            # Publish to event bus
            if self._event_bus:
                await self._event_bus.publish(
                    "strategist:scenario",
                    {
                        "event_summary": scenario_set.event_summary,
                        "scenarios": [
                            {
                                "name": s.name,
                                "probability": s.probability,
                                "description": s.description,
                                "affected_sectors": s.affected_sectors,
                                "time_horizon": s.time_horizon,
                            }
                            for s in scenario_set.scenarios
                        ],
                        "recommended_action": scenario_set.recommended_action,
                    },
                )
            return scenario_set
        except Exception as exc:
            logger.warning("Scenario planning failed: %s", exc)
            return None

    def _build_prompt(
        self,
        event: dict[str, Any],
        chains: list[dict[str, Any]],
        analogies: list[dict[str, Any]],
    ) -> str:
        """Build the LLM prompt from event + chains + analogies."""
        analogy_text = ""
        if analogies:
            analogy_text = "\n历史类比:\n" + "\n".join(
                f"- {a.get('historical_event', 'N/A')}: "
                f"{a.get('predicted_pattern', '')}"
                for a in analogies[:3]
            )

        chain_text = ""
        if chains:
            path_lines: list[str] = []
            for chain in chains:
                for path in chain.get("paths", []):
                    cause = path.get("cause", "")
                    effect = path.get("effect", "")
                    direction = path.get("direction", "")
                    path_lines.append(f"- {cause} -> {effect} ({direction})")
            if path_lines:
                chain_text = "\n因果链:\n" + "\n".join(path_lines)

        return f"""Event: {event.get("one_line_summary", "")}
Type: {event.get("event_type", "")}
Certainty: {event.get("certainty", "N/A")}
Reversal risk: {event.get("reversal_risk", "N/A")}
Related sectors: {", ".join(event.get("key_sectors", []))}
{chain_text}
{analogy_text}

Generate three scenarios (bull/base/bear). Output JSON with all text values in Chinese:
{{
  "scenarios": [
    {{
      "name": "bull",
      "probability": 0.0-1.0,
      "description": "optimistic scenario description in Chinese",
      "trigger_conditions": ["trigger condition 1 in Chinese", "trigger condition 2 in Chinese"],
      "affected_sectors": ["sector in Chinese"],
      "sector_direction": {{"sector in Chinese": "positive"}},
      "time_horizon": "1-3d|1-2w|1-3m",
      "confidence": 0.0-1.0
    }},
    ...
  ],
  "recommended_action": "one-line action advice in Chinese"
}}

Probabilities must sum to 1.0."""

    def _parse_scenarios(
        self, event: dict[str, Any], parsed: dict[str, Any]
    ) -> ScenarioSet:
        """Parse LLM JSON response into a ScenarioSet."""
        scenarios: list[Scenario] = []
        for s in parsed.get("scenarios", []):
            scenarios.append(
                Scenario(
                    name=s.get("name", "unknown"),
                    probability=float(s.get("probability", 0.33)),
                    description=s.get("description", ""),
                    trigger_conditions=s.get("trigger_conditions", []),
                    affected_sectors=s.get("affected_sectors", []),
                    sector_direction=s.get("sector_direction", {}),
                    time_horizon=s.get("time_horizon", "1-3d"),
                    confidence=float(s.get("confidence", 0.5)),
                )
            )

        # Normalize probabilities to sum to 1.0
        total = sum(s.probability for s in scenarios) or 1.0
        for s in scenarios:
            s.probability = round(s.probability / total, 2)

        return ScenarioSet(
            event_summary=event.get("one_line_summary", ""),
            scenarios=scenarios,
            recommended_action=parsed.get("recommended_action", "观望"),
        )


@lru_cache(maxsize=1)
def get_scenario_planner_agent() -> ScenarioPlannerAgent:
    """Singleton factory for ScenarioPlannerAgent."""
    from src.intelligence.event_bus import get_event_bus
    from src.web.dependencies import get_llm_router

    return ScenarioPlannerAgent(event_bus=get_event_bus(), llm_router=get_llm_router())

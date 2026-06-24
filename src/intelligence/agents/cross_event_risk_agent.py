"""Cross-Event Risk Assessor — detects compound risk from multiple simultaneous events.

When multiple negative events cluster, risk is multiplicative not additive.
Detects correlation spikes and tail-risk accumulation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.cross_event_risk")


@dataclass
class CompoundRisk:
    """Result of a cross-event compound risk assessment."""

    risk_level: str  # "low" | "medium" | "high" | "critical"
    risk_score: float  # 0-1
    contributing_events: list[str]
    correlation_clusters: list[list[str]]  # groups of correlated events
    systemic_risk: bool  # true if multiple domains affected
    recommended_hedge: str
    alert_message: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class CrossEventRiskAgent:
    """Strategist team: assesses compound risk from multiple events."""

    RISK_THRESHOLDS = {
        "low": 0.3,
        "medium": 0.5,
        "high": 0.7,
        "critical": 0.85,
    }

    LLM_SYSTEM_PROMPT = (
        "You are a risk management expert. Output strict JSON. "
        "All text values must be in Chinese."
    )

    def __init__(
        self,
        event_bus: Any | None = None,
        llm_router: Any | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._llm_router = llm_router
        self._recent_events: list[dict[str, Any]] = []  # sliding window

    async def assess_risk(
        self,
        new_event: dict[str, Any],
        recent_events: list[dict[str, Any]] | None = None,
    ) -> CompoundRisk:
        """Assess compound risk considering all recent events.

        Args:
            new_event: The latest event to incorporate.
            recent_events: Override for the internal sliding window.

        Returns:
            CompoundRisk assessment.
        """
        events = recent_events or self._recent_events

        # Add new event
        events.append(new_event)

        # Keep only last 24h
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        events = [
            e for e in events if e.get("created_at", "") > cutoff or e is new_event
        ]
        self._recent_events = events

        if len(events) < 2:
            return CompoundRisk(
                risk_level="low",
                risk_score=0.1,
                contributing_events=[new_event.get("one_line_summary", "")],
                correlation_clusters=[],
                systemic_risk=False,
                recommended_hedge="无需对冲",
                alert_message="",
            )

        # Cluster events by domain overlap
        clusters = self._cluster_events(events)

        # Calculate compound risk score
        risk_score = self._calculate_compound_risk(events, clusters)
        risk_level = "low"
        for level, threshold in sorted(
            self.RISK_THRESHOLDS.items(),
            key=lambda x: x[1],
            reverse=True,
        ):
            if risk_score >= threshold:
                risk_level = level
                break

        # Check for systemic risk (3+ domains affected)
        all_domains: set[str] = set()
        for e in events:
            all_domains.update(e.get("affected_domains", []))
        systemic = len(all_domains) >= 3

        contributing = [e.get("one_line_summary", "unknown") for e in events]

        # LLM assessment for high risk
        hedge_advice = "保持观望"
        alert_msg = ""
        if risk_level in ("high", "critical"):
            llm_result = await self._llm_risk_assessment(events, clusters, risk_score)
            hedge_advice = llm_result.get("recommended_hedge", hedge_advice)
            alert_msg = llm_result.get("alert_message", "")

        risk = CompoundRisk(
            risk_level=risk_level,
            risk_score=round(risk_score, 3),
            contributing_events=contributing,
            correlation_clusters=[
                [e.get("one_line_summary", "") for e in c] for c in clusters
            ],
            systemic_risk=systemic,
            recommended_hedge=hedge_advice,
            alert_message=alert_msg,
        )

        # Publish if medium+
        if risk_score >= self.RISK_THRESHOLDS["medium"] and self._event_bus:
            await self._event_bus.publish(
                "strategist:risk_alert",
                {
                    "risk_level": risk_level,
                    "risk_score": risk_score,
                    "contributing_events": contributing,
                    "systemic_risk": systemic,
                    "recommended_hedge": hedge_advice,
                    "alert_message": alert_msg,
                },
            )
            logger.warning(
                "Compound risk alert: %s (%.2f) — %d events",
                risk_level,
                risk_score,
                len(events),
            )

        return risk

    def _cluster_events(
        self, events: list[dict[str, Any]]
    ) -> list[list[dict[str, Any]]]:
        """Cluster events by domain/sector overlap."""
        clusters: list[list[dict[str, Any]]] = []
        assigned: set[int] = set()

        for i, e1 in enumerate(events):
            if i in assigned:
                continue
            cluster = [e1]
            assigned.add(i)
            d1 = set(e1.get("affected_domains", []))
            s1 = set(e1.get("key_sectors", []))

            for j, e2 in enumerate(events):
                if j in assigned:
                    continue
                d2 = set(e2.get("affected_domains", []))
                s2 = set(e2.get("key_sectors", []))
                if (d1 & d2) or (s1 & s2):
                    cluster.append(e2)
                    assigned.add(j)

            if len(cluster) > 1:
                clusters.append(cluster)

        return clusters

    def _calculate_compound_risk(
        self,
        events: list[dict[str, Any]],
        clusters: list[list[dict[str, Any]]],
    ) -> float:
        """Compound risk: more concurrent negative events = exponentially higher risk."""
        negative_events = [e for e in events if e.get("sentiment") == "negative"]
        base_risk = min(len(negative_events) * 0.15, 0.6)

        # Cluster amplification (correlated events amplify risk)
        cluster_amp = sum(len(c) * 0.1 for c in clusters)

        # High-certainty events weigh more
        certainty_factor = sum(e.get("certainty", 0.5) for e in negative_events) / max(
            len(negative_events), 1
        )

        # Reversal risk amplification
        high_reversal = sum(1 for e in events if e.get("reversal_risk") == "high")
        reversal_amp = high_reversal * 0.05

        return min(base_risk + cluster_amp + reversal_amp * certainty_factor, 1.0)

    async def _llm_risk_assessment(
        self,
        events: list[dict[str, Any]],
        clusters: list[list[dict[str, Any]]],
        risk_score: float,
    ) -> dict[str, Any]:
        """Use LLM to generate hedge advice for high/critical risk."""
        if not self._llm_router:
            return {
                "recommended_hedge": "减仓观望",
                "alert_message": f"多事件复合风险 ({risk_score:.0%})",
            }

        events_text = "\n".join(f"- {e.get('one_line_summary', '')}" for e in events)
        prompt = f"""当前有{len(events)}个同时发生的事件，综合风险分数 {risk_score:.2f}：

{events_text}

请评估复合风险并给出对冲建议，输出 JSON：
{{
  "recommended_hedge": "具体的风险对冲建议",
  "alert_message": "50字以内的风险警报消息"
}}"""

        try:
            resp = self._llm_router.generate(
                model="deepseek-chat",
                system=self.LLM_SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=300,
            )
            return json.loads(resp) if isinstance(resp, str) else resp
        except Exception as exc:
            logger.warning("LLM risk assessment failed: %s", exc)
            return {
                "recommended_hedge": "减仓观望",
                "alert_message": f"多事件复合风险 ({risk_score:.0%})",
            }


@lru_cache(maxsize=1)
def get_cross_event_risk_agent() -> CrossEventRiskAgent:
    """Singleton factory for CrossEventRiskAgent."""
    from src.intelligence.event_bus import get_event_bus
    from src.web.dependencies import get_llm_router

    return CrossEventRiskAgent(event_bus=get_event_bus(), llm_router=get_llm_router())

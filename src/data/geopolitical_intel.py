"""Geopolitical intelligence triangulation pipeline.

Correlates signals from GDELT, Polymarket, GPR index, ACLED, and keyword
monitoring into a single GeopoliticalRiskAssessment. This is our free
approximation of institutional tools like BlackRock BGRI or Dataminr.

Does NOT fetch data itself — it correlates signals from existing fetchers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("data.geopolitical_intel")

__all__ = ["GeopoliticalRiskAssessment", "GeopoliticalIntelPipeline"]

_CACHE_TTL = 900  # 15 minutes


@dataclass
class RegionRisk:
    """Risk assessment for a specific region."""

    region: str
    risk_score: float  # 0-1
    events_count: int
    fatalities: int
    tone: float  # GDELT tone, negative = bad
    key_event: str  # one-line summary


@dataclass
class GeopoliticalRiskAssessment:
    """Composite geopolitical risk assessment from multiple sources."""

    overall_risk_score: float  # 0-1
    risk_level: str  # low|moderate|elevated|high|extreme
    regions: dict[str, RegionRisk] = field(default_factory=dict)
    key_events: list[str] = field(default_factory=list)  # top 5, one-line
    market_channels: list[str] = field(default_factory=list)  # transmission paths
    sources_used: int = 0
    confidence: float = 0.0  # 0-1, based on source agreement

    def to_snapshot_text(self) -> str:
        """Format for serialize_for_llm."""
        parts = [f"风险: {self.overall_risk_score:.2f} ({self.risk_level})"]
        if self.key_events:
            parts.append("关键事件: " + "; ".join(self.key_events[:3]))
        if self.market_channels:
            parts.append("传导: " + ", ".join(self.market_channels[:4]))
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_score": self.overall_risk_score,
            "risk_level": self.risk_level,
            "key_events": self.key_events,
            "market_channels": self.market_channels,
            "sources_used": self.sources_used,
            "confidence": self.confidence,
        }


def _classify_risk_level(score: float) -> str:
    if score >= 0.8:
        return "extreme"
    if score >= 0.6:
        return "high"
    if score >= 0.4:
        return "elevated"
    if score >= 0.2:
        return "moderate"
    return "low"


class GeopoliticalIntelPipeline:
    """Triangulate geopolitical risk from multiple sources.

    Usage::

        pipeline = GeopoliticalIntelPipeline(
            gdelt_fetcher=..., polymarket_fetcher=...,
            gpr_fetcher=..., acled_fetcher=...,
        )
        assessment = await pipeline.assess()
    """

    def __init__(
        self,
        gdelt_fetcher: Any | None = None,
        polymarket_fetcher: Any | None = None,
        gpr_fetcher: Any | None = None,
        acled_fetcher: Any | None = None,
    ) -> None:
        self._gdelt = gdelt_fetcher
        self._polymarket = polymarket_fetcher
        self._gpr = gpr_fetcher
        self._acled = acled_fetcher
        self._cache: dict[str, tuple[float, Any]] = {}

    def _get_cache(self, key: str) -> Any | None:
        if key in self._cache:
            expire_ts, val = self._cache[key]
            if time.time() < expire_ts:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time() + _CACHE_TTL, val)

    async def assess(self) -> GeopoliticalRiskAssessment:
        """Run full geopolitical risk assessment.

        Gathers data from all available sources in parallel,
        then computes a composite risk score.
        """
        cached = self._get_cache("assessment")
        if cached is not None:
            return cached

        # Gather all signals in parallel
        gdelt_score, gdelt_events, gdelt_key = await self._assess_gdelt()
        poly_score, poly_events = await self._assess_polymarket()
        gpr_score, gpr_key = await self._assess_gpr()
        acled_score, acled_events, acled_channels = await self._assess_acled()

        # Compute composite score (weighted average of available sources)
        scores: list[tuple[float, float]] = []  # (score, weight)
        sources_used = 0
        key_events: list[str] = []
        channels: list[str] = []

        if gdelt_score is not None:
            scores.append((gdelt_score, 0.30))
            sources_used += 1
            key_events.extend(gdelt_key)

        if poly_score is not None:
            scores.append((poly_score, 0.25))
            sources_used += 1
            key_events.extend(poly_events)

        if gpr_score is not None:
            scores.append((gpr_score, 0.25))
            sources_used += 1
            if gpr_key:
                key_events.append(gpr_key)

        if acled_score is not None:
            scores.append((acled_score, 0.20))
            sources_used += 1
            key_events.extend(acled_events)
            channels.extend(acled_channels)

        if not scores:
            return GeopoliticalRiskAssessment(
                overall_risk_score=0.0,
                risk_level="low",
                sources_used=0,
                confidence=0.0,
            )

        # Normalize weights to sum to 1
        total_weight = sum(w for _, w in scores)
        composite = sum(s * w for s, w in scores) / total_weight

        # Confidence based on source agreement (std dev)
        if len(scores) > 1:
            mean = sum(s for s, _ in scores) / len(scores)
            variance = sum((s - mean) ** 2 for s, _ in scores) / len(scores)
            std_dev = variance**0.5
            confidence = max(0.0, 1.0 - std_dev)
        else:
            confidence = 0.5

        # Add default market channels
        if composite > 0.4 and not channels:
            channels = ["避险→黄金股", "油价→成本→化工板块"]

        result = GeopoliticalRiskAssessment(
            overall_risk_score=round(composite, 3),
            risk_level=_classify_risk_level(composite),
            key_events=key_events[:5],
            market_channels=channels[:4],
            sources_used=sources_used,
            confidence=round(confidence, 2),
        )

        self._set_cache("assessment", result)
        logger.info(
            "Geopolitical assessment: score=%.3f level=%s sources=%d confidence=%.2f",
            result.overall_risk_score,
            result.risk_level,
            result.sources_used,
            result.confidence,
        )
        return result

    # -- Per-source assessors -------------------------------------------------

    async def _assess_gdelt(
        self,
    ) -> tuple[float | None, list[str], list[str]]:
        """Assess risk from GDELT tone data."""
        if self._gdelt is None:
            return None, [], []
        try:
            summaries = await self._gdelt.fetch_china_relevant()
            geo_summary = summaries.get("geopolitical")
            risk_summary = summaries.get("global_risk")

            if not geo_summary and not risk_summary:
                return None, [], []

            # Convert tone to risk score (more negative = higher risk)
            tones = []
            if geo_summary:
                tones.append(geo_summary.avg_tone)
            if risk_summary:
                tones.append(risk_summary.avg_tone)

            avg_tone = sum(tones) / len(tones)
            # Map tone (-10 to +10) to risk (0 to 1): tone -5 → risk 0.75
            risk_score = max(0.0, min(1.0, 0.5 - avg_tone / 10))

            key_events = []
            if geo_summary and geo_summary.most_negative_title:
                key_events.append(geo_summary.most_negative_title[:80])

            return risk_score, key_events, []
        except Exception as exc:
            logger.debug("GDELT assessment failed: %s", exc)
            return None, [], []

    async def _assess_polymarket(self) -> tuple[float | None, list[str]]:
        """Assess risk from Polymarket prediction probabilities."""
        if self._polymarket is None:
            return None, []
        try:
            signals = await self._polymarket.get_geopolitical_signals()
            if signals is None:
                return None, []

            # Extract risk probabilities
            events = []
            risk_scores = []

            for signal in getattr(signals, "signals", []):
                prob = getattr(signal, "probability", 0)
                title = getattr(signal, "title", "")
                if prob > 0.3:
                    events.append(f"{title}: {prob:.0%}")
                # Higher probability of negative events = higher risk
                if any(
                    kw in title.lower()
                    for kw in ("conflict", "war", "crisis", "recession", "invasion")
                ):
                    risk_scores.append(prob)

            if not risk_scores:
                return 0.2, events[:2]

            return max(risk_scores), events[:2]
        except Exception as exc:
            logger.debug("Polymarket assessment failed: %s", exc)
            return None, []

    async def _assess_gpr(self) -> tuple[float | None, str]:
        """Assess risk from GPR index."""
        if self._gpr is None:
            return None, ""
        try:
            reading = await self._gpr.fetch_latest()
            if reading is None:
                return None, ""

            # Map percentile to risk score
            risk_score = reading.percentile / 100.0

            key = ""
            if reading.percentile > 80:
                key = f"GPR指数: {reading.gpr_index:.0f} ({reading.percentile:.0f}分位, {reading.trend})"

            return risk_score, key
        except Exception as exc:
            logger.debug("GPR assessment failed: %s", exc)
            return None, ""

    async def _assess_acled(
        self,
    ) -> tuple[float | None, list[str], list[str]]:
        """Assess risk from ACLED conflict data."""
        if self._acled is None:
            return None, [], []
        try:
            events = await self._acled.fetch_recent(days=7)
            if not events:
                return None, [], []

            summary = self._acled.get_conflict_summary(events)

            # More events + more fatalities = higher risk
            event_count = summary["total_events"]
            fatalities = summary["total_fatalities"]

            # Normalize: 100+ events/week in strategic areas is high
            strategic_events = [e for e in events if e.market_relevance != "none"]
            strategic_ratio = len(strategic_events) / max(len(events), 1)

            risk_score = min(
                1.0,
                (event_count / 200) * 0.3
                + (fatalities / 500) * 0.3
                + strategic_ratio * 0.4,
            )

            key_events = []
            # Find most severe events
            high_fatality = sorted(events, key=lambda e: e.fatalities, reverse=True)
            for e in high_fatality[:2]:
                if e.fatalities > 0:
                    key_events.append(
                        f"{e.country}: {e.event_type} ({e.fatalities}人死亡)"
                    )

            channels = list(summary.get("market_channels", {}).keys())

            return risk_score, key_events, channels
        except Exception as exc:
            logger.debug("ACLED assessment failed: %s", exc)
            return None, [], []

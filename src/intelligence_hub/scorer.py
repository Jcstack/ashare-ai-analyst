"""Content scorer — computes ContentScore [0-100] per InfoItem.

Part of v23.0 Multi-Source Intelligence Aggregation.

Formula (v23.0 Phase 2 — with cross-verification):
  ContentScore =
    SourceWeight         x 45  (effective_weight from registry)
  + TimelinessScore      x 20  (decay: 1h->1.0, 6h->0.8, 24h->0.5, 72h->0.2, >72h->0.05)
  + CrossVerification    x 15  (from event clustering: 1 src=0.0, 2=0.3, 3=0.6, 4+=1.0)
  + DomainRelevance      x 10  (1.0 if matches user domains, 0.2 otherwise)
  + QualitySignals       x 10  (has summary +0.4, has URL +0.3, has symbols +0.3)
  - NoisePenalty         x 20  (short title, no content, low-engagement social)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.source_registry import SourceRegistry

logger = logging.getLogger(__name__)

# Default timeliness buckets (hours, factor)
_DEFAULT_TIMELINESS = [
    (1, 1.0),
    (6, 0.8),
    (24, 0.5),
    (72, 0.2),
    (999999, 0.05),
]

# Default weights (Phase 2: timeliness 25→20, +cross_verification 15)
_DEFAULT_WEIGHTS = {
    "source_weight": 45,
    "timeliness": 20,
    "cross_verification": 15,
    "domain_relevance": 10,
    "quality_signals": 10,
    "noise_penalty": 20,
}


@dataclass
class ScoreResult:
    """Score output with explanation payload."""

    score: float
    explain: dict[str, Any] = field(default_factory=dict)


class ContentScorer:
    """Scores InfoItems based on source quality, timeliness, relevance, and noise."""

    def __init__(
        self,
        registry: SourceRegistry,
        scoring_config: dict[str, Any] | None = None,
    ) -> None:
        self._registry = registry
        cfg = scoring_config or {}
        self._weights = cfg.get("weights", _DEFAULT_WEIGHTS)
        self._timeliness_buckets = self._parse_timeliness(cfg)
        quality = cfg.get("quality_bonuses", {})
        self._q_summary = quality.get("has_summary", 0.4)
        self._q_url = quality.get("has_url", 0.3)
        self._q_symbols = quality.get("has_symbols", 0.3)
        noise = cfg.get("noise_thresholds", {})
        self._min_title_len = noise.get("min_title_length", 10)
        self._social_min_score = noise.get("social_min_score", 5)

    @staticmethod
    def _parse_timeliness(cfg: dict[str, Any]) -> list[tuple[float, float]]:
        buckets = cfg.get("timeliness_buckets")
        if not buckets:
            return _DEFAULT_TIMELINESS
        return [(b["max_hours"], b["factor"]) for b in buckets]

    def score(
        self,
        item: InfoItem,
        user_domains: list[str] | None = None,
        cross_verification_map: dict[str, float] | None = None,
    ) -> ScoreResult:
        explain: dict[str, Any] = {}

        # 1. Source weight component
        w_source = self._weights.get("source_weight", 45)
        meta = self._registry.get(item.source_id)
        ew = meta.effective_weight if meta else 0.5
        source_pts = ew * w_source
        explain["source_weight"] = {
            "effective_weight": ew,
            "points": round(source_pts, 2),
        }

        # 2. Timeliness component
        w_time = self._weights.get("timeliness", 20)
        age_hours = self._compute_age_hours(item)
        timeliness_factor = self._timeliness_factor(age_hours)
        timeliness_pts = timeliness_factor * w_time
        explain["timeliness"] = {
            "age_hours": round(age_hours, 1),
            "factor": timeliness_factor,
            "points": round(timeliness_pts, 2),
        }

        # 3. Cross-verification component (Phase 2)
        w_cv = self._weights.get("cross_verification", 15)
        cv_factor = 0.0
        if cross_verification_map and item.item_id in cross_verification_map:
            cv_factor = cross_verification_map[item.item_id]
        cv_pts = cv_factor * w_cv
        explain["cross_verification"] = {
            "factor": cv_factor,
            "points": round(cv_pts, 2),
        }

        # 4. Domain relevance component
        w_domain = self._weights.get("domain_relevance", 10)
        domain_factor = self._domain_relevance(item, user_domains)
        domain_pts = domain_factor * w_domain
        explain["domain_relevance"] = {
            "factor": domain_factor,
            "points": round(domain_pts, 2),
        }

        # 5. Quality signals component
        w_quality = self._weights.get("quality_signals", 10)
        quality_factor = self._quality_factor(item)
        quality_pts = quality_factor * w_quality
        explain["quality_signals"] = {
            "factor": round(quality_factor, 2),
            "points": round(quality_pts, 2),
        }

        # 6. Noise penalty component
        w_noise = self._weights.get("noise_penalty", 20)
        noise_factor = self._noise_factor(item)
        noise_pts = noise_factor * w_noise
        explain["noise_penalty"] = {
            "factor": round(noise_factor, 2),
            "points": round(noise_pts, 2),
        }

        raw = (
            source_pts + timeliness_pts + cv_pts + domain_pts + quality_pts - noise_pts
        )
        final = max(0.0, min(100.0, raw))

        return ScoreResult(score=round(final, 1), explain=explain)

    def score_batch(
        self,
        items: list[InfoItem],
        user_domains: list[str] | None = None,
        cross_verification_map: dict[str, float] | None = None,
    ) -> list[ScoreResult]:
        return [
            self.score(item, user_domains, cross_verification_map) for item in items
        ]

    @staticmethod
    def _compute_age_hours(item: InfoItem) -> float:
        ref = item.published_at or item.fetched_at
        if not ref:
            return 999.0
        try:
            dt = datetime.strptime(ref, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            delta = datetime.now(UTC) - dt
            return max(0.0, delta.total_seconds() / 3600.0)
        except (ValueError, TypeError):
            return 999.0

    def _timeliness_factor(self, age_hours: float) -> float:
        for max_h, factor in self._timeliness_buckets:
            if age_hours <= max_h:
                return factor
        return 0.05

    def _domain_relevance(
        self,
        item: InfoItem,
        user_domains: list[str] | None,
    ) -> float:
        if not user_domains:
            return 0.5  # neutral when no user preference
        meta = self._registry.get(item.source_id)
        if meta and meta.domain_tags:
            overlap = set(meta.domain_tags) & set(user_domains)
            if overlap:
                return 1.0
        return 0.2

    def _quality_factor(self, item: InfoItem) -> float:
        score = 0.0
        if item.summary:
            score += self._q_summary
        if item.url:
            score += self._q_url
        if item.related_symbols:
            score += self._q_symbols
        return min(1.0, score)

    def _noise_factor(self, item: InfoItem) -> float:
        penalties = 0.0
        if len(item.title) < self._min_title_len:
            penalties += 0.4
        if not item.summary and not item.url:
            penalties += 0.3
        # Social noise: low-score Reddit posts
        extra = item.extra or {}
        if "score" in extra and isinstance(extra["score"], (int, float)):
            if extra["score"] < self._social_min_score:
                penalties += 0.3
        return min(1.0, penalties)

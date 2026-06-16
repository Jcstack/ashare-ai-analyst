"""Source registry — layer/weight/health tracking for intelligence sources.

Part of v23.0 Multi-Source Intelligence Aggregation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

LAYER_BUDGETS = {"L1": 0.35, "L2": 0.15, "L3": 0.25, "L4": 0.15, "L5": 0.10}

# Health thresholds
_DEFAULT_WARN_FAILURES = 3
_DEFAULT_DOWN_FAILURES = 8


@dataclass
class SourceMeta:
    """Metadata and health state for a single information source."""

    source_id: str
    layer: str  # L1-L5
    base_weight: float
    compliance_level: str  # LOW | MEDIUM | HIGH
    domain_tags: list[str] = field(default_factory=list)
    status: str = "OK"  # OK | WARN | DOWN
    consecutive_failures: int = 0
    avg_latency_ms: float = 0.0
    _latency_samples: list[float] = field(default_factory=list, repr=False)

    @property
    def effective_weight(self) -> float:
        if self.status == "DOWN":
            return 0.0
        if self.status == "WARN":
            return self.base_weight * 0.5
        return self.base_weight

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "layer": self.layer,
            "base_weight": self.base_weight,
            "effective_weight": self.effective_weight,
            "compliance_level": self.compliance_level,
            "domain_tags": self.domain_tags,
            "status": self.status,
            "consecutive_failures": self.consecutive_failures,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
        }


class SourceRegistry:
    """In-memory registry of all sources with health tracking."""

    def __init__(
        self,
        sources_config: list[dict[str, Any]],
        *,
        warn_after: int = _DEFAULT_WARN_FAILURES,
        down_after: int = _DEFAULT_DOWN_FAILURES,
    ) -> None:
        self._warn_after = warn_after
        self._down_after = down_after
        self._sources: dict[str, SourceMeta] = {}
        for cfg in sources_config:
            sid = cfg.get("source_id", "")
            if not sid:
                continue
            self._sources[sid] = SourceMeta(
                source_id=sid,
                layer=cfg.get("layer", "L4"),
                base_weight=float(cfg.get("base_weight", 0.5)),
                compliance_level=cfg.get("compliance_level", "LOW"),
                domain_tags=cfg.get("domain_tags", []),
            )
        logger.info("SourceRegistry initialized with %d sources", len(self._sources))

    def get(self, source_id: str) -> SourceMeta | None:
        return self._sources.get(source_id)

    def record_success(self, source_id: str, latency_ms: float = 0.0) -> None:
        meta = self._sources.get(source_id)
        if meta is None:
            return
        meta.consecutive_failures = 0
        meta.status = "OK"
        if latency_ms > 0:
            meta._latency_samples.append(latency_ms)
            # Keep last 20 samples
            if len(meta._latency_samples) > 20:
                meta._latency_samples = meta._latency_samples[-20:]
            meta.avg_latency_ms = sum(meta._latency_samples) / len(
                meta._latency_samples
            )

    def record_failure(self, source_id: str, error: str = "") -> None:
        meta = self._sources.get(source_id)
        if meta is None:
            return
        meta.consecutive_failures += 1
        if meta.consecutive_failures >= self._down_after:
            meta.status = "DOWN"
        elif meta.consecutive_failures >= self._warn_after:
            meta.status = "WARN"
        if error:
            logger.warning(
                "Source %s failure #%d: %s",
                source_id,
                meta.consecutive_failures,
                error,
            )

    def get_all_health(self) -> list[dict[str, Any]]:
        return [meta.to_dict() for meta in self._sources.values()]

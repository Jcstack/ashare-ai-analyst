"""Geopolitical event monitor for macro intelligence.

Lightweight keyword-based scanner that detects geopolitical events
(conflict, sanctions, policy, trade) from news/intel text items.

Per PRD v34.0 FR-GI001: Global Intelligence — geopolitical keyword scan.
Keywords loaded from config/macro_intelligence.yaml → geopolitical_keywords.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("data.geopolitical_monitor")

# Fallback keywords when config is unavailable
_DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "conflict": ["战争", "冲突", "军事", "袭击", "入侵", "空袭", "导弹"],
    "sanctions": ["制裁", "禁运", "关税", "贸易战", "出口管制"],
}

_DEFAULT_REGIONS: list[str] = [
    "中东",
    "伊朗",
    "以色列",
    "俄罗斯",
    "乌克兰",
    "朝鲜",
    "台海",
    "南海",
]

# Region keyword → canonical region label
_REGION_MAP: dict[str, str] = {
    "中东": "中东",
    "伊朗": "中东",
    "以色列": "中东",
    "俄罗斯": "俄乌",
    "乌克兰": "俄乌",
    "朝鲜": "东北亚",
    "台海": "台海",
    "南海": "南海",
}


@dataclass
class GeopoliticalEvent:
    """A detected geopolitical event from text scanning."""

    event_type: str  # "conflict" | "sanctions" | "policy" | "trade"
    region: str  # canonical region label or "未知"
    severity: str  # "critical" | "elevated" | "watch"
    keywords_matched: list[str]
    source_text: str
    timestamp: str  # ISO 8601

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "region": self.region,
            "severity": self.severity,
            "keywords_matched": self.keywords_matched,
            "source_text": self.source_text,
            "timestamp": self.timestamp,
        }


class GeopoliticalMonitor:
    """Keyword-based geopolitical event scanner.

    Scans text for configured keywords and classifies matches by type,
    region, and severity.  Works with existing intelligence hub data —
    no external RSS/GDELT dependency.
    """

    def __init__(self) -> None:
        self._keywords: dict[str, list[str]] = {}
        self._regions: list[str] = []
        self._load_config()

    def _load_config(self) -> None:
        """Load keyword lists from macro_intelligence config with fallback."""
        try:
            config = load_config("macro_intelligence")
            geo_cfg = config.get("geopolitical_keywords", {})
        except Exception:
            logger.warning("Failed to load macro_intelligence config; using defaults")
            geo_cfg = {}

        # Event-type keyword lists (conflict, sanctions, etc.)
        for category in ("conflict", "sanctions", "policy", "trade"):
            configured = geo_cfg.get(category, [])
            if configured:
                self._keywords[category] = [str(k) for k in configured]
            elif category in _DEFAULT_KEYWORDS:
                self._keywords[category] = _DEFAULT_KEYWORDS[category]
            # else: category has no keywords — skip silently

        # Region keywords
        self._regions = [
            str(r) for r in geo_cfg.get("regions", _DEFAULT_REGIONS)
        ]

        total = sum(len(v) for v in self._keywords.values())
        logger.info(
            "GeopoliticalMonitor loaded: %d keywords across %d categories, %d regions",
            total,
            len(self._keywords),
            len(self._regions),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_text(self, text: str) -> GeopoliticalEvent | None:
        """Scan a single text for geopolitical keywords.

        Returns a GeopoliticalEvent if any keyword matches, else None.
        """
        if not text:
            return None

        matched_keywords: list[str] = []
        matched_type: str | None = None

        for category, keywords in self._keywords.items():
            for kw in keywords:
                if kw in text:
                    matched_keywords.append(kw)
                    if matched_type is None:
                        matched_type = category

        if not matched_keywords:
            return None

        return GeopoliticalEvent(
            event_type=matched_type or "unknown",
            region=self.get_region(text),
            severity=self.get_severity(len(matched_keywords)),
            keywords_matched=matched_keywords,
            source_text=text[:500],  # truncate for storage
            timestamp=datetime.now().isoformat(timespec="seconds"),
        )

    def scan_batch(self, items: list[dict]) -> list[GeopoliticalEvent]:
        """Scan a batch of intel items for geopolitical events.

        Each item dict should have a ``"text"`` or ``"title"`` key.
        Returns list of detected events (may be empty).
        """
        events: list[GeopoliticalEvent] = []
        for item in items:
            text = item.get("text") or item.get("title") or ""
            event = self.scan_text(text)
            if event is not None:
                events.append(event)
        return events

    def get_region(self, text: str) -> str:
        """Detect canonical region from text keywords.

        Returns the first matching region label, or ``"未知"`` if none found.
        """
        for region_kw in self._regions:
            if region_kw in text:
                return _REGION_MAP.get(region_kw, region_kw)
        return "未知"

    @staticmethod
    def get_severity(match_count: int) -> str:
        """Map keyword match count to severity level.

        - 3+ matches → ``"critical"``
        - 2 matches  → ``"elevated"``
        - 1 match    → ``"watch"``
        """
        if match_count >= 3:
            return "critical"
        if match_count == 2:
            return "elevated"
        return "watch"

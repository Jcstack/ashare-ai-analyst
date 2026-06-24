"""Causal Chain Constructor — builds impact chains from events using templates + LLM.

Loads structured templates from config/impact_chain_templates.yaml and matches
events via regex patterns. Falls back to LLM for novel events that don't match
any template.

Part of v50.0 Intelligence System Redesign.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ImpactChainLink:
    """A single link in a causal impact chain."""

    order: int
    impact: str
    sectors: list[str]
    direction: str  # "bullish" | "bearish"
    confidence: float  # decayed from base event confidence
    affected_stocks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "impact": self.impact,
            "sectors": self.sectors,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "affected_stocks": self.affected_stocks,
        }


@dataclass
class CausalChain:
    """A complete causal chain from a trigger event to market impacts."""

    event_id: str
    event_description: str
    event_type: str
    base_confidence: float
    chain: list[ImpactChainLink]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    valid_until: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_description": self.event_description,
            "event_type": self.event_type,
            "base_confidence": self.base_confidence,
            "chain": [link.to_dict() for link in self.chain],
            "created_at": self.created_at.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
        }

    @property
    def all_sectors(self) -> list[str]:
        """All unique sectors across all chain links."""
        sectors: list[str] = []
        for link in self.chain:
            for s in link.sectors:
                if s not in sectors:
                    sectors.append(s)
        return sectors

    @property
    def all_stocks(self) -> list[str]:
        """All unique stocks across all chain links."""
        stocks: list[str] = []
        for link in self.chain:
            for s in link.affected_stocks:
                if s not in stocks:
                    stocks.append(s)
        return stocks


class CausalChainConstructor:
    """Constructs causal impact chains from events using templates + LLM.

    Pipeline:
        1. Try template matching first (fast, deterministic)
        2. If no template matches, use LLM for novel events (slow but flexible)
        3. Apply confidence decay per chain link order
    """

    def __init__(
        self,
        templates_path: str = "config/impact_chain_templates.yaml",
        llm_client: Any = None,
        default_validity_hours: int = 24,
    ) -> None:
        self._templates = self._load_templates(templates_path)
        self._llm = llm_client
        self._default_validity_hours = default_validity_hours
        self._compiled_patterns: dict[str, re.Pattern[str]] = {}
        self._compile_patterns()
        logger.info(
            "CausalChainConstructor initialized with %d templates",
            len(self._templates),
        )

    def _load_templates(self, path: str) -> dict[str, dict[str, Any]]:
        """Load impact chain templates from YAML config."""
        try:
            # Try absolute path first, then relative to project root
            p = Path(path)
            if not p.is_absolute():
                from src.utils.config import get_project_root

                p = get_project_root() / path
            if p.exists():
                with open(p, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                templates = data.get("templates", {})
                logger.info("Loaded %d templates from %s", len(templates), p)
                return templates
        except Exception as exc:
            logger.warning("Failed to load templates from %s: %s", path, exc)
        return {}

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for efficient matching."""
        for name, template in self._templates.items():
            pattern = template.get("event_pattern", "")
            if pattern:
                try:
                    self._compiled_patterns[name] = re.compile(pattern, re.IGNORECASE)
                except re.error as exc:
                    logger.warning(
                        "Invalid regex pattern for template '%s': %s", name, exc
                    )

    def construct_chain(self, event: dict[str, Any]) -> CausalChain | None:
        """Construct a causal chain for an event.

        Args:
            event: Dict with keys: title, summary/description, confidence,
                   sectors (optional), event_type (optional).

        Returns:
            CausalChain if a template matches or LLM succeeds, None otherwise.
        """
        event_text = self._extract_event_text(event)
        if not event_text:
            return None

        base_confidence = float(event.get("confidence", 0.7))

        # Step 1: Try template matching (fast, deterministic)
        match = self._match_template(event_text)
        if match:
            name, template = match
            links = self._build_from_template(template, event, base_confidence)
            now = datetime.now(UTC)
            return CausalChain(
                event_id=event.get("event_id", str(uuid.uuid4())),
                event_description=event_text,
                event_type=name,
                base_confidence=base_confidence,
                chain=links,
                created_at=now,
                valid_until=now + timedelta(hours=self._default_validity_hours),
            )

        # Step 2: LLM fallback for novel events (if available)
        # NOTE: LLM path is async-capable but called synchronously here.
        # The trading loop can call construct_chain_async() for async usage.
        logger.debug("No template match for: %s", event_text[:60])
        return None

    async def construct_chain_async(self, event: dict[str, Any]) -> CausalChain | None:
        """Async version with LLM fallback for novel events."""
        # Try template first (same as sync)
        event_text = self._extract_event_text(event)
        if not event_text:
            return None

        base_confidence = float(event.get("confidence", 0.7))

        match = self._match_template(event_text)
        if match:
            name, template = match
            links = self._build_from_template(template, event, base_confidence)
            now = datetime.now(UTC)
            return CausalChain(
                event_id=event.get("event_id", str(uuid.uuid4())),
                event_description=event_text,
                event_type=name,
                base_confidence=base_confidence,
                chain=links,
                created_at=now,
                valid_until=now + timedelta(hours=self._default_validity_hours),
            )

        # LLM fallback
        if self._llm is not None:
            links = await self._build_from_llm(event, base_confidence)
            if links:
                now = datetime.now(UTC)
                return CausalChain(
                    event_id=event.get("event_id", str(uuid.uuid4())),
                    event_description=event_text,
                    event_type="llm_inferred",
                    base_confidence=base_confidence * 0.8,  # LLM discount
                    chain=links,
                    created_at=now,
                    valid_until=now + timedelta(hours=self._default_validity_hours),
                )

        return None

    def _match_template(self, event_text: str) -> tuple[str, dict[str, Any]] | None:
        """Match event text against compiled template patterns.

        Returns the first matching (template_name, template_dict) or None.
        """
        for name, pattern in self._compiled_patterns.items():
            if pattern.search(event_text):
                return name, self._templates[name]
        return None

    def _build_from_template(
        self,
        template: dict[str, Any],
        event: dict[str, Any],
        base_confidence: float,
    ) -> list[ImpactChainLink]:
        """Build chain links from a matched template with confidence decay."""
        links: list[ImpactChainLink] = []
        for step in template.get("chain", []):
            order = step.get("order", len(links) + 1)
            decay = float(step.get("confidence_decay", 0.7))
            resolved_sectors = self._resolve_sectors(step.get("sectors", []), event)

            link = ImpactChainLink(
                order=order,
                impact=step.get("impact", ""),
                sectors=resolved_sectors,
                direction=step.get("direction", "bullish"),
                confidence=base_confidence * decay,
            )
            links.append(link)
        return links

    async def _build_from_llm(
        self,
        event: dict[str, Any],
        base_confidence: float,
    ) -> list[ImpactChainLink]:
        """Use LLM to construct a causal chain for novel events.

        Prompts the LLM for first/second/third-order impacts with affected
        sectors and direction. Returns empty list on failure.
        """
        event_text = self._extract_event_text(event)

        prompt = (
            "Analyze this financial event and construct a causal impact chain "
            "for A-share (Chinese stock market) investing.\n\n"
            f"Event: {event_text}\n\n"
            "Return a JSON array of impact chain links, each with:\n"
            '- "order": 1/2/3 (1=direct, 2=derived, 3=market implication)\n'
            '- "impact": brief description of the impact (in Chinese)\n'
            '- "sectors": list of affected A-share sectors (in Chinese)\n'
            '- "direction": "bullish" or "bearish"\n'
            '- "confidence_decay": float 0.0-1.0 (higher = more certain)\n\n'
            "Return ONLY the JSON array, no other text."
        )

        try:
            import json

            response = await self._llm.generate(prompt)
            # Parse LLM response as JSON array
            text = response if isinstance(response, str) else str(response)
            # Extract JSON from potential markdown code blocks
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())

            links: list[ImpactChainLink] = []
            for step in data:
                order = int(step.get("order", len(links) + 1))
                decay = float(step.get("confidence_decay", 0.5))
                link = ImpactChainLink(
                    order=order,
                    impact=step.get("impact", ""),
                    sectors=step.get("sectors", []),
                    direction=step.get("direction", "bullish"),
                    confidence=base_confidence * decay,
                )
                links.append(link)
            return links
        except Exception as exc:
            logger.warning("LLM chain construction failed: %s", exc)
            return []

    def _resolve_sectors(self, sectors: list[str], event: dict[str, Any]) -> list[str]:
        """Resolve special sector references like _from_event."""
        resolved: list[str] = []
        for s in sectors:
            if s == "_from_event":
                # Extract sectors from event metadata
                event_sectors = event.get("sectors", [])
                resolved.extend(event_sectors)
            elif s == "_from_knowledge_graph":
                # Future: query knowledge graph for related sectors
                # For now, skip these — they produce no sectors
                pass
            else:
                resolved.append(s)
        return resolved

    @staticmethod
    def _extract_event_text(event: dict[str, Any]) -> str:
        """Extract searchable text from an event dict."""
        parts = [
            event.get("title", ""),
            event.get("summary", ""),
            event.get("description", ""),
        ]
        return " ".join(p for p in parts if p).strip()

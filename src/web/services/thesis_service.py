"""Thesis service — web-layer wrapper around ThesisTracker.

Provides async-friendly access to thesis lifecycle operations for the
REST API, with filtering, detail retrieval, and evidence management.
"""

from __future__ import annotations

from typing import Any

from src.agent_loop.thesis_tracker import ThesisTracker
from src.utils.logger import get_logger

logger = get_logger("web.thesis_service")


class ThesisService:
    """Service layer for thesis lifecycle operations."""

    def __init__(self, tracker: ThesisTracker | None = None) -> None:
        self._tracker = tracker or ThesisTracker()

    @property
    def tracker(self) -> ThesisTracker:
        return self._tracker

    def list_theses(
        self,
        status: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """List theses with optional filtering."""
        theses = self._tracker.list_theses(status=status, symbol=symbol)
        return [t.to_dict() for t in theses]

    def get_thesis(self, thesis_id: str) -> dict[str, Any] | None:
        """Get thesis detail with full evidence history."""
        thesis = self._tracker.get_thesis(thesis_id)
        if thesis is None:
            return None
        return thesis.to_dict()

    def create_thesis(
        self,
        symbol: str,
        direction: str,
        narrative: str,
        entry_condition: str = "",
        invalidation_condition: str = "",
        confidence: float = 0.5,
        expires_days: int = 5,
        position_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new thesis and return its dict representation."""
        thesis = self._tracker.create_thesis(
            symbol=symbol,
            direction=direction,
            narrative=narrative,
            entry_condition=entry_condition,
            invalidation_condition=invalidation_condition,
            confidence=confidence,
            expires_days=expires_days,
            position_id=position_id,
        )
        return thesis.to_dict()

    def add_evidence(
        self,
        thesis_id: str,
        evidence_type: str,
        description: str,
        source: str = "",
        confidence_impact: float = 0.0,
    ) -> dict[str, Any] | None:
        """Add evidence to a thesis. Returns updated thesis dict or None."""
        thesis = self._tracker.add_evidence(
            thesis_id=thesis_id,
            evidence_type=evidence_type,
            description=description,
            source=source,
            confidence_impact=confidence_impact,
        )
        if thesis is None:
            return None
        return thesis.to_dict()

    def invalidate_thesis(self, thesis_id: str, reason: str) -> dict[str, Any] | None:
        """Manually invalidate a thesis. Returns updated thesis dict or None."""
        thesis = self._tracker.invalidate_thesis(thesis_id, reason)
        if thesis is None:
            return None
        return thesis.to_dict()

    def realize_thesis(self, thesis_id: str, reason: str) -> dict[str, Any] | None:
        """Mark a thesis as realized. Returns updated thesis dict or None."""
        thesis = self._tracker.realize_thesis(thesis_id, reason)
        if thesis is None:
            return None
        return thesis.to_dict()

    def get_active_theses(self) -> list[dict[str, Any]]:
        """Return all active/weakening theses."""
        return [t.to_dict() for t in self._tracker.get_active_theses()]

    def get_weakening_theses(self) -> list[dict[str, Any]]:
        """Return theses with weakening confidence."""
        return [t.to_dict() for t in self._tracker.get_weakening_theses()]

    def apply_daily_decay(self) -> list[dict[str, Any]]:
        """Apply daily decay and return theses that changed status."""
        changed = self._tracker.apply_daily_decay()
        return [t.to_dict() for t in changed]

    def check_expiry(self) -> list[dict[str, Any]]:
        """Check for expired theses. Returns list of newly expired."""
        expired = self._tracker.check_expiry()
        return [t.to_dict() for t in expired]

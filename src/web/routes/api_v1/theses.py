"""Thesis lifecycle API endpoints.

Endpoints:
    GET    /api/v1/theses                       — List theses (filterable)
    GET    /api/v1/theses/{thesis_id}           — Thesis detail with evidence
    POST   /api/v1/theses                       — Create a thesis manually
    POST   /api/v1/theses/{thesis_id}/evidence  — Add evidence
    POST   /api/v1/theses/{thesis_id}/invalidate — Manually invalidate
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.web.dependencies import get_thesis_service
from src.web.services.thesis_service import ThesisService

router = APIRouter(tags=["theses"])


# ------------------------------------------------------------------
# Request/Response schemas
# ------------------------------------------------------------------


class CreateThesisRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol, e.g. 600036.SH")
    direction: str = Field(default="long", description="long or short")
    narrative: str = Field(..., description="Investment narrative in plain language")
    entry_condition: str = Field(default="", description="Condition to enter position")
    invalidation_condition: str = Field(
        default="", description="Condition that would invalidate the thesis"
    )
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Initial confidence 0-1"
    )
    expires_days: int = Field(default=5, ge=1, le=30, description="Days until expiry")
    position_id: str | None = Field(
        default=None, description="Link to portfolio position"
    )


class AddEvidenceRequest(BaseModel):
    evidence_type: str = Field(..., description="'supporting' or 'contradicting'")
    description: str = Field(..., description="What happened")
    source: str = Field(default="", description="Evidence source")
    confidence_impact: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Impact on confidence (positive=supporting, negative=contradicting)",
    )


class InvalidateRequest(BaseModel):
    reason: str = Field(..., description="Why the thesis is being invalidated")


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get("/theses")
async def list_theses(
    status: str | None = Query(None, description="Filter by status"),
    symbol: str | None = Query(None, description="Filter by symbol"),
    svc: ThesisService = Depends(get_thesis_service),
) -> dict[str, Any]:
    """List theses with optional filtering by status and symbol."""
    theses = svc.list_theses(status=status, symbol=symbol)
    return {"theses": theses, "count": len(theses)}


@router.get("/theses/{thesis_id}")
async def get_thesis(
    thesis_id: str,
    svc: ThesisService = Depends(get_thesis_service),
) -> dict[str, Any]:
    """Get thesis detail including full evidence history."""
    thesis = svc.get_thesis(thesis_id)
    if thesis is None:
        raise HTTPException(status_code=404, detail="Thesis not found")
    return thesis


@router.post("/theses", status_code=201)
async def create_thesis(
    req: CreateThesisRequest,
    svc: ThesisService = Depends(get_thesis_service),
) -> dict[str, Any]:
    """Create a new investment thesis."""
    thesis = svc.create_thesis(
        symbol=req.symbol,
        direction=req.direction,
        narrative=req.narrative,
        entry_condition=req.entry_condition,
        invalidation_condition=req.invalidation_condition,
        confidence=req.confidence,
        expires_days=req.expires_days,
        position_id=req.position_id,
    )
    return thesis


@router.post("/theses/{thesis_id}/evidence")
async def add_evidence(
    thesis_id: str,
    req: AddEvidenceRequest,
    svc: ThesisService = Depends(get_thesis_service),
) -> dict[str, Any]:
    """Add supporting or contradicting evidence to a thesis."""
    if req.evidence_type not in ("supporting", "contradicting"):
        raise HTTPException(
            status_code=400,
            detail="evidence_type must be 'supporting' or 'contradicting'",
        )
    thesis = svc.add_evidence(
        thesis_id=thesis_id,
        evidence_type=req.evidence_type,
        description=req.description,
        source=req.source,
        confidence_impact=req.confidence_impact,
    )
    if thesis is None:
        raise HTTPException(status_code=404, detail="Thesis not found")
    return thesis


@router.post("/theses/{thesis_id}/invalidate")
async def invalidate_thesis(
    thesis_id: str,
    req: InvalidateRequest,
    svc: ThesisService = Depends(get_thesis_service),
) -> dict[str, Any]:
    """Manually invalidate a thesis."""
    thesis = svc.invalidate_thesis(thesis_id, req.reason)
    if thesis is None:
        raise HTTPException(status_code=404, detail="Thesis not found")
    return thesis

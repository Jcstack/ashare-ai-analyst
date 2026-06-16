"""Intel Reports REST API endpoints.

Part of v25.0 Intel-Portfolio Analysis (FR-IA004).
Mounted at /api/v1/reports.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.web.dependencies import get_intel_report_service
from src.web.schemas.intel_report import (
    ChatFromReportResponse,
    IntelReportResponse,
    ReportListResponse,
    ReportUnreadCountResponse,
)
from src.web.services.intel_report_service import IntelReportService

router = APIRouter(tags=["intel-reports"])


@router.get("/reports", response_model=ReportListResponse)
async def list_reports(
    symbol: str | None = Query(None, description="Filter by symbol"),
    unread_only: bool = Query(False, description="Only unread reports"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: IntelReportService = Depends(get_intel_report_service),
) -> dict:
    """List intel reports with optional filters."""
    return service.get_reports(
        symbol=symbol,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
    )


@router.get("/reports/unread-count", response_model=ReportUnreadCountResponse)
async def unread_count(
    service: IntelReportService = Depends(get_intel_report_service),
) -> dict:
    """Return unread report count."""
    return {"count": service.get_unread_count()}


@router.get("/reports/{report_id}", response_model=IntelReportResponse)
async def get_report(
    report_id: str,
    service: IntelReportService = Depends(get_intel_report_service),
) -> dict:
    """Get a single report by ID."""
    report = service.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.post("/reports/{report_id}/read")
async def mark_read(
    report_id: str,
    service: IntelReportService = Depends(get_intel_report_service),
) -> dict:
    """Mark a report as read."""
    if not service.mark_read(report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"status": "ok"}


@router.delete("/reports/{report_id}")
async def delete_report(
    report_id: str,
    service: IntelReportService = Depends(get_intel_report_service),
) -> dict:
    """Delete a report."""
    if not service.delete(report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"status": "ok"}


@router.post("/reports/{report_id}/chat", response_model=ChatFromReportResponse)
def create_chat_from_report(
    report_id: str,
    service: IntelReportService = Depends(get_intel_report_service),
) -> dict:
    """Create a deep-analysis chat thread from a report (non-blocking).

    Returns the thread_id and initial message text.  The frontend
    sends the initial message via ``/chat/threads/{id}/messages``
    so the user sees a loading spinner immediately.
    """
    result = service.create_chat_from_report(report_id)
    if not result:
        raise HTTPException(status_code=404, detail="Report not found")
    return result

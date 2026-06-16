"""Holiday Research Workbench API endpoints.

Provides auto-collected research context, user note management,
structured evidence collection, LLM research question generation,
scenario analysis, comprehensive AI analysis, and follow-up Q&A
for holiday-period stock research.

Endpoints are mounted at ``/api/v1/advisor/holiday-research``.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends

from src.web.dependencies import (
    get_association_profile_builder,
    get_holiday_research_service,
    get_profile_override_service,
)
from src.web.schemas.holiday_research import (
    AddEvidenceRequest,
    AddNoteRequest,
    ComprehensiveAnalysisResult,
    ConversationMessage,
    EvidenceItem,
    FollowupRequest,
    FollowupResponse,
    HolidayResearchContext,
    ProfileOverrideRequest,
    ProfileOverrideResponse,
    ResearchChecklist,
    ScenarioAnalysisRequest,
    ScenarioAnalysisResult,
    UserNote,
)
from src.web.services.holiday_research_service import HolidayResearchService
from src.web.services.profile_override_service import ProfileOverrideService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["holiday-research"])


@router.get("/{symbol}/context", response_model=HolidayResearchContext)
async def get_research_context(
    symbol: str,
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> dict:
    """Get auto-collected research context + user notes for a stock."""
    try:
        return await asyncio.to_thread(svc.collect_context, symbol)
    except Exception:
        logger.exception("Research context failed for %s", symbol)
        return {"status": "error", "symbol": symbol}


@router.get("/{symbol}/notes", response_model=list[UserNote])
async def get_notes(
    symbol: str,
    holiday_key: str = "",
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> list:
    """Get user research notes for a stock."""
    try:
        hk = holiday_key or svc._get_holiday_key()
        return await asyncio.to_thread(svc.get_user_notes, symbol, hk)
    except Exception:
        logger.exception("Get notes failed for %s", symbol)
        return []


@router.post("/{symbol}/notes", response_model=UserNote)
async def add_note(
    symbol: str,
    request: AddNoteRequest,
    holiday_key: str = "",
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> dict:
    """Add a user research note."""
    try:
        hk = holiday_key or svc._get_holiday_key()
        return await asyncio.to_thread(
            svc.add_user_note, symbol, hk, request.content, request.note_type
        )
    except Exception:
        logger.exception("Add note failed for %s", symbol)
        return {"id": "", "content": request.content, "note_type": request.note_type}


@router.delete("/{symbol}/notes/{note_id}")
async def delete_note(
    symbol: str,
    note_id: str,
    holiday_key: str = "",
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> dict:
    """Delete a user research note."""
    try:
        hk = holiday_key or svc._get_holiday_key()
        deleted = await asyncio.to_thread(svc.delete_user_note, symbol, hk, note_id)
        return {"status": "success" if deleted else "not_found", "note_id": note_id}
    except Exception:
        logger.exception("Delete note failed for %s note %s", symbol, note_id)
        return {"status": "error", "note_id": note_id}


# --- v3.4: Structured Evidence ---


@router.get("/{symbol}/evidence", response_model=list[EvidenceItem])
async def get_evidence(
    symbol: str,
    holiday_key: str = "",
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> list:
    """Get structured evidence items for a stock."""
    try:
        hk = holiday_key or svc._get_holiday_key()
        return await asyncio.to_thread(svc.get_evidence, symbol, hk)
    except Exception:
        logger.exception("Get evidence failed for %s", symbol)
        return []


@router.post("/{symbol}/evidence", response_model=EvidenceItem)
async def add_evidence(
    symbol: str,
    request: AddEvidenceRequest,
    holiday_key: str = "",
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> dict:
    """Add a structured evidence item."""
    try:
        hk = holiday_key or svc._get_holiday_key()
        return await asyncio.to_thread(
            svc.add_evidence,
            symbol,
            hk,
            request.content,
            request.evidence_type,
            request.linked_question_id,
            request.impact,
            request.confidence,
            request.source,
        )
    except Exception:
        logger.exception("Add evidence failed for %s", symbol)
        return {"id": "", "content": request.content}


@router.delete("/{symbol}/evidence/{evidence_id}")
async def delete_evidence(
    symbol: str,
    evidence_id: str,
    holiday_key: str = "",
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> dict:
    """Delete an evidence item."""
    try:
        hk = holiday_key or svc._get_holiday_key()
        deleted = await asyncio.to_thread(svc.delete_evidence, symbol, hk, evidence_id)
        return {
            "status": "success" if deleted else "not_found",
            "evidence_id": evidence_id,
        }
    except Exception:
        logger.exception("Delete evidence failed for %s", symbol)
        return {"status": "error", "evidence_id": evidence_id}


# --- v3.4: Research Questions ---


@router.post("/{symbol}/research-questions", response_model=ResearchChecklist)
async def generate_research_questions(
    symbol: str,
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> dict:
    """Generate LLM-powered targeted research questions for a stock."""
    try:
        return await asyncio.to_thread(svc.generate_research_questions, symbol)
    except Exception:
        logger.exception("Research questions failed for %s", symbol)
        return {"status": "error", "symbol": symbol, "questions": []}


# --- v3.4: Scenario Analysis ---


@router.post("/{symbol}/scenarios", response_model=ScenarioAnalysisResult)
async def analyze_scenarios(
    symbol: str,
    request: ScenarioAnalysisRequest | None = None,
    holiday_key: str = "",
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> dict:
    """Evaluate scenarios using collected evidence + association profile."""
    try:
        hk = holiday_key or svc._get_holiday_key()
        scenarios = None
        if request and request.scenarios:
            scenarios = [s.model_dump() for s in request.scenarios]
        return await asyncio.to_thread(svc.analyze_scenarios, symbol, hk, scenarios)
    except Exception:
        logger.exception("Scenario analysis failed for %s", symbol)
        return {
            "status": "error",
            "symbol": symbol,
            "scenarios": [],
            "disclaimer": "AI 分析仅供参考，不构成投资建议。",
        }


# --- Profile Overrides ---


@router.get("/{symbol}/profile-overrides", response_model=ProfileOverrideResponse)
async def get_profile_overrides(
    symbol: str,
    svc: ProfileOverrideService = Depends(get_profile_override_service),
) -> dict:
    """Get current profile overrides for a stock."""
    override = svc.get_override(symbol)
    if override is None:
        return {"symbol": symbol, "has_override": False}
    return {
        "symbol": symbol,
        "has_override": True,
        "added_concepts": override.get("added_concepts", []),
        "removed_concept_codes": override.get("removed_concept_codes", []),
        "added_peers": override.get("added_peers", []),
        "removed_peer_symbols": override.get("removed_peer_symbols", []),
        "added_keywords": override.get("added_keywords", []),
        "removed_keywords": override.get("removed_keywords", []),
        "industry_override": override.get("industry_override"),
        "updated_at": override.get("updated_at", ""),
    }


@router.put("/{symbol}/profile-overrides", response_model=ProfileOverrideResponse)
async def update_profile_overrides(
    symbol: str,
    request: ProfileOverrideRequest,
    svc: ProfileOverrideService = Depends(get_profile_override_service),
) -> dict:
    """Update profile overrides for a stock (merge semantics)."""
    try:
        updates = request.model_dump(exclude_none=True)
        # Convert pydantic sub-models to plain dicts for JSON storage
        if "added_concepts" in updates:
            updates["added_concepts"] = [
                c.model_dump() if hasattr(c, "model_dump") else c
                for c in updates["added_concepts"]
            ]
        if "added_peers" in updates:
            updates["added_peers"] = [
                p.model_dump() if hasattr(p, "model_dump") else p
                for p in updates["added_peers"]
            ]
        result = svc.set_override(symbol, updates)
        return {
            "symbol": symbol,
            "has_override": True,
            "added_concepts": result.get("added_concepts", []),
            "removed_concept_codes": result.get("removed_concept_codes", []),
            "added_peers": result.get("added_peers", []),
            "removed_peer_symbols": result.get("removed_peer_symbols", []),
            "added_keywords": result.get("added_keywords", []),
            "removed_keywords": result.get("removed_keywords", []),
            "industry_override": result.get("industry_override"),
            "updated_at": result.get("updated_at", ""),
        }
    except Exception:
        logger.exception("Update profile overrides failed for %s", symbol)
        return {"symbol": symbol, "has_override": False}


@router.delete("/{symbol}/profile-overrides")
async def delete_profile_overrides(
    symbol: str,
    svc: ProfileOverrideService = Depends(get_profile_override_service),
) -> dict:
    """Delete all profile overrides for a stock (reset to auto)."""
    deleted = svc.delete_override(symbol)
    return {
        "status": "success" if deleted else "not_found",
        "symbol": symbol,
    }


@router.get("/industries")
async def list_available_industries(
    builder=Depends(get_association_profile_builder),
) -> dict:
    """List available industry profiles for override dropdown."""
    return {"industries": builder.get_available_industries()}


# --- Conversation History ---


@router.get("/{symbol}/conversation", response_model=list[ConversationMessage])
async def get_conversation(
    symbol: str,
    holiday_key: str = "",
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> list:
    """Get multi-turn conversation history for a stock."""
    try:
        hk = holiday_key or svc._get_holiday_key()
        return await asyncio.to_thread(svc.get_conversation, symbol, hk)
    except Exception:
        logger.exception("Get conversation failed for %s", symbol)
        return []


@router.delete("/{symbol}/conversation")
async def clear_conversation(
    symbol: str,
    holiday_key: str = "",
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> dict:
    """Clear conversation history for a stock."""
    try:
        hk = holiday_key or svc._get_holiday_key()
        cleared = await asyncio.to_thread(svc.clear_conversation, symbol, hk)
        return {"status": "success" if cleared else "not_found", "symbol": symbol}
    except Exception:
        logger.exception("Clear conversation failed for %s", symbol)
        return {"status": "error", "symbol": symbol}


# --- Comprehensive Analysis + Follow-up ---


@router.post("/{symbol}/analyze", response_model=ComprehensiveAnalysisResult)
async def analyze_comprehensive(
    symbol: str,
    holiday_key: str = "",
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> dict:
    """Trigger comprehensive AI analysis combining auto context + user notes."""
    try:
        hk = holiday_key or svc._get_holiday_key()
        return await asyncio.to_thread(svc.analyze_comprehensive, symbol, hk)
    except Exception:
        logger.exception("Comprehensive analysis failed for %s", symbol)
        return {
            "status": "error",
            "symbol": symbol,
            "overall_assessment": "分析暂时不可用",
            "disclaimer": "AI 分析仅供参考，不构成投资建议。",
        }


@router.post("/{symbol}/ask", response_model=FollowupResponse)
async def ask_followup(
    symbol: str,
    request: FollowupRequest,
    holiday_key: str = "",
    svc: HolidayResearchService = Depends(get_holiday_research_service),
) -> dict:
    """Ask a follow-up question with full research context."""
    try:
        hk = holiday_key or svc._get_holiday_key()
        return await asyncio.to_thread(svc.ask_followup, symbol, hk, request.question)
    except Exception:
        logger.exception("Followup failed for %s", symbol)
        return {
            "status": "error",
            "question": request.question,
            "answer": "追问服务暂时不可用",
            "disclaimer": "AI 分析仅供参考，不构成投资建议。",
        }

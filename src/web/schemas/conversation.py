"""Pydantic models for the unified AI conversation endpoint.

v11.0: Single conversation entry point that merges initial analysis with
multi-turn follow-up Q&A, position context, and holiday awareness.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.web.schemas.agent import UnifiedAnalysisResult


class PositionContext(BaseModel):
    """Optional portfolio position context injected into analysis."""

    cost_price: float
    shares: int = 0
    holding_days: int | None = None


class IntelContext(BaseModel):
    """Intelligence Hub items to inject as analysis context."""

    item_ids: list[str] = Field(default_factory=list)
    analysis_angle: str | None = None
    sector: str | None = None


class ConversationRequest(BaseModel):
    """Request body for starting or continuing a conversation."""

    message: str | None = None
    session_id: str | None = None
    position: PositionContext | None = None
    intel_context: IntelContext | None = None


class ConversationMessageItem(BaseModel):
    """Single message in the conversation history."""

    role: str = "user"
    content: str = ""
    timestamp: str = ""


class ConversationResponse(BaseModel):
    """Response from the conversation endpoint."""

    status: str = "ok"
    session_id: str = ""
    symbol: str = ""
    analysis: UnifiedAnalysisResult | None = None
    messages: list[ConversationMessageItem] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    generated_at: str = ""
    model_used: str = ""
    disclaimer: str = ""
    message: str | None = None

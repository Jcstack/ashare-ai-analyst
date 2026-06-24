"""Chat and Agent conversation data models.

Defines Pydantic models for the v12.0 chat-first Agent architecture:
threads, messages, rich cards, trade decisions, and API payloads.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core chat models
# ---------------------------------------------------------------------------


class ThreadContext(BaseModel):
    """Contextual binding for a chat thread."""

    symbol: str | None = None
    mode: Literal["stock", "portfolio", "market", "general"] = "general"
    intel_item_ids: list[str] | None = None
    matched_portfolio_symbols: list[str] | None = None


class ToolCallRecord(BaseModel):
    """Record of a single tool invocation during agent processing."""

    tool_name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output_summary: str = ""
    duration_ms: float = 0.0


class RichCard(BaseModel):
    """Structured UI card embedded in an agent message."""

    type: str  # stock_analysis | trade_decision | portfolio_summary | ...
    props: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    """A single message in a chat thread."""

    id: str
    role: Literal["user", "assistant"]
    content: str
    rich_cards: list[RichCard] | None = None
    tool_calls: list[ToolCallRecord] | None = None
    timestamp: str
    lineage_snapshot_id: str | None = None
    agent_name: str | None = None
    delegation_chain: list[str] | None = None
    satisfaction: Literal["satisfied", "unsatisfied"] | None = None
    feedback: str | None = None


class ChatThread(BaseModel):
    """A conversation thread between the user and the agent."""

    id: str
    title: str
    messages: list[ChatMessage] = Field(default_factory=list)
    context: ThreadContext | None = None
    persona: str | None = None
    created_at: str
    updated_at: str
    processing_status: str = "ready"  # "processing" | "ready" | "error"


# ---------------------------------------------------------------------------
# Trade-related models
# ---------------------------------------------------------------------------


class Trade(BaseModel):
    """A trade execution record (simulated or manual)."""

    id: str
    symbol: str
    stock_name: str
    action: Literal["buy", "sell", "add", "reduce"]
    shares: int
    price: float
    amount: float
    source: Literal["agent", "manual"]
    reasoning: str = ""
    agent_recommendation_id: str | None = None
    decision_feedback: str | None = None
    status: Literal["pending", "executed", "cancelled"] = "pending"
    executed_at: str | None = None
    created_at: str = ""
    thread_id: str | None = None
    gate_request_id: str | None = None


class AgentRecommendation(BaseModel):
    """An AI-generated trading recommendation."""

    id: str
    thread_id: str
    symbol: str
    action: str
    confidence: float
    reasoning: str
    risk_warnings: list[str] = Field(default_factory=list)
    stop_loss: float | None = None
    user_decision: Literal["accepted", "rejected", "modified", "pending"] = "pending"
    user_feedback: str | None = None
    actual_outcome: dict[str, Any] | None = None
    created_at: str = ""


class TradingProfile(BaseModel):
    """User trading behavior profile accumulated from trade history."""

    total_trades: int = 0
    win_rate: float = 0.0
    avg_holding_days: float = 0.0
    risk_tolerance: Literal["conservative", "moderate", "aggressive"] = "moderate"
    common_biases: list[str] = Field(default_factory=list)
    preferred_sectors: list[str] = Field(default_factory=list)
    agent_adoption_rate: float = 0.0
    last_updated: str = ""


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------


class CreateThreadRequest(BaseModel):
    """Request to create a new chat thread."""

    message: str
    context: ThreadContext | None = None
    use_multi_agent: bool = False
    persona: str | None = None


class CreateThreadResponse(BaseModel):
    """Response after creating a thread.

    When processing_status is 'processing', reply is None and the frontend
    should poll GET /threads/:id until status changes to 'ready'.
    """

    thread_id: str
    title: str
    reply: ChatMessage | None = None
    processing_status: str = "ready"  # "processing" | "ready" | "error"


class MessageFeedbackRequest(BaseModel):
    """Request to submit feedback on an assistant message."""

    satisfaction: Literal["satisfied", "unsatisfied"]
    feedback: str | None = None


class SendMessageRequest(BaseModel):
    """Request to send a follow-up message in an existing thread."""

    message: str
    use_multi_agent: bool = False


class ThreadListItem(BaseModel):
    """Summary of a thread for list views."""

    id: str
    title: str
    last_message_preview: str = ""
    context: ThreadContext | None = None
    persona: str | None = None
    created_at: str
    updated_at: str


class ThreadListResponse(BaseModel):
    """Response for listing threads."""

    threads: list[ThreadListItem] = Field(default_factory=list)
    total: int = 0


class PersonaInfo(BaseModel):
    """Persona definition for the chat thread persona selector."""

    key: str
    display_name: str
    description: str
    icon: str = "default"
    backend: str = "gemini"

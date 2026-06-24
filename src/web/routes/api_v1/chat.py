"""Chat API endpoints for the v12.0 Agent architecture.

Provides thread-based conversational interface to the Master Agent.
PRD v50 aligned: POST /threads returns immediately, processes in background.
Frontend polls GET /threads/:id for completion.
"""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from src.llm.base import LLMProviderError
from src.web.dependencies import get_agent_service, get_suggestion_service
from src.web.schemas.chat import (
    ChatThread,
    CreateThreadRequest,
    CreateThreadResponse,
    MessageFeedbackRequest,
    SendMessageRequest,
    ThreadListResponse,
)
from src.web.services.agent_service import AgentService
from src.web.services.suggestion_service import SuggestionService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# Track background tasks to prevent GC
_background_tasks: set[asyncio.Task] = set()


@router.post("/threads", response_model=CreateThreadResponse)
async def create_thread(
    body: CreateThreadRequest,
    agent: AgentService = Depends(get_agent_service),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Create a new chat thread and start processing in background.

    Returns immediately with thread_id and processing_status='processing'.
    Frontend should poll GET /threads/:id until processing_status='ready'.
    """
    try:
        thread_id = agent.create_thread_background(
            message=body.message,
            context=body.context,
            persona=body.persona,
        )
    except Exception as exc:
        logger.exception("Failed to create thread: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="创建对话失败，请稍后重试。",
        )

    # Save user message immediately so it appears in polls
    from src.web.schemas.chat import ChatMessage
    import uuid
    from datetime import datetime, timezone

    user_msg = ChatMessage(
        id=str(uuid.uuid4()),
        role="user",
        content=body.message,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    agent._save_message(thread_id, user_msg)

    # Use threading for background processing (asyncio.create_task gets
    # lost in Gunicorn + UvicornWorker due to event loop lifecycle)
    import threading

    def _run_background():
        import asyncio as _aio

        try:
            _aio.run(
                _process_thread_safe(
                    agent, thread_id, body.message, body.use_multi_agent
                )
            )
        except Exception as exc:
            logger.exception("Background thread crashed for %s: %s", thread_id[:8], exc)
            agent._set_thread_status(thread_id, "error")

    t = threading.Thread(target=_run_background, daemon=True)
    t.start()
    logger.info("Background thread started for %s", thread_id[:8])

    title = body.message[:50].strip()
    if len(body.message) > 50:
        title += "..."

    return CreateThreadResponse(
        thread_id=thread_id,
        title=title,
        reply=None,
        processing_status="processing",
    )


async def _process_thread_safe(
    agent: AgentService,
    thread_id: str,
    message: str,
    use_multi_agent: bool,
) -> None:
    """Background wrapper with error handling."""
    try:
        await agent.process_thread_background(
            thread_id, message, use_multi_agent=use_multi_agent
        )
    except LLMProviderError as exc:
        logger.error("Background LLM error for thread %s: %s", thread_id[:8], exc)
        agent._set_thread_status(thread_id, "error")
    except Exception as exc:
        logger.exception(
            "Background processing failed for thread %s: %s", thread_id[:8], exc
        )
        agent._set_thread_status(thread_id, "error")


@router.post("/threads/{thread_id}/messages")
async def send_message(
    thread_id: str,
    body: SendMessageRequest,
    agent: AgentService = Depends(get_agent_service),
):
    """Send a follow-up message in an existing thread."""
    thread = agent.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    try:
        reply = await agent.send_message(
            thread_id=thread_id,
            message=body.message,
            use_multi_agent=body.use_multi_agent,
        )
    except LLMProviderError as exc:
        logger.error("LLM provider unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="AI 服务暂时不可用，请检查 LLM 配置后重试。",
        )
    except Exception as exc:
        logger.exception("Failed to send message: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="发送消息失败，请稍后重试。",
        )
    return {"reply": reply}


@router.post("/threads/{thread_id}/messages/{message_id}/feedback")
async def submit_feedback(
    thread_id: str,
    message_id: str,
    body: MessageFeedbackRequest,
    agent: AgentService = Depends(get_agent_service),
):
    """Submit user feedback (satisfaction rating) on an assistant message."""
    updated = agent.submit_feedback(
        thread_id=thread_id,
        message_id=message_id,
        satisfaction=body.satisfaction,
        feedback=body.feedback,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"status": "ok"}


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads(
    limit: int = 50,
    offset: int = 0,
    agent: AgentService = Depends(get_agent_service),
):
    """List all chat threads, ordered by most recent update."""
    items, total = agent.list_threads(limit=limit, offset=offset)
    return ThreadListResponse(threads=items, total=total)


@router.get("/threads/{thread_id}", response_model=ChatThread)
async def get_thread(
    thread_id: str,
    agent: AgentService = Depends(get_agent_service),
):
    """Get a thread with all its messages."""
    thread = agent.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: str,
    agent: AgentService = Depends(get_agent_service),
):
    """Delete a thread and all its messages."""
    deleted = agent.delete_thread(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"status": "deleted", "thread_id": thread_id}


@router.get("/personas")
async def list_personas(
    agent: AgentService = Depends(get_agent_service),
):
    """List available chat personas for the frontend selector."""
    return {"personas": [p.model_dump() for p in agent.list_personas()]}


@router.get("/suggestions")
async def get_suggestions(
    svc: SuggestionService = Depends(get_suggestion_service),
):
    """Get personalized quick-start suggestions for the chat welcome screen."""
    try:
        suggestions = svc.get_quick_questions()
    except Exception:
        logger.debug("Suggestion generation failed, returning defaults")
        suggestions = [
            {
                "icon": "portfolio",
                "label": "持仓诊断",
                "prompt": "帮我诊断一下当前持仓组合",
            },
            {
                "icon": "market",
                "label": "盘面研判",
                "prompt": "今天大盘走势如何？有什么需要关注的？",
            },
        ]
    return {"suggestions": suggestions}

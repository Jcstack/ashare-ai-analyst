"""Chat API endpoints for the v12.0 Agent architecture.

Provides thread-based conversational interface to the Master Agent.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

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


@router.post("/threads", response_model=CreateThreadResponse)
async def create_thread(
    body: CreateThreadRequest,
    agent: AgentService = Depends(get_agent_service),
):
    """Create a new chat thread and send the first message."""
    try:
        thread_id, reply = await agent.create_thread(
            message=body.message,
            context=body.context,
            use_multi_agent=body.use_multi_agent,
            persona=body.persona,
        )
    except LLMProviderError as exc:
        logger.error("LLM provider unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="AI 服务暂时不可用，请检查 LLM 配置后重试。",
        )
    except Exception as exc:
        logger.exception("Failed to create thread: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="创建对话失败，请稍后重试。",
        )

    # Re-read thread to get title
    thread = agent.get_thread(thread_id)
    title = thread.title if thread else body.message[:50]

    return CreateThreadResponse(
        thread_id=thread_id,
        title=title,
        reply=reply,
    )


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

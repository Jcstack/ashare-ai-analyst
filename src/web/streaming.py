"""SSE streaming — Server-Sent Events for real-time Agent responses.

Part of v19.0 Production Hardening.

Provides async generators that yield SSE-formatted events for tool calls,
intermediate results, and final answers. Compatible with FastAPI's
StreamingResponse.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class SSEEventType(str, Enum):
    """Types of SSE events sent to the client."""

    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    ANSWER = "answer"
    ERROR = "error"
    DONE = "done"


@dataclass
class SSEEvent:
    """A single SSE event to be sent to the client."""

    event_type: SSEEventType
    data: dict[str, Any]
    event_id: str | None = None

    def format(self) -> str:
        """Format as SSE wire protocol.

        Returns a string like:
            event: tool_start
            data: {"tool": "get_stock_quote", "args": {...}}

        """
        lines: list[str] = []
        if self.event_id:
            lines.append(f"id: {self.event_id}")
        lines.append(f"event: {self.event_type.value}")
        lines.append(f"data: {json.dumps(self.data, ensure_ascii=False, default=str)}")
        lines.append("")  # Blank line terminates the event
        return "\n".join(lines) + "\n"


class StreamingSession:
    """Manages SSE event generation for a single streaming request.

    Usage:
        session = StreamingSession()
        session.emit_tool_start("get_stock_quote", {"symbol": "600519"})
        session.emit_tool_result("get_stock_quote", {"price": 1800.0})
        session.emit_answer("茅台当前价格 1800 元")
        session.emit_done()

        # Then iterate over session.events() to get SSEEvent objects
    """

    def __init__(self) -> None:
        self._events: list[SSEEvent] = []
        self._event_counter = 0

    def emit_tool_start(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> SSEEvent:
        """Record a tool invocation start."""
        event = self._make_event(
            SSEEventType.TOOL_START,
            {"tool": tool_name, "arguments": arguments or {}},
        )
        self._events.append(event)
        return event

    def emit_tool_result(
        self,
        tool_name: str,
        result: Any,
        duration_ms: float | None = None,
    ) -> SSEEvent:
        """Record a tool result."""
        data: dict[str, Any] = {"tool": tool_name, "result": result}
        if duration_ms is not None:
            data["duration_ms"] = round(duration_ms, 1)
        event = self._make_event(SSEEventType.TOOL_RESULT, data)
        self._events.append(event)
        return event

    def emit_thinking(self, content: str) -> SSEEvent:
        """Record an intermediate thinking step."""
        event = self._make_event(
            SSEEventType.THINKING,
            {"content": content},
        )
        self._events.append(event)
        return event

    def emit_answer(
        self,
        content: str,
        rich_cards: list[dict[str, Any]] | None = None,
    ) -> SSEEvent:
        """Record the final answer."""
        data: dict[str, Any] = {"content": content}
        if rich_cards:
            data["rich_cards"] = rich_cards
        event = self._make_event(SSEEventType.ANSWER, data)
        self._events.append(event)
        return event

    def emit_error(self, message: str, code: str = "internal") -> SSEEvent:
        """Record an error."""
        event = self._make_event(
            SSEEventType.ERROR,
            {"message": message, "code": code},
        )
        self._events.append(event)
        return event

    def emit_done(self) -> SSEEvent:
        """Signal that the stream is complete."""
        event = self._make_event(SSEEventType.DONE, {})
        self._events.append(event)
        return event

    def events(self) -> list[SSEEvent]:
        """Get all recorded events."""
        return list(self._events)

    def format_all(self) -> str:
        """Format all events as SSE wire protocol string."""
        return "".join(e.format() for e in self._events)

    def _make_event(
        self,
        event_type: SSEEventType,
        data: dict[str, Any],
    ) -> SSEEvent:
        self._event_counter += 1
        return SSEEvent(
            event_type=event_type,
            data=data,
            event_id=str(self._event_counter),
        )


async def stream_events(events: list[SSEEvent]) -> AsyncIterator[str]:
    """Async generator that yields SSE-formatted strings.

    Use with FastAPI StreamingResponse:
        return StreamingResponse(
            stream_events(session.events()),
            media_type="text/event-stream",
        )
    """
    for event in events:
        yield event.format()


def format_keepalive() -> str:
    """Format an SSE keepalive comment.

    Keeps the connection alive when no data is being sent.
    """
    return ": keepalive\n\n"

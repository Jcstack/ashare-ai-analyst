"""Tests for SSE streaming — Server-Sent Events for real-time Agent responses.

Part of v19.0 Production Hardening.
"""

from __future__ import annotations

import json

import pytest

from src.web.streaming import (
    SSEEvent,
    SSEEventType,
    StreamingSession,
    format_keepalive,
    stream_events,
)


class TestSSEEvent:
    """Tests for SSEEvent formatting."""

    def test_format_basic(self):
        event = SSEEvent(
            event_type=SSEEventType.ANSWER,
            data={"content": "hello"},
        )
        formatted = event.format()
        assert "event: answer\n" in formatted
        assert 'data: {"content": "hello"}\n' in formatted
        assert formatted.endswith("\n\n")

    def test_format_with_event_id(self):
        event = SSEEvent(
            event_type=SSEEventType.TOOL_START,
            data={"tool": "get_quote"},
            event_id="42",
        )
        formatted = event.format()
        assert "id: 42\n" in formatted
        assert "event: tool_start\n" in formatted

    def test_format_without_event_id(self):
        event = SSEEvent(
            event_type=SSEEventType.DONE,
            data={},
        )
        formatted = event.format()
        assert "id:" not in formatted

    def test_format_chinese_content(self):
        event = SSEEvent(
            event_type=SSEEventType.ANSWER,
            data={"content": "茅台当前价格 1800 元"},
        )
        formatted = event.format()
        assert "茅台当前价格 1800 元" in formatted

    def test_format_preserves_json_structure(self):
        data = {"tool": "get_quote", "arguments": {"symbol": "600519"}}
        event = SSEEvent(event_type=SSEEventType.TOOL_START, data=data)
        formatted = event.format()
        # Extract data line
        for line in formatted.split("\n"):
            if line.startswith("data: "):
                parsed = json.loads(line[6:])
                assert parsed == data
                break

    def test_all_event_types(self):
        """All event types should be formattable."""
        for event_type in SSEEventType:
            event = SSEEvent(event_type=event_type, data={"test": True})
            formatted = event.format()
            assert f"event: {event_type.value}\n" in formatted


class TestStreamingSession:
    """Tests for StreamingSession event accumulation."""

    def test_empty_session(self):
        session = StreamingSession()
        assert session.events() == []

    def test_emit_tool_start(self):
        session = StreamingSession()
        event = session.emit_tool_start("get_quote", {"symbol": "600519"})
        assert event.event_type == SSEEventType.TOOL_START
        assert event.data["tool"] == "get_quote"
        assert event.data["arguments"]["symbol"] == "600519"
        assert event.event_id == "1"

    def test_emit_tool_result(self):
        session = StreamingSession()
        event = session.emit_tool_result(
            "get_quote", {"price": 1800.0}, duration_ms=120.5
        )
        assert event.event_type == SSEEventType.TOOL_RESULT
        assert event.data["tool"] == "get_quote"
        assert event.data["result"]["price"] == 1800.0
        assert event.data["duration_ms"] == 120.5

    def test_emit_tool_result_no_duration(self):
        session = StreamingSession()
        event = session.emit_tool_result("get_quote", {"price": 1800.0})
        assert "duration_ms" not in event.data

    def test_emit_thinking(self):
        session = StreamingSession()
        event = session.emit_thinking("正在分析技术面...")
        assert event.event_type == SSEEventType.THINKING
        assert event.data["content"] == "正在分析技术面..."

    def test_emit_answer(self):
        session = StreamingSession()
        event = session.emit_answer("茅台近期偏弱")
        assert event.event_type == SSEEventType.ANSWER
        assert event.data["content"] == "茅台近期偏弱"

    def test_emit_answer_with_rich_cards(self):
        session = StreamingSession()
        cards = [{"type": "stock_analysis", "symbol": "600519"}]
        event = session.emit_answer("分析结果", rich_cards=cards)
        assert event.data["rich_cards"] == cards

    def test_emit_error(self):
        session = StreamingSession()
        event = session.emit_error("连接超时", code="timeout")
        assert event.event_type == SSEEventType.ERROR
        assert event.data["message"] == "连接超时"
        assert event.data["code"] == "timeout"

    def test_emit_done(self):
        session = StreamingSession()
        event = session.emit_done()
        assert event.event_type == SSEEventType.DONE
        assert event.data == {}

    def test_event_counter_increments(self):
        session = StreamingSession()
        e1 = session.emit_thinking("step 1")
        e2 = session.emit_thinking("step 2")
        e3 = session.emit_answer("done")
        assert e1.event_id == "1"
        assert e2.event_id == "2"
        assert e3.event_id == "3"

    def test_events_list(self):
        session = StreamingSession()
        session.emit_tool_start("tool_a")
        session.emit_tool_result("tool_a", {})
        session.emit_answer("result")
        session.emit_done()
        assert len(session.events()) == 4

    def test_events_returns_copy(self):
        session = StreamingSession()
        session.emit_done()
        events = session.events()
        events.clear()
        assert len(session.events()) == 1  # Original unchanged

    def test_format_all(self):
        session = StreamingSession()
        session.emit_thinking("step 1")
        session.emit_answer("result")
        session.emit_done()
        formatted = session.format_all()
        assert "event: thinking\n" in formatted
        assert "event: answer\n" in formatted
        assert "event: done\n" in formatted

    def test_full_workflow(self):
        """Simulate a complete agent response workflow."""
        session = StreamingSession()
        session.emit_tool_start("get_stock_quote", {"symbol": "600519"})
        session.emit_tool_result("get_stock_quote", {"price": 1800.0}, duration_ms=85.2)
        session.emit_thinking("正在综合分析...")
        session.emit_answer("茅台当前价格 1800 元，建议观望。")
        session.emit_done()

        events = session.events()
        assert len(events) == 5
        assert events[0].event_type == SSEEventType.TOOL_START
        assert events[1].event_type == SSEEventType.TOOL_RESULT
        assert events[2].event_type == SSEEventType.THINKING
        assert events[3].event_type == SSEEventType.ANSWER
        assert events[4].event_type == SSEEventType.DONE


class TestStreamEvents:
    """Tests for the async generator."""

    @pytest.mark.anyio
    async def test_stream_events(self):
        session = StreamingSession()
        session.emit_answer("hello")
        session.emit_done()

        chunks = []
        async for chunk in stream_events(session.events()):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert "event: answer\n" in chunks[0]
        assert "event: done\n" in chunks[1]

    @pytest.mark.anyio
    async def test_stream_empty(self):
        chunks = []
        async for chunk in stream_events([]):
            chunks.append(chunk)
        assert chunks == []


class TestKeepalive:
    """Tests for keepalive formatting."""

    def test_format_keepalive(self):
        ka = format_keepalive()
        assert ka == ": keepalive\n\n"
        assert ka.startswith(":")  # SSE comment

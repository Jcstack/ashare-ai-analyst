"""Tests for the Master Agent service."""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

from src.llm.base import LLMToolResponse, ProviderName, ToolCall
from src.web.schemas.chat import ThreadContext
from src.web.services.agent_service import AgentService
from src.web.services.tool_registry import ToolRegistry


def _make_service(tmp_path: Path) -> tuple[AgentService, MagicMock, ToolRegistry]:
    """Create an AgentService with mocked LLM router."""
    mock_router = MagicMock()
    registry = ToolRegistry()
    # Register a simple test tool
    registry.register(
        name="get_realtime_quote",
        description="Get quote",
        input_schema={
            "type": "object",
            "properties": {"symbols": {"type": "array", "items": {"type": "string"}}},
            "required": ["symbols"],
        },
        handler=lambda symbols: {
            s: {"price": 100.0, "change_pct": 1.5} for s in symbols
        },
    )
    service = AgentService(
        llm_router=mock_router,
        tool_registry=registry,
        db_path=tmp_path / "test_agent.db",
    )
    return service, mock_router, registry


class TestAgentServiceDB:
    """Test database operations."""

    def test_ensure_db_creates_tables(self, tmp_path):
        """Database tables are created on init."""
        service, _, _ = _make_service(tmp_path)
        conn = service._connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "threads" in table_names
        assert "messages" in table_names
        assert "trades" in table_names
        assert "recommendations" in table_names
        conn.close()

    def test_create_thread_end_turn(self, tmp_path):
        """Create thread with immediate end_turn response."""
        service, mock_router, _ = _make_service(tmp_path)

        # Mock LLM to return immediate text reply
        mock_router.complete_with_tools.return_value = LLMToolResponse(
            text="茅台最近走势偏弱，建议观望。",
            tool_calls=[],
            stop_reason="end_turn",
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=50,
        )

        thread_id, reply = asyncio.run(service.create_thread(message="帮我看看茅台"))

        assert thread_id
        assert reply.role == "assistant"
        assert "茅台" in reply.content or "观望" in reply.content

        # Thread should be persisted
        thread = service.get_thread(thread_id)
        assert thread is not None
        assert len(thread.messages) == 2  # user + assistant
        assert thread.messages[0].role == "user"
        assert thread.messages[1].role == "assistant"

    def test_create_thread_with_tool_call(self, tmp_path):
        """Create thread where agent calls a tool before replying."""
        service, mock_router, _ = _make_service(tmp_path)

        # First call: agent requests tool use
        tool_response = LLMToolResponse(
            text=None,
            tool_calls=[
                ToolCall(
                    id="call_123",
                    name="get_realtime_quote",
                    input={"symbols": ["600519"]},
                )
            ],
            stop_reason="tool_use",
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
        )

        # Second call: agent produces final reply
        final_response = LLMToolResponse(
            text="茅台当前价格100元，涨幅1.5%，走势偏强。",
            tool_calls=[],
            stop_reason="end_turn",
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
        )

        mock_router.complete_with_tools.side_effect = [tool_response, final_response]

        thread_id, reply = asyncio.run(service.create_thread(message="茅台现在多少钱"))

        assert reply.role == "assistant"
        assert "100" in reply.content or "茅台" in reply.content

        # Should have called LLM twice (tool_use + end_turn)
        assert mock_router.complete_with_tools.call_count == 2

        # Reply should have tool call records
        assert reply.tool_calls is not None
        assert len(reply.tool_calls) == 1
        assert reply.tool_calls[0].tool_name == "get_realtime_quote"

    def test_send_message_followup(self, tmp_path):
        """Send a follow-up message in an existing thread."""
        service, mock_router, _ = _make_service(tmp_path)

        # Create thread first
        mock_router.complete_with_tools.return_value = LLMToolResponse(
            text="好的，我来帮你看看。",
            tool_calls=[],
            stop_reason="end_turn",
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
        )

        thread_id, _ = asyncio.run(service.create_thread(message="你好"))

        # Send follow-up
        mock_router.complete_with_tools.return_value = LLMToolResponse(
            text="请告诉我你想了解哪只股票。",
            tool_calls=[],
            stop_reason="end_turn",
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
        )

        reply = asyncio.run(service.send_message(thread_id, "帮我分析一下"))

        assert reply.role == "assistant"

        # Thread should now have 4 messages (2 from create + 2 from followup)
        thread = service.get_thread(thread_id)
        assert len(thread.messages) == 4

    def test_list_threads(self, tmp_path):
        """List threads returns items ordered by most recent."""
        service, _, _ = _make_service(tmp_path)

        # Insert some threads directly
        conn = service._connect()
        for i in range(3):
            conn.execute(
                "INSERT INTO threads (id, title, context, created_at, updated_at) "
                "VALUES (?, ?, NULL, ?, ?)",
                (
                    f"thread_{i}",
                    f"Thread {i}",
                    f"2026-02-14T{10 + i}:00:00Z",
                    f"2026-02-14T{10 + i}:00:00Z",
                ),
            )
        conn.commit()
        conn.close()

        items, total = service.list_threads()
        assert len(items) == 3
        assert total == 3
        # Most recent first
        assert items[0].id == "thread_2"

    def test_delete_thread(self, tmp_path):
        """Delete thread removes it and its messages."""
        service, _, _ = _make_service(tmp_path)

        conn = service._connect()
        conn.execute(
            "INSERT INTO threads (id, title, context, created_at, updated_at) "
            "VALUES ('t1', 'Test', NULL, '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO messages (id, thread_id, role, content, timestamp) "
            "VALUES ('m1', 't1', 'user', 'hello', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        assert service.delete_thread("t1") is True
        assert service.get_thread("t1") is None
        assert service.delete_thread("t1") is False  # Already deleted

    def test_rich_cards_extraction(self, tmp_path):
        """Rich cards are extracted from the <!--RICH_CARDS:...--> marker."""
        service, mock_router, _ = _make_service(tmp_path)

        cards_json = json.dumps(
            [
                {
                    "type": "stock_analysis",
                    "props": {"symbol": "600519", "signal": "bearish"},
                }
            ]
        )
        text_with_cards = f"茅台走势偏弱。\n\n<!--RICH_CARDS:{cards_json}-->"

        mock_router.complete_with_tools.return_value = LLMToolResponse(
            text=text_with_cards,
            tool_calls=[],
            stop_reason="end_turn",
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
        )

        _, reply = asyncio.run(service.create_thread(message="分析茅台"))

        # Rich cards should be extracted
        assert reply.rich_cards is not None
        assert len(reply.rich_cards) == 1
        assert reply.rich_cards[0].type == "stock_analysis"
        assert reply.rich_cards[0].props["symbol"] == "600519"

        # Text should have the marker stripped
        assert "RICH_CARDS" not in reply.content

    def test_max_tool_rounds(self, tmp_path):
        """Agent loop stops after max rounds to prevent infinite loops."""
        service, mock_router, _ = _make_service(tmp_path)

        # Always return tool_use, never end_turn
        mock_router.complete_with_tools.return_value = LLMToolResponse(
            text="Still thinking...",
            tool_calls=[
                ToolCall(
                    id="call_loop",
                    name="get_realtime_quote",
                    input={"symbols": ["000001"]},
                )
            ],
            stop_reason="tool_use",
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
        )

        _, reply = asyncio.run(service.create_thread(message="test"))

        # Should have been called MAX_TOOL_ROUNDS times (10)
        assert mock_router.complete_with_tools.call_count == 10
        # Reply should still be returned (last text from the response)
        assert reply.content

    def test_create_thread_with_context(self, tmp_path):
        """Thread context is persisted."""
        service, mock_router, _ = _make_service(tmp_path)

        mock_router.complete_with_tools.return_value = LLMToolResponse(
            text="OK",
            tool_calls=[],
            stop_reason="end_turn",
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
        )

        ctx = ThreadContext(symbol="600519", mode="stock")
        thread_id, _ = asyncio.run(service.create_thread(message="分析", context=ctx))

        thread = service.get_thread(thread_id)
        assert thread.context is not None
        assert thread.context.symbol == "600519"
        assert thread.context.mode == "stock"


class TestLLMToolResponse:
    """Test LLMToolResponse data class."""

    def test_end_turn_response(self):
        """LLMToolResponse with end_turn has text and no tool calls."""
        resp = LLMToolResponse(
            text="Hello",
            tool_calls=[],
            stop_reason="end_turn",
            provider=ProviderName.ANTHROPIC,
            model="test",
        )
        assert resp.text == "Hello"
        assert resp.tool_calls == []
        assert resp.stop_reason == "end_turn"

    def test_tool_use_response(self):
        """LLMToolResponse with tool_use has tool calls."""
        resp = LLMToolResponse(
            text=None,
            tool_calls=[
                ToolCall(id="1", name="test", input={"x": 1}),
            ],
            stop_reason="tool_use",
            provider=ProviderName.ANTHROPIC,
            model="test",
        )
        assert resp.text is None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "test"

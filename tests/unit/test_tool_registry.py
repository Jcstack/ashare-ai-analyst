"""Tests for the agent tool registry."""

import asyncio
import json

from src.web.services.tool_registry import ToolRegistry


class TestToolRegistry:
    """Test ToolRegistry registration and execution."""

    def test_register_and_list_definitions(self):
        """Registering a tool makes it appear in definitions."""
        registry = ToolRegistry()
        registry.register(
            name="test_tool",
            description="A test tool",
            input_schema={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            },
            handler=lambda x: {"result": x * 2},
        )

        defs = registry.get_tool_definitions()
        assert len(defs) == 1
        assert defs[0]["name"] == "test_tool"
        assert defs[0]["description"] == "A test tool"
        assert "x" in defs[0]["input_schema"]["properties"]

    def test_execute_sync_handler(self):
        """Execute a sync handler via the registry."""
        registry = ToolRegistry()
        registry.register(
            name="add",
            description="Add two numbers",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
            handler=lambda a, b: {"sum": a + b},
        )

        result_str = asyncio.run(registry.execute("add", {"a": 3, "b": 5}))
        result = json.loads(result_str)
        assert result["sum"] == 8

    def test_execute_async_handler(self):
        """Execute an async handler via the registry."""

        async def async_handler(name: str) -> dict:
            return {"greeting": f"Hello, {name}!"}

        registry = ToolRegistry()
        registry.register(
            name="greet",
            description="Greet someone",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            handler=async_handler,
            is_async=True,
        )

        result_str = asyncio.run(registry.execute("greet", {"name": "Alice"}))
        result = json.loads(result_str)
        assert result["greeting"] == "Hello, Alice!"

    def test_execute_unknown_tool(self):
        """Executing an unknown tool returns an error JSON."""
        registry = ToolRegistry()
        result_str = asyncio.run(registry.execute("nonexistent", {}))
        result = json.loads(result_str)
        assert "error" in result
        assert "nonexistent" in result["error"]

    def test_execute_handler_error(self):
        """Handler errors are caught and returned as JSON."""
        registry = ToolRegistry()
        registry.register(
            name="failing",
            description="Always fails",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: 1 / 0,
        )

        result_str = asyncio.run(registry.execute("failing", {}))
        result = json.loads(result_str)
        assert "error" in result
        assert "failing" == result["tool"]

    def test_register_all_with_empty_deps(self):
        """register_all with empty deps registers only dep-free tools."""
        registry = ToolRegistry()
        registry.register_all({})
        defs = registry.get_tool_definitions()
        # get_portfolio is always registered (reads file, no service dep)
        names = {d["name"] for d in defs}
        assert "get_portfolio" in names

    def test_multiple_tools(self):
        """Multiple tools can be registered."""
        registry = ToolRegistry()
        for i in range(5):
            registry.register(
                name=f"tool_{i}",
                description=f"Tool {i}",
                input_schema={"type": "object", "properties": {}},
                handler=lambda: {"ok": True},
            )

        defs = registry.get_tool_definitions()
        assert len(defs) == 5
        names = {d["name"] for d in defs}
        assert names == {f"tool_{i}" for i in range(5)}

    def test_serialize_pydantic_model(self):
        """Pydantic model results are serialized correctly."""
        from pydantic import BaseModel

        class Result(BaseModel):
            value: int
            label: str

        registry = ToolRegistry()
        registry.register(
            name="pydantic_tool",
            description="Returns a Pydantic model",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: Result(value=42, label="answer"),
        )

        result_str = asyncio.run(registry.execute("pydantic_tool", {}))
        result = json.loads(result_str)
        assert result["value"] == 42
        assert result["label"] == "answer"

    def test_serialize_list_result(self):
        """List results are serialized correctly."""
        registry = ToolRegistry()
        registry.register(
            name="list_tool",
            description="Returns a list",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: [1, 2, 3],
        )

        result_str = asyncio.run(registry.execute("list_tool", {}))
        result = json.loads(result_str)
        assert result == [1, 2, 3]

    def test_serialize_string_result(self):
        """String results are returned as-is."""
        registry = ToolRegistry()
        registry.register(
            name="str_tool",
            description="Returns a string",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: "hello world",
        )

        result_str = asyncio.run(registry.execute("str_tool", {}))
        assert result_str == "hello world"

    def test_register_prediction_tools(self):
        """Prediction tools are registered when services are provided."""
        from unittest.mock import MagicMock

        registry = ToolRegistry()

        # Create mock services with the methods the registry expects
        advisor_svc = MagicMock()
        advisor_svc.get_stock_advice = MagicMock(return_value={"signal": "buy"})
        advisor_svc.get_portfolio_advice = MagicMock(return_value={"health": "good"})
        advisor_svc.get_holiday_impact = MagicMock(return_value={"impact": "low"})

        sentiment_svc = MagicMock()
        sentiment_svc.get_market_pulse = MagicMock(return_value={"mood": "neutral"})

        prediction_svc = MagicMock()
        prediction_svc.predict = MagicMock(return_value={"trend": "up"})

        backtest_svc = MagicMock()
        backtest_svc.run_backtest = MagicMock(return_value={"status": "ok"})

        registry.register_all(
            {
                "advisor_service": advisor_svc,
                "sentiment_service": sentiment_svc,
                "prediction_service": prediction_svc,
                "backtest_service": backtest_svc,
            }
        )

        defs = registry.get_tool_definitions()
        names = {d["name"] for d in defs}

        assert "get_stock_advice" in names
        assert "get_portfolio_advice" in names
        assert "get_holiday_impact" in names
        assert "get_sentiment_report" in names
        assert "analyze_stock_detailed" in names
        assert "backtest_strategy" in names

    def test_prediction_tools_definitions_have_required_fields(self):
        """Each prediction tool definition has name, description, and input_schema."""
        from unittest.mock import MagicMock

        registry = ToolRegistry()

        advisor_svc = MagicMock()
        sentiment_svc = MagicMock()
        prediction_svc = MagicMock()
        backtest_svc = MagicMock()

        registry.register_all(
            {
                "advisor_service": advisor_svc,
                "sentiment_service": sentiment_svc,
                "prediction_service": prediction_svc,
                "backtest_service": backtest_svc,
            }
        )

        prediction_tool_names = {
            "get_stock_advice",
            "get_portfolio_advice",
            "get_holiday_impact",
            "get_sentiment_report",
            "analyze_stock_detailed",
            "backtest_strategy",
        }

        defs = registry.get_tool_definitions()
        for d in defs:
            if d["name"] in prediction_tool_names:
                assert "description" in d and len(d["description"]) > 0
                assert "input_schema" in d
                assert d["input_schema"]["type"] == "object"

    def test_prediction_tool_execute_stock_advice(self):
        """get_stock_advice tool executes and returns serialized result."""
        from unittest.mock import MagicMock

        registry = ToolRegistry()
        advisor_svc = MagicMock()
        advisor_svc.get_stock_advice = MagicMock(
            return_value={"signal": "buy", "confidence": 0.72}
        )

        registry.register_all({"advisor_service": advisor_svc})

        result_str = asyncio.run(
            registry.execute("get_stock_advice", {"symbol": "600519"})
        )
        result = json.loads(result_str)
        assert result["signal"] == "buy"
        advisor_svc.get_stock_advice.assert_called_once_with("600519")

    def test_prediction_tool_execute_backtest(self):
        """backtest_strategy tool executes with correct parameters."""
        from unittest.mock import MagicMock

        registry = ToolRegistry()
        backtest_svc = MagicMock()
        backtest_svc.run_backtest = MagicMock(
            return_value={"status": "ok", "metrics": {"sharpe": 1.5}}
        )

        registry.register_all({"backtest_service": backtest_svc})

        result_str = asyncio.run(
            registry.execute(
                "backtest_strategy",
                {"symbol": "600519", "strategy_key": "trend_following"},
            )
        )
        result = json.loads(result_str)
        assert result["status"] == "ok"
        backtest_svc.run_backtest.assert_called_once_with(
            symbol="600519", strategy_key="trend_following"
        )

    def test_prediction_tool_execute_sentiment(self):
        """get_sentiment_report tool executes with optional watchlist."""
        from unittest.mock import MagicMock

        registry = ToolRegistry()
        sentiment_svc = MagicMock()
        sentiment_svc.get_market_pulse = MagicMock(
            return_value={"mood": "bullish", "score": 65}
        )

        registry.register_all({"sentiment_service": sentiment_svc})

        result_str = asyncio.run(
            registry.execute(
                "get_sentiment_report", {"watchlist": ["600519", "300750"]}
            )
        )
        result = json.loads(result_str)
        assert result["mood"] == "bullish"
        sentiment_svc.get_market_pulse.assert_called_once_with(
            watchlist=["600519", "300750"]
        )

"""Tests for src.llm.gateway — LLMGateway governance wrapper."""

import threading
import time
from unittest.mock import MagicMock

import pytest

from src.llm.base import (
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    LLMToolResponse,
    ProviderName,
)
from src.llm.gateway import EVENT_LLM_CALL, LLMGateway


def _make_response(**kwargs):
    defaults = {
        "text": "hello",
        "provider": ProviderName.CLAUDE_CODE,
        "model": "claude_code:sonnet",
        "input_tokens": 10,
        "output_tokens": 20,
        "latency_ms": 100.0,
        "cost_usd": 0.001,
    }
    defaults.update(kwargs)
    return LLMResponse(**defaults)


def _make_tool_response(**kwargs):
    defaults = {
        "text": "tool result",
        "tool_calls": [],
        "stop_reason": "end_turn",
        "provider": ProviderName.CLAUDE_CODE,
        "model": "claude_code:sonnet",
        "input_tokens": 10,
        "output_tokens": 20,
        "latency_ms": 100.0,
        "cost_usd": 0.001,
    }
    defaults.update(kwargs)
    return LLMToolResponse(**defaults)


class TestLLMGatewayComplete:
    """Tests for LLMGateway.complete()."""

    def test_complete_delegates_to_router(self):
        router = MagicMock()
        expected = _make_response()
        router.complete.return_value = expected

        gw = LLMGateway(router=router)
        msgs = [LLMMessage(role="user", content="test")]
        result = gw.complete(msgs, caller="test_caller")

        assert result is expected
        router.complete.assert_called_once()

    def test_complete_passes_all_kwargs(self):
        router = MagicMock()
        router.complete.return_value = _make_response()

        gw = LLMGateway(router=router)
        msgs = [LLMMessage(role="user", content="test")]
        gw.complete(
            msgs,
            caller="svc.method",
            max_tokens=2048,
            temperature=0.5,
            symbol="600519",
            analysis_type="unified",
        )

        call_kwargs = router.complete.call_args.kwargs
        assert call_kwargs["max_tokens"] == 2048
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["symbol"] == "600519"
        assert call_kwargs["analysis_type"] == "unified"

    def test_complete_records_audit_log(self):
        router = MagicMock()
        router.complete.return_value = _make_response()
        audit = MagicMock()

        gw = LLMGateway(router=router, audit_log=audit)
        msgs = [LLMMessage(role="user", content="test")]
        gw.complete(msgs, caller="test_svc")

        audit.log.assert_called_once()
        call_args = audit.log.call_args
        # Gateway calls: self._audit_log.log(EVENT_LLM_CALL, payload=payload, actor=caller)
        assert call_args.args[0] == EVENT_LLM_CALL
        payload = call_args.kwargs["payload"]
        assert payload["caller"] == "test_svc"
        assert payload["success"] is True
        assert payload["call_type"] == "complete"
        assert payload["provider"] == ProviderName.CLAUDE_CODE.value
        assert payload["model"] == "claude_code:sonnet"
        assert payload["input_tokens"] == 10
        assert payload["output_tokens"] == 20
        assert "elapsed_ms" in payload

    def test_complete_wraps_generic_exception(self):
        router = MagicMock()
        router.complete.side_effect = ValueError("boom")

        gw = LLMGateway(router=router)
        msgs = [LLMMessage(role="user", content="test")]

        with pytest.raises(LLMProviderError, match="Gateway error"):
            gw.complete(msgs, caller="test")

    def test_complete_passes_through_llm_error(self):
        router = MagicMock()
        router.complete.side_effect = LLMProviderError("provider down")

        gw = LLMGateway(router=router)
        msgs = [LLMMessage(role="user", content="test")]

        with pytest.raises(LLMProviderError, match="provider down"):
            gw.complete(msgs, caller="test")

    def test_complete_logs_error_on_failure(self):
        router = MagicMock()
        router.complete.side_effect = LLMProviderError("fail")
        audit = MagicMock()

        gw = LLMGateway(router=router, audit_log=audit)
        msgs = [LLMMessage(role="user", content="test")]

        with pytest.raises(LLMProviderError):
            gw.complete(msgs, caller="test")

        audit.log.assert_called_once()
        payload = audit.log.call_args.kwargs["payload"]
        assert payload["success"] is False
        assert "fail" in payload["error"]

    def test_complete_audit_log_failure_does_not_raise(self):
        """If audit_log.log() itself raises, the gateway should not propagate it."""
        router = MagicMock()
        router.complete.return_value = _make_response()
        audit = MagicMock()
        audit.log.side_effect = RuntimeError("audit broken")

        gw = LLMGateway(router=router, audit_log=audit)
        msgs = [LLMMessage(role="user", content="test")]
        # Should succeed despite audit failure
        result = gw.complete(msgs, caller="test")
        assert result.text == "hello"

    def test_complete_no_audit_log_still_works(self):
        """Gateway without audit_log should work fine."""
        router = MagicMock()
        router.complete.return_value = _make_response()

        gw = LLMGateway(router=router)  # no audit_log
        msgs = [LLMMessage(role="user", content="test")]
        result = gw.complete(msgs, caller="test")
        assert result.text == "hello"


class TestLLMGatewayCompleteWithTools:
    """Tests for LLMGateway.complete_with_tools()."""

    def test_complete_with_tools_delegates(self):
        router = MagicMock()
        expected = _make_tool_response()
        router.complete_with_tools.return_value = expected

        gw = LLMGateway(router=router)
        msgs = [LLMMessage(role="user", content="test")]
        tools = [{"name": "get_quote", "description": "Get stock quote"}]
        result = gw.complete_with_tools(msgs, tools, caller="agent")

        assert result is expected
        router.complete_with_tools.assert_called_once()

    def test_complete_with_tools_passes_kwargs(self):
        router = MagicMock()
        router.complete_with_tools.return_value = _make_tool_response()

        gw = LLMGateway(router=router)
        msgs = [LLMMessage(role="user", content="test")]
        tools = [{"name": "lookup"}]
        gw.complete_with_tools(
            msgs,
            tools,
            caller="agent",
            preferred_provider=ProviderName.ANTHROPIC,
            max_tokens=1024,
            temperature=0.1,
            symbol="000001",
            analysis_type="tool_call",
        )

        call_kwargs = router.complete_with_tools.call_args.kwargs
        assert call_kwargs["preferred_provider"] == ProviderName.ANTHROPIC
        assert call_kwargs["max_tokens"] == 1024
        assert call_kwargs["temperature"] == 0.1
        assert call_kwargs["symbol"] == "000001"

    def test_complete_with_tools_records_audit(self):
        router = MagicMock()
        router.complete_with_tools.return_value = _make_tool_response()
        audit = MagicMock()

        gw = LLMGateway(router=router, audit_log=audit)
        msgs = [LLMMessage(role="user", content="test")]
        gw.complete_with_tools(msgs, [], caller="agent.tool")

        audit.log.assert_called_once()
        payload = audit.log.call_args.kwargs["payload"]
        assert payload["call_type"] == "complete_with_tools"
        assert payload["caller"] == "agent.tool"
        assert payload["success"] is True

    def test_complete_with_tools_wraps_generic_exception(self):
        router = MagicMock()
        router.complete_with_tools.side_effect = TypeError("bad tools")

        gw = LLMGateway(router=router)
        msgs = [LLMMessage(role="user", content="test")]

        with pytest.raises(LLMProviderError, match="Gateway error"):
            gw.complete_with_tools(msgs, [], caller="agent")

    def test_complete_with_tools_passes_through_llm_error(self):
        router = MagicMock()
        router.complete_with_tools.side_effect = LLMProviderError("tool fail")

        gw = LLMGateway(router=router)
        msgs = [LLMMessage(role="user", content="test")]

        with pytest.raises(LLMProviderError, match="tool fail"):
            gw.complete_with_tools(msgs, [], caller="agent")


class TestHashMessages:
    """Tests for message hashing (dedup key)."""

    def test_same_messages_same_hash(self):
        msgs = [LLMMessage(role="user", content="hello")]
        h1 = LLMGateway._hash_messages(msgs)
        h2 = LLMGateway._hash_messages(msgs)
        assert h1 == h2

    def test_different_messages_different_hash(self):
        m1 = [LLMMessage(role="user", content="hello")]
        m2 = [LLMMessage(role="user", content="world")]
        assert LLMGateway._hash_messages(m1) != LLMGateway._hash_messages(m2)

    def test_different_roles_different_hash(self):
        m1 = [LLMMessage(role="user", content="hello")]
        m2 = [LLMMessage(role="assistant", content="hello")]
        assert LLMGateway._hash_messages(m1) != LLMGateway._hash_messages(m2)

    def test_hash_is_16_hex_chars(self):
        msgs = [LLMMessage(role="user", content="test")]
        h = LLMGateway._hash_messages(msgs)
        assert len(h) == 16
        # Verify it's valid hex
        int(h, 16)

    def test_multi_message_hash_deterministic(self):
        msgs = [
            LLMMessage(role="system", content="You are helpful."),
            LLMMessage(role="user", content="Analyze 600519"),
        ]
        h1 = LLMGateway._hash_messages(msgs)
        h2 = LLMGateway._hash_messages(msgs)
        assert h1 == h2

    def test_hash_handles_list_content(self):
        """Messages with list content (tool_use blocks) should hash correctly."""
        msgs = [LLMMessage(role="user", content=[{"type": "text", "text": "hello"}])]
        h = LLMGateway._hash_messages(msgs)
        assert len(h) == 16


class TestInFlightDedup:
    """Tests for in-flight request deduplication."""

    def test_concurrent_identical_calls_dedup(self):
        """Two threads with identical messages should result in one router call."""
        router = MagicMock()
        call_count = {"n": 0}
        response = _make_response()

        def slow_complete(**kwargs):
            call_count["n"] += 1
            time.sleep(0.15)
            return response

        router.complete.side_effect = slow_complete

        gw = LLMGateway(router=router)
        msgs = [LLMMessage(role="user", content="same message")]
        results = [None, None]
        errors = [None, None]

        def call(idx):
            try:
                results[idx] = gw.complete(msgs, caller=f"thread-{idx}")
            except Exception as e:
                errors[idx] = e

        t1 = threading.Thread(target=call, args=(0,))
        t2 = threading.Thread(target=call, args=(1,))
        t1.start()
        time.sleep(0.02)  # Ensure t1 acquires the dedup slot first
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # Both should get the same result
        assert results[0] is response
        assert results[1] is response
        assert errors[0] is None
        assert errors[1] is None
        # Router should be called only once (dedup)
        assert call_count["n"] == 1

    def test_concurrent_identical_calls_error_propagates(self):
        """If the first call errors, the waiting thread should also get the error."""
        router = MagicMock()
        err = LLMProviderError("all providers down")

        def slow_fail(**kwargs):
            time.sleep(0.1)
            raise err

        router.complete.side_effect = slow_fail

        gw = LLMGateway(router=router)
        msgs = [LLMMessage(role="user", content="same message")]
        errors = [None, None]

        def call(idx):
            try:
                gw.complete(msgs, caller=f"thread-{idx}")
            except Exception as e:
                errors[idx] = e

        t1 = threading.Thread(target=call, args=(0,))
        t2 = threading.Thread(target=call, args=(1,))
        t1.start()
        time.sleep(0.02)
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # Both threads should have received an error
        assert errors[0] is not None
        assert errors[1] is not None
        assert isinstance(errors[0], LLMProviderError)
        assert isinstance(errors[1], LLMProviderError)

    def test_different_messages_no_dedup(self):
        """Different messages should not be deduplicated."""
        router = MagicMock()
        router.complete.return_value = _make_response()

        gw = LLMGateway(router=router)
        m1 = [LLMMessage(role="user", content="first")]
        m2 = [LLMMessage(role="user", content="second")]

        gw.complete(m1, caller="a")
        gw.complete(m2, caller="b")

        assert router.complete.call_count == 2

    def test_dedup_slot_cleaned_up_after_call(self):
        """After a call completes, the dedup slot should be removed so
        subsequent identical calls go through normally."""
        router = MagicMock()
        router.complete.return_value = _make_response()

        gw = LLMGateway(router=router)
        msgs = [LLMMessage(role="user", content="repeat")]

        gw.complete(msgs, caller="first")
        gw.complete(msgs, caller="second")

        # Two sequential calls = two router calls (no dedup for sequential)
        assert router.complete.call_count == 2
        # Inflight map should be empty
        assert len(gw._inflight) == 0


class TestProxyProperties:
    """Test that proxy properties delegate to router."""

    def test_available_providers(self):
        router = MagicMock()
        router.available_providers = [ProviderName.CLAUDE_CODE]
        gw = LLMGateway(router=router)
        assert gw.available_providers == [ProviderName.CLAUDE_CODE]

    def test_usage_tracker(self):
        router = MagicMock()
        tracker = MagicMock()
        router.usage_tracker = tracker
        gw = LLMGateway(router=router)
        assert gw.usage_tracker is tracker

    def test_get_provider(self):
        router = MagicMock()
        provider = MagicMock()
        router.get_provider.return_value = provider
        gw = LLMGateway(router=router)
        assert gw.get_provider(ProviderName.ANTHROPIC) is provider
        router.get_provider.assert_called_once_with(ProviderName.ANTHROPIC)

    def test_select_provider(self):
        from src.llm.router import RoutingStrategy

        router = MagicMock()
        decision = MagicMock()
        router.select_provider.return_value = decision
        gw = LLMGateway(router=router)
        assert gw.select_provider(RoutingStrategy.COST) is decision
        router.select_provider.assert_called_once_with(RoutingStrategy.COST)


class TestDefaultTimeout:
    """Test default_timeout parameter."""

    def test_default_timeout_value(self):
        router = MagicMock()
        gw = LLMGateway(router=router)
        assert gw._default_timeout == 360.0

    def test_custom_timeout(self):
        router = MagicMock()
        gw = LLMGateway(router=router, default_timeout=30.0)
        assert gw._default_timeout == 30.0


class TestCallerModelRouting:
    """Tests for caller-based model routing (I-065)."""

    def _make_gw(self, caller_map: dict[str, str]) -> LLMGateway:
        router = MagicMock()
        router.complete.return_value = _make_response()
        router.complete_with_tools.return_value = _make_tool_response()
        gw = LLMGateway(router=router)
        gw._caller_model_map = caller_map
        return gw

    def test_resolve_exact_match(self):
        gw = self._make_gw({"conversation_service": "gemini-2.5-flash"})
        assert (
            gw._resolve_caller_model("conversation_service.followup")
            == "gemini-2.5-flash"
        )

    def test_resolve_prefix_match(self):
        gw = self._make_gw({"holiday_research": "gemini-2.5-flash"})
        assert gw._resolve_caller_model("holiday_research.qa") == "gemini-2.5-flash"
        assert (
            gw._resolve_caller_model("holiday_research.scenarios") == "gemini-2.5-flash"
        )

    def test_resolve_longest_prefix_wins(self):
        gw = self._make_gw(
            {
                "trading_advisor": "gemini-2.5-flash",
                "trading_advisor.generate_reopen_briefing": "gemini-2.0-flash",
            }
        )
        # Specific prefix should win over general
        assert (
            gw._resolve_caller_model("trading_advisor.generate_reopen_briefing")
            == "gemini-2.0-flash"
        )
        # General prefix still works for other methods
        assert (
            gw._resolve_caller_model("trading_advisor.advise_stock")
            == "gemini-2.5-flash"
        )

    def test_resolve_no_match_returns_none(self):
        gw = self._make_gw({"conversation_service": "gemini-2.5-flash"})
        assert gw._resolve_caller_model("review_agent.review_candidates") is None
        assert gw._resolve_caller_model("unknown_caller") is None

    def test_resolve_empty_caller(self):
        gw = self._make_gw({"conversation_service": "gemini-2.5-flash"})
        assert gw._resolve_caller_model("") is None

    def test_resolve_empty_map(self):
        gw = self._make_gw({})
        assert gw._resolve_caller_model("conversation_service.followup") is None

    def test_complete_passes_model_override(self):
        gw = self._make_gw({"move_analyzer": "gemini-2.5-flash"})
        msgs = [LLMMessage(role="user", content="test")]
        gw.complete(msgs, caller="move_analyzer.analyze_move")

        call_kwargs = gw._router.complete.call_args.kwargs
        assert call_kwargs["model"] == "gemini-2.5-flash"

    def test_complete_no_override_passes_none(self):
        gw = self._make_gw({"move_analyzer": "gemini-2.5-flash"})
        msgs = [LLMMessage(role="user", content="test")]
        gw.complete(msgs, caller="review_agent.review_candidates")

        call_kwargs = gw._router.complete.call_args.kwargs
        assert call_kwargs["model"] is None

    def test_complete_with_tools_passes_model_override(self):
        gw = self._make_gw({"backtest_interpret": "gemini-2.5-flash"})
        msgs = [LLMMessage(role="user", content="test")]
        tools = [{"name": "test_tool"}]
        gw.complete_with_tools(
            msgs, tools, caller="backtest_interpret.interpret_backtest"
        )

        call_kwargs = gw._router.complete_with_tools.call_args.kwargs
        assert call_kwargs["model"] == "gemini-2.5-flash"

    def test_load_caller_model_map_from_config(self, monkeypatch):
        """Verify _load_caller_model_map reads from config."""
        mock_config = {
            "caller_model_map": {
                "move_analyzer": "gemini-2.5-flash",
                "sentiment_report": "gemini-2.5-flash",
            }
        }
        monkeypatch.setattr(
            "src.llm.gateway.load_config",
            lambda name: mock_config,
        )
        result = LLMGateway._load_caller_model_map()
        assert result == {
            "move_analyzer": "gemini-2.5-flash",
            "sentiment_report": "gemini-2.5-flash",
        }

    def test_load_caller_model_map_missing_config(self, monkeypatch):
        """Missing config returns empty map (graceful degradation)."""
        monkeypatch.setattr(
            "src.llm.gateway.load_config",
            lambda name: {},
        )
        assert LLMGateway._load_caller_model_map() == {}

    def test_load_caller_model_map_config_error(self, monkeypatch):
        """Config load failure returns empty map."""
        monkeypatch.setattr(
            "src.llm.gateway.load_config",
            lambda name: (_ for _ in ()).throw(FileNotFoundError("no file")),
        )
        assert LLMGateway._load_caller_model_map() == {}


class TestDynamicUpgrade:
    """Tests for dynamic model upgrade rules."""

    _RULES = {
        "quality_model": "gemini-2.5-pro",
        "cost_models": ["gemini-2.5-flash", "gemini-2.0-flash"],
        "keywords": ["财报分析", "深度分析", "估值", "DCF", "ROE"],
        "context_length_threshold": 5000,
    }

    def _make_gw(
        self,
        caller_map: dict | None = None,
        upgrade_rules: dict | None = None,
    ) -> LLMGateway:
        router = MagicMock()
        router.complete.return_value = _make_response()
        router.complete_with_tools.return_value = _make_tool_response()
        gw = LLMGateway(router=router)
        gw._caller_model_map = caller_map or {}
        gw._upgrade_rules = upgrade_rules if upgrade_rules is not None else self._RULES
        return gw

    # ── _maybe_upgrade_model unit tests ──

    def test_keyword_triggers_upgrade(self):
        gw = self._make_gw()
        msgs = [LLMMessage(role="user", content="请做一下财报分析")]
        result = gw._maybe_upgrade_model("gemini-2.5-flash", msgs)
        assert result == "gemini-2.5-pro"

    def test_keyword_english_triggers_upgrade(self):
        gw = self._make_gw()
        msgs = [LLMMessage(role="user", content="Calculate the DCF model")]
        result = gw._maybe_upgrade_model("gemini-2.5-flash", msgs)
        assert result == "gemini-2.5-pro"

    def test_keyword_only_checks_user_messages(self):
        """System/assistant messages containing keywords should NOT trigger upgrade."""
        gw = self._make_gw()
        msgs = [
            LLMMessage(role="system", content="你是财报分析专家"),
            LLMMessage(role="user", content="股票代码是什么"),
        ]
        # System message has the keyword, but user message doesn't
        result = gw._maybe_upgrade_model("gemini-2.5-flash", msgs)
        assert result == "gemini-2.5-flash"

    def test_context_length_triggers_upgrade(self):
        gw = self._make_gw()
        # Create a message with >5000 chars total
        long_content = "x" * 5001
        msgs = [LLMMessage(role="user", content=long_content)]
        result = gw._maybe_upgrade_model("gemini-2.5-flash", msgs)
        assert result == "gemini-2.5-pro"

    def test_context_length_across_multiple_messages(self):
        gw = self._make_gw()
        msgs = [
            LLMMessage(role="system", content="a" * 2000),
            LLMMessage(role="user", content="b" * 2000),
            LLMMessage(role="assistant", content="c" * 2000),
        ]
        # Total: 6000 > 5000 threshold
        result = gw._maybe_upgrade_model("gemini-2.5-flash", msgs)
        assert result == "gemini-2.5-pro"

    def test_no_trigger_keeps_cost_model(self):
        gw = self._make_gw()
        msgs = [LLMMessage(role="user", content="今天天气怎么样")]
        result = gw._maybe_upgrade_model("gemini-2.5-flash", msgs)
        assert result == "gemini-2.5-flash"

    def test_quality_model_not_upgraded(self):
        """Quality-tier model should pass through unchanged."""
        gw = self._make_gw()
        msgs = [LLMMessage(role="user", content="请做一下财报分析")]
        # gemini-2.5-pro is the quality model, not in cost_models → no upgrade
        result = gw._maybe_upgrade_model("gemini-2.5-pro", msgs)
        assert result == "gemini-2.5-pro"

    def test_none_model_passes_through(self):
        """None model (no caller match) should pass through."""
        gw = self._make_gw()
        msgs = [LLMMessage(role="user", content="请做一下财报分析")]
        result = gw._maybe_upgrade_model(None, msgs)
        assert result is None

    def test_empty_rules_passes_through(self):
        gw = self._make_gw(upgrade_rules={})
        msgs = [LLMMessage(role="user", content="请做一下财报分析")]
        result = gw._maybe_upgrade_model("gemini-2.5-flash", msgs)
        assert result == "gemini-2.5-flash"

    def test_second_cost_model_also_upgrades(self):
        """gemini-2.0-flash should also be eligible for upgrade."""
        gw = self._make_gw()
        msgs = [LLMMessage(role="user", content="深度分析一下这只股票")]
        result = gw._maybe_upgrade_model("gemini-2.0-flash", msgs)
        assert result == "gemini-2.5-pro"

    # ── Integration: complete() and complete_with_tools() ──

    def test_complete_upgrades_cost_model_on_keyword(self):
        gw = self._make_gw(caller_map={"conversation_service": "gemini-2.5-flash"})
        msgs = [LLMMessage(role="user", content="请做一下DCF估值分析")]
        gw.complete(msgs, caller="conversation_service.followup")

        call_kwargs = gw._router.complete.call_args.kwargs
        assert call_kwargs["model"] == "gemini-2.5-pro"

    def test_complete_keeps_cost_model_without_trigger(self):
        gw = self._make_gw(caller_map={"conversation_service": "gemini-2.5-flash"})
        msgs = [LLMMessage(role="user", content="这只股票涨了多少")]
        gw.complete(msgs, caller="conversation_service.followup")

        call_kwargs = gw._router.complete.call_args.kwargs
        assert call_kwargs["model"] == "gemini-2.5-flash"

    def test_complete_with_tools_upgrades_on_keyword(self):
        gw = self._make_gw(caller_map={"backtest_interpret": "gemini-2.5-flash"})
        msgs = [LLMMessage(role="user", content="计算ROE和估值")]
        gw.complete_with_tools(msgs, [], caller="backtest_interpret.run")

        call_kwargs = gw._router.complete_with_tools.call_args.kwargs
        assert call_kwargs["model"] == "gemini-2.5-pro"

    # ── Config loading ──

    def test_load_upgrade_rules_from_config(self, monkeypatch):
        mock_config = {
            "upgrade_rules": {
                "quality_model": "gemini-2.5-pro",
                "cost_models": ["gemini-2.5-flash"],
                "keywords": ["估值"],
                "context_length_threshold": 3000,
            }
        }
        monkeypatch.setattr("src.llm.gateway.load_config", lambda name: mock_config)
        result = LLMGateway._load_upgrade_rules()
        assert result["quality_model"] == "gemini-2.5-pro"
        assert result["cost_models"] == ["gemini-2.5-flash"]
        assert result["keywords"] == ["估值"]
        assert result["context_length_threshold"] == 3000

    def test_load_upgrade_rules_missing_config(self, monkeypatch):
        monkeypatch.setattr("src.llm.gateway.load_config", lambda name: {})
        assert LLMGateway._load_upgrade_rules() == {}

    def test_load_upgrade_rules_missing_quality_model(self, monkeypatch):
        """If quality_model is missing, rules are empty (no upgrade possible)."""
        mock_config = {"upgrade_rules": {"cost_models": ["gemini-2.5-flash"]}}
        monkeypatch.setattr("src.llm.gateway.load_config", lambda name: mock_config)
        assert LLMGateway._load_upgrade_rules() == {}

    def test_load_upgrade_rules_config_error(self, monkeypatch):
        monkeypatch.setattr(
            "src.llm.gateway.load_config",
            lambda name: (_ for _ in ()).throw(FileNotFoundError("no file")),
        )
        assert LLMGateway._load_upgrade_rules() == {}


class TestGrounding:
    """Tests for Gemini Grounding (Google Search augmentation)."""

    def _make_gw(self, grounding_cfg: dict | None = None) -> LLMGateway:
        router = MagicMock()
        router.complete.return_value = _make_response()
        gw = LLMGateway(router=router)
        if grounding_cfg is not None:
            gw._grounding_cfg = grounding_cfg
        return gw

    def test_should_ground_enabled_caller(self):
        gw = self._make_gw(
            {"enabled": True, "enabled_callers": ["review_agent", "trading_advisor"]}
        )
        assert gw._should_ground("review_agent.review_candidates") is True
        assert gw._should_ground("trading_advisor.advise_stock") is True

    def test_should_ground_disabled_caller(self):
        gw = self._make_gw({"enabled": True, "enabled_callers": ["review_agent"]})
        assert gw._should_ground("conversation_service.followup") is False
        assert gw._should_ground("unknown") is False

    def test_should_ground_globally_disabled(self):
        gw = self._make_gw({"enabled": False, "enabled_callers": ["review_agent"]})
        assert gw._should_ground("review_agent.review_candidates") is False

    def test_complete_passes_grounding_to_router(self):
        gw = self._make_gw({"enabled": True, "enabled_callers": ["review_agent"]})
        msgs = [LLMMessage(role="user", content="test")]
        gw.complete(msgs, caller="review_agent.review_candidates")

        call_kwargs = gw._router.complete.call_args.kwargs
        assert call_kwargs["grounding"] is True

    def test_complete_no_grounding_for_unmatched_caller(self):
        gw = self._make_gw({"enabled": True, "enabled_callers": ["review_agent"]})
        msgs = [LLMMessage(role="user", content="test")]
        gw.complete(msgs, caller="realtime_analyzer.unified")

        call_kwargs = gw._router.complete.call_args.kwargs
        assert call_kwargs["grounding"] is False

    def test_complete_explicit_grounding_override(self):
        gw = self._make_gw({"enabled": True, "enabled_callers": []})
        msgs = [LLMMessage(role="user", content="test")]
        gw.complete(msgs, caller="any_caller", grounding=True)

        call_kwargs = gw._router.complete.call_args.kwargs
        assert call_kwargs["grounding"] is True

    def test_load_grounding_config(self, monkeypatch):
        mock_config = {
            "grounding": {
                "enabled": True,
                "enabled_callers": ["review_agent", "trading_advisor"],
            }
        }
        monkeypatch.setattr("src.llm.gateway.load_config", lambda name: mock_config)
        result = LLMGateway._load_grounding_config()
        assert result["enabled"] is True
        assert "review_agent" in result["enabled_callers"]

    def test_load_grounding_config_disabled(self, monkeypatch):
        monkeypatch.setattr("src.llm.gateway.load_config", lambda name: {})
        result = LLMGateway._load_grounding_config()
        assert result["enabled"] is False

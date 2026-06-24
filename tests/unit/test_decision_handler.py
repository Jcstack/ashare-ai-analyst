"""Tests for DecisionHandler — decision parsing, validation, and publishing."""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from src.agent_loop.agent_state import AgentState
from src.agent_loop.decision_handler import DecisionHandler


@pytest.fixture()
def mock_web_deps():
    """Inject a mock ``src.web.dependencies`` module into sys.modules.

    Many DecisionHandler methods use local imports like
    ``from src.web.dependencies import get_redis`` which cannot be resolved
    in the unit-test environment (heavy transitive deps).  This fixture
    injects a lightweight mock module so those imports succeed.
    """
    deps_mod = types.ModuleType("src.web.dependencies")

    mock_redis_fn = MagicMock(return_value=None)
    deps_mod.get_redis = mock_redis_fn  # type: ignore[attr-defined]

    mock_ps = MagicMock()
    mock_ps.list_positions.return_value = []
    deps_mod.get_portfolio_store = MagicMock(  # type: ignore[attr-defined]
        return_value=mock_ps,
    )
    deps_mod.get_capital_service = MagicMock()  # type: ignore[attr-defined]

    saved = sys.modules.get("src.web.dependencies")
    sys.modules["src.web.dependencies"] = deps_mod
    yield deps_mod
    if saved is None:
        sys.modules.pop("src.web.dependencies", None)
    else:
        sys.modules["src.web.dependencies"] = saved


class TestParseDecisions:
    """Test JSON extraction from LLM responses."""

    def test_parse_decisions_valid_json(self):
        text = (
            "分析完毕。\n\n"
            "```json\n"
            '{"decisions": [{"type": "buy_signal", "action": "buy", '
            '"symbol": "600519", "name": "贵州茅台", "shares": 100, '
            '"entry_price": 1800.0, "stop_loss": 1750.0, '
            '"target_price": 1900.0, "confidence": 0.8}]}\n'
            "```"
        )
        decisions = DecisionHandler.parse_decisions(text)
        assert len(decisions) == 1
        assert decisions[0]["symbol"] == "600519"
        assert decisions[0]["action"] == "buy"

    def test_parse_decisions_markdown_fenced(self):
        text = (
            "综合判断如下：\n\n"
            "```json\n"
            "{\n"
            '  "decisions": [\n'
            '    {"action": "hold", "symbol": "000001", "summary": "继续持有"}\n'
            "  ]\n"
            "}\n"
            "```\n\n"
            "以上是我的分析。"
        )
        decisions = DecisionHandler.parse_decisions(text)
        assert len(decisions) == 1
        assert decisions[0]["action"] == "hold"

    def test_parse_decisions_no_json(self):
        text = "市场整体平稳，无需操作。"
        decisions = DecisionHandler.parse_decisions(text)
        assert decisions == []

    def test_parse_decisions_invalid_json(self):
        text = '```json\n{"decisions": [invalid json here]}\n```'
        decisions = DecisionHandler.parse_decisions(text)
        assert decisions == []

    def test_parse_decisions_empty_text(self):
        assert DecisionHandler.parse_decisions("") == []
        assert DecisionHandler.parse_decisions(None) == []  # type: ignore[arg-type]


class TestValidateDecision:
    """Test decision validation logic."""

    def test_validate_decision_valid(self):
        decision = {
            "action": "buy",
            "shares": 200,
            "entry_price": 47.20,
            "stop_loss": 45.50,
            "target_price": 50.00,
        }
        assert DecisionHandler.validate_decision(decision) is None

    def test_validate_decision_zero_shares(self):
        decision = {
            "action": "buy",
            "shares": 50,  # < 100 after rounding
            "entry_price": 47.20,
        }
        result = DecisionHandler.validate_decision(decision)
        assert result is not None
        assert "shares too small" in result

    def test_validate_decision_stop_above_entry(self):
        decision = {
            "action": "buy",
            "shares": 200,
            "entry_price": 47.20,
            "stop_loss": 48.00,  # above entry
            "target_price": 50.00,
        }
        result = DecisionHandler.validate_decision(decision)
        assert result is not None
        assert "stop_loss" in result

    def test_validate_decision_target_below_entry(self):
        decision = {
            "action": "buy",
            "shares": 200,
            "entry_price": 47.20,
            "stop_loss": 45.00,
            "target_price": 46.00,  # below entry
        }
        result = DecisionHandler.validate_decision(decision)
        assert result is not None
        assert "target_price" in result

    def test_validate_decision_non_numeric_price(self):
        decision = {
            "action": "buy",
            "shares": 200,
            "entry_price": "not_a_number",
        }
        result = DecisionHandler.validate_decision(decision)
        assert result is not None
        assert "entry_price not numeric" in result

    def test_validate_decision_zero_price(self):
        decision = {
            "action": "buy",
            "shares": 200,
            "entry_price": 0,
        }
        result = DecisionHandler.validate_decision(decision)
        assert result is not None
        assert "entry_price must be > 0" in result

    def test_validate_decision_hold_skips_validation(self):
        """Hold/watch actions should not trigger trade validation."""
        decision = {
            "action": "hold",
            "symbol": "600519",
            "summary": "继续持有",
        }
        assert DecisionHandler.validate_decision(decision) is None

    def test_validate_decision_sell_no_stop_loss_check(self):
        """Sell actions validate price but not stop_loss/target_price."""
        decision = {
            "action": "sell",
            "shares": 200,
            "entry_price": 47.20,
        }
        assert DecisionHandler.validate_decision(decision) is None

    def test_validate_decision_non_numeric_stop_loss(self):
        decision = {
            "action": "buy",
            "shares": 200,
            "entry_price": 47.20,
            "stop_loss": "invalid",
        }
        result = DecisionHandler.validate_decision(decision)
        assert result is not None
        assert "stop_loss not numeric" in result


class TestStoreThesis:
    """Test _store_thesis — Phase 1 thesis anchoring."""

    def test_store_thesis_buy(self, mock_web_deps):
        """Buy decision should store thesis in Redis."""
        mock_redis = MagicMock()
        mock_web_deps.get_redis.return_value = mock_redis

        DecisionHandler._store_thesis(
            "002688",
            {
                "entry_price": 6.14,
                "stop_loss": 5.90,
                "target_price": 6.48,
                "summary": "趋势刚启动",
            },
        )

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "thesis:002688"
        assert call_args[0][1] == 30 * 86400
        stored = json.loads(call_args[0][2])
        assert stored["entry_price"] == 6.14
        assert stored["stop_loss"] == 5.90
        assert stored["target_price"] == 6.48

    def test_store_thesis_truncates_summary(self, mock_web_deps):
        """Summary should be truncated to 200 chars."""
        mock_redis = MagicMock()
        mock_web_deps.get_redis.return_value = mock_redis
        long_summary = "X" * 300

        DecisionHandler._store_thesis(
            "600519",
            {"summary": long_summary, "entry_price": 100},
        )

        call_args = mock_redis.setex.call_args
        stored = json.loads(call_args[0][2])
        assert len(stored["summary"]) == 200

    def test_store_thesis_no_redis_no_error(self, mock_web_deps):
        """No Redis connection should silently pass."""
        mock_web_deps.get_redis.return_value = None
        # Should not raise
        DecisionHandler._store_thesis("002688", {"entry_price": 6.14})


class TestThesisTargetPriceGuard:
    """Test the thesis-anchored target price guard for hold decisions."""

    @pytest.fixture()
    def handler(self):
        """Create a DecisionHandler with mocked MessageStore and Redis."""
        mock_ms = MagicMock()
        mock_ms.create_message.return_value = 1
        mock_redis = MagicMock()
        return DecisionHandler(message_store=mock_ms, redis_client=mock_redis)

    @pytest.fixture()
    def state(self):
        """Create a minimal AgentState mock."""
        s = MagicMock(spec=AgentState)
        s.add_decision = MagicMock()
        s.add_finding = MagicMock()
        return s

    @pytest.mark.asyncio()
    async def test_hold_tp_restored_when_no_fundamental_reason(
        self, handler, state, mock_web_deps
    ):
        """Target price should be restored if LLM lowered it without reason."""
        thesis = {
            "target_price": 6.48,
            "stop_loss": 5.50,  # Low sl so stop-loss check doesn't fire
            "entry_price": 6.14,
            "summary": "看好反弹",
            "created_at": "2026-04-02",
        }
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(thesis)
        mock_web_deps.get_redis.return_value = mock_redis

        mock_ps = MagicMock()
        mock_ps.list_positions.return_value = [{"symbol": "002688"}]
        mock_web_deps.get_portfolio_store.return_value = mock_ps

        # Mock RealtimeQuoteManager so stop-loss check sees price ABOVE sl
        mock_quote = MagicMock()
        mock_quote.get_single_quote.return_value = {"price": 6.10, "pct_change": -0.5}
        mock_web_deps.RealtimeQuoteManager = MagicMock(return_value=mock_quote)

        decision = {
            "action": "hold",
            "symbol": "002688",
            "name": "金河生物",
            "target_price": 5.80,  # below 6.48 → should be restored
            "stop_loss": 5.50,
            "confidence": 0.6,
            "summary": "继续持有观察",
        }

        with patch("src.data.realtime.RealtimeQuoteManager", return_value=mock_quote):
            await handler.push_single_decision(decision, state, "test")

        assert decision["target_price"] == 6.48

    @pytest.mark.asyncio()
    async def test_hold_tp_allowed_with_fundamental_keyword(
        self, handler, state, mock_web_deps
    ):
        """Target price drop allowed if summary contains fundamental reason."""
        thesis = {
            "target_price": 6.48,
            "stop_loss": 5.90,
            "entry_price": 6.14,
            "summary": "看好反弹",
            "created_at": "2026-04-02",
        }
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(thesis)
        mock_web_deps.get_redis.return_value = mock_redis

        mock_ps = MagicMock()
        mock_ps.list_positions.return_value = [{"symbol": "002688"}]
        mock_web_deps.get_portfolio_store.return_value = mock_ps

        decision = {
            "action": "hold",
            "symbol": "002688",
            "name": "金河生物",
            "target_price": 5.80,  # >10% below 6.48
            "stop_loss": 5.90,
            "confidence": 0.6,
            "summary": "业绩预告不及预期，下调目标",  # contains 业绩 keyword
        }

        await handler.push_single_decision(decision, state, "test")

        # Should keep the lowered target since fundamental reason given
        assert decision["target_price"] == 5.80

    @pytest.mark.asyncio()
    async def test_hold_tp_restored_even_small_drift(
        self, handler, state, mock_web_deps
    ):
        """Any target below original is restored (unless fundamental reason)."""
        thesis = {
            "target_price": 6.48,
            "stop_loss": 5.50,  # Low sl so stop-loss doesn't fire
            "entry_price": 6.14,
            "summary": "看好反弹",
            "created_at": "2026-04-02",
        }
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(thesis)
        mock_web_deps.get_redis.return_value = mock_redis

        mock_ps = MagicMock()
        mock_ps.list_positions.return_value = [{"symbol": "002688"}]
        mock_web_deps.get_portfolio_store.return_value = mock_ps

        mock_quote = MagicMock()
        mock_quote.get_single_quote.return_value = {"price": 6.10, "pct_change": -0.5}

        decision = {
            "action": "hold",
            "symbol": "002688",
            "name": "金河生物",
            "target_price": 6.20,  # below 6.48 → guard triggers
            "stop_loss": 5.50,
            "confidence": 0.6,
            "summary": "小幅调整目标",
        }

        with patch("src.data.realtime.RealtimeQuoteManager", return_value=mock_quote):
            await handler.push_single_decision(decision, state, "test")

        # Should restore to original thesis target
        assert decision["target_price"] == 6.48

    @pytest.mark.asyncio()
    async def test_hold_no_thesis_in_redis_no_guard(
        self, handler, state, mock_web_deps
    ):
        """No thesis in Redis means guard should be silently skipped."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None  # No thesis stored
        mock_web_deps.get_redis.return_value = mock_redis

        mock_ps = MagicMock()
        mock_ps.list_positions.return_value = [{"symbol": "002688"}]
        mock_web_deps.get_portfolio_store.return_value = mock_ps

        decision = {
            "action": "hold",
            "symbol": "002688",
            "name": "金河生物",
            "target_price": 5.00,
            "stop_loss": 4.50,
            "confidence": 0.6,
            "summary": "继续持有",
        }

        await handler.push_single_decision(decision, state, "test")

        # No guard applied — target stays as-is
        assert decision["target_price"] == 5.00

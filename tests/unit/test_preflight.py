"""Tests for PreflightRiskCheck — aggregated pre-order validation.

Part of v19.0 Production Hardening — Phase 1.1.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from unittest.mock import MagicMock, patch

from src.trading.preflight import PreflightResult, PreflightRiskCheck
from src.web.services.broker_interface import Balance


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_kill_switch() -> MagicMock:
    ks = MagicMock()
    ks.is_active.return_value = False
    return ks


@pytest.fixture
def mock_broker() -> MagicMock:
    broker = MagicMock()
    broker.get_balance.return_value = Balance(
        available_cash=500_000, total_assets=1_000_000
    )
    return broker


@pytest.fixture
def preflight(
    mock_kill_switch: MagicMock, mock_broker: MagicMock
) -> PreflightRiskCheck:
    return PreflightRiskCheck(
        kill_switch=mock_kill_switch,
        broker=mock_broker,
        max_order_amount=100_000,
    )


# ---------------------------------------------------------------------------
# Helper — patch trading hours + circuit breaker to always pass
# ---------------------------------------------------------------------------


def _patch_market_open():
    """Patch market hours and circuit breaker to pass."""
    hours_patch = patch(
        "src.trading.preflight.PreflightRiskCheck._check_trading_hours",
        return_value={"name": "trading_hours", "passed": True, "reason": ""},
    )
    breaker_patch = patch(
        "src.trading.preflight.PreflightRiskCheck._check_circuit_breaker",
        return_value={"name": "circuit_breaker", "passed": True, "reason": ""},
    )
    return hours_patch, breaker_patch


def _patch_constraints_pass():
    """Patch board constraint check to pass."""
    return patch(
        "src.trading.preflight.PreflightRiskCheck._check_constraints",
        return_value={"name": "board_restriction", "passed": True, "reason": ""},
    )


# ---------------------------------------------------------------------------
# Tests — all checks pass
# ---------------------------------------------------------------------------


class TestAllChecksPass:
    def test_buy_passes_when_all_ok(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498", action="buy", shares=100, price=25.0
            )
        assert result.passed is True
        assert all(c["passed"] for c in result.checks)

    def test_sell_passes_when_all_ok(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498", action="sell", shares=100, price=25.0
            )
        assert result.passed is True


# ---------------------------------------------------------------------------
# Tests — kill switch blocks
# ---------------------------------------------------------------------------


class TestKillSwitchBlocks:
    def test_kill_switch_active_blocks_order(
        self, mock_kill_switch: MagicMock, preflight: PreflightRiskCheck
    ):
        mock_kill_switch.is_active.return_value = True
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498", action="buy", shares=100, price=25.0
            )
        assert result.passed is False
        ks_check = next(c for c in result.checks if c["name"] == "kill_switch")
        assert ks_check["passed"] is False


# ---------------------------------------------------------------------------
# Tests — insufficient cash blocks buy
# ---------------------------------------------------------------------------


class TestInsufficientCash:
    def test_insufficient_cash_blocks_buy(
        self, mock_broker: MagicMock, preflight: PreflightRiskCheck
    ):
        mock_broker.get_balance.return_value = Balance(
            available_cash=1_000, total_assets=50_000
        )
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498", action="buy", shares=100, price=25.0
            )
        assert result.passed is False
        cash_check = next(c for c in result.checks if c["name"] == "available_cash")
        assert cash_check["passed"] is False
        assert "Insufficient" in cash_check["reason"]

    def test_cash_check_not_run_for_sell(
        self, mock_broker: MagicMock, preflight: PreflightRiskCheck
    ):
        mock_broker.get_balance.return_value = Balance(
            available_cash=0, total_assets=50_000
        )
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498", action="sell", shares=100, price=25.0
            )
        # Cash check should not appear for sell actions
        cash_checks = [c for c in result.checks if c["name"] == "available_cash"]
        assert len(cash_checks) == 0


# ---------------------------------------------------------------------------
# Tests — invalid board blocks
# ---------------------------------------------------------------------------


class TestBoardRestriction:
    def test_invalid_board_blocks(
        self, mock_kill_switch: MagicMock, mock_broker: MagicMock
    ):
        preflight = PreflightRiskCheck(
            kill_switch=mock_kill_switch,
            broker=mock_broker,
            max_order_amount=100_000,
        )
        hours_p, breaker_p = _patch_market_open()
        with hours_p, breaker_p:
            with patch(
                "src.trading.preflight.PreflightRiskCheck._check_constraints",
                return_value={
                    "name": "board_restriction",
                    "passed": False,
                    "reason": "Board 'cyb' not allowed (main board only)",
                },
            ):
                result = preflight.check(
                    symbol="300750", action="buy", shares=100, price=150.0
                )
        assert result.passed is False
        board_check = next(c for c in result.checks if c["name"] == "board_restriction")
        assert board_check["passed"] is False
        assert "not allowed" in board_check["reason"]


# ---------------------------------------------------------------------------
# Tests — invalid lot size blocks
# ---------------------------------------------------------------------------


class TestLotSize:
    def test_invalid_lot_size_blocks(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498", action="buy", shares=150, price=25.0
            )
        assert result.passed is False
        lot_check = next(c for c in result.checks if c["name"] == "lot_size")
        assert lot_check["passed"] is False
        assert "150" in lot_check["reason"]

    def test_zero_shares_blocks(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498", action="buy", shares=0, price=25.0
            )
        lot_check = next(c for c in result.checks if c["name"] == "lot_size")
        assert lot_check["passed"] is False

    def test_valid_lot_size_passes(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498", action="sell", shares=200, price=25.0
            )
        lot_check = next(c for c in result.checks if c["name"] == "lot_size")
        assert lot_check["passed"] is True


# ---------------------------------------------------------------------------
# Tests — order amount exceeds limit
# ---------------------------------------------------------------------------


class TestOrderAmountLimit:
    def test_exceeds_limit_blocks(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            # 1000 * 150 = 150,000 > 100,000 limit
            result = preflight.check(
                symbol="600498", action="sell", shares=1000, price=150.0
            )
        assert result.passed is False
        amt_check = next(c for c in result.checks if c["name"] == "order_amount")
        assert amt_check["passed"] is False
        assert "exceeds" in amt_check["reason"]

    def test_within_limit_passes(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            # 100 * 25 = 2,500 <= 100,000 limit
            result = preflight.check(
                symbol="600498", action="buy", shares=100, price=25.0
            )
        amt_check = next(c for c in result.checks if c["name"] == "order_amount")
        assert amt_check["passed"] is True

    def test_exactly_at_limit_passes(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            # 1000 * 100 = 100,000 == limit
            result = preflight.check(
                symbol="600498", action="sell", shares=1000, price=100.0
            )
        amt_check = next(c for c in result.checks if c["name"] == "order_amount")
        assert amt_check["passed"] is True


# ---------------------------------------------------------------------------
# Tests — circuit breaker gate reads persisted halt state (regression: P0.1)
# ---------------------------------------------------------------------------


def _patch_hours_pass():
    return patch(
        "src.trading.preflight.PreflightRiskCheck._check_trading_hours",
        return_value={"name": "trading_hours", "passed": True, "reason": ""},
    )


class TestCircuitBreakerGate:
    def test_halted_breaker_blocks_order(self, preflight: PreflightRiskCheck):
        """A persisted halt (is_halted() True) must fail the preflight gate.

        Regression for the bug where _check_circuit_breaker only read a fresh
        instance's in-memory state (always NORMAL) and never loaded Redis.
        """
        with (
            _patch_hours_pass(),
            _patch_constraints_pass(),
            patch("src.risk.circuit_breaker.CircuitBreaker") as MockBreaker,
        ):
            instance = MockBreaker.return_value
            instance.is_halted.return_value = True
            instance.state.value = "daily_halt"
            result = preflight.check(
                symbol="600498", action="buy", shares=100, price=25.0
            )
        cb = next(c for c in result.checks if c["name"] == "circuit_breaker")
        assert cb["passed"] is False
        assert "daily_halt" in cb["reason"]
        assert result.passed is False
        instance.is_halted.assert_called_once()

    def test_normal_breaker_passes(self, preflight: PreflightRiskCheck):
        with (
            _patch_hours_pass(),
            _patch_constraints_pass(),
            patch("src.risk.circuit_breaker.CircuitBreaker") as MockBreaker,
        ):
            MockBreaker.return_value.is_halted.return_value = False
            result = preflight.check(
                symbol="600498", action="sell", shares=100, price=25.0
            )
        cb = next(c for c in result.checks if c["name"] == "circuit_breaker")
        assert cb["passed"] is True


# ---------------------------------------------------------------------------
# Tests — T+1 sellability (regression: P0.2 — advertised but never run)
# ---------------------------------------------------------------------------


class TestT1Sellability:
    def test_sell_bought_today_blocks(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498",
                action="sell",
                shares=100,
                price=25.0,
                buy_date=date.today(),
            )
        t1 = next(c for c in result.checks if c["name"] == "t1_sellability")
        assert t1["passed"] is False
        assert "T+1" in t1["reason"]
        assert result.passed is False

    def test_sell_bought_earlier_passes(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498",
                action="sell",
                shares=100,
                price=25.0,
                buy_date=date.today() - timedelta(days=1),
            )
        t1 = next(c for c in result.checks if c["name"] == "t1_sellability")
        assert t1["passed"] is True

    def test_no_buy_date_skips_enforcement(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498", action="sell", shares=100, price=25.0
            )
        t1 = next(c for c in result.checks if c["name"] == "t1_sellability")
        assert t1["passed"] is True

    def test_t1_not_run_for_buy(self, preflight: PreflightRiskCheck):
        hours_p, breaker_p = _patch_market_open()
        constraints_p = _patch_constraints_pass()
        with hours_p, breaker_p, constraints_p:
            result = preflight.check(
                symbol="600498",
                action="buy",
                shares=100,
                price=25.0,
                buy_date=date.today(),
            )
        t1_checks = [c for c in result.checks if c["name"] == "t1_sellability"]
        assert len(t1_checks) == 0


# ---------------------------------------------------------------------------
# Tests — PreflightResult summary
# ---------------------------------------------------------------------------


class TestPreflightResultSummary:
    def test_summary_all_passed(self):
        result = PreflightResult(
            passed=True,
            checks=[
                {"name": "kill_switch", "passed": True, "reason": ""},
                {"name": "lot_size", "passed": True, "reason": ""},
            ],
        )
        assert "All preflight checks passed" in result.summary()

    def test_summary_shows_failed_names(self):
        result = PreflightResult(
            passed=False,
            checks=[
                {"name": "kill_switch", "passed": False, "reason": "active"},
                {"name": "lot_size", "passed": True, "reason": ""},
            ],
        )
        assert "kill_switch" in result.summary()
        assert "BLOCKED" in result.summary()

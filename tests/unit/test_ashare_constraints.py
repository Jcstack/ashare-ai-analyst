"""Tests for Phase 6 — AShareConstraintChecker."""

from __future__ import annotations

import pytest

from src.agent_loop.ashare_constraints import AShareConstraintChecker


@pytest.fixture
def checker() -> AShareConstraintChecker:
    return AShareConstraintChecker()


class TestDetectBoardType:
    """Board detection from stock code prefix."""

    def test_main_board_sse(self) -> None:
        assert AShareConstraintChecker._detect_board_type("600519") == "main"

    def test_main_board_szse(self) -> None:
        assert AShareConstraintChecker._detect_board_type("000001") == "main"

    def test_chinext(self) -> None:
        assert AShareConstraintChecker._detect_board_type("300750") == "chinext"

    def test_star_market(self) -> None:
        assert AShareConstraintChecker._detect_board_type("688981") == "star"

    def test_bse(self) -> None:
        assert AShareConstraintChecker._detect_board_type("830799") == "bse"


class TestRoundToLot:
    """100-share lot rounding."""

    def test_rounds_down_to_100(self) -> None:
        assert AShareConstraintChecker._round_to_lot(150, "main", "buy") == 100

    def test_exact_lot(self) -> None:
        assert AShareConstraintChecker._round_to_lot(300, "main", "buy") == 300

    def test_zero_if_less_than_100(self) -> None:
        assert AShareConstraintChecker._round_to_lot(50, "main", "buy") == 0

    def test_sell_allows_odd_lots(self) -> None:
        assert AShareConstraintChecker._round_to_lot(73, "main", "sell") == 73


class TestAssessTrade:
    """Full trade assessment."""

    def test_basic_buy_assessment(self, checker: AShareConstraintChecker) -> None:
        result = checker.assess_trade(
            symbol="600519",
            action="buy",
            shares=100,
            price=1800.0,
            portfolio_value=1_000_000.0,
        )
        assert result.tradeable is True
        assert result.board_type == "main"
        assert result.price_limit_pct == 10.0
        assert result.shares_rounded == 100
        assert result.overnight_max_loss_pct == 0.10

    def test_chinext_has_20_pct_limit(self, checker: AShareConstraintChecker) -> None:
        result = checker.assess_trade(
            symbol="300750",
            action="buy",
            shares=100,
            price=50.0,
            portfolio_value=100_000.0,
        )
        assert result.price_limit_pct == 20.0
        assert result.overnight_max_loss_pct == 0.20

    def test_star_market_has_20_pct_limit(self, checker: AShareConstraintChecker) -> None:
        result = checker.assess_trade(
            symbol="688981",
            action="buy",
            shares=100,
            price=100.0,
            portfolio_value=500_000.0,
        )
        assert result.price_limit_pct == 20.0

    def test_insufficient_shares_not_tradeable(self, checker: AShareConstraintChecker) -> None:
        result = checker.assess_trade(
            symbol="600519",
            action="buy",
            shares=50,
            price=1800.0,
            portfolio_value=100_000.0,
        )
        assert result.tradeable is False
        assert any("一手" in v for v in result.constraint_violations)

    def test_min_order_value_check(self) -> None:
        checker = AShareConstraintChecker(config={"min_order_value": 5000})
        result = checker.assess_trade(
            symbol="000001",
            action="buy",
            shares=100,
            price=10.0,  # 100 * 10 = 1000 < 5000
            portfolio_value=100_000.0,
        )
        assert result.tradeable is False
        assert any("金额" in v for v in result.constraint_violations)

    def test_near_upper_limit_warning(self, checker: AShareConstraintChecker) -> None:
        result = checker.assess_trade(
            symbol="600519",
            action="buy",
            shares=100,
            price=99.0,
            portfolio_value=100_000.0,
            market_data={"prev_close": 90.0, "upper_limit": 99.0, "lower_limit": 81.0},
        )
        assert result.near_limit_warning is True
        assert any("涨停" in w for w in result.risk_warnings)

    def test_sell_always_tradeable(self, checker: AShareConstraintChecker) -> None:
        result = checker.assess_trade(
            symbol="600519",
            action="sell",
            shares=73,  # Odd lot OK for sell
            price=1800.0,
            portfolio_value=100_000.0,
        )
        assert result.tradeable is True
        assert result.shares_rounded == 73

    def test_overnight_risk_budget_warning(self) -> None:
        checker = AShareConstraintChecker(
            config={"overnight_risk_budget_pct": 0.02}
        )
        result = checker.assess_trade(
            symbol="600519",
            action="buy",
            shares=100,
            price=1800.0,
            portfolio_value=100_000.0,  # 180k position in 100k portfolio
        )
        # 10% of 180k = 18k > 2% of 100k = 2k → warning
        assert any("隔夜风险" in w for w in result.risk_warnings)

    def test_liquidity_warning(self, checker: AShareConstraintChecker) -> None:
        result = checker.assess_trade(
            symbol="600519",
            action="buy",
            shares=10000,
            price=1800.0,
            portfolio_value=20_000_000.0,
            market_data={"avg_volume": 5000},  # Very low volume
        )
        # 10000 shares / (5000 * 0.05) = 40 days to exit → warning
        assert not result.liquidity_adequate
        assert any("流动性" in w for w in result.risk_warnings)

    def test_gap_risk_score(self, checker: AShareConstraintChecker) -> None:
        result = checker.assess_trade(
            symbol="600519",
            action="buy",
            shares=100,
            price=1800.0,
            portfolio_value=1_000_000.0,
            market_data={"daily_change_pct": 0.09},  # 9% change today
        )
        assert result.gap_risk_score > 0.5  # High gap risk


class TestT1Sellable:
    """T+1 settlement check."""

    def test_all_sellable_no_today_bought(self, checker: AShareConstraintChecker) -> None:
        positions = [{"symbol": "600519", "shares": 500, "today_bought": 0}]
        sellable, locked = checker.check_t1_sellable("600519", positions)
        assert sellable == 500
        assert locked == 0

    def test_today_bought_locked(self, checker: AShareConstraintChecker) -> None:
        positions = [{"symbol": "600519", "shares": 500, "today_bought": 200}]
        sellable, locked = checker.check_t1_sellable("600519", positions)
        assert sellable == 300
        assert locked == 200

    def test_not_held(self, checker: AShareConstraintChecker) -> None:
        positions = [{"symbol": "000001", "shares": 100}]
        sellable, locked = checker.check_t1_sellable("600519", positions)
        assert sellable == 0
        assert locked == 0


class TestAdjustSharesForLiquidity:
    """Liquidity-based share adjustment."""

    def test_reduces_shares_for_low_volume(self, checker: AShareConstraintChecker) -> None:
        adjusted = checker.adjust_shares_for_liquidity(
            shares=10000,
            symbol="600519",
            avg_volume=1000,
            max_days=2.0,
        )
        # Max: 1000 * 0.05 * 2 = 100 shares
        assert adjusted == 100

    def test_no_reduction_for_high_volume(self, checker: AShareConstraintChecker) -> None:
        adjusted = checker.adjust_shares_for_liquidity(
            shares=1000,
            symbol="600519",
            avg_volume=1_000_000,
            max_days=2.0,
        )
        assert adjusted == 1000

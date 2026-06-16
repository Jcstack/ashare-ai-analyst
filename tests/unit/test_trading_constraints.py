"""Tests for TradingConstraintsEngine."""

from datetime import date, timedelta

import pytest

from src.trading.constraints import (
    MAIN_BOARD_SH,
    MAIN_BOARD_SZ,
    TradingConstraintsEngine,
)

DEFAULT_CONFIG = {
    "allowed_boards": ["main"],
    "max_hold_days": 3,
    "max_single_position_pct": 30.0,
    "max_intraday_chase_pct": 5.0,
    "min_daily_turnover_wan": 5000,
    "lot_size": 100,
    "commission_rate": 0.0003,
    "stamp_duty_rate": 0.001,
    "min_commission": 5.0,
}


@pytest.fixture
def engine():
    return TradingConstraintsEngine(config=DEFAULT_CONFIG)


class TestBoardClassification:
    def test_main_board_sh(self, engine):
        for prefix in MAIN_BOARD_SH:
            assert engine.get_board(f"{prefix}001") == "main"

    def test_main_board_sz(self, engine):
        for prefix in MAIN_BOARD_SZ:
            assert engine.get_board(f"{prefix}001") == "main"

    def test_chinext(self, engine):
        assert engine.get_board("300001") == "chinext"
        assert engine.get_board("301001") == "chinext"

    def test_star(self, engine):
        assert engine.get_board("688001") == "star"
        assert engine.get_board("689001") == "star"

    def test_bse(self, engine):
        assert engine.get_board("830001") == "bse"

    def test_board_allowed(self, engine):
        assert engine.is_board_allowed("600001")
        assert engine.is_board_allowed("002155")
        assert not engine.is_board_allowed("300001")
        assert not engine.is_board_allowed("688001")


class TestConstraintChecks:
    def test_main_board_passes(self, engine):
        result = engine.check("002155", "湖南黄金")
        assert result.passed
        assert len(result.violations) == 0

    def test_chinext_blocked(self, engine):
        result = engine.check("300001", "特锐德")
        assert not result.passed
        assert result.blocked
        assert result.violations[0].rule == "exchange_blocked"

    def test_star_blocked(self, engine):
        result = engine.check("688001", "华兴源创")
        assert not result.passed
        assert result.blocked

    def test_st_blocked(self, engine):
        result = engine.check("000001", "ST测试", is_st=True)
        assert not result.passed
        assert any(v.rule == "st_stock" for v in result.violations)

    def test_halted_blocked(self, engine):
        result = engine.check("600001", "测试停牌", is_halted=True)
        assert not result.passed

    def test_chase_buy_warning(self, engine):
        result = engine.check("600001", "追涨测试", intraday_change_pct=7.5)
        assert result.passed  # warning, not block
        assert len(result.warnings) == 1
        assert result.warnings[0].rule == "chase_buy"

    def test_below_chase_threshold_no_warning(self, engine):
        result = engine.check("600001", "正常", intraday_change_pct=3.0)
        assert result.passed
        assert len(result.warnings) == 0

    def test_low_liquidity_warning(self, engine):
        result = engine.check("600001", "低流动性", daily_turnover_wan=2000)
        assert result.passed
        assert any(v.rule == "low_liquidity" for v in result.warnings)

    def test_concentration_warning(self, engine):
        result = engine.check("600001", "重仓股", position_pct=45.0)
        assert result.passed
        assert any(v.rule == "concentration" for v in result.warnings)

    def test_hold_too_long_warning(self, engine):
        result = engine.check("600001", "长期持有", hold_days=5)
        assert result.passed
        assert any(v.rule == "hold_too_long" for v in result.warnings)

    def test_multiple_violations(self, engine):
        result = engine.check(
            "300001",
            "创业板追高",
            intraday_change_pct=8.0,
            daily_turnover_wan=1000,
        )
        assert not result.passed
        assert len(result.violations) >= 1  # at least exchange_blocked


class TestFilterCandidates:
    def test_filter_mixed(self, engine):
        candidates = [
            {"symbol": "600001", "name": "浦发银行"},
            {"symbol": "300001", "name": "特锐德"},
            {"symbol": "002155", "name": "湖南黄金"},
            {"symbol": "688001", "name": "华兴源创"},
        ]
        passed, rejected = engine.filter_candidates(candidates)
        assert len(passed) == 2
        assert len(rejected) == 2
        passed_symbols = {c["symbol"] for c in passed}
        assert "600001" in passed_symbols
        assert "002155" in passed_symbols

    def test_filter_all_pass(self, engine):
        candidates = [
            {"symbol": "600001", "name": "浦发银行"},
            {"symbol": "601318", "name": "中国平安"},
        ]
        passed, rejected = engine.filter_candidates(candidates)
        assert len(passed) == 2
        assert len(rejected) == 0


class TestTPlus1:
    def test_can_sell_next_day(self, engine):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert engine.can_sell_today(yesterday)

    def test_cannot_sell_same_day(self, engine):
        today = date.today().isoformat()
        assert not engine.can_sell_today(today)

    def test_overnight_risk_note(self, engine):
        note = engine.overnight_risk_note()
        assert "T+1" in note
        assert "隔夜" in note


class TestCostCalculation:
    def test_buy_cost(self, engine):
        cost = engine.calc_trade_cost(price=20.0, shares=1000, side="buy")
        assert cost["amount"] == 20000.0
        assert cost["commission"] == 6.0  # 20000 * 0.0003 rounded
        assert cost["stamp_duty"] == 0.0
        assert cost["net_amount"] > cost["amount"]  # buy = amount + cost

    def test_sell_cost_with_stamp_duty(self, engine):
        cost = engine.calc_trade_cost(price=20.0, shares=1000, side="sell")
        assert cost["stamp_duty"] == 20000 * 0.001
        assert cost["net_amount"] < cost["amount"]

    def test_min_commission(self, engine):
        cost = engine.calc_trade_cost(price=5.0, shares=100, side="buy")
        assert cost["commission"] == 5.0  # min commission

    def test_lot_rounding(self, engine):
        assert engine.round_to_lot(150) == 100
        assert engine.round_to_lot(250) == 200
        assert engine.round_to_lot(99) == 0
        assert engine.round_to_lot(500) == 500

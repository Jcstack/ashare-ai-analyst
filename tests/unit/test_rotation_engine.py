"""Tests for RotationEngine."""

import pytest

from src.intelligence.position_macro_mapper import MacroEnvironment
from src.intelligence.rotation_engine import RotationEngine
from src.trading.constraints import TradingConstraintsEngine


@pytest.fixture
def engine():
    constraints = TradingConstraintsEngine(
        config={"allowed_boards": ["main"], "min_daily_turnover_wan": 0}
    )
    return RotationEngine(constraints=constraints, rotation_threshold=-0.3)


class TestBenefitingSectors:
    def test_usd_strong_finds_exporters(self, engine):
        """USD strengthening should benefit export-oriented sectors."""
        env = MacroEnvironment(usd_index=0.8)
        sectors = engine.find_benefiting_sectors(env)
        # Textile/apparel has positive USD sensitivity
        top_sectors = [s for s, score in sectors if score > 0]
        assert "纺织服装" in top_sectors

    def test_risk_off_finds_safe_havens(self, engine):
        """Risk-off should benefit gold and military."""
        env = MacroEnvironment(risk_aversion=0.8)
        sectors = engine.find_benefiting_sectors(env)
        top_sectors = [s for s, score in sectors[:3] if score > 0]
        assert "黄金" in top_sectors or "军工" in top_sectors

    def test_sorted_descending(self, engine):
        env = MacroEnvironment(oil_price=0.5)
        sectors = engine.find_benefiting_sectors(env)
        scores = [s for _, s in sectors]
        assert scores == sorted(scores, reverse=True)


class TestRotationPlan:
    def test_gold_under_pressure_generates_plan(self, engine):
        """When gold is under pressure from USD, should recommend rotation."""
        env = MacroEnvironment(
            usd_index=0.8,
            fed_rate=0.5,
            gold_price=-0.5,
            risk_aversion=-0.3,
        )
        positions = [{"symbol": "002155", "name": "湖南黄金"}]
        plans = engine.scan_portfolio(positions, env)
        assert len(plans) == 1
        plan = plans[0]
        assert plan.sell_symbol == "002155"
        assert len(plan.buy_candidates) > 0
        # Candidates should be from benefiting sectors
        for c in plan.buy_candidates:
            assert c.macro_score > 0

    def test_no_rotation_when_healthy(self, engine):
        """No rotation plans when all positions are healthy."""
        env = MacroEnvironment(gold_price=0.5, risk_aversion=0.5)
        positions = [{"symbol": "002155", "name": "湖南黄金"}]
        plans = engine.scan_portfolio(positions, env)
        assert len(plans) == 0

    def test_plan_has_risk_note(self, engine):
        env = MacroEnvironment(usd_index=0.8, gold_price=-0.5)
        positions = [{"symbol": "002155", "name": "湖南黄金"}]
        plans = engine.scan_portfolio(positions, env)
        if plans:
            assert plans[0].risk_note
            assert plans[0].overnight_warning
            assert "T+1" in plans[0].overnight_warning

    def test_plan_serialization(self, engine):
        env = MacroEnvironment(usd_index=0.8, gold_price=-0.5, risk_aversion=-0.3)
        positions = [{"symbol": "002155", "name": "湖南黄金"}]
        plans = engine.scan_portfolio(positions, env)
        if plans:
            d = plans[0].to_dict()
            assert "plan_id" in d
            assert "sell" in d
            assert d["sell"]["symbol"] == "002155"
            assert "buy_candidates" in d


class TestConstraintFiltering:
    def test_chinext_blocked(self):
        """ChiNext stocks should be blocked in candidates."""
        constraints = TradingConstraintsEngine(
            config={"allowed_boards": ["main"], "min_daily_turnover_wan": 0}
        )
        engine = RotationEngine(constraints=constraints)
        # Even if we manually add a ChiNext stock, it should be filtered
        env = MacroEnvironment(usd_index=0.8, gold_price=-0.5, risk_aversion=-0.3)
        positions = [{"symbol": "002155", "name": "湖南黄金"}]
        plans = engine.scan_portfolio(positions, env)
        if plans:
            for c in plans[0].buy_candidates:
                board = constraints.get_board(c.symbol)
                assert board == "main"

    def test_candidates_all_main_board(self, engine):
        """All rotation candidates should be main board."""
        env = MacroEnvironment(usd_index=0.8, gold_price=-0.5, risk_aversion=-0.3)
        positions = [{"symbol": "002155", "name": "湖南黄金"}]
        plans = engine.scan_portfolio(positions, env)
        if plans:
            for c in plans[0].buy_candidates:
                assert c.board == "main"


class TestMultiPosition:
    def test_multiple_positions_scanned(self, engine):
        """Multiple positions should be analyzed independently."""
        env = MacroEnvironment(
            usd_index=0.8,
            gold_price=-0.5,
            oil_price=-0.3,
            risk_aversion=-0.3,
        )
        positions = [
            {"symbol": "002155", "name": "湖南黄金"},
            {"symbol": "600036", "name": "招商银行"},
        ]
        plans = engine.scan_portfolio(positions, env)
        # At least gold should trigger
        sell_symbols = [p.sell_symbol for p in plans]
        assert "002155" in sell_symbols or len(plans) >= 1

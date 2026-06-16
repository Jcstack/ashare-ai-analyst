"""Tests for PositionMacroMapper."""

import pytest

from src.intelligence.position_macro_mapper import (
    MacroEnvironment,
    PositionMacroMapper,
)


@pytest.fixture
def mapper():
    return PositionMacroMapper()


class TestSectorLookup:
    def test_known_stock(self, mapper):
        assert mapper.get_sector("002155") == "黄金"
        assert mapper.get_sector("601857") == "石油"
        assert mapper.get_sector("600036") == "银行"

    def test_unknown_stock(self, mapper):
        assert mapper.get_sector("999999") == "unknown"

    def test_sensitivities(self, mapper):
        sens = mapper.get_sensitivities("002155")
        assert sens["gold_price"] > 0.5  # gold stock highly correlated
        assert sens["usd_index"] < -0.5  # inverse to USD


class TestMacroScore:
    def test_gold_in_risk_off(self, mapper):
        """Gold should score well in risk-off environment."""
        env = MacroEnvironment(
            gold_price=0.5,
            usd_index=-0.5,
            risk_aversion=0.8,
        )
        profile = mapper.analyze_position("002155", "湖南黄金", env)
        assert profile.current_macro_score > 0.2
        assert profile.rotation_signal in ("hold", "add")

    def test_gold_in_usd_strong(self, mapper):
        """Gold should score poorly when USD strengthens."""
        env = MacroEnvironment(
            gold_price=-0.5,
            usd_index=0.8,
            fed_rate=0.5,
            risk_aversion=-0.3,
        )
        profile = mapper.analyze_position("002155", "湖南黄金", env)
        assert profile.current_macro_score < -0.2
        assert profile.rotation_signal in ("reduce", "exit")

    def test_oil_stock_in_oil_surge(self, mapper):
        """Oil stocks should benefit from oil price surge."""
        env = MacroEnvironment(oil_price=0.8)
        profile = mapper.analyze_position("601857", "中国石油", env)
        assert profile.current_macro_score > 0

    def test_neutral_environment(self, mapper):
        """All zeros should produce neutral score."""
        env = MacroEnvironment()
        profile = mapper.analyze_position("002155", "湖南黄金", env)
        assert profile.current_macro_score == 0.0
        assert profile.rotation_signal == "hold"

    def test_unknown_stock_neutral(self, mapper):
        """Unknown stock should get neutral score."""
        env = MacroEnvironment(gold_price=1.0)
        profile = mapper.analyze_position("999999", "未知股票", env)
        assert profile.current_macro_score == 0.0


class TestRotationSignals:
    def test_exit_signal(self, mapper):
        signal, reason = mapper.determine_rotation_signal(-0.6)
        assert signal == "exit"

    def test_reduce_signal(self, mapper):
        signal, reason = mapper.determine_rotation_signal(-0.35)
        assert signal == "reduce"

    def test_add_signal(self, mapper):
        signal, reason = mapper.determine_rotation_signal(0.4)
        assert signal == "add"

    def test_hold_signal(self, mapper):
        signal, reason = mapper.determine_rotation_signal(0.1)
        assert signal == "hold"


class TestPortfolioAnalysis:
    def test_portfolio_sorted_by_score(self, mapper):
        """Portfolio analysis should sort worst-positioned first."""
        positions = [
            {"symbol": "002155", "name": "湖南黄金"},
            {"symbol": "601857", "name": "中国石油"},
            {"symbol": "600036", "name": "招商银行"},
        ]
        env = MacroEnvironment(usd_index=0.8, oil_price=0.5)
        profiles = mapper.analyze_portfolio(positions, env)
        assert len(profiles) == 3
        # Gold should score worst with strong USD
        assert profiles[0].current_macro_score <= profiles[1].current_macro_score

    def test_portfolio_exposure(self, mapper):
        positions = [
            {"symbol": "002155"},
            {"symbol": "600489"},
        ]
        exposure = mapper.portfolio_macro_exposure(positions)
        assert "gold_price" in exposure
        assert exposure["gold_price"] > 0.5  # both gold stocks

    def test_empty_portfolio(self, mapper):
        assert mapper.portfolio_macro_exposure([]) == {}


class TestSerialization:
    def test_profile_to_dict(self, mapper):
        env = MacroEnvironment(gold_price=0.5)
        profile = mapper.analyze_position("002155", "湖南黄金", env)
        d = profile.to_dict()
        assert d["symbol"] == "002155"
        assert "macro_sensitivities" in d
        assert "rotation_signal" in d

    def test_env_to_dict(self):
        env = MacroEnvironment(gold_price=0.5, usd_index=-0.3)
        d = env.to_dict()
        assert d["gold_price"] == 0.5
        assert d["usd_index"] == -0.3

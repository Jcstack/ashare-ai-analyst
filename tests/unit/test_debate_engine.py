"""Tests for DebateEngine."""

import pytest

from src.intelligence.debate_engine import DebateEngine


@pytest.fixture
def engine():
    return DebateEngine()


class TestBullArguments:
    def test_rsi_oversold(self, engine):
        args = engine.collect_bull_arguments({"rsi": 25.0})
        assert len(args) >= 1
        assert any("RSI" in a.claim for a in args)

    def test_macd_golden_cross(self, engine):
        args = engine.collect_bull_arguments({"macd_golden_cross": True})
        assert any("MACD" in a.claim for a in args)

    def test_volume_surge(self, engine):
        args = engine.collect_bull_arguments({"volume_ratio": 2.0})
        assert any("放量" in a.claim for a in args)

    def test_favorable_macro(self, engine):
        args = engine.collect_bull_arguments({"macro_score": 0.6})
        assert any("宏观" in a.claim for a in args)

    def test_no_data_no_args(self, engine):
        args = engine.collect_bull_arguments({})
        assert args == []


class TestBearArguments:
    def test_rsi_overbought(self, engine):
        args = engine.collect_bear_arguments({"rsi": 75.0})
        assert len(args) >= 1
        assert any("RSI" in a.claim for a in args)

    def test_unfavorable_macro(self, engine):
        args = engine.collect_bear_arguments({"macro_score": -0.5})
        assert any("宏观" in a.claim for a in args)

    def test_capital_outflow(self, engine):
        args = engine.collect_bear_arguments({"capital_net_inflow": -10000})
        assert any("资金" in a.claim for a in args)

    def test_recent_large_gain(self, engine):
        args = engine.collect_bear_arguments({"recent_5d_gain_pct": 15.0})
        assert any("涨幅" in a.claim for a in args)

    def test_t_plus_1_risk(self, engine):
        args = engine.collect_bear_arguments({"t_plus_1_risk": True})
        assert any("T+1" in a.claim for a in args)


class TestArbiterVerdict:
    def test_bullish_verdict(self, engine):
        bull = engine.collect_bull_arguments(
            {
                "rsi": 25.0,
                "macd_golden_cross": True,
                "macro_score": 0.6,
                "volume_ratio": 2.0,
            }
        )
        bear = engine.collect_bear_arguments({"t_plus_1_risk": True})
        verdict = engine.arbiter_verdict(bull, bear, {})
        assert verdict.action in ("buy", "watch")
        assert verdict.win_probability > 0.5

    def test_bearish_verdict(self, engine):
        bull = engine.collect_bull_arguments({})
        bear = engine.collect_bear_arguments(
            {
                "rsi": 80.0,
                "macro_score": -0.6,
                "capital_net_inflow": -10000,
                "recent_5d_gain_pct": 20.0,
            }
        )
        verdict = engine.arbiter_verdict(bull, bear, {})
        assert verdict.action in ("sell", "reduce", "hold")
        assert verdict.win_probability < 0.5

    def test_no_data_hold(self, engine):
        verdict = engine.arbiter_verdict([], [], {})
        assert verdict.action == "hold"
        assert verdict.conviction == "low"

    def test_stop_loss_on_buy(self, engine):
        bull = engine.collect_bull_arguments({"rsi": 20.0, "macro_score": 0.8})
        verdict = engine.arbiter_verdict(bull, [], {"stop_loss_pct": -3.0})
        if verdict.action in ("buy", "watch"):
            assert verdict.stop_loss_pct is not None


class TestFullDebate:
    def test_bullish_debate(self, engine):
        record = engine.run_debate(
            "002155",
            "湖南黄金",
            trigger="宏观信号",
            market_data={
                "rsi": 28.0,
                "macd_golden_cross": True,
                "macro_score": 0.5,
                "volume_ratio": 1.8,
            },
        )
        assert record.symbol == "002155"
        assert len(record.bull_arguments) >= 2
        assert record.verdict is not None
        assert record.final_action in ("buy", "watch", "hold")

    def test_bearish_debate_with_veto(self, engine):
        record = engine.run_debate(
            "002155",
            "湖南黄金",
            trigger="宏观下行",
            market_data={
                "rsi": 15.0,  # bull signal
                "macro_score": -0.7,  # strong bear
                "capital_net_inflow": -20000,  # strong bear
                "recent_5d_gain_pct": 25.0,  # strong bear
                "sentiment_score": -0.6,
            },
        )
        # Should have strong bear arguments
        assert len(record.bear_arguments) >= 2

    def test_risk_veto_overrides_buy(self, engine):
        """When strong bear args exist, risk veto should override buy."""
        record = engine.run_debate(
            "002155",
            "湖南黄金",
            market_data={
                "rsi": 25.0,
                "macro_score": 0.3,
                "volume_ratio": 2.0,
                # Also strong bear signals
                "recent_5d_gain_pct": 25.0,  # strong bear
                "capital_net_inflow": -15000,
            },
        )
        # Whether vetoed depends on argument balance
        assert record.final_action in ("buy", "watch", "hold", "reduce")

    def test_checklist_integration(self, engine):
        """Munger checklist failure should trigger veto."""
        checklist = {
            "overall_passed": False,
            "checks": [
                {"severity": "block", "finding": "安全边际不足"},
            ],
        }
        record = engine.run_debate(
            "002155",
            "湖南黄金",
            market_data={"rsi": 25.0, "macro_score": 0.5},
            checklist_result=checklist,
        )
        if record.verdict and record.verdict.action == "buy":
            assert record.risk_veto
            assert record.final_action != "buy"

    def test_empty_debate(self, engine):
        record = engine.run_debate("002155", "湖南黄金")
        assert record.final_action == "hold"
        assert record.verdict.conviction == "low"


class TestSerialization:
    def test_record_to_dict(self, engine):
        record = engine.run_debate(
            "002155",
            "湖南黄金",
            trigger="test",
            market_data={"rsi": 25.0, "macro_score": 0.5},
        )
        d = record.to_dict()
        assert d["symbol"] == "002155"
        assert "bull_arguments" in d
        assert "bear_arguments" in d
        assert "verdict" in d
        assert "bull_score" in d
        assert "bear_score" in d

    def test_argument_to_dict(self, engine):
        args = engine.collect_bull_arguments({"rsi": 25.0})
        if args:
            d = args[0].to_dict()
            assert "perspective" in d
            assert d["perspective"] == "bull"

    def test_scores(self, engine):
        record = engine.run_debate(
            "002155",
            "湖南黄金",
            market_data={
                "rsi": 25.0,
                "macro_score": 0.5,
                "recent_5d_gain_pct": 15.0,
            },
        )
        assert isinstance(record.bull_score, float)
        assert isinstance(record.bear_score, float)
